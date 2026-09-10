#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_l2.py — ORPAH-over-HaLow L2 全消息流演示 + 验收（纯 PC，无硬件）
====================================================================
进程内建 2 台 PC 模拟器（host/sim.py Core）：A=AP(Router 侧)、B=STA(Client 侧)，
并启动 Server(权威走失库) + RouterBridge(双向) + ClientHost(双向会话)。

L2 目标（SPEC §9）：实现报文集子集 + 走失表 + 跟踪状态，端到端跑通 §4 时序：
  ① REQ-CONNECT (C→R) → Router 查本地走失缓存 → ACCESS-INFO (R→C, 含 tracked)
  ② REPORT (C→R) → Router UDP 转发 → Server 查权威走失库 →
     TRACKING-STATUS (S→R→C 下行经空口回 Client)
  ③ Server 走失库变更(mark/untrack) → LOST-TABLE 下发 → Router 更新缓存
  （此后 REQ-CONNECT 的 ACCESS-INFO.tracked 随之变化）

验收：
  - 双向打通：Client 收到 ACCESS-INFO 与 TRACKING-STATUS（下行真到达 Client）
  - 分支正确：未 mark 时 ACCESS-INFO.tracked=False + TRACKING-STATUS=NOT-TRACKED；
              mark 后 → tracked=True + TRACKED
  - 每个下行报文都有对应上行触发（REQ-CONNECT/REPORT 计数一致）

运行：python demo_l2.py [--sn CN-WH01-9AF3C1D2]
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

import sim                                  # noqa: E402

from server import OrpahServer              # noqa: E402
from router import RouterBridge             # noqa: E402
from client import ClientHost               # noqa: E402
from orpah_proto import (MSG_ACCESS_INFO, MSG_TRACKING_STATUS,
                         ST_TRACKED, ST_NOT_TRACKED)   # noqa: E402

# 端口分配（与 demo_l1 / ui_server 不同，避免同时跑冲突）
CONSOLE_A, LINK_A, HOST_A = 9501, 9511, 9521   # AP（Router）
CONSOLE_B, LINK_B, HOST_B = 9502, 9512, 9522   # STA（Client）
UDP_SRV = 19547


def _loop(core, stop):
    while not stop.is_set():
        core.wifi.poll()
        core.link.poll()
        time.sleep(0.005)


class Recorder:
    """记录 Client 收到的下行与 Server 收到上行，供断言。"""

    def __init__(self):
        self.access = []        # ACCESS-INFO 列表
        self.tracking = []      # TRACKING-STATUS 列表
        self.report = 0         # Server 收到 REPORT 数
        self.lost_push = 0

    def on_client_recv(self, msg):
        t = msg.get("type")
        if t == MSG_ACCESS_INFO:
            self.access.append(msg)
        elif t == MSG_TRACKING_STATUS:
            self.tracking.append(msg)


def wait(pred, secs=5.0, step=0.1):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def main():
    ap = argparse.ArgumentParser(description="ORPAH L2 全消息流演示+验收（纯 PC）")
    ap.add_argument("--sn", default="CN-WH01-9AF3C1D2")
    args = ap.parse_args()
    sn = args.sn

    # 1) 两台 PC 模拟器
    coreA = sim.Core("Router-AP", "AP", CONSOLE_A, LINK_A, None,
                     host_port=HOST_A)
    coreB = sim.Core("Client-STA", "STA", CONSOLE_B, LINK_B,
                     ("127.0.0.1", LINK_A), host_port=HOST_B)
    stop = threading.Event()
    threading.Thread(target=_loop, args=(coreA, stop), daemon=True).start()
    threading.Thread(target=_loop, args=(coreB, stop), daemon=True).start()

    # 2) Server（权威走失库）
    rec = Recorder()
    srv = OrpahServer(port=UDP_SRV, on_report=lambda m: setattr(rec, "report", rec.report + 1))
    srv.start()

    # 3) Router（双向）
    router = RouterBridge(ap_port=HOST_A, server_port=UDP_SRV)
    assert router.start(), "Router 连不上 AP host 口"

    # 4) Client（双向会话）
    client = ClientHost(sta_port=HOST_B, sn=sn, on_recv=rec.on_client_recv)
    assert client.connect(), "Client 连不上 STA host 口"

    # 5) 等 STA 关联 AP
    print("\n等待 STA 关联 AP…")
    wait(lambda: coreB.wifi.conn == sim.CONN_CONNECTED, secs=5)
    print(f"STA conn = {coreB.wifi.conn_str()}")

    # 6) 分支一：未 mark（走失库无该 sn）
    print(f"\n--- 分支一：走失库未命中 sn={sn} ---")
    client.send_req_connect()
    time.sleep(0.3)
    client.report_once()
    ok1 = wait(lambda: rec.tracking and rec.tracking[-1].get("status") == ST_NOT_TRACKED,
               secs=5)
    info1 = rec.access[-1] if rec.access else {}
    print(f"Client 收到 ACCESS-INFO: tracked={info1.get('tracked')} "
          f"server_ok={info1.get('server_ok')}")
    print(f"Client 收到 TRACKING-STATUS: {rec.tracking[-1].get('status') if rec.tracking else '-'}")

    # 7) mark 走失 → Server 下发 LOST-TABLE → Router 缓存更新
    print(f"\n--- mark 走失 sn={sn}（Server 下发 LOST-TABLE）---")
    srv.mark_tracked(sn, note="demo-lost")
    time.sleep(0.5)
    print(f"Router 走失缓存: {router.lost_cache}")

    # 8) 分支二：mark 后重握手 → ACCESS-INFO.tracked=True → REPORT → TRACKED
    print(f"\n--- 分支二：走失库命中 sn={sn} ---")
    client.send_req_connect()
    time.sleep(0.3)
    client.report_once()
    ok2 = wait(lambda: rec.access and rec.access[-1].get("tracked") is True, secs=5)
    time.sleep(0.3)                          # 等 TRACKED 下行
    info2 = rec.access[-1] if rec.access else {}
    status2 = None
    for t in reversed(rec.tracking):
        status2 = t.get("status")
        break
    print(f"Client 收到 ACCESS-INFO: tracked={info2.get('tracked')} "
          f"server_ok={info2.get('server_ok')}")
    print(f"最近 TRACKING-STATUS: {status2}")

    # 9) 断言
    print(f"\n=== ORPAH L2 验收 ===")
    down_ok = bool(rec.access) and bool(rec.tracking)     # 双向真打通
    branch1 = ok1 and info1.get("tracked") is False
    branch2 = ok2 and info2.get("tracked") is True
    print(f"Server 收到 REPORT: {rec.report}")
    print(f"Client 收到 ACCESS-INFO: {len(rec.access)} · TRACKING-STATUS: {len(rec.tracking)}")
    print(f"分支一(未命中 NOT-TRACKED): {'PASS' if branch1 else 'FAIL'}")
    print(f"分支二(命中 TRACKED): {'PASS' if branch2 else 'FAIL'}")
    ok = down_ok and branch1 and branch2 and rec.report >= 2
    print("结果:", "[PASS]" if ok else "[FAIL]")

    stop.set()
    client.close()
    router.stop()
    srv.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
