#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
router.py — ORPAH Router（L1 桥 + L2 双向）
===========================================
Router = HaLow AP 的「网口上行」侧（真实中 = TH-RJ45 的 RJ45 口通往局域网/服务器）。

L1 角色：连接 AP 模块的 host 数据口（DATA_RX，读 AP 从空口收到的帧），
把其中 ORPAH 载荷用真实 UDP 转交 Server。

L2（双向，SPEC §4/§5）：
  上行：Client 帧 → REQ-CONNECT / REPORT
       - REQ-CONNECT → 查本地走失缓存 → 回 ACCESS-INFO（tracked/server_ok）
       - REPORT → UDP 转发 Server
  下行：Server UDP 应答/下发 → 注入 AP 空口回 Client
       - TRACKING-STATUS（Server 对 REPORT 的回执）→ 注入回 Client
       - LOST-TABLE（Server 下发）→ 更新本地走失缓存

    AP 模块 --(host 口, 双向)--> router.py --(UDP, 双向)--> server.py

HostBus 一个连接即可双向：recv_frame 收上行、send_frame 注入下行。

可独立运行，也可被 demo/ui 内嵌（复用 RouterBridge 类）：
    python orpah/router.py --ap-port 9101 --server-port 19447
"""
import argparse
import collections
import socket
import sys
import threading
import time

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from host_bus import HostBus
from orpah_proto import (ORPAH_UDP_PORT, MAC_BCAST, MSG_REQ_CONNECT,
                         MSG_REPORT, MSG_TRACKING_STATUS, MSG_LOST_TABLE,
                         MSG_ERROR, MSG_ID_REPORT,
                         parse_eth_frame, decode_msg, encode_msg,
                         build_access_info, build_eth_frame,
                         build_lost_table_req, build_found, new_rid,
                         ST_NOT_TRACKED)

LOG = True


def log(*a):
    if LOG:
        print("[router]", *a, flush=True)


class RouterBridge:
    """ORPAH 路由器桥（双向）：AP host 口 ⇄ UDP ⇄ Server。"""

    def __init__(self, ap_port, server_port=ORPAH_UDP_PORT,
                 ap_host="127.0.0.1", server_host="127.0.0.1",
                 self_mac=None, on_up=None, on_down=None, on_found=None,
                 on_up_id=None):
        self.ap = HostBus(host=ap_host, port=ap_port, name="router")
        self.server_addr = (server_host, server_port)
        self.up_count = 0
        self.down_count = 0
        self.id_up_count = 0               # 透传给 Server 的 ID-REPORT 条数（与 up_count 分开）
        self.found_count = 0               # 发现走失（ORPAH-FOUND 上报）次数
        self.on_up = on_up                  # callable(msg) 上行转发（REPORT）
        self.on_down = on_down              # callable(msg) 下行注入（回 Client）
        self.on_found = on_found            # callable(msg) 发现走失上报
        self.on_up_id = on_up_id            # callable(msg) 上行转发（ID-REPORT）
        # 本地走失缓存（Server LOST-TABLE 下发）：sn -> tracked(bool)
        self.lost_cache = {}
        # 本 Router 的 MAC（下行帧 src；缺省给个演示值）
        self.mac = self_mac if self_mac is not None else \
            bytes([0x4A, 0x06, 0x59, 0x80, 0, 1])
        self.udp = None
        self._stop = threading.Event()
        # 主动拉表同步用：收到 Server 的 LOST-TABLE（_apply_lost_table）时置位
        self._lost_event = threading.Event()
        # 是否已成功同步过走失表（此后依赖 Server 推送即可；重启后复位为未同步）
        self._synced = False
        # 拉表应答 vs 推送区分（2026-09-12 改）：靠 **关联号 rid** 配对，不再用时间窗猜。
        # 发出 REQ 时把本次 rid 记进 `_pull_rids`；只有 rid 落在集合里的 LOST-TABLE
        # 算“本机拉表的应答”，其余（无 rid 的主动推送）计“收到走失表下发”。
        # 2026-09-12 复核修正：用**集合**而不是单个变量 —— `start()` 里两个循环线程先起、
        # 再调 `sync()`，而 `_handle_up` 也可能在未同步时再调一次 `sync()` →
        # **两次拉表可能重叠**；单变量时“读-判-写”非原子，后一次 sync 覆盖前一次的 rid
        # 会让先到的应答掉配对（多计 1 次）。集合天然支持多个 in-flight 请求。
        # `_pull_lock` 只保护这个集合（deque 有 maxlen 上限，应答丢失也不会无界增长）。
        self._pull_lock = threading.Lock()
        self._pull_rids = collections.deque(maxlen=8)
        # 收到的 Server 主动推送的走失表次数（下发计数，供 UI Router 卡片展示）
        self.lost_push_recv = 0

    def start(self):
        if not self.ap.connect():
            log(f"连不上 AP 模块 host 口 :{self.ap.addr[1]}，退出")
            return False
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.settimeout(0.5)            # 让下行线程可轮询 stop
        log(f"已连 AP 模块 host 口 :{self.ap.addr[1]}；Server -> "
            f"{self.server_addr[0]}:{self.server_addr[1]}")
        threading.Thread(target=self._air_loop, daemon=True).start()
        threading.Thread(target=self._udp_loop, daemon=True).start()
        # 启动即主动拉一次走失表（重启/新 Router 追平；Server 未就绪则超时忽略）
        if self.sync(timeout=1.5):
            log(f"启动拉表成功（走失缓存 {len(self.lost_cache)} 项）")
        return True

    # ---------------- 上行：AP 空口收帧 ----------------
    def _air_loop(self):
        while not self._stop.is_set():
            eth = self.ap.recv_frame(timeout=1.0)
            if eth is None:
                continue
            parsed = parse_eth_frame(eth)
            if parsed is None:
                continue                      # 非 ORPAH 类型帧，忽略
            _et, payload = parsed
            msg = decode_msg(payload)
            if msg is None:
                log("收到无法解析的 ORPAH 载荷，忽略")
                continue
            self._handle_up(msg, eth)

    def _handle_up(self, msg, eth):
        mtype = msg.get("type")
        sn = msg.get("sn")
        if mtype == MSG_REQ_CONNECT:
            # 查本地走失缓存 → ACCESS-INFO 回 Client（含 server_ok）。
            # 若尚未与 Server 同步过走失表（启动拉表超时/重启后），先主动拉一次；
            # 同步成功后 Server 每次变更都会推来全量表，无需每条 REQ 都拉。
            if not self._synced:
                self.sync(timeout=1.5)
            tracked = bool(self.lost_cache.get(str(sn), {}).get("tracked"))
            status = ST_NOT_TRACKED if not tracked else "TRACKED"
            info = build_access_info(sn, tracked=tracked, server_ok=True,
                                     status=status)
            self._down(info)
            log(f"REQ-CONNECT sn={sn} tracked={tracked} -> 回 ACCESS-INFO")
            # 命中走失表 → 上报“发现”业务告警（每次命中都发）
            if tracked:
                self._announce_found(sn)
            return
        if mtype == MSG_REPORT:
            self.up_count += 1
            try:
                # Server 应答要回到本 Router 的 UDP socket → 用同一 socket 发
                self.udp.sendto(encode_msg(msg), self.server_addr)
            except OSError as e:
                log(f"转发 Server 失败: {e}")
                return
            log(f"[{self.up_count}] 上行 ORPAH-REPORT sn={sn} "
                f"seq={msg.get('seq')} -> {self.server_addr[0]}:{self.server_addr[1]}")
            if self.on_up:
                self.on_up(msg)
            return
        if mtype == MSG_ID_REPORT:
            # 已签 orpah-id-report：Router 只透传（不改 hdr/payload/sig），
            # Server 侧验签（§9.3）。不占 REPORT 上行计数（up_count），
            # 但它是真实进 UDP 的帧 → 单独计 id_up_count（UI 把 UDP 段按内容分色显示）。
            try:
                self.udp.sendto(encode_msg(msg), self.server_addr)
            except OSError as e:
                log(f"转发 Server 失败: {e}")
                return
            self.id_up_count += 1
            log(f"[{self.id_up_count}] 上行 ORPAH-ID-REPORT sn={sn} -> "
                f"{self.server_addr[0]}:{self.server_addr[1]}")
            if self.on_up_id:
                self.on_up_id(msg)
            return
        # 其它类型（一般不会经 Router 上行）——记录
        log(f"收到上行类型 {mtype} sn={sn}，忽略")

    def _announce_found(self, sn):
        """本 Router 检测到走失 sn（REQ-CONNECT 命中本地缓存）→ 上报 ORPAH-FOUND。

        业务告警：每次命中都发（供 Server 记录 / UI「发现记录」）。
        """
        msg = build_found(sn)
        try:
            self.udp.sendto(encode_msg(msg), self.server_addr)
        except OSError as e:
            log(f"发现上报失败: {e}")
            return
        self.found_count += 1
        log(f"[found {self.found_count}] 发现走失 sn={sn} -> "
            f"{self.server_addr[0]}:{self.server_addr[1]}")
        if self.on_found:
            self.on_found(msg)

    # ---------------- 下行：Server UDP 应答 → 注入 Client ----------------
    def _udp_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = decode_msg(data)
            if msg is None:
                continue
            mtype = msg.get("type")
            if mtype == MSG_LOST_TABLE:
                self._apply_lost_table(msg)
                continue
            if mtype == MSG_TRACKING_STATUS:
                self._down(msg)              # Server 回执 → 注入回 Client
                continue
            if mtype == MSG_ERROR:
                # 服务器错误（如 FORMAT-ERR）→ 若带 sn 也回给 Client 参考
                if msg.get("sn"):
                    self._down(msg)
                continue
            log(f"收到 Server 类型 {mtype}，忽略")

    def _apply_lost_table(self, table):
        entries = table.get("entries") or []
        # 先构造新表再**整体替换**：原来是 `self.lost_cache = {}` 再逐条填，中间有一瞬
        # 缓存为空 —— 若此时 REQ-CONNECT 到来会误答 NOT-TRACKED（极窄窗口，但没必要留）。
        # 重建后一次性绑定：读方要么看到旧表、要么看到新表，不会看到“半张表”。
        cache = {}
        for e in entries:
            cache[str(e.get("sn"))] = {
                "tracked": bool(e.get("tracked")),
                "note": e.get("note", ""),
            }
        self.lost_cache = cache
        log(f"LOST-TABLE 更新（{len(entries)} 项）")
        # 计数：Server 主动推送才算“收到走失表下发”；本机拉表的应答不算。
        # 判据 = **rid 是否在当前在飞集合里**（无 rid ⇒ 主动推送；rid 不在集合里 ⇒ 也是推送，
        # 例：上一次超时的旧应答／别的 Router 的应答被广播给本机）。
        rid = table.get("rid")
        is_reply = False
        if rid:
            with self._pull_lock:
                if rid in self._pull_rids:
                    self._pull_rids.remove(rid)
                    is_reply = True
        if is_reply:
            log("（本机拉表应答：不计“收到走失表下发”）")
        else:
            self.lost_push_recv += 1
        self._lost_event.set()          # 通知等待中的 sync()

    def sync(self, timeout=2.0):
        """主动向 Server 拉取当前走失表并等回包（同步）。

        发 ORPAH-LOST-TABLE-REQ（带**关联号 rid**）；Server 的应答原样回显 rid，
        由 _udp_loop → _apply_lost_table 处理并置 _lost_event。
        发送失败/超时返回 False（缓存保持原样，下次 REQ-CONNECT 会再触发）。

        注：等待期间若 Server 恰好主动推来一张表（无 rid），**也算拿到权威全量表**
        它按“推送”计数；本次 rid 留在集合里，等应答真到了再按“应答”配对
        （集合支持多个 in-flight 请求 → 两次拉表重叠也不会丢配对）。
        """
        self._lost_event.clear()
        if not self.udp:
            return False
        rid = new_rid()
        with self._pull_lock:
            self._pull_rids.append(rid)
        try:
            self.udp.sendto(encode_msg(build_lost_table_req(rid=rid)),
                            self.server_addr)
        except OSError as e:
            with self._pull_lock:
                if rid in self._pull_rids:
                    self._pull_rids.remove(rid)
            log(f"拉表请求发送失败: {e}")
            return False
        ok = self._lost_event.wait(timeout)
        if ok:
            self._synced = True          # 已拿到权威全量表，此后依赖推送即可
        else:
            log("拉表等待 Server 回包超时（下次 REQ-CONNECT 会再试）")
        return ok

    def _down(self, msg):
        """把一条报文注入 AP 空口，回给（广播，STA 侧必收）Client。"""
        eth = build_eth_frame(encode_msg(msg), src_mac=self.mac,
                              dst_mac=MAC_BCAST)
        if not self.ap.send_frame(eth):
            log("下行注入失败（AP 未连接？）")
            return
        self.down_count += 1
        log(f"[down {self.down_count}] {msg.get('type')} sn={msg.get('sn', '-')} "
            f"-> 空口广播")
        if self.on_down:
            self.on_down(msg)

    def stop(self):
        self._stop.set()
        if self.udp:
            try:
                self.udp.close()
            except OSError:
                pass
        self.ap.close()


def main():
    ap = argparse.ArgumentParser(description="ORPAH Router（双向：AP host 口 ⇄ UDP ⇄ Server）")
    ap.add_argument("--ap-port", type=int, required=True,
                    help="AP 模块 host 数据口 TCP 端口（sim.py --host）")
    ap.add_argument("--server-port", type=int, default=ORPAH_UDP_PORT)
    ap.add_argument("--timeout", type=float, default=30,
                    help="空闲退出秒数（默认 30；<=0 一直跑）")
    args = ap.parse_args()

    r = RouterBridge(ap_port=args.ap_port, server_port=args.server_port)
    if not r.start():
        return 1
    try:
        if args.timeout > 0:
            idle = 0.0
            while idle < args.timeout:
                time.sleep(1)
                if r.up_count > 0 or r.down_count > 0:
                    idle = 0.0
                else:
                    idle += 1
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        r.stop()
    log(f"共上行转发 {r.up_count} 条，下行 {r.down_count} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
