#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_l3.py — ORPAH-over-HaLow L3 多 Router 漫游/去重 演示 + 验收（纯 PC，无硬件）
================================================================================
在 demo_l2（1 AP+1 Router）基础上，把拓扑扩为 **2 台 Router + 1 个移动 Client**
（同一 sn 先后出现在 R1、R2 两网），验证 SPEC F-04/F-07/F-01：

  ① 漫游/选路（F-07）：同一 Client 先在 R1 网络上报（seq 1..2），随后“移动”到
     R2 网络继续上报（seq 3..）——Server 以**上报来源**作为该 sn 的**当前 Router**
     （最新位置优先），TRACKING-STATUS 下行只回当前 Router，旧 Router 不再收到该
     sn 的下行。
  ② 去重（F-04）：同 (sn,seq) 重复（同一 Router 重发、或另一 Router 迟到转发同一
     帧）→ Server 丢弃：不重复计数、不再回 TRACKING-STATUS、且**不把“当前 Router”
     切回旧 Router**（防漫游时被迟到重传拽回）。
  ③ SN 格式校验（F-01，对齐《Orpah ID 协议规范》v1.7）：SN = CC-ORG-UNIQUE[-CHECK]
     非法 sn（如含空格/不合法字符）→ Server 回 ERROR code=FORMAT-ERR（bad-sn:…），
     不计数。
  ④ 新 Router 追平（F-03 补充）：Server 首次见到一台 Router 上报 → 立即把当前走失
     表推给它，避免它在 REQ-CONNECT 时因本地缓存为空误答 NOT-TRACKED。

拓扑：
    Client(同 sn) --STA1--> R1(AP1) --UDP--> Server
                 └--STA2--> R2(AP2) --UDP--> /      （漫游：先后经 R1、R2）

运行：python demo_l3.py [--sn CN-WH01-9AF3C1D2]
验收断言见文件尾（PASS/FAIL 汇总）。
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
from orpah_proto import (MSG_ACCESS_INFO, MSG_TRACKING_STATUS, MSG_ERROR,
                         ST_TRACKED, ST_NOT_TRACKED, ERR_FORMAT,
                         build_report)      # noqa: E402

# ---- 端口分配（独立于 demo_l1/9401..、demo_l2/9501..、ui_server/9401..）----
# R1 腿：AP1 + STA1（R1 网络）
CONSOLE_A1, LINK_A1, HOST_A1 = 9601, 9611, 9621
CONSOLE_B1, LINK_B1, HOST_B1 = 9602, 9612, 9622
# R2 腿：AP2 + STA2（R2 网络）
CONSOLE_A2, LINK_A2, HOST_A2 = 9603, 9613, 9623
CONSOLE_B2, LINK_B2, HOST_B2 = 9604, 9614, 9624
UDP_SRV = 19647


def _loop(core, stop):
    while not stop.is_set():
        core.wifi.poll()
        core.link.poll()
        time.sleep(0.005)


class Downs:
    """按 Router 记录下行（r1/r2）与 Client 收到的 ERROR，供断言。"""

    def __init__(self):
        self.r1 = []        # [(type, sn, status/code)]
        self.r2 = []
        self.err_c2 = []    # c2(漫游到 R2 的 Client) 收到的 ERROR

    def _down(self, which, msg):
        which.append((msg.get("type"), msg.get("sn", "-"),
                      msg.get("status", msg.get("code", "-"))))

    def r1_down(self, msg):
        self._down(self.r1, msg)

    def r2_down(self, msg):
        self._down(self.r2, msg)

    def c2_recv(self, msg):
        if msg.get("type") == MSG_ERROR:
            self.err_c2.append(msg)


def wait(pred, secs=6.0, step=0.1):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def count_tracking(downs):
    """某 Router 下行的 TRACKING-STATUS 数。"""
    return sum(1 for t, _, s in downs if t == MSG_TRACKING_STATUS)


