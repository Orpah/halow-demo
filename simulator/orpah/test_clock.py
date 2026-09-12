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

print()
if FAILS:
    print(f"时钟可信：{len(FAILS)} 项失败")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("时钟可信测试全部通过")
