#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — ORPAH 奥帕服务器（L1 + L2）
=======================================
真实 UDP socket 收 ORPAH-REPORT（JSON）。收到即打印/记录 = L1 验收：
「一个 payload(JSON) 从 Client(STA) 上行到 Server」。

L2 扩展（SPEC §7/§5）：Server 是**走失表权威**：
  - 收 REPORT → 校验(格式/解码 + SN 码号，见《Orpah ID 协议规范》) → 查走失库 → 回 TRACKING-STATUS
    给该 Router（命中=TRACKED+LOG-OK / 未命中=NOT-TRACKED / 校验失败=*ERR）
  - 去重/最新位置（F-04/F-07）：同 (sn,seq) 重复（重传/多 Router 转发同一帧）丢弃
    不重复计数；每次接受新 REPORT 才把该 sn 的「当前 Router」切到上报来源（漫游时
    下行只回最新 Router）；首次见到的 Router 立即推当前走失表（新 Router 追平）。
  - 维护走失库（内存表）：mark_tracked(sn) / untrack(sn) / snapshot()
  - 走失库变更 → 向所有见过（上报过）的 Router 下发 LOST-TABLE（Router 据此在
    REQ-CONNECT 阶段直接告知 ACCESS-INFO 的 tracked 标志）

可独立运行，也可被 demo/ui 内嵌（复用 OrpahServer 类）：
    python orpah/server.py --port 19447
