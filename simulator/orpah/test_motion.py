#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_motion.py — 「移动的人」运动模型的单测（纯函数，不依赖 IoTDB/服务）。

关注三件事：
  1) 确定性：位置只由时刻决定（回放可复现）；
  2) 连续性：相邻时刻的位置差 ≈ 速度×时间（不能瞬移）；
  3) RSSI 换算：距离越远越弱、钳位正确、最近路由器判定正确。
跑法：C:\\Python313\\python.exe test_motion.py
"""
import math

import motion

FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


# 演示三台路由器的坐标（与 ui_server._seed_stations 一致）
ROUTERS = [("S1", 30.0, 0.0), ("S2", -15.0, 26.0), ("S3", -15.0, -26.0)]

print("== 1. 构造与几何 ==")
w = motion.Walk()
ck("路线闭合且长度 > 100 m", w.total > 100, f"{w.total:.1f} m")
ck("绕一圈时长 = 总长/速度",
   abs(w.loop_sec - w.total / motion.SPEED_MPS) < 1e-9, f"{w.loop_sec:.0f} s")
try:
    motion.Walk(points=[(0, 0)])
    ok = False
except ValueError:
    ok = True
ck("少于 2 个点报错", ok)

print("== 2. pos 确定性与周期性 ==")
t0 = motion.WALK_EPOCH_MS + 12345
ck("同时刻同位置", w.pos(t0) == w.pos(t0))
loop_ms = w.loop_sec * 1000
p1, p2 = w.pos(t0), w.pos(t0 + int(round(loop_ms)))
ck("一个周期后回到同一点（±1 cm）",
   math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < 0.01, f"{p1} vs {p2}")
ck("与固定 epoch 相位一致（可复现）",
   motion.Walk().pos(t0) == w.pos(t0))

print("== 3. 连续性（不瞬移） ==")
dt = 100.0                                    # 100 ms
worst = 0.0
t = t0
prev = w.pos(t)
for _ in range(400):
    t += dt
    cur = w.pos(t)
    d = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
    worst = max(worst, d)
    prev = cur
ck("单步位移 ≈ 速度×dt", worst <= motion.SPEED_MPS * dt / 1000.0 + 1e-9,
   f"最大 {worst:.4f} m ≤ {motion.SPEED_MPS * dt / 1000.0:.4f} m")
ck("40 秒内确实走动了", math.hypot(*(a - b for a, b in
   zip(w.pos(t), w.pos(t0)))) > 10, f"{(t - t0) / 1000:.0f} s")

print("== 4. RSSI 路径损耗换算 ==")
ck("1 m 处 ≈ 参考强度 A", motion.path_loss(1.0) == int(round(motion.RSSI_A)),
   str(motion.path_loss(1.0)))
ck("0 m 不炸（下限 1 m）", motion.path_loss(0.0) == motion.path_loss(1.0))
seq = [motion.path_loss(d) for d in (1, 5, 10, 30, 100, 1000)]
ck("距离越远越弱（单调递减）", all(a > b for a, b in zip(seq, seq[1:])), str(seq))
ck("返回整数 dBm", all(isinstance(v, int) for v in seq))
ck("超远钳到下限", motion.path_loss(1e9) == motion.RSSI_MIN, str(motion.path_loss(1e9)))
ck("过近按 1 m 算（不放大、不报错）",
   motion.path_loss(0.001) == motion.path_loss(1.0), str(motion.path_loss(0.001)))
ck("A 高于上限时钳到上限",
   motion.path_loss(1.0, A=-20) == motion.RSSI_MAX, str(motion.path_loss(1.0, A=-20)))

print("== 5. 多路由器一致（演示数据可用性） ==")
lo, hi = 999, -999
for k in range(240):                          # 采样 8 分钟（每 2 s 一个上报点）
    t = t0 + k * 2000
    for sid, sx, sy in ROUTERS:
        r = w.rssi_to(t, sx, sy)
        lo, hi = min(lo, r), max(hi, r)
ck("RSSI 落在 -90..-40 dBm（像真的）", -90 <= lo and hi <= -40, f"{lo}..{hi} dBm")
ck("没有触到钳位边界（说明距离合理）",
   lo > motion.RSSI_MIN and hi < motion.RSSI_MAX, f"{lo}..{hi}")
dmin, dmax = 999, 0
for k in range(240):
    t = t0 + k * 2000
    for sid, sx, sy in ROUTERS:
        d = motion.dist(*w.pos(t), sx, sy)
        dmin, dmax = min(dmin, d), max(dmax, d)
ck("人到各路由器距离 1..80 m", 1 <= dmin and dmax <= 80, f"{dmin:.1f}..{dmax:.1f} m")
ck("人不是静止的（8 分钟内走遍路线）",
   len({tuple(round(v, 1) for v in w.pos(t0 + k * 2000)) for k in range(240)}) > 100)

print("== 6. 最近路由器（设备链路的 AP） ==")
bad = []
for k in range(200):                          # 沿路线扫一遍，最近台必须真的最近
    t = t0 + k * 3000
    pos = w.pos(t)
    sid, rssi = w.nearest(t, ROUTERS)
    want = min(ROUTERS, key=lambda r: motion.dist(*pos, r[1], r[2]))
    if sid != want[0] or rssi != motion.path_loss(motion.dist(*pos, want[1], want[2])):
        bad.append((t, sid, want[0], rssi))
ck("nearest 始终等于几何最近的站位，且 rssi 一致", not bad,
   f"不一致 {len(bad)} 次：{bad[:2]}")
sid, rssi = w.nearest(t0, ROUTERS)
ck("空站位表不炸", w.nearest(t0, []) == (None, None))

print("== 7. 默认单例 ==")
ck("default() 复用同一实例", motion.default() is motion.default())

print()
if FAIL:
    print(f"失败 {len(FAIL)} 项：" + "；".join(FAIL))
    raise SystemExit(1)
print("全部通过")
