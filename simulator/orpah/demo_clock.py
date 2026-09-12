#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_clock.py — 设备时钟偏移/漂移估计演示（`clock.py`，纯计算，几毫秒跑完“几小时”）

**为什么演示要看这个**：生产里「设备时钟准不准」只能靠「设备自报 ts」与「服务器接收时刻」
反推，而这两者的差里混着三样东西：真实时钟偏差（offset）、晶振漂移（drift, ppm 级）、
以及**整数秒时间戳的量化噪声**（设备 `int(time.time())` 截断 → 单条偏移在 1s 宽的格子里连续抖动，
sd≈0.29s，比 ppm 级漂移大得多）。这个演示用**合成观测**把三样东西分开看：
什么时候能给出漂移、什么时候只能说“还看不出来”。

场景（全部确定性）：

    A 时钟准      1s 上报 · 1h        → offset≈-0.5s（整数秒截断的固有偏置），漂移「噪声里看不出趋势」
    B 晶振偏快    +200ppm · 1h        → 漂移 ≈ +200ppm（ppm 级要这么长的基线才分得出来）
    C 同数据只看前 2min（+200ppm）    → 漂移「基线不足」——不编数，也不谎称是噪声
    D 设备被拨表 +120s                → offset 立刻读到 +119.5s；漂移「基线不足」（跳变后的段还短）
    E 拨表后又跑了 20min（+2000ppm）  → 漂移重新可用，且**只用跳变后的段**（不被跳变前污染）
    F 一条乱报（重启垃圾 ts，+6000s） → offset 与漂移都不受影响（中位数 + 分箱中位数）

最后打印**分辨率随基线变好**（1s 上报下 60s → ~4000ppm、10min → ~110ppm、1h → ~9ppm），
用来解释「为什么需要长基线」而不是拿 60s 窗的噪声当漂移报警。

