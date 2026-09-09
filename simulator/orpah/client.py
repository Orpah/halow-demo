#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
client.py — ORPAH Client host（L1）
===================================
Client = 被追踪终端（真实中 = 免电池可穿戴：TX-AH 电台 + CH32V203 主机/SPI 数据面；
纯 PC 阶段 = 连 STA 模块 host 口注入报文）。

L1 角色：连接 STA 模块的 host 数据口（DATA_TX），把 ORPAH-REPORT（JSON）封装成
以太网帧注入 → STA 走空口发给 AP（Router）。

    client.py --(host 口 DATA_TX: 以太网帧)--> STA 模块 --HaLow--> AP 模块(Router)

可独立运行（周期上报），也可被 demo_l1.py 内嵌（复用 ClientHost.report_once）：
    python orpah/client.py --sta-port 9102 --sn TXAH-0001 --every 5
"""
import argparse
import socket
import sys
import time

from host_bus import HostBus
from orpah_proto import (MAC_BCAST, build_report, encode_report_json,
                         build_eth_frame)

LOG = True


def log(*a):
    if LOG:
        print("[client]", *a, flush=True)


class ClientHost:
    """ORPAH Client host：向 STA 模块注入 ORPAH-REPORT。"""

    def __init__(self, sta_port, sn="ORPAH-0001", rssi=-55, mac=None,
                 sta_host="127.0.0.1", on_sent=None):
        self.sta = HostBus(host=sta_host, port=sta_port, name="client")
        self.sn = sn
        self.rssi = rssi
        self.seq = 0
        self.on_sent = on_sent              # callable(msg_dict, eth_len) or None
        # 缺省本机 MAC（4A:06:59:00:00:01），6 字节
        self.mac = mac if mac is not None else bytes([0x4A, 0x06, 0x59, 0, 0, 1])

    def connect(self, retries=100):
        return self.sta.connect(retries=retries)

    def close(self):
        self.sta.close()

    def report_once(self, extra=None):
        """注入一条 ORPAH-REPORT；返回注入的以太网帧长度（失败 -1）。"""
        self.seq += 1
        msg = build_report(sn=self.sn, rssi=self.rssi, seq=self.seq,
                           extra=extra)
        payload = encode_report_json(msg)
        eth = build_eth_frame(payload, src_mac=self.mac, dst_mac=MAC_BCAST)
        if not self.sta.send_frame(eth):
            log("注入失败（STA 未连接？）")
            return -1
        log(f"[{self.seq}] 注入 ORPAH-REPORT sn={self.sn} "
            f"rssi={self.rssi} ({len(eth)}B 以太网帧)")
        if self.on_sent:
            self.on_sent(msg, len(eth))
        return len(eth)


def main():
    ap = argparse.ArgumentParser(description="ORPAH Client host L1（STA 模块注入上报）")
    ap.add_argument("--sta-port", type=int, required=True,
                    help="STA 模块 host 数据口 TCP 端口（sim.py --host）")
    ap.add_argument("--sn", default="ORPAH-0001", help="终端序列号/IMEI")
    ap.add_argument("--rssi", type=int, default=-55, help="注入报文的 rssi")
    ap.add_argument("--every", type=float, default=5.0,
                    help="周期上报秒数（默认 5；<=0 只发一次后退出）")
    args = ap.parse_args()

    c = ClientHost(sta_port=args.sta_port, sn=args.sn, rssi=args.rssi)
    if not c.connect():
        log(f"连不上 STA 模块 host 口 :{args.sta_port}，退出")
        return 1
    log(f"已连 STA 模块 host 口 :{args.sta_port}，开始上报 sn={args.sn}")

    def report():
        while True:
            c.report_once()
            if args.every <= 0:
                return
            time.sleep(args.every)

    import threading
    threading.Thread(target=report, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    # 让独立运行也能 Ctrl-C 干净退出
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