def main():
    ap = argparse.ArgumentParser(description="ORPAH L3 多 Router 漫游/去重演示+验收")
    ap.add_argument("--sn", default="CN-WH01-9AF3C1D2",
                    help="终端 SN（Orpah ID：CC-ORG-UNIQUE[-CHECK]，Crockford Base32）")
    args = ap.parse_args()
    sn = args.sn

    # 1) 四台 PC 模拟器：AP1/STA1（R1 网络）、AP2/STA2（R2 网络）
    core_a1 = sim.Core("Router1-AP", "AP", CONSOLE_A1, LINK_A1, None,
                       host_port=HOST_A1)
    core_b1 = sim.Core("Client1-STA", "STA", CONSOLE_B1, LINK_B1,
                       ("127.0.0.1", LINK_A1), host_port=HOST_B1)
    core_a2 = sim.Core("Router2-AP", "AP", CONSOLE_A2, LINK_A2, None,
                       host_port=HOST_A2)
    core_b2 = sim.Core("Client2-STA", "STA", CONSOLE_B2, LINK_B2,
                       ("127.0.0.1", LINK_A2), host_port=HOST_B2)
    stop = threading.Event()
    for c in (core_a1, core_b1, core_a2, core_b2):
        threading.Thread(target=_loop, args=(c, stop), daemon=True).start()

    # 2) Server（权威走失库 + 去重）
    rec = Downs()
    srv = OrpahServer(port=UDP_SRV)
    srv.start()

    # 3) 两台 Router（各自连自己的 AP host 口，共用 Server）
    r1 = RouterBridge(ap_port=HOST_A1, server_port=UDP_SRV,
                      on_down=rec.r1_down)
    r2 = RouterBridge(ap_port=HOST_A2, server_port=UDP_SRV,
                      on_down=rec.r2_down)
    assert r1.start(), "Router1 连不上 AP1 host 口"
    assert r2.start(), "Router2 连不上 AP2 host 口"

    # 4) 两个 Client（同一 sn；一个在 R1 网、一个在 R2 网，模拟移动前后的两处）
    c1 = ClientHost(sta_port=HOST_B1, sn=sn)
    c2 = ClientHost(sta_port=HOST_B2, sn=sn, on_recv=rec.c2_recv)
    assert c1.connect(), "Client1 连不上 STA1 host 口"
    assert c2.connect(), "Client2 连不上 STA2 host 口"

    # 5) 等两台 STA 各自关联到自己的 AP
    print("\n等待 STA1/STA2 关联…")
    wait(lambda: core_b1.wifi.conn == sim.CONN_CONNECTED, secs=8)
    wait(lambda: core_b2.wifi.conn == sim.CONN_CONNECTED, secs=8)
    print(f"STA1 conn={core_b1.wifi.conn_str()} · STA2 conn={core_b2.wifi.conn_str()}")

    # ========== 阶段 A：Client 在 R1 网络（seq 1..2，未 mark）==========
    print(f"\n--- 阶段A：sn={sn} 在 R1 网络（2 条，未 mark）---")
    c1.send_req_connect(); time.sleep(0.3); c1.report_once()     # seq1
    c1.send_req_connect(); time.sleep(0.3); c1.report_once()     # seq2
    ok_a = wait(lambda: count_tracking(rec.r1) >= 2, secs=5)
    r1_len_after_a = len(rec.r1)
    print(f"R1 下行 TRACKING-STATUS={count_tracking(rec.r1)}（期望 2，NOT-TRACKED）")

    # ========== 阶段 B：漫游到 R2 网络（seq 续 3..）==========
    print(f"\n--- 阶段B：sn={sn} 漫游到 R2 网络（seq 续 {c1.seq + 1}）---")
    c2.seq = c1.seq                        # seq 续接（同一设备连续计数）
    c2.send_req_connect(); time.sleep(0.3); c2.report_once()     # seq3 经 R2
    ok_b = wait(lambda: count_tracking(rec.r2) >= 1 and
                rec.r2 and rec.r2[-1][2] == ST_NOT_TRACKED, secs=5)
    time.sleep(0.3)                        # 让“错误地也经 R1”的机会窗口过去
    r1_no_new = len(rec.r1) == r1_len_after_a   # 漫游后 R1 不应再收到该 sn 下行
    print(f"seq3 回执经 R2={count_tracking(rec.r2)} 条 · R1 无新增下行={r1_no_new}"
          f"（漫游后应只经 R2，R1 不再收到该 sn 下行）")

    # ========== 阶段 C：在 R2 mark 走失 → 双 Router 都收到 LOST-TABLE ==========
    print(f"\n--- 阶段C：mark 走失 sn={sn}（在 R2 网络）---")
    srv.mark_tracked(sn, note="roaming-demo")
    time.sleep(0.6)
    c_tracked = (r1.lost_cache.get(str(sn), {}).get("tracked") is True and
                 r2.lost_cache.get(str(sn), {}).get("tracked") is True)
    print(f"R1 缓存={r1.lost_cache.get(str(sn))} · R2 缓存={r2.lost_cache.get(str(sn))}")

    # ========== 阶段 D：R2 第二次会话（缓存已追平 → tracked=True → TRACKED）==========
    print(f"\n--- 阶段D：sn={sn} 在 R2 再次会话（应 tracked=True）---")
    c2.send_req_connect(); time.sleep(0.3); c2.report_once()     # seq4 经 R2
    ok_d = wait(lambda: count_tracking(rec.r2) >= 2 and
                rec.r2 and rec.r2[-1][2] == ST_TRACKED, secs=5)
    # 检查最近一次 ACCESS-INFO 是否 tracked=True（经 R2 下行）
    acc_r2 = [m for m in rec.r2 if m[0] == MSG_ACCESS_INFO]
    d_tracked = bool(acc_r2 and acc_r2[-1][2] in (True, ST_TRACKED, "TRACKED"))
    print(f"R2 最近 ACCESS-INFO tracked 标志: {acc_r2[-1][2] if acc_r2 else '-'}")
    accepted_before = srv.count

    # ========== 阶段 E：去重（同 seq 重发，F-04）==========
    print(f"\n--- 阶段E：去重测试（重发已接受的 seq={c2.seq}）---")
    r2_before_dup = len(rec.r2)
    # E1 同 Router（R2）重发刚接受的 seq
    c2._inject(build_report(sn=sn, rssi=c2.rssi, seq=c2.seq))
    time.sleep(0.5)
    dup1 = srv.dup_dropped >= 1
    no_reply1 = len(rec.r2) == r2_before_dup
    # E2 跨 Router：R1 迟到重发同一 seq（模拟旧 Router 也听到该帧广播）
    srv_router_before = srv.router_for.get(str(sn))
    r1_before_dup = len(rec.r1)
    c1._inject(build_report(sn=sn, rssi=c1.rssi, seq=c2.seq))
    time.sleep(0.5)
    dup2 = srv.dup_dropped >= 2
    no_reply2 = len(rec.r1) == r1_before_dup          # R1 没因重传产生下行
    not_bounced = srv.router_for.get(str(sn)) == srv_router_before  # 当前 Router 仍是 R2
    accepted_after = srv.count
    print(f"去重丢弃={srv.dup_dropped} · Server 计数 {accepted_before}→{accepted_after}"
          f"（应不变）· 当前 Router 未切回 R1={not_bounced}")

    # ========== 阶段 F：SN 格式校验（F-01，非法 sn → FORMAT-ERR）==========
    print(f"\n--- 阶段F：SN 校验（非法 sn → FORMAT-ERR）---")
    bad = "bad sn!"                        # 含空格 + 标点 → bad-format
    c2.sn = bad
    before_f = srv.count
    c2.report_once()                       # 会带非法 sn 经 R2 → Server 拒
    fmt_err = wait(lambda: any(m.get("code") == ERR_FORMAT for m in rec.err_c2),
                   secs=5)
    c2.sn = sn                             # 还原
    not_counted = srv.count == before_f
    print(f"Client 收到 ERROR code=FORMAT-ERR={fmt_err} · Server 计数不变={not_counted}"
          f"（{rec.err_c2[0].get('msg_text', '') if rec.err_c2 else '-'}）")

    # ========== 汇总 ==========
    print(f"\n=== ORPAH L3 多 Router 漫游/去重 验收 ===")
    print(f"Server 接受 REPORT（新 seq）: {srv.count}（期望 4 = seq1..4）")
    print(f"去重丢弃: {srv.dup_dropped}（期望 2）")
    checks = {
        "A 未 mark·经 R1 两条 NOT-TRACKED": ok_a,
        "B 漫游 R2：seq3 回执经 R2（最新 Router 优先）": ok_b and r1_no_new,
        "C mark 后 R1/R2 双缓存 tracked=True": c_tracked,
        "D R2 二次会话 tracked=True + TRACKED": ok_d and d_tracked,
        "E 同 Router 重发去重不回执": dup1 and no_reply1,
        "E 跨 Router 迟到重发去重且不切回旧 Router": dup2 and no_reply2 and not_bounced,
        "F 非法 SN → FORMAT-ERR 且不计数": fmt_err and not_counted,
    }
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    ok = all(checks.values()) and srv.count == 4 and srv.dup_dropped == 2
    print("结果:", "[PASS]" if ok else "[FAIL]")

    stop.set()
    c1.close(); c2.close(); r1.stop(); r2.stop(); srv.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