运行：C:\\Python313\\python.exe demo_clock.py
"""
import os
import random
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import clock as clk                                                    # noqa: E402

FAILS = []
T0 = 1_700_000_000          # 固定 epoch → 结果可复现


def ck(name, cond, extra=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def obs(n, dt=1.0, drift_ppm=0.0, offset=0.0, seed=1, t_off=0.0):
    """造观测 `[(rx_ts, device_ts), …]` —— **照真实系统的模型**，别自己发明：

    - `rx`（服务器接收时刻）= 连续（`time.time()` 有小数，上报相位在周期内随机）；
    - 设备自报 `ts` = **整数秒**（`client.py` 里 `int(time.time())`，真机 RTC 也是秒粒度）；
    → 单条偏移 = 设备 − 接收，在 `[offset−1, offset)` 上**连续**均匀抖动（sd≈0.29s）。
    这个 1 秒粒度就是「ppm 级漂移难估」的根源：`σ_slope` 基本全来自它。

    `t_off`：本段从整段时间轴的哪一秒开始（`drift_ppm` 相对**本段开头**算）——
    拼“拨表前后两段”时必须给，否则两段在时间上重叠、序列就不是一段真历史了
    （踩过：重叠数据会让跳变检测看不出跳变，然后我把锅扣在估计器头上）。
    """
    rnd = random.Random(seed)
    t0 = T0 + t_off
    out = []
    for i in range(n):
        rx = t0 + i * dt + rnd.uniform(0.0, dt)
        dev = int(rx + offset + drift_ppm * 1e-6 * (rx - t0))
        out.append((rx, float(dev)))
    return out


def show(tag, est):
    dr = est.get("drift_ppm")
    print(f"  {tag:<22} offset={est.get('offset'):>8.3f}s  drift="
          + (f"{dr:>9.1f}ppm" if dr is not None else f"—（{est.get('drift_why')}）")
          + f"   n={est.get('n')} 拟合段={est.get('drift_n')}条/{est.get('drift_span')}s")


def near(name, got, want, tol):
    ck(name, got is not None and abs(got - want) <= tol, f"got={got} want={want}±{tol}")


print("=" * 84)
print("设备时钟估计演示（clock.py）：1s 上报 · 设备时间戳是整数秒（1s 量化噪声）")
print("=" * 84)
print(f"参数：DRIFT_MIN_SPAN={clk.DRIFT_MIN_SPAN:g}s · DRIFT_SIGMA_K={clk.DRIFT_SIGMA_K:g} · "
      f"箱数≤{clk.DRIFT_BINS}（每箱≥{clk.DRIFT_BIN_MIN} 条）· 环形窗={clk.DEFAULT_WINDOW} 条")

print("\n--- A 时钟准（跑 1h）---")
est = clk.estimate(obs(3601), jump_sec=30)
show("A 时钟准 1h", est)
near("A：offset ≈ -0.5s（整数秒截断的固有偏置，不是设备真的慢 0.5s）", est["offset"], -0.5, 0.2)
ck("A：漂移不给数 —— 原因=noise（噪声里看不出趋势，不编 0 也不编别的）",
   est["drift_ppm"] is None and est["drift_why"] == "noise", str(est))

print("\n--- B 晶振偏快 +200ppm（跑 1h）---")
est = clk.estimate(obs(3601, drift_ppm=200), jump_sec=30)
show("B +200ppm 1h", est)
near("B：offset ≈ +0.2s（当前时刻的偏差：漂移 1h 累计 +0.72s − 截断 0.5s）",
     est["offset"], 0.22, 0.4)
near("B：漂移估出 +200ppm（晶振级，短窗做不到）", est["drift_ppm"], 200, 30)

print("\n--- C 同一份数据只看前 2min ---")
est = clk.estimate(obs(3601, drift_ppm=200)[:120], jump_sec=30)
show("C 只取前 2min", est)
ck("C：漂移不给数 —— 原因=min_span（基线不足；与“噪声”区分开，否则没法判断该等多久）",
   est["drift_ppm"] is None and est["drift_why"] == "min_span", str(est))

print("\n--- D 设备被拨表 +120s（跳变刚发生）---")
step = obs(700) + obs(30, offset=120.0, seed=2, t_off=700)
est = clk.estimate(step, jump_sec=30)
show("D 拨表 +120s", est)
near("D：offset 立刻读到 +119.5s（只看最近 8 条）", est["offset"], 119.5, 0.3)
ck("D：漂移不给数 —— 原因=min_span（跳变后的段只有 30s，不够长）",
   est["drift_ppm"] is None and est["drift_why"] == "min_span", str(est))

print("\n--- E 拨表后又跑了 20min（+2000ppm 的坏晶振）---")
step2 = obs(700) + obs(1200, offset=120.0, drift_ppm=2000, seed=3, t_off=700)
est = clk.estimate(step2, jump_sec=30)
show("E 拨表 + 20min", est)
near("E：offset ≈ 121.9s（拨了 120s，之后又漂快了 2.4s，减掉截断 0.5s）", est["offset"], 121.9, 0.4)
near("E：漂移重新可用 ≈ +2000ppm", est["drift_ppm"], 2000, 40)
ck("E：拟合**只用跳变后的段**（跳变前的旧基线被排除）",
   est["drift_n"] < est["n"] and est["drift_span"] >= clk.DRIFT_MIN_SPAN, str(est))

print("\n--- F 一条乱报（重启后的垃圾 ts，+6000s）---")
junk = obs(3601, drift_ppm=200)
junk[1800] = (junk[1800][0], junk[1800][1] + 6000)
est = clk.estimate(junk, jump_sec=30)
show("F 含一条乱报", est)
near("F：offset 不受影响（同 B 的当前偏差，中位数压住乱报）", est["offset"], 0.22, 0.4)
near("F：漂移不受影响（分箱中位数把乱报挡在箱外）", est["drift_ppm"], 200, 30)
ck("F：乱报不被误判成“跳变”（否则漂移会被清空重攒）", est["drift_why"] is None, str(est))

print("\n--- 分辨率：真漂移=0 的数据，不同基线下的斜率噪声（结论都该是“看不出”）---")
for span in (60, 600, 3600):
    data = obs(span + 1, seed=span)
    est = clk.estimate(data, jump_sec=30)
    pts = clk._bin_medians([(float(r), float(d) - float(r)) for r, d in data])
    sig_ppm = (clk._fit(pts)[3] or 0.0) * 1e6
    verdict = f"看出 {est['drift_ppm']:.0f}ppm" if est["drift_ppm"] is not None \
        else f"看不出（{est['drift_why']}）"
    print(f"  基线 {span:>5}s：σ_slope ≈ {sig_ppm:>6.0f}ppm → 认定门限 {clk.DRIFT_SIGMA_K:g}σ ≈ "
          f"{sig_ppm * clk.DRIFT_SIGMA_K:>6.0f}ppm；本次结论={verdict}")
    ck(f"无漂移时 {span}s 基线不该报出漂移", est["drift_ppm"] is None, str(est))

print()
if FAILS:
    print(f"结果: [FAIL] 时钟漂移演示 {len(FAILS)} 项失败")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("结果: [PASS] 时钟漂移演示全部通过")
