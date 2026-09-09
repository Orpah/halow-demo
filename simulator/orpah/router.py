#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
router.py — ORPAH Router（L1 桥）
=================================
Router = HaLow AP 的「网口上行」侧（真实中 = TH-RJ45 的 RJ45 口通往局域网/服务器）。

L1 角色：连接 AP 模块的 host 数据口（DATA_RX，读 AP 从空口收到的帧），
把其中 ORPAH 载荷用真实 UDP 转交 Server。

    AP 模块 --(host 口 DATA_RX)--> router.py --(UDP: ORPAH JSON)--> server.py

可独立运行，也可被 demo_l1.py 以线程方式内嵌（复用 RouterBridge 类）：
    python orpah/router.py --ap-port 9101 --server-port 19447
"""
import argparse
import socket
import threading
import time

from host_bus import HostBus
from orpah_proto import ORPAH_UDP_PORT, parse_eth_frame, decode_report_json

LOG = True


def log(*a):
    if LOG:
        print("[router]", *a, flush=True)


class RouterBridge:
    """L1 路由器桥：AP host 口收帧 → 拆 ORPAH JSON → UDP 转发 Server。"""

    def __init__(self, ap_port, server_port=ORPAH_UDP_PORT,
                 ap_host="127.0.0.1", server_host="127.0.0.1"):
        self.ap = HostBus(host=ap_host, port=ap_port, name="router")
        self.server_addr = (server_host, server_port)
        self.up_count = 0
        self._stop = threading.Event()

    def start(self):
        if not self.ap.connect():
            log(f"连不上 AP 模块 host 口 :{self.ap.addr[1]}，退出")
            return False
        log(f"已连 AP 模块 host 口 :{self.ap.addr[1]}；上行转发 UDP -> "
            f"{self.server_addr[0]}:{self.server_addr[1]}")
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while not self._stop.is_set():
            eth = self.ap.recv_frame(timeout=1.0)
            if eth is None:
                continue
            parsed = parse_eth_frame(eth)
            if parsed is None:
                continue                      # 非 ORPAH 类型帧，忽略
            _et, payload = parsed
            msg = decode_report_json(payload)
            if msg is None:
                log("收到非 ORPAH-REPORT 载荷，忽略")
                continue
            self.up_count += 1
            try:
                udp.sendto(payload, self.server_addr)   # 原样 JSON → Server
            except OSError as e:
                log(f"转发 Server 失败: {e}")
                continue
            log(f"[{self.up_count}] 上行 ORPAH-REPORT sn={msg.get('sn')} "
                f"seq={msg.get('seq')} -> {self.server_addr[0]}:{self.server_addr[1]}")
        try:
            udp.close()
        except OSError:
            pass

    def stop(self):
        self._stop.set()
        self.ap.close()


def main():
    ap = argparse.ArgumentParser(description="ORPAH Router L1 桥（AP host 口 → UDP → Server）")
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
                if r.up_count > 0:
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
    log(f"共上行转发 {r.up_count} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
