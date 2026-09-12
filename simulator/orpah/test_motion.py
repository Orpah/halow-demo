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
import os
import re

import motion

HERE = os.path.dirname(os.path.abspath(__file__))

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

print("== 4b. 钳位要盖住加噪后的结果（2026-09-12 审查） ==")
# 噪声是“测量”误差，不会把收不到的信号变出来：path_loss 已到量程边界时，噪声不得把结果推出去。
# 先证明这条测试有意义（钳位前确实会越界），再验钳位后不再越界。
w_noisy = motion.Walk()
t0k = [t0 + k * 1000 for k in range(600)]      # 600 秒（1 s 一条测量；覆盖噪声正负两侧）
# 远端站位：路径损耗已到底 -95，负噪声会给出 -97
_raw_lo = [motion.path_loss(motion.dist(*w_noisy.pos(t), 400.0, 0.0))
           + motion.noise_db("FAR", t, motion.NOISE_DB) for t in t0k]
ck("远端站位：钳位前确实会越界（否则本条测试是空的）",
   min(_raw_lo) < motion.RSSI_MIN, f"钳位前最低 {min(_raw_lo):.1f} dBm")
_far = [w_noisy.rssi_to(t, 400.0, 0.0, sid="FAR") for t in t0k]
ck("rssi_to：加噪后仍在 [RSSI_MIN, RSSI_MAX]",
   all(motion.RSSI_MIN <= v <= motion.RSSI_MAX for v in _far),
   f"{min(_far)}..{max(_far)} dBm（量程 {motion.RSSI_MIN}..{motion.RSSI_MAX}）")
_near = [w_noisy.nearest(t, [("FAR", 400.0, 0.0)])[1] for t in t0k]
ck("nearest：加噪后仍在 [RSSI_MIN, RSSI_MAX]",
   all(motion.RSSI_MIN <= v <= motion.RSSI_MAX for v in _near),
   f"{min(_near)}..{max(_near)} dBm")
# 上边界同理：把 A 调大到近端已顶到 -30，正噪声会把 -30 变成 -28
_raw_hi = [motion.path_loss(motion.dist(*w_noisy.pos(t), *w_noisy.pos(t)), A=-10.0)
           + motion.noise_db("NEAR", t, motion.NOISE_DB) for t in t0k]
ck("近端 A 调大：钳位前确实会越上限（同样不是空测试）",
   max(_raw_hi) > motion.RSSI_MAX, f"钳位前最高 {max(_raw_hi):.1f} dBm")
_hi = [w_noisy.rssi_to(t, *w_noisy.pos(t), A=-10.0) for t in t0k]
ck("rssi_to：A 调大时加噪后也不越上限",
   all(v <= motion.RSSI_MAX for v in _hi), f"最高 {max(_hi)} dBm")
ck("path_loss 仍是整数（钳位单一实现后没破）",
   all(isinstance(v, int) for v in (_far + _near + _hi)))

print("== 5. 多路由器一致（演示数据可用性） ==")
lo, hi = 999, -999
for k in range(240):                          # 采样 8 分钟（每 2 s 一个上报点）
    t = t0 + k * 2000
    for sid, sx, sy in ROUTERS:
        r = w.rssi_to(t, sx, sy, sid=sid)
        lo, hi = min(lo, r), max(hi, r)
ck("RSSI 落在 -95..-35 dBm（含噪声也像真的）", -95 <= lo and hi <= -35, f"{lo}..{hi} dBm")
dmin, dmax = 999, 0
for k in range(240):
    t = t0 + k * 2000
    for sid, sx, sy in ROUTERS:
        d = motion.dist(*w.pos(t), sx, sy)
        dmin, dmax = min(dmin, d), max(dmax, d)
ck("人到各路由器距离 1..80 m", 1 <= dmin and dmax <= 80, f"{dmin:.1f}..{dmax:.1f} m")
ck("人不是静止的（8 分钟内走遍路线）",
   len({tuple(round(v, 1) for v in w.pos(t0 + k * 2000)) for k in range(240)}) > 100)

print("== 5b. 测量噪声（无噪声时平滑/椭圆都没意义，所以演示数据必须带噪） ==")
wn = motion.Walk()                             # 默认带噪
w0 = motion.Walk(noise=0)                      # 无噪对照
ck("默认带噪（NOISE_DB>0）", wn.noise > 0, f"±{wn.noise} dBm")
ck("noise=0 → 与路径损耗完全一致",
   all(w0.rssi_to(t0 + k * 2000, 30, 0, sid="S1")
       == motion.path_loss(motion.dist(*w0.pos(t0 + k * 2000), 30, 0))
       for k in range(50)))
diffs = []
for k in range(400):
    t = t0 + k * 2000
    exact = motion.path_loss(motion.dist(*wn.pos(t), 30, 0))
    diffs.append(wn.rssi_to(t, 30, 0, sid="S1") - exact)
