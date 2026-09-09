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
                         MSG_ERROR, parse_eth_frame, decode_msg, encode_msg,
                         build_access_info, build_eth_frame,
                         ST_NOT_TRACKED)

LOG = True


def log(*a):
    if LOG:
        print("[router]", *a, flush=True)


class RouterBridge:
    """ORPAH 路由器桥（双向）：AP host 口 ⇄ UDP ⇄ Server。"""

    def __init__(self, ap_port, server_port=ORPAH_UDP_PORT,
                 ap_host="127.0.0.1", server_host="127.0.0.1",
                 self_mac=None, on_up=None, on_down=None):
        self.ap = HostBus(host=ap_host, port=ap_port, name="router")
        self.server_addr = (server_host, server_port)
        self.up_count = 0
        self.down_count = 0
        self.on_up = on_up                  # callable(msg) 上行转发（REPORT）
        self.on_down = on_down              # callable(msg) 下行注入（回 Client）
        # 本地走失缓存（Server LOST-TABLE 下发）：sn -> tracked(bool)
        self.lost_cache = {}
        # 本 Router 的 MAC（下行帧 src；缺省给个演示值）
        self.mac = self_mac if self_mac is not None else \
            bytes([0x4A, 0x06, 0x59, 0x80, 0, 1])
        self.udp = None
        self._stop = threading.Event()

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
            # 查本地走失缓存 → ACCESS-INFO 回 Client（含 server_ok）
            tracked = bool(self.lost_cache.get(str(sn), {}).get("tracked"))
            status = ST_NOT_TRACKED if not tracked else "TRACKED"
            info = build_access_info(sn, tracked=tracked, server_ok=True,
                                     status=status)
            self._down(info)
            log(f"REQ-CONNECT sn={sn} tracked={tracked} -> 回 ACCESS-INFO")
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
        # 其它类型（一般不会经 Router 上行）——记录
        log(f"收到上行类型 {mtype} sn={sn}，忽略")

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
        self.lost_cache = {}
        for e in entries:
            self.lost_cache[str(e.get("sn"))] = {
                "tracked": bool(e.get("tracked")),
                "note": e.get("note", ""),
            }
        log(f"LOST-TABLE 更新（{len(entries)} 项）")

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
