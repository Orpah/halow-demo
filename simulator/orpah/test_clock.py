#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_clock.py — 时钟可信：无 RTC 设备（ts=0）在窗口 / 存储 / 审计里的一致处理

背景（ROADMAP §四「时钟可信」）：**免电池客户端没有 RTC**，协议 §5.5 规定「ts=0 = 未知 →
跳过时间窗判断，仅靠 nonce 防重放」。但「收不收」只解决一半：如果 ts=0 被字面写库，
就会落在 1970 → 设备流与路由器观测序列时刻对不上（定位/回放按时间对齐 → 匹配不到），
审计里也分不清「设备说的时间」和「服务器看到的时间」。
本文件盯住三件事：① 归一化规则 ② 验签窗口 ③ 端到端落库/审计的**留痕**。

运行：C:\\Python313\\python.exe test_clock.py
"""
import json
import os
import queue
import socket
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import orpah_id as oid                       # noqa: E402
import orpah_proto as P                      # noqa: E402
from server import OrpahServer               # noqa: E402

FAILS = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)

NOW = 1789000000                     # 固定“现在”，便于断言

print("== 1. effective_ts 归一化规则（唯一入口，各层共用）==")
CASES = [
    (NOW, NOW, P.TS_SRC_DEVICE, "正常设备时间 → 用设备时间"),
    (NOW - 60, NOW - 60, P.TS_SRC_DEVICE, "轻微滞后 → 仍用设备时间"),
    (0, NOW, P.TS_SRC_SERVER, "ts=0（无 RTC）→ 服务器接收时刻"),
    (None, NOW, P.TS_SRC_SERVER, "ts 缺失 → 服务器接收时刻"),
    ("123", NOW, P.TS_SRC_SERVER, "ts 是字符串 → 服务器接收时刻"),
    (True, NOW, P.TS_SRC_SERVER, "ts 是 bool（int 子类，别被坑）→ 服务器接收时刻"),
    (946684799, NOW, P.TS_SRC_SERVER, "早于 2000-01-01（荒谬时钟）→ 服务器接收时刻"),
    (946684800, 946684800, P.TS_SRC_DEVICE, "恰好 2000-01-01 → 视为可用（边界含）且**保留设备时间**"),
    (NOW + 86400, NOW + 86400, P.TS_SRC_DEVICE, "超前 1 天（=TS_MAX_SKEW_S 边界）→ 可用且保留设备时间"),
    (NOW + 86401, NOW, P.TS_SRC_SERVER, "超前 >1 天（时钟错乱）→ 服务器接收时刻"),
]
for ts, want, want_src, why in CASES:
    got, src = P.effective_ts(ts, NOW)
    ck(f"effective_ts({ts!r}) → ({want}, {want_src})  ({why})",
       (got, src) == (want, want_src), f"got=({got},{src})")
ck("rx 缺省时用当前时间（不报错、不为 0）",
   P.effective_ts(0)[0] > 1600000000 and P.effective_ts(0)[1] == P.TS_SRC_SERVER)

print("== 2. 验签的时间窗（ts=0 跳过窗口，仅靠 nonce 防重放）==")
ks = oid.KeyStore()
dev = oid.Device(sn="CN-WH01-9AF3C1D2", se_sn="ATECC608B-DEMO")
ks.register(dev)
used = oid.NonceCache()


def verify(ts, nonce):
    rep = dev.report(level=0, ts=ts, nonce=nonce)
    return oid.verify_report(rep, ks, now=NOW, used_nonces=used)


v = verify(0, "NONCE-0001")
ck("ts=0 → 验签通过（不因时间被拒）", bool(v.get("accepted")), str(v))
v = verify(NOW, "NONCE-0002")
ck("ts=now → 通过", bool(v.get("accepted")), str(v))
v = verify(NOW - 301, "NONCE-0003")
ck("超窗 301s → timestamp_out_of_window",
   (not v.get("accepted")) and v.get("error") == "timestamp_out_of_window", str(v))
v = verify(NOW + 301, "NONCE-0004")
ck("超前 301s → 同样拒（双向都查）",
   (not v.get("accepted")) and v.get("error") == "timestamp_out_of_window", str(v))
v = verify(0, "NONCE-0001")
ck("ts=0 也不能重放（nonce 仍拦）",
   (not v.get("accepted")) and v.get("error") == "replay_detected", str(v))

print("== 3. 端到端（进程内 UDP）：ts=0 的报告落库时刻 + 审计留痕 ==")
PORT = 19711
# 用 server 自带的 on_id_report 回调 + 队列来等结果，**不轮询 deque**：
# 轮询要拍一个“猜得够不够长”的次数（曾写 20×0.05s=1s）—— 一旦超时就只剩一句
# “拿到了 None”，查起来很难；队列等待是确定性的，超时也能报清是“没等到回调”。
ID_EVENTS = queue.Queue()
srv = OrpahServer(port=PORT, keystore=ks, id_nonces=oid.NonceCache(),
                  on_id_report=ID_EVENTS.put)
srv.start()
time.sleep(0.3)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(3)
WAIT_S = 5.0                                  # 回调等待上限（进程内 UDP 实测 <10ms）


def send_id(ts, nonce):
    """发一条签名上报 → 等服务器回调，返回那条 rec（超时返回 None）。"""
    while not ID_EVENTS.empty():              # 丢掉上一条的残留，避免拿错
        ID_EVENTS.get_nowait()
    msg = P.build_id_report(dev.report(level=0, ts=ts, nonce=nonce))
    sock.sendto(P.encode_msg(msg), ("127.0.0.1", PORT))
    deadline = time.time() + WAIT_S
    while True:
        left = deadline - time.time()
        if left <= 0:
            return None                       # 超时（调用方的断言会报 None）
        try:
            rec = ID_EVENTS.get(timeout=left)
        except queue.Empty:
            return None
        if rec.get("nonce") == nonce:         # 要的就是这条（正常就是第一条）
            return rec


t0 = int(time.time())
r0 = send_id(0, "NONCE-E2E-1")
ck("ts=0 的签名上报被接受", bool(r0 and r0.get("accepted")), str(r0))
ck("留痕：ts_src=server（时间来自服务器）", bool(r0 and r0.get("ts_src") == P.TS_SRC_SERVER),
   str(r0 and r0.get("ts_src")))
ck("ts_eff 落在“现在”附近（不是 0/1970）",
   bool(r0 and abs(r0.get("ts_eff", 0) - t0) < 30), str(r0 and r0.get("ts_eff")))
r1 = send_id(t0, "NONCE-E2E-2")
ck("ts=now 的签名上报被接受", bool(r1 and r1.get("accepted")), str(r1))
ck("留痕：ts_src=device（时间来自设备）", bool(r1 and r1.get("ts_src") == P.TS_SRC_DEVICE),
   str(r1 and r1.get("ts_src")))
sock.close()
srv.stop()

# ---- 4) 设备时钟偏移/漂移估计（clock.py，2026-09-12 深化） -------------------
# 只**估计**不改数据：给「设备自报 ts vs 服务器接收时刻」样本，看偏移（中位数）与漂移（ppm）。
import clock as clk                                                   # noqa: E402

print("== 4. 设备时钟偏移/漂移估计 ==")
ck("样本不足 → ok=False 且 offset=None（宁缺勿编）",
   (lambda e: e["ok"] is False and e["offset"] is None)(clk.estimate([])))
ck("2 个样本 → 仍不够（MIN_SAMPLES=3）", clk.estimate([(0, 5), (1, 5)])["ok"] is False)

# 固定偏移 +30s，跨 60s，无漂移 → offset=30、drift≈0
fixed = [(1000 + i * 10, 1000 + i * 10 + 30) for i in range(7)]
est = clk.estimate(fixed)
ck("固定偏移：中位数 = +30s", abs(est["offset"] - 30) < 1e-9, str(est))
ck("固定偏移：漂移 ≈ 0 ppm", abs(est["drift_ppm"]) < 1e-6, str(est["drift_ppm"]))
ck("样本数/跨度如实给出（n=7, span=60s）",
   est["n"] == 7 and abs(est["span"] - 60) < 1e-9, str(est))

# 线性漂移：设备每秒快 1ms = +1000 ppm；同时带回 5s 固定偏移
drift = [(1000 + i * 10, 1000 + i * 10 + 5 + i * 10 * 0.001) for i in range(40)]
est = clk.estimate(drift)
ck("线性漂移：+1000ppm（1ms/s）估得准", abs(est["drift_ppm"] - 1000) < 1.0,
   str(round(est["drift_ppm"], 3)))

# 跨度太短 → 不给漂移（但偏移照给）
short = [(1000, 1005), (1001, 1006), (1002, 1007)]
est = clk.estimate(short)
ck("跨度 <30s → drift_ppm=None（斜率无意义，不编 0）",
   est["drift_ppm"] is None and abs(est["offset"] - 5) < 1e-9, str(est))

# 单点跳变（设备乱报一次）不影响中位数 offset=0
noisy = [(1000, 1000), (1010, 1010), (1020, 1020), (1030, 9630), (1040, 1040)]
est = clk.estimate(noisy)
ck("单点跳变（设备乱报一次）不影响中位数 offset=0",
   abs(est["offset"]) < 1e-9 and est["spread"] > 8000, str(est))
ck("批量样本：offset_of 与 estimate 一致",
   clk.offset_of(noisy)[0] == est["offset"])     # 注：n<=8 时 tail==整窗，这条是同义反复；真不变式见下

# 偏移**只看最近 OFFSET_WINDOW 条**（2026-09-13 实测后改）：换钟/拨表要能很快反映。
# 实测教训：偏移也用整窗中位数时，现场拨偏 +120s 后一分钟内读数仍≈0（旧样本压着中位数）。
mixed = [(1000 + i, 1000 + i + (0 if i < 12 else 120)) for i in range(21)]   # 前 12 条正常、后 9 条 +120s
est = clk.estimate(mixed)
ck("偏移反应快：拨偏后 9 条即读回 +120s（不被旧样本压住）",
   abs(est["offset"] - 120) < 1e-9, str(est))
ck("偏移只用最近 8 条（n_off=8 / 整窗 n=21）",
   est["n_off"] == clk.OFFSET_WINDOW == 8 and est["n"] == 21, str(est))
ck("对照：若强行用整窗中位数，读数会被拉到 0（证明就是窗口的锅）",
   clk.offset_of(mixed)[0] == 0.0 and clk.estimate(mixed, offset_window=64)["offset"] == 0.0)
ck("不变式：estimate.offset == offset_of(最近 n_off 条)（跨函数一致，且≠整窗中位数）",
   clk.offset_of(mixed[-est["n_off"]:])[0] == est["offset"] != clk.offset_of(mixed)[0])
ck("n_off 随实际样本数收缩（不足 8 条时不会越界取空）",
   (lambda e: e["n_off"] == 4 and abs(e["offset"] - 1) < 1e-9)(
       clk.estimate([(1000 + i, 1000 + i + 1) for i in range(4)])))
ck("offset_window=0 → 退化为整窗（显式关掉短窗，便于对照）",
   clk.estimate(mixed, offset_window=0)["offset"] == clk.offset_of(mixed)[0])
ck("偏移窗仍免疫单点跳变（最近 8 条里坏 1 条不动摇）",
   abs(clk.estimate(mixed + [(1021, 1021 + 120 + 9999)])["offset"] - 120) < 1e-9)

# 漂移仍用**整窗长基线**（与偏移的短窗分开）
drift40 = [(1000 + i, 1000 + i + i * 0.001) for i in range(40)]
est = clk.estimate(drift40)
ck("漂移用整窗（n=40 > n_off=8）+ 斜率准（+1000ppm）",
   est["n"] == 40 and est["n_off"] == 8 and abs(est["drift_ppm"] - 1000) < 1.0,
   str(round(est["drift_ppm"], 3)))

# ---- 漂移“只在能信的时候给”（2026-09-13 实测两个坑）--------------------------
# 坑 1：窗内一次**跳变**（拨表/重启对时）会被 LS 当成巨大漂移。
# 实测：现场拨偏 +120s → drift_ppm 读成 ~2,000,000。
step_win = [(1000 + i, 1000 + i + (0 if i < 10 else 120)) for i in range(40)]   # 40s 窗内跳 120s
est = clk.estimate(step_win, step_spread=30)
ck("窗内有跳变（spread_win 120 > 阈值 30）→ 不给漂移（跳变不是漂移）",
   est["drift_ppm"] is None and est["spread_win"] > 100, str(est))
ck("同一条样本：不设 step_spread 时确实会读成天文数字（说明门是必需的）",
   (clk.drift_ppm_of(step_win) or 0) > 1e6, str(clk.drift_ppm_of(step_win)))
ck("spread_win=整窗散布（跳变指标）≠ spread=最近 8 条散布（当前抖动）",
   est["spread_win"] > 100 > est["spread"])

# 坑 2：整数秒设备时间的**量化噪声**（±0.5s）在短窗里盖过 ppm 级漂移。
import random                                                          # noqa: E402
rnd = random.Random(7)
noisy60 = [(1000 + i, 1000 + i + rnd.uniform(-0.5, 0.5)) for i in range(61)]   # 60s、1s 一条、无漂移
est = clk.estimate(noisy60)
ck("无漂移 + 量化噪声（60s 窗）→ 看不出趋势 → drift=None（不报假漂移）",
   est["drift_ppm"] is None and est["span"] >= clk.DRIFT_MIN_SPAN, str(est))
ck("同噪声下 offset 仍然可信（中位数压住抖动）", abs(est["offset"]) < 0.5, str(est["offset"]))

rnd2 = random.Random(7)
gross = [(1000 + i, 1000 + i + 0.02 * i + rnd2.uniform(-0.5, 0.5)) for i in range(61)]  # +20000ppm
est = clk.estimate(gross)
ck("真的在漂（+20000ppm：坏晶振级）→ 门不会把真漂移也挡掉",
   est["drift_ppm"] is not None and abs(est["drift_ppm"] - 20000) < 9000,
   str(None if est["drift_ppm"] is None else round(est["drift_ppm"])))

# 两个点连一条线不叫趋势（σ 没有意义）
two = [(1000, 1000), (1060, 1063.6)]                                    # 跨 60s、差 3.6s = 60000ppm
ck("只有 2 个样本 → drift=None（两个点必过，标准差没意义）",
   clk.estimate(two)["drift_ppm"] is None and clk.estimate(two)["ok"] is False)

# ClockTracker：按 SN 分别维护 + 越界起点只记一次 + snapshot 可读
# 注意 add(sn, device_ts, rx_ts)（offset = device − rx）；且 ok 需 ≥3 样本，
# 故「首次越界时刻」= 第 3 个样本的 rx（前两个样本不够，不判越界）。
# window=4：中位数要「窗内多数」才翻面 → 设备拨回来后需再收够样本才解除（≈ window/2 个周期）。
tr = clk.ClockTracker(window=4, offset_warn=30)
e_a = None
for i in range(4):
    e_a = tr.add("A", 1000 + i + 2, 1000 + i)     # A：设备快 2s（未越界）
ck("Tracker：未越界 → 无 breach_since",
   e_a["breach_since"] is None and abs(e_a["offset"] - 2) < 1e-9, str(e_a))
e_b = None
for i in range(4, 8):
    e_b = tr.add("B", 2000 + i + 90, 2000 + i)    # B：设备快 90s（越界）
ck("Tracker：越界 → 记 breach_since（= 够样本后首次越界那条的 rx=2006）",
   e_b["breach_since"] == 2006.0, str(e_b["breach_since"]))
for i in range(8, 12):                            # 继续越界：起点不变
    tr.add("B", 2000 + i + 90, 2000 + i)
ck("Tracker：持续越界不重置起点", tr.get("B")["breach_since"] == 2006.0,
   str(tr.get("B")["breach_since"]))
for i in range(12, 16):                           # 回到正常：清除越界
    tr.add("B", 2000 + i + 1, 2000 + i)
ck("Tracker：回到正常（窗内多数转正）→ 清除 breach_since",
   tr.get("B")["breach_since"] is None, str(tr.get("B")))
snap = tr.snapshot()
ck("Tracker：snapshot 按 SN 分开、互不串台",
   set(snap) == {"A", "B"} and abs(snap["A"]["offset"] - 2) < 1e-9
   and abs(snap["B"]["offset"] - 1) < 1e-9, str({k: v["offset"] for k, v in snap.items()}))
trw = clk.ClockTracker(window=3)
for i in range(10):
    trw.add("W", 5000 + i, 5000 + i)
ck("Tracker：环形窗有上限（window=3 → 只留 3 条样本）",
   trw.get("W")["n"] == 3, str(trw.get("W")["n"]))
ck("Tracker：没见过的 SN → None", trw.get("nobody") is None)

# 并发：`add()` 由上报线程写、`snapshot()` 由 HTTP 线程读（`clock.py` 文档里承诺线程安全）——
# 不测的话「锁」只是注释。4 写线程 × 50 条 + 2 读线程，跑完必须一条不少、无异常。
import threading                                                     # noqa: E402
tc = clk.ClockTracker(window=256, offset_warn=30)
_err = []
_rounds, _writers = 50, 4


def _writer(tid):
    try:
        for i in range(_rounds):
            tc.add("C", 5000 + tid * 1000 + i + 3, 5000 + tid * 1000 + i)
    except Exception as e:                                           # noqa: BLE001
        _err.append(("writer", repr(e)))


def _reader():
    try:
        for _ in range(60):
            snap = tc.snapshot()
            for e in snap.values():
                assert e["offset"] is None or isinstance(e["offset"], float)
    except Exception as e:                                           # noqa: BLE001
        _err.append(("reader", repr(e)))


_ths = [threading.Thread(target=_writer, args=(t,)) for t in range(_writers)]
_ths += [threading.Thread(target=_reader) for _ in range(2)]
for _t in _ths:
    _t.start()
for _t in _ths:
    _t.join(timeout=10)
ck("并发：4 写 × 50 条 + 2 读线程 → 无异常且一条不丢",
   not _err and not any(t.is_alive() for t in _ths) and tc.get("C")["n"] == _rounds * _writers,
   str(_err) + " n=" + str(tc.get("C")["n"]))

print()
if FAILS:
    print(f"时钟可信：{len(FAILS)} 项失败")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("时钟可信测试全部通过")