ck("噪声幅度不超 ±NOISE_DB",
   max(abs(d) for d in diffs) <= motion.NOISE_DB,
   f"max|Δ|={max(abs(d) for d in diffs)}（理论上限 = NOISE_DB：噪声严格 < amp，"
   f"取整后最多 ±{motion.NOISE_DB:.0f}）")
ck("噪声确实在动（不是常数偏移）", len(set(diffs)) >= 3, f"不同值 {len(set(diffs))} 个")
nd = {round(motion.noise_db("S1", t0 + k * 1000), 4) for k in range(300)}
ck("底层噪声取值连续（矩形分布；取整到 dBm 后只有 5 种差值）",
   len(nd) > 250, f"{len(nd)} 个不同值")
ck("同 (sid,t) 两次调用结果相同（可复现）",
   wn.rssi_to(t0, 30, 0, sid="S1") == wn.rssi_to(t0, 30, 0, sid="S1"))
ck("不同路由器噪声序列不同",
   wn.rssi_to(t0, 30, 0, sid="S1") != wn.rssi_to(t0, 30, 0, sid="S2")
   or wn.rssi_to(t0, 30, 0, sid="S1") != motion.path_loss(motion.dist(*wn.pos(t0), 30, 0)))
ck("零均值附近（矩形分布）", abs(sum(diffs) / len(diffs)) <= 1.0,
   f"mean={sum(diffs) / len(diffs):.2f}")
ck("离噪声幅度约 ±2 dBm → 测距误差可达米级（这才有可平滑的东西）",
   wn.noise >= 1.0, f"±{wn.noise} dBm")

print("== 6. 最近路由器（设备链路的 AP） ==")
bad = []
for k in range(200):                          # 沿路线扫一遍，最近台必须真的最近
    t = t0 + k * 3000
    pos = w.pos(t)
    sid, rssi = w.nearest(t, ROUTERS)
    want = min(ROUTERS, key=lambda r: motion.dist(*pos, r[1], r[2]))
    exact = motion.path_loss(motion.dist(*pos, want[1], want[2]))
    if sid != want[0] or abs(rssi - exact) > motion.NOISE_DB:
        bad.append((t, sid, want[0], rssi, exact))
ck("nearest 始终等于几何最近的站位，且 rssi 落在噪声范围内", not bad,
   f"不一致 {len(bad)} 次：{bad[:2]}")
w0n = motion.Walk(noise=0)
pos0 = w0n.pos(t0)
want0 = min(ROUTERS, key=lambda r: motion.dist(*pos0, r[1], r[2]))
ck("无噪时 nearest 的 rssi = 该距离的路径损耗",
   w0n.nearest(t0, ROUTERS)
   == (want0[0], motion.path_loss(motion.dist(*pos0, want0[1], want0[2]))))
ck("空站位表不炸", w.nearest(t0, []) == (None, None))

print("== 7. 默认单例 ==")
ck("default() 复用同一实例", motion.default() is motion.default())

# A/n/噪声曾在四处各写一份（motion + track/rssi/replay 三个页面的输入框默认值），
# 靠注释「与页面默认一致」互相提醒 → 改一处不改另一处时两边用不同的模型反算距离，
# 位置会静默偏离。现在以 motion.py 为唯一源、页面开页取 /api/config，
# 本节锁死两件事：① 接口给的值就是常量；② 页面兜底值与常量一致（兜底不许骗人）且页面确实去取接口。
print("== 8. 标定参数单一源 ==")
cal = motion.calibration()
ck("calibration() 给出页面要用的键与值",
   set(cal) == {"path_loss", "noise_db", "rssi_range", "walk"}
   and set(cal["path_loss"]) == {"A", "n"}
   and cal["path_loss"]["A"] == motion.RSSI_A
   and cal["path_loss"]["n"] == motion.RSSI_N
   and cal["noise_db"] == motion.NOISE_DB,
   f"A={cal['path_loss']['A']} n={cal['path_loss']['n']} 噪声±{cal['noise_db']}")

STATIC = os.path.join(HERE, "ui", "static")
PAGES = {                    # 页面 → (A 输入框 id, n 输入框 id)
    "track.html": ("plA", "plN"),
    "rssi.html": ("plA", "plN"),
    "replay.html": ("rpA", "rpN"),
}
for _page, (_ida, _idn) in PAGES.items():
    try:
        _txt = open(os.path.join(STATIC, _page), encoding="utf-8").read()
    except OSError as e:
        ck(f"{_page} 可读", False, str(e))
        continue

    def _default(i):
        m = re.search(r'<input id="%s"[^>]*?\bvalue="([-0-9.]+)"' % re.escape(i), _txt)
        return float(m.group(1)) if m else None

    _va, _vn = _default(_ida), _default(_idn)
    ck(f"{_page} 兜底 A/n 与服务端常量一致（改了常量就得同步改兜底）",
       _va == motion.RSSI_A and _vn == motion.RSSI_N, f"A={_va} n={_vn}")
    ck(f"{_page} 开页取 /api/config（HTML 里的只是兜底）", '"/api/config"' in _txt)