"""
import argparse
import socket
import sys
import threading
import time
from collections import deque

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from orpah_proto import (ORPAH_UDP_PORT, MSG_REPORT, MSG_REQ_CONNECT,
                         MSG_TRACKING_STATUS, MSG_LOST_TABLE,
                         MSG_LOST_TABLE_REQ, MSG_FOUND, MSG_ID_REPORT,
                         build_tracking_status, build_lost_table,
                         build_error, decode_msg, encode_msg,
                         ST_TRACKED, ST_NOT_TRACKED, ST_LOG_OK,
                         ERR_FORMAT, ERR_LOG, sn_err, effective_ts)
import orpah_id as oid                     # Orpah ID 验签（§9.3）

LOG = True


def log(*a):
    if LOG:
        print("[server]", *a, flush=True)


class OrpahServer:
    """UDP 服务器：收 ORPAH 报文 + 权威走失库 + 应答/LOST-TABLE 下发。"""

    def __init__(self, port=ORPAH_UDP_PORT, on_report=None, on_down=None,
                 on_lost=None, on_push=None, on_found=None,
                 keystore=None, id_nonces=None, on_id_report=None):
        self.port = port
        self.on_report = on_report          # callable(msg) or None（收到 REPORT）
        self.on_down = on_down              # callable(msg, router_addr) 下行应答
        self.on_lost = on_lost              # callable(lost_table_dict) 走失表变更
        self.on_push = on_push              # callable(entries, target_n) 发布走失表
        self.on_found = on_found            # callable(msg, router_addr) 发现走失上报
        self.reports = []                   # 收到的 REPORT（内存缓冲，演示用）
        self.count = 0
        self.down_count = 0                 # 已下发的应答数
        self.found_count = 0                # 收到 Router 发现走失上报（ORPAH-FOUND）次数
        self.founds = []                    # 最近 FOUND（内存缓冲）
        # Orpah ID 验签（§9.3）：keystore + nonce 去重 + 验签结果回调
        self.keystore = keystore
        # 独立运行（未传入）也默认启用 nonce 去重（防重放）；UI 传入共享缓存
        self.id_nonces = id_nonces if id_nonces is not None else oid.NonceCache()
        self.on_id_report = on_id_report
        self.id_report_total = 0
        self.id_reports = deque(maxlen=20)     # 环形（appendleft 自动截断，线程安全）
        self._stop = threading.Event()
        self.sock = None
        # 权威走失库：sn -> {"tracked": bool, "note": str, "since": ts}
        self.lost = {}
        # 该 sn 的报文来自哪个 Router（UDP addr），应答/下发回这里（最新位置）
        self.router_for = {}
        # 所有见过（上报过）的 Router（LOST-TABLE 全量下发的目标）
        self.routers = set()
        self.pull_count = 0               # Router 主动拉表（LOST-TABLE-REQ）次数
        # 去重（F-04）：sn -> {"last_seq": int|None, "seqs": set} 已接受的 seq
        self.seen = {}
        self.dup_dropped = 0             # 因重复被丢弃的 REPORT 数
        self._lock = threading.Lock()

    # ---------------- 走失库操作（权威，供 UI/脚本控制） ----------------
    def mark_tracked(self, sn, note="", push=True):
        """标记 sn 为走失（正在跟踪）；向相关 Router 下发 LOST-TABLE。"""
        with self._lock:
            self.lost[str(sn)] = {"tracked": True, "note": note,
                                  "since": int(time.time())}
        log(f"走失库：标记 {sn} 为走失（正在跟踪）")
        if push:
            self._push_lost()
            self._fire_publish()          # 服务器主动发布走失数据（供 UI 记录）
        if self.on_lost:
            self.on_lost(self.snapshot())
        return True

    def untrack(self, sn, push=True):
        """取消 sn 走失状态。"""
        with self._lock:
            if str(sn) in self.lost:
                self.lost[str(sn)]["tracked"] = False
        log(f"走失库：取消 {sn} 走失")
        if push:
            self._push_lost()
            self._fire_publish()
        if self.on_lost:
            self.on_lost(self.snapshot())
        return True

    def snapshot(self):
        with self._lock:
            return dict(self.lost)

    def _fire_publish(self):
        """走失表变更且确有 Router 在下发目标时，触发发布记录回调（on_push）。

        只统计**服务器主动发布**（mark/untrack 的下发）；Router 主动拉表
        （LOST-TABLE-REQ）的应答不算“发布”，不在此列。
        """
        with self._lock:
            if not self.routers:
                return
            entries = [{"sn": k, "tracked": bool(v["tracked"]),
                        "note": v.get("note", "")} for k, v in self.lost.items()]
            n = len(self.routers)
        if self.on_push:
            self.on_push(entries, n)

    # ---------------- 网络 ----------------
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.settimeout(0.5)
        threading.Thread(target=self._loop, daemon=True).start()
        log(f"监听 127.0.0.1:{self.port} (UDP)，等待 ORPAH 报文…")
        if self.keystore is None:
            log("（未配置 Orpah ID 密钥库：ORPAH-ID-REPORT 一律判 unknown_device；"
                "可用 --keystore-file 加载）")
        return self

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = decode_msg(data)
            if msg is None:
                log(f"收到无法解析的 UDP 数据（{len(data)}B，来自 {addr}）")
                continue
            self._handle(msg, addr)

    def _handle(self, msg, addr):
        mtype = msg.get("type")
        sn = msg.get("sn")
        # 非 REPORT 的带 sn 报文也记住 Router（如误达 Server 的 REQ-CONNECT，仅记录）
        if mtype == MSG_REPORT:
            self._on_report(msg, addr)
        elif mtype == MSG_REQ_CONNECT:
            # REQ-CONNECT 只应到 Router；若误达 Server，忽略（由 Router 处理）
            if sn:
                with self._lock:
                    self.router_for[str(sn)] = addr
        elif mtype == MSG_LOST_TABLE_REQ:
            # R→S 主动拉表：把当前走失表全量回给这台 Router，并记入“见过集”
            # （此后走失表变更也会推给它）。重启/新 Router 即使无变更事件也能追平。
            with self._lock:
                is_new = addr not in self.routers
                self.routers.add(addr)
            self.pull_count += 1
            log(f"收到 LOST-TABLE-REQ <- {addr[0]}:{addr[1]} "
                f"({'新 Router' if is_new else '已有 Router'})"
                f" -> 回当前走失表（{len(self.lost)} 项）")
            self._push_lost(to=[addr])
        elif mtype == MSG_FOUND:
            # R→S 业务告警：某 Router 发现走失 sn（每次命中都上报）
            self._note_router(addr)
            self.found_count += 1
            self.founds.append(msg)
            log(f"[发现 {self.found_count}] Router {addr[0]}:{addr[1]} "
                f"上报发现走失 sn={sn}")
            if self.on_found:
                self.on_found(msg, addr)
        elif mtype == MSG_ID_REPORT:
            # R→S 已签 orpah-id-report → 验签（§9.3）并记录 trust
            self._on_id_report(msg, addr)
        else:
            log(f"收到未处理类型 {mtype}（来自 {addr}），忽略")

    def _on_report(self, msg, addr):
        sn = msg.get("sn")
        # 校验 1：SN 格式（Orpah ID：CC-ORG-UNIQUE[-CHECK]，见 orpah_proto.sn_err）→ FORMAT-ERR
        reason = sn_err(sn)
        if reason:
            log(f"SN 校验失败 sn={sn!r} ({reason}) -> FORMAT-ERR")
            self._reply(addr, build_error(ERR_FORMAT, sn=sn,
                                          msg_text=f"bad-sn:{reason}"))
            return
        seq = msg.get("seq")
        # 校验 2 + 去重（F-04）：同 (sn,seq) 重复（重传/多 Router 转发同一帧）→ 丢弃，
        # 不重复计数、不更新“当前 Router”（防漫游时下行被旧 Router 的迟到重传拽回）。
        with self._lock:
            st = self.seen.setdefault(str(sn), {"last_seq": None, "seqs": set()})
            if seq is not None and seq in st["seqs"]:
                self.dup_dropped += 1
                log(f"重复上报丢弃 sn={sn} seq={seq} "
                    f"(共去重 {self.dup_dropped})")
                return
            if seq is not None:
                st["seqs"].add(seq)
                st["last_seq"] = (max(st["last_seq"], seq)
                                   if st["last_seq"] is not None else seq)
                # 窗口上限：防无界增长；超限清空（容忍序号重启/回绕的简化策略）
                if len(st["seqs"]) > 256:
                    st["seqs"].clear()
                    st["seqs"].add(seq)
        # 接受（新 REPORT）：计数 + 记当前 Router = 上报来源（最新位置优先，F-07）
        self.count += 1
        self.reports.append(msg)
        with self._lock:
            self.router_for[str(sn)] = addr
        log(f"[{self.count}] ORPAH-REPORT <- {addr}: sn={sn} "
            f"ts={msg.get('ts')} rssi={msg.get('rssi', '-')} seq={seq}")
        # 首次见到的 Router → 立即把当前走失表推给它（新 Router 追平；
        # 否则它 REQ-CONNECT 时本地缓存为空会误答 NOT-TRACKED）
        self._note_router(addr)
        # 查走失库 → 回 TRACKING-STATUS（命中=TRACKED+LOG-OK；未命中=NOT-TRACKED）
        rec = self.lost.get(str(sn))
        if rec and rec.get("tracked"):
            st = ST_TRACKED
            note = rec.get("note", "")
            status = build_tracking_status(sn, st,
                                           msg_text=f"log-ok tracked{'; '+note if note else ''}")
            # 命中：LOG-OK 也一并（状态码主 TRACKED；语义 = 已记录且正在跟踪）
        else:
            st = ST_NOT_TRACKED
            status = build_tracking_status(sn, st, msg_text="log-ok not-tracked")
        self._reply(addr, status)
        if self.on_report:
            self.on_report(msg)

    def _on_id_report(self, msg, addr):
        """R→S ORPAH-ID-REPORT：验签已签 orpah-id-report（§9.3），记录 trust。"""
        report = msg.get("report") if isinstance(msg, dict) else None
        hdr = (report or {}).get("hdr") or {}
        payload = (report or {}).get("payload") or {}
        sn = payload.get("sn") or msg.get("sn")
        # 前置 SN 格式校验（与 _on_report 一致，早日志；最终仍由 verify_report 裁决）
        reason = sn_err(sn)
        if reason:
            log(f"ORPAH-ID-REPORT SN 校验失败 sn={sn!r} ({reason})")
        if not isinstance(report, dict):
            v = {"accepted": False, "error": "bad_format", "trust": "none"}
        else:
            v = oid.verify_report(report, self.keystore,
                                  used_nonces=self.id_nonces)
        sig = (report or {}).get("sig") or ""
        # 时钟可信（§5.5）：ts=0/缺失/荒谬 → 验签层已跳过时间窗，这里再把「时间是从设备来的
        # 还是服务器接收时刻」记下来（审计需要能区分，否则事后无从分辨）。
        ts_eff, ts_src = effective_ts(payload.get("ts"), None)
        rec = {
            "t": time.strftime("%H:%M:%S"),
            "sn": sn or "-",
            "alg": hdr.get("alg", "-"),
            "level": hdr.get("level", "-"),
            "trust": v.get("trust") if v.get("accepted") else "-",
            "accepted": bool(v.get("accepted")),
            "error": v.get("error"),
            # 命中的密钥代次（多代并存 → 审计“用的是哪一代钥匙”）
            "kid": v.get("kid"),
            "gen": v.get("gen"),
            "sig": sig[:36] + ("…" if len(sig) > 36 else ""),
            "nonce": payload.get("nonce", ""),
            "ts_src": ts_src,          # device / server（留痕用，见 orpah_proto.effective_ts）
            "ts_eff": ts_eff,          # 实际用于记录的时刻（秒）
        }
        self.id_report_total += 1
        self.id_reports.appendleft(rec)
        log(f"[id {self.id_report_total}] ORPAH-ID-REPORT <- {addr[0]}:{addr[1]}: "
            f"sn={rec['sn']} alg={rec['alg']} level={rec['level']} "
            f"trust={rec['trust']} accepted={rec['accepted']}")
        if self.on_id_report:
            self.on_id_report(rec)

    def _note_router(self, addr):
        """记录一台 Router 地址；首次见到 → 若已有走失表立即推全量（新 Router 追平）。"""
        new = False
        with self._lock:
            if addr not in self.routers:
                self.routers.add(addr)
                new = True
        if new:
            log(f"新 Router {addr[0]}:{addr[1]} 出现")
            if self.lost:                      # 已有走失记录 → 立即补发全量表
                self._push_lost(to=[addr])

    def _push_lost(self, to=None):
        """把当前走失表下发（默认给所有见过/上报过的 Router；to 指定单台）。"""
        entries = [{"sn": k, "tracked": bool(v["tracked"]), "note": v.get("note", "")}
                   for k, v in self.lost.items()]
        with self._lock:
            addrs = sorted(self.routers) if to is None else list(to)
        table = build_lost_table(entries)
        for a in addrs:
            self._reply(a, table)
        if addrs:
            log(f"下发 LOST-TABLE（{len(entries)} 项）-> {len(addrs)} 台 Router")

    def _reply(self, addr, msg):
        """向指定 Router 回一条报文（UDP）。"""
        try:
            self.sock.sendto(encode_msg(msg), addr)
            self.down_count += 1
        except OSError as e:
            log(f"应答失败 {addr}: {e}")
            return
        log(f"[down {self.down_count}] {msg.get('type')} sn={msg.get('sn', '-')} "
            f"-> {addr[0]}:{addr[1]}")

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="ORPAH 奥帕服务器（UDP 收报文 + 走失库）")
    ap.add_argument("--port", type=int, default=ORPAH_UDP_PORT)
    ap.add_argument("--mark", action="append", default=[],
                    help="启动即标记为走失的 sn（可多次，如 --mark CN-WH01-9AF3C1D2）")
    ap.add_argument("--timeout", type=float, default=30,
                    help="空闲退出前秒数（默认 30；<=0 一直跑）")
    ap.add_argument("--keystore-file", default=None,
                    help="Orpah ID 密钥库 JSON（含 pubkey/hmac_key，KeyStore.save 导出）；"
                         "缺省不启用 Orpah ID 验签")
    args = ap.parse_args()

    ks = None
    if args.keystore_file:
        ks = oid.KeyStore()
        ks.load(args.keystore_file)
        log(f"已加载 Orpah ID 密钥库 {args.keystore_file}")
    srv = OrpahServer(port=args.port, keystore=ks)
    srv.start()
    for sn in args.mark:
        srv.mark_tracked(sn)
    try:
        if args.timeout > 0:
            idle = 0.0
            while idle < args.timeout:
                time.sleep(1)
                if srv.count > 0 or srv.down_count > 0:
                    idle = 0.0
                else:
                    idle += 1
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    log(f"共收到 {srv.count} 条 ORPAH-REPORT，下发 {srv.down_count} 条应答")


if __name__ == "__main__":
    main()
