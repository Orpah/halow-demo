#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_l1.py — ORPAH-over-HaLow L1 端到端演示 + 验收（纯 PC，无硬件）
==================================================================
进程内建 2 台 PC 模拟器（host/sim.py 的 Core）：
    A = AP   （Router 的 HaLow 侧，host 数据口 = Router 网口上行）
    B = STA  （Client 的 HaLow 侧，host 数据口 = Client 主机）
并启动：Server(UDP) 线程 + RouterBridge + ClientHost。

数据流（全走真实 TCP host 口与空口）：
    client.py --注入--> STA模块(B) --虚拟空口--> AP模块(A) --host口--> router.py
        --真实UDP--> server.py

验收：Client 注入 N 条 ORPAH-REPORT，Server 收到 >= N 条且 sn 匹配 → PASS。

运行：python demo_l1.py [--n 3]
"""
import argparse
import os
import sys
import threading
import time

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host")
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)
ORPAH_DIR = os.path.dirname(os.path.abspath(__file__))
if ORPAH_DIR not in sys.path:
    sys.path.insert(0, ORPAH_DIR)

import sim                                  # noqa: E402  (host/sim.py)

from server import OrpahServer, LOG as _SLOG    # noqa: E402
from router import RouterBridge, LOG as _RLOG   # noqa: E402
from client import ClientHost, LOG as _CLOG      # noqa: E402

# 端口分配（避免与常用端口冲突）
CONSOLE_A, LINK_A, HOST_A = 9401, 9411, 9421   # AP（Router）
CONSOLE_B, LINK_B, HOST_B = 9402, 9412, 9422   # STA（Client）
UDP_SRV = 19447


def _loop(core, stop):
    while not stop.is_set():
        core.wifi.poll()
        core.link.poll()
        time.sleep(0.005)


def main():
    ap = argparse.ArgumentParser(description="ORPAH L1 端到端演示+验收（纯 PC）")
    ap.add_argument("--n", type=int, default=3, help="上报条数（默认 3）")
    ap.add_argument("--sn", default="CN-WH01-9AF3C1D2")
    args = ap.parse_args()

    # 1) 两台 PC 模拟器：A=AP(Router) 开 host 口；B=STA(Client) 开 host 口
    coreA = sim.Core("Router-AP", "AP", CONSOLE_A, LINK_A, None,
                     host_port=HOST_A)
    coreB = sim.Core("Client-STA", "STA", CONSOLE_B, LINK_B,
                     ("127.0.0.1", LINK_A), host_port=HOST_B)
    stop = threading.Event()
    threading.Thread(target=_loop, args=(coreA, stop), daemon=True).start()
    threading.Thread(target=_loop, args=(coreB, stop), daemon=True).start()

    # 2) Server（真实 UDP）
    srv = OrpahServer(port=UDP_SRV)
    srv.start()

    # 3) Router 桥（连 AP 的 host 口）
    router = RouterBridge(ap_port=HOST_A, server_port=UDP_SRV)
    assert router.start(), "Router 连不上 AP host 口"

    # 4) Client host（连 STA 的 host 口）
    client = ClientHost(sta_port=HOST_B, sn=args.sn)
    assert client.connect(), "Client 连不上 STA host 口"

    # 5) 等 STA 关联上 AP（空口自动连接）
    print("\n等待 STA 关联 AP…")
    for _ in range(100):
        if coreB.wifi.conn == sim.CONN_CONNECTED:
            break
        time.sleep(0.1)
    print(f"STA conn = {coreB.wifi.conn_str()}")

    # 6) 注入 N 条上报（每条间隔 0.2s，让链路走完）
    print(f"\nClient 注入 {args.n} 条 ORPAH-REPORT (sn={args.sn})…")
    sent = 0
    for _ in range(args.n):
        if client.report_once() >= 0:
            sent += 1
        time.sleep(0.2)

    # 7) 等 Server 收到
    ok = False
    for _ in range(50):
        if srv.count >= sent:
            ok = True
            break
        time.sleep(0.1)

    print(f"\n=== ORPAH L1 验收 ===")
    print(f"Client 注入: {sent} 条")
    print(f"Server 收到: {srv.count} 条  (sn 一致: "
          f"{all(r.get('sn') == args.sn for r in srv.reports)})")
    print("结果:", "[PASS]" if ok and sent > 0 else "[FAIL]")

    stop.set()
    client.close()
    router.stop()
    srv.stop()
    return 0 if ok and sent > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
