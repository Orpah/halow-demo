#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — ORPAH 奥帕服务器（L1）
==================================
真实 UDP socket 收 ORPAH-REPORT（JSON）。收到即打印/记录 = L1 验收：
「一个 payload(JSON) 从 Client(STA) 上行到 Server」。

可独立运行，也可被 demo_l1.py 以线程方式内嵌（复用 OrpahServer 类）：
    python orpah/server.py --port 19447
"""
import argparse
import socket
import threading
import time

from orpah_proto import ORPAH_UDP_PORT, decode_report_json

LOG = True


def log(*a):
    if LOG:
        print("[server]", *a, flush=True)


class OrpahServer:
    """UDP 服务器：收 ORPAH-REPORT JSON。"""

    def __init__(self, port=ORPAH_UDP_PORT, on_report=None):
        self.port = port
        self.on_report = on_report          # callable(msg) or None
        self.reports = []                   # 收到的报文（内存缓冲，演示用）
        self.count = 0
        self._stop = threading.Event()
        self.sock = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.settimeout(0.5)
        threading.Thread(target=self._loop, daemon=True).start()
        log(f"监听 127.0.0.1:{self.port} (UDP)，等待 ORPAH-REPORT…")
        return self

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = decode_report_json(data)
            if msg is None:
                log(f"收到无法解析的 UDP 数据（{len(data)}B，来自 {addr}）")
                continue
            self.count += 1
            self.reports.append(msg)
            log(f"[{self.count}] ORPAH-REPORT <- {addr}: sn={msg.get('sn')} "
                f"ts={msg.get('ts')} rssi={msg.get('rssi', '-')} seq={msg.get('seq')}")
            if self.on_report:
                self.on_report(msg)

    def stop(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="ORPAH 奥帕服务器（L1，UDP 收 JSON）")
    ap.add_argument("--port", type=int, default=ORPAH_UDP_PORT)
    ap.add_argument("--timeout", type=float, default=30,
                    help="收 N 条后退出前的空闲秒数（默认 30；<=0 则一直跑）")
    args = ap.parse_args()

    srv = OrpahServer(port=args.port)
    srv.start()
    try:
        if args.timeout > 0:
            idle = 0.0
            while idle < args.timeout:
                time.sleep(1)
                if srv.count > 0:
                    idle = 0.0            # 收到过：继续等新的（演示不退出）
                else:
                    idle += 1
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    log(f"共收到 {srv.count} 条 ORPAH-REPORT")


if __name__ == "__main__":
    main()
