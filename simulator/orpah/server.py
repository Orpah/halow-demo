#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — ORPAH 奥帕服务器（L1 + L2）
=======================================
真实 UDP socket 收 ORPAH-REPORT（JSON）。收到即打印/记录 = L1 验收：
「一个 payload(JSON) 从 Client(STA) 上行到 Server」。

L2 扩展（SPEC §7/§5）：Server 是**走失表权威**：
  - 收 REPORT → 校验(格式/解码) → 查走失库 → 回 TRACKING-STATUS 给该 Router
    （命中=TRACKED+LOG-OK / 未命中=NOT-TRACKED / 校验失败=*ERR）
  - 维护走失库（内存表）：mark_tracked(sn) / untrack(sn) / snapshot()
  - 走失库变更 → 向相关 Router 下发 LOST-TABLE（Router 据此在 REQ-CONNECT
    阶段直接告知 ACCESS-INFO 的 tracked 标志）

可独立运行，也可被 demo/ui 内嵌（复用 OrpahServer 类）：
    python orpah/server.py --port 19447
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

from orpah_proto import (ORPAH_UDP_PORT, MSG_REPORT, MSG_REQ_CONNECT,
                         MSG_TRACKING_STATUS, MSG_LOST_TABLE,
                         build_tracking_status, build_lost_table,
                         build_error, decode_msg, encode_msg,
                         ST_TRACKED, ST_NOT_TRACKED, ST_LOG_OK,
                         ERR_FORMAT, ERR_LOG)

LOG = True


def log(*a):
    if LOG:
        print("[server]", *a, flush=True)


class OrpahServer:
    """UDP 服务器：收 ORPAH 报文 + 权威走失库 + 应答/LOST-TABLE 下发。"""

    def __init__(self, port=ORPAH_UDP_PORT, on_report=None, on_down=None,
                 on_lost=None):
        self.port = port
        self.on_report = on_report          # callable(msg) or None（收到 REPORT）
        self.on_down = on_down              # callable(msg, router_addr) 下行应答
        self.on_lost = on_lost              # callable(lost_table_dict) 走失表变更
        self.reports = []                   # 收到的 REPORT（内存缓冲，演示用）
        self.count = 0
        self.down_count = 0                 # 已下发的应答数
        self._stop = threading.Event()
        self.sock = None
        # 权威走失库：sn -> {"tracked": bool, "note": str, "since": ts}
        self.lost = {}
        # 该 sn 的报文来自哪个 Router（UDP addr），应答/下发回这里
        self.router_for = {}
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
        if self.on_lost:
            self.on_lost(self.snapshot())
        return True

    def snapshot(self):
        with self._lock:
            return dict(self.lost)

    # ---------------- 网络 ----------------
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.settimeout(0.5)
        threading.Thread(target=self._loop, daemon=True).start()
        log(f"监听 127.0.0.1:{self.port} (UDP)，等待 ORPAH 报文…")
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
        # 记住该 sn 的上行 Router（应答/下发回这里）
        if sn:
            with self._lock:
                self.router_for[str(sn)] = addr
        if mtype == MSG_REPORT:
            self._on_report(msg, addr)
        elif mtype == MSG_REQ_CONNECT:
            # REQ-CONNECT 只应到 Router；若误达 Server，忽略（由 Router 处理）
            pass
        else:
            log(f"收到未处理类型 {mtype}（来自 {addr}），忽略")

    def _on_report(self, msg, addr):
        sn = msg.get("sn")
        # 校验：格式（缺 sn / 类型错）→ FORMAT-ERR
        if not sn:
            self._reply(addr, build_error(ERR_FORMAT, msg_text="missing sn"))
            return
        self.count += 1
        self.reports.append(msg)
        log(f"[{self.count}] ORPAH-REPORT <- {addr}: sn={sn} "
            f"ts={msg.get('ts')} rssi={msg.get('rssi', '-')} seq={msg.get('seq')}")
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

    def _push_lost(self):
        """把当前走失表下发给所有已见过的 Router（LOST-TABLE）。"""
        entries = [{"sn": k, "tracked": bool(v["tracked"]), "note": v.get("note", "")}
                   for k, v in self.lost.items()]
        with self._lock:
            addrs = set(self.router_for.values())
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
                    help="启动即标记为走失的 sn（可多次，如 --mark ORPAH-0001）")
    ap.add_argument("--timeout", type=float, default=30,
                    help="空闲退出前秒数（默认 30；<=0 一直跑）")
    args = ap.parse_args()

    srv = OrpahServer(port=args.port)
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