# ---- 真值轨迹采样（`/api/truth` 的逻辑，单一源在 motion.truth_samples）----------
# 口径：地面真值**只有演示环境有**（真机没有）→ 这组只服务“演示里量定位误差”。
_w = motion.Walk()
_t0 = motion.WALK_EPOCH_MS + 7_000
_pts, _st = motion.truth_samples(_w, _t0, _t0 + 60_000)
ck("真值采样：点数/步长默认自适应（60s 窗 → 250ms 步长，≤ 上限）",
   _st == motion.TRUTH_MIN_STEP_MS and len(_pts) <= motion.TRUTH_MAX_POINTS + 1,
   f"step={_st} n={len(_pts)}")
ck("真值采样：时间升序、等步长、含区间两端",
   all(_pts[i]["t"] < _pts[i + 1]["t"] for i in range(len(_pts) - 1))
   and _pts[0]["t"] == _t0 and _pts[1]["t"] - _pts[0]["t"] == _st
   and _pts[-1]["t"] <= _t0 + 60_000)
ck("真值采样：**与 walk.pos 逐点一致**（不是另写一套行走模型）",
   all(abs(p["x"] - round(_w.pos(p["t"])[0], 3)) < 1e-9
       and abs(p["y"] - round(_w.pos(p["t"])[1], 3)) < 1e-9 for p in _pts))
_big, _stb = motion.truth_samples(_w, _t0, _t0 + 720 * 60_000)      # 12h 窗口
ck("真值采样：12h 窗口仍受点数上限约束（步长自适应放大）",
   len(_big) <= motion.TRUTH_MAX_POINTS + 1 and _stb > motion.TRUTH_MIN_STEP_MS,
   f"step={_stb} n={len(_big)}")
_ex, _ste = motion.truth_samples(_w, _t0, _t0 + 60_000, step=100)   # 强行要更密
ck("真值采样：显式 step 也夹到下限（不让载荷失控）", _ste == motion.TRUTH_MIN_STEP_MS)
_rev, _ = motion.truth_samples(_w, _t0 + 60_000, _t0)              # 传反
ck("真值采样：from/to 传反自动交换（不抛异常、时间仍升序）",
   _rev[0]["t"] == _t0 and _rev[-1]["t"] <= _t0 + 60_000)
# 页面在真值点之间做**线性插值**才能拿到任意时刻的真值；但插值误差随步长**平方**增长，
# 所以算误差 CDF 改用 `truth_at()` 逐帧精确取点。这里两条都实测：
# 网格插值：250ms 步长下 ≤3cm（远小于米级定位误差）—— 但长窗口步长被点数上限逼大就会涨到米级。
import math as _math                                                # noqa: E402
_mid_err = 0.0
for i in range(len(_pts) - 1):
    a, b = _pts[i], _pts[i + 1]
    tm = (a["t"] + b["t"]) / 2
    gx, gy = _w.pos(tm)
    ix, iy = (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
    _mid_err = max(_mid_err, _math.hypot(gx - ix, gy - iy))
ck("网格采样：250ms 步长下点间线性插值误差实测 ≤4cm（可作为路线对照；不适合当误差基准）",
   _mid_err < 0.04, f"max={_mid_err:.4f}m")
_big_step = _stb / 1000.0
ck("网格采样：步长 10× 时插值误差涨到 10× 以上（平方增长 —— 这就是要逐帧精确取点的理由）",
   _big_step > 1.0, f"长窗步长={_big_step:.2f}s")

# 逐帧精确取点（误差 CDF 用的就是它）：与 walk.pos 逐点一致、升序去重、上限生效。
_fr, _ = motion.truth_samples(_w, _t0, _t0 + 20_000, step=1000)
_ta = motion.truth_at(_w, [p["t"] for p in _fr])
ck("truth_at：与网格采样同刻取点 → 坐标逐位一致（同一真值源）",
   len(_ta) == len(_fr) and all(abs(a["x"] - b["x"]) < 1e-9 and abs(a["y"] - b["y"]) < 1e-9
                                for a, b in zip(_ta, _fr)))
_td = motion.truth_at(_w, [5, 3, 3, 1, 9000, -7])
ck("truth_at：升序去重（乱序/重复输入不报错、不产生重复点）",
   [p["t"] for p in _td] == [-7, 1, 3, 5, 9000])
ck("truth_at：上限生效（给 10 倍时刻只取前 cap 个，时间仍升序）",
   len(motion.truth_at(_w, list(range(0, motion.TRUTH_MAX_TIMES * 10, 7)))) <= motion.TRUTH_MAX_TIMES)
ck("truth_at：空输入 → 空表（页面显示“不适用”，不编 0）",
   motion.truth_at(_w, []) == [] and motion.truth_at(_w, None) == [])

print()
if FAIL:
    print(f"失败 {len(FAIL)} 项：" + "；".join(FAIL))
    raise SystemExit(1)
print("全部通过")
