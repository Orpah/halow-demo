#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_energy.py — 能量轴（免电池客户端能量模型）单测，离线、纯计算。

覆盖：三参数模型的收支/间隔/级别选择；**"降级只为跟得住人"**（不省电也就不用降）；
`net ≤ 0` 时只花采集电 + 还能撑多久；**没采集就如实沉默**（`interval=None`，不编一个数）；
不主动降 L3；能量轴扫描与头条数字（`min_harvest_mw`）；电量推进 `drain()` 的边界。

跑法：C:\\Python313\\python.exe test_energy.py
"""
import sys

import energy as en

# 控制台是 GBK：打印非 GBK 字符（µ/✓/✗/−…）会 UnicodeEncodeError 崩 → 统一兜住
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


print("== 1. 电压映射（电量 → battery_mv）==")
ck("满电 → 上限电压", en.mv_of(en.STORE_MJ) == en.CELL_FULL_MV)
ck("空电 → 下限电压", en.mv_of(0) == en.CELL_EMPTY_MV)
ck("半电 → 中间值（线性）",
   en.mv_of(en.STORE_MJ / 2) == (en.CELL_EMPTY_MV + en.CELL_FULL_MV) // 2)
ck("越界钳位（超出容量也不超上限、负值不跌破下限）",
   en.mv_of(en.STORE_MJ * 3) == en.CELL_FULL_MV and en.mv_of(-5) == en.CELL_EMPTY_MV)
ck("store=0 不炸（返回下限）", en.mv_of(10, store_mj=0) == en.CELL_EMPTY_MV)

print("== 2. 采集充足：ES256 + 够用的间隔 ==")
p = en.plan(1.0, en.CHARGE0_MJ)                     # net = 0.95 mW
ck("采集 1mW → 用 ES256（不降级）", p["level"] == "ES256" and not p["degraded"], str(p))
ck("间隔 = cost_es/net", abs(p["interval_s"] - 15.0 / 0.95) < 0.01, str(p["interval_s"]))
ck("收支平衡 → silence_in_s 为 null（不会因没电沉默）",
   p["budget_ok"] and p["silence_in_s"] is None)
ck("usable=True（跟得住人）", p["usable"] and p["why"] == "ok")

print("== 3. 采集偏低：降级**只为把间隔拉回可用区** ==")
p = en.plan(0.08, en.CHARGE0_MJ)                    # net = 0.03 → ES256 要 500s（>300 上限）
ck("ES256 撑不住、HS256 够用 → 降级到 HS256 且标明成因",
   p["level"] == "HS256" and p["degraded"] and p["degraded_reason"] == "energy", str(p))
ck("why=degraded_saves（是「为了还能跟住人」，不是「为省电而省电」）",
   p["why"] == "degraded_saves")
ck("两个候选间隔都给出（页面才能解释为什么降）",
   p["interval_es256_s"] == 500.0 and abs(p["interval_hs256_s"] - 166.67) < 0.01, str(p))
ck("降级后 usable=True", p["usable"])
ck("**降级不跨 L3**：级别只可能是 ES256/HS256（能量再紧也不发裸报）",
   p["level"] in ("ES256", "HS256"))

print("== 4. 采集太低：慢到跟不住人（但仍不降 L3） ==")
p = en.plan(0.06, en.CHARGE0_MJ)                    # net = 0.01 → HS256 要 500s
ck("两个级别都超上限 → why=too_slow 且 usable=False",
   p["why"] == "too_slow" and not p["usable"], str(p))
ck("仍然用 HS256（能量紧时没理由挑更贵的算法）", p["level"] == "HS256")
ck("收支其实平衡（只是太慢）→ silence_in_s 仍为 null",
   p["budget_ok"] and p["silence_in_s"] is None, str(p))

print("== 5. 采不敷出：没有可维持间隔（不装出能持续的样子）+ 给出「还能撑多久」 ==")
p = en.plan(0.03, en.CHARGE0_MJ)                    # net = -0.02（比待机还少）
ck("net≤0 → interval_s 为 None（没有可维持的间隔）", p["interval_s"] is None, str(p))
ck("why=deficit（有采集但不够待机）", p["why"] == "deficit")
ck("budget_ok=False（在吃储能）", not p["budget_ok"])
ck("silence_in_s = charge /(sleep - harvest) = 1500/0.02 = 75000s",
   abs(p["silence_in_s"] - 75000.0) < 1.0, str(p["silence_in_s"]))
ck("degraded_reason=energy（标出成因=能量）", p["degraded_reason"] == "energy")
ck("usable=False（跟不住人）", not p["usable"])
ck("★ 硬撑（宁可吃储能也要被听见）：survive_s 给出代价",
   abs(en.survive_s(en.CHARGE0_MJ, 0.0, en.EMERGENCY_INTERVAL_S, "HS256")
       - 1500.0 / (0.05 + 5.0 / 60.0)) < 0.5,
   str(en.survive_s(en.CHARGE0_MJ, 0.0, en.EMERGENCY_INTERVAL_S, "HS256")))
ck("survive_s：收支平衡 → None（不会因没电停，不给 0）",
   en.survive_s(100, 1.0, 60, "HS256") is None)
ck("survive_s：已没电 → 0.0", en.survive_s(0.0, 0.0, 60, "HS256") == 0.0)

print("== 6. 完全没采集：**如实沉默**，不编间隔 ==")
p = en.plan(0.0, en.CHARGE0_MJ)
ck("interval_s 为 None（没有可维持的间隔）", p["interval_s"] is None, str(p))
ck("why=no_energy", p["why"] == "no_energy")
ck("silence_in_s = charge/sleep = 1500/0.05 = 30000s",
   abs(p["silence_in_s"] - 30000.0) < 1.0, str(p["silence_in_s"]))
ck("interval_es256_s / interval_hs256_s 都为 None（不编候选）",
   p["interval_es256_s"] is None and p["interval_hs256_s"] is None)
ck("usable=False（不能假装能定位）", not p["usable"])

print("== 7. 电量不够一次上报：why=empty（现在发不动） ==")
p = en.plan(1.0, 1.0)                               # 电量 1 mJ < cost_es 15 mJ
ck("电量 < 单次耗电 → why=empty", p["why"] == "empty", str(p))
ck("usable=False", not p["usable"])
ck("长期收支仍然平衡 → silence_in_s=None（「现在发不动」与「会不会没电」是两件事）",
   p["silence_in_s"] is None, str(p))
p = en.plan(0.0, 0.0)
ck("没采集且电量耗尽 → silence_in_s=0（确实停了，不是 null）", p["silence_in_s"] == 0.0)

print("== 8. 单调性与可用阈值（能量轴的趋势必须单调）==")
hs = [i * 0.02 for i in range(0, 41)]               # 0 … 0.8 mW
rows = en.sweep(hs, en.CHARGE0_MJ)["rows"]          # sweep 的行带 harvest_mw（plan 本身不带）
ck("每个级别的间隔都随采集增加而**不增**（两条曲线各自单调；None=没有可维持间隔，跳过）",
   all(b["interval_hs256_s"] <= a["interval_hs256_s"] + 1e-9
       for a, b in zip([r for r in rows if r["interval_hs256_s"]],
                       [r for r in rows if r["interval_hs256_s"]][1:]))
   and all(b["interval_es256_s"] <= a["interval_es256_s"] + 1e-9
           for a, b in zip([r for r in rows if r["interval_es256_s"]],
                           [r for r in rows if r["interval_es256_s"]][1:])),
   f"{[(r['harvest_mw'], r['interval_es256_s'], r['interval_hs256_s']) for r in rows[:3]]}…")
ck("级别随采集增加而**升级**（HS256 → ES256，不会倒退）",
   [r["level"] for r in rows] == sorted([r["level"] for r in rows], reverse=True))
ck("同一个级别内部，间隔随采集增加而下降",
   all(b[1] <= a[1] + 1e-9 for a, b in
       zip([(r["level"], r["interval_s"]) for r in rows if r["interval_s"]],
           [(r["level"], r["interval_s"]) for r in rows if r["interval_s"]][1:])
       if a[0] == b[0]))
ck("存在一个「够用」的采集门槛（低采集不可用、高采集可用）",
   not rows[0]["usable"] and rows[-1]["usable"])
first_ok = next(r["harvest_mw"] for r in rows if r["usable"])
ck("门槛落在合理区间（0 < h ≤ 0.8 mW）", 0 < first_ok <= 0.8, f"h={first_ok}")
ck("跨过门槛的第一行是 **HS256 降级**（先用便宜算法达成「跟得住人」），"
   "再到更高采集才升级为 ES256（不降级）",
   next(r["level"] for r in rows if r["usable"]) == "HS256"
   and next(r["level"] for r in rows if r["usable"] and not r["degraded"]) == "ES256"
   and next(r["harvest_mw"] for r in rows if r["usable"] and not r["degraded"]) > first_ok,
   f"第一个可用={first_ok} mW/{next(r['level'] for r in rows if r['usable'])}；"
   f"第一个不降级={next(r['harvest_mw'] for r in rows if r['usable'] and not r['degraded'])} mW")
# 已知且**有意**的特性：升级算法那一下会让间隔跳大一次（“安全优先，只要还能跟得住人”）——
# 把它写下来，避免下次当成 bug（实测：0.08 mW 时 HS256/167s → 0.10 mW 时 ES256/300s）
_up = [(a["harvest_mw"], a["level"], a["interval_s"], b["harvest_mw"], b["level"], b["interval_s"])
       for a, b in zip(rows, rows[1:])
       if a["interval_s"] and b["interval_s"] and b["interval_s"] > a["interval_s"] + 1e-9]
ck("升级那一下间隔会跳大一次（有意：ES256 比 HS256 贵 3 倍），且只发生在级别变化处",
   all(u[1] != u[4] for u in _up) and len(_up) == 1, str(_up))

print("== 9. 能量轴扫描：头条数字 = 持续跟踪所需的最小采集功率 ==")
ax = en.axis(n=13, h_max=1.0)
ck("点数正确（含 0 与 h_max）",
   ax["n"] == 13 and ax["rows"][0]["harvest_mw"] == 0.0
   and ax["rows"][-1]["harvest_mw"] == 1.0)
ck("min_harvest_mw = 第一个 usable 的采集功率",
   ax["min_harvest_mw"] == next(r["harvest_mw"] for r in ax["rows"] if r["usable"]))
ck("无解时不编数：h_max 太小 → min_harvest_mw 为 None",
   en.axis(n=5, h_max=0.001)["min_harvest_mw"] is None)
ck("自定义 cost（真机标定后替换演示值）也能算",
   en.plan(0.5, 1000, cost={"ES256": 30.0, "HS256": 10.0})["interval_s"] > 0)
ck("n<2 被钳到 2（不崩）", en.axis(n=1)["n"] == 2)

print("== 10. drain()：电量推进与边界 ==")
c = en.drain(1000, 0.0, 100, "ES256", 100)          # 采集 0、待机 0.05W·100s=5mJ、上报 15mJ
ck("采集 0 的一拍：只掉待机 + 一次上报（5 + 15 = 20 mJ）", abs(c - 980.0) < 1e-6, str(c))
c = en.drain(1000, 1.0, 10, "ES256", 100)           # 采集 100mJ 进来，每 10s 一次 → 10 次上报 = 150mJ
ck("采集足够时电量上升（100 − 5 − 150 = 945）", abs(c - 945.0) < 1e-6, str(c))
ck("interval_s=None（沉默）→ 只付待机",
   abs(en.drain(1000, 0.0, None, "HS256", 100) - 995.0) < 1e-6)
ck("钳在 [0, store]（不出现负电量、不超容量）",
   en.drain(1, 0.0, 2, "ES256", 100) == 0.0
   and en.drain(en.STORE_MJ, 99.0, 2, "HS256", 100) == en.STORE_MJ)

print()
if FAIL:
    print(f"{len(FAIL)} 项失败: " + "; ".join(FAIL))
    sys.exit(1)
print("能量轴测试全部通过")
