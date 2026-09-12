#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""energy.py — 免电池/低功耗客户端的**能量轴**（纯计算，2026-09-13）

## 为什么有这个东西（用户 2026-09-13 定方向）

ORPAH 的终端设定是**免电池可穿戴**（项链/鞋/钮扣，靠运动/光/射频取能）。对免电池设备，
真正的约束不是信号距离，而是**能量预算**：每次上报都要花电（唤醒 → 关联/发帧 → 签名），
而采集功率是**波动的**（进屋、被衣服盖住、站着不动 → 采集骤降）。于是「多久报一次」
「还签不签得起 ES256」不再是常数，而是**能量的函数**（ROADMAP §一 那句话）。

最要命的一点：**沉默有两种相反的成因** —— 设备**没电了**（等它取能）还是**被藏/被干扰**
（立刻搜）。演示里两者原来都只触发「长未上报」，找人场景下处置正好相反。本模块给出
**可算的判据**（当前电量能撑多久），让服务端能把两种沉默分开（`alerts.py` 里做）。

## 模型（**三个参数**，2026-09-13 用户选定「A. 三参数单源模型」）

| 参数 | 含义 |
|---|---|
| `harvest_mw` | 平均**采集**功率（mW）——可调，是能量轴的横轴 |
| `store_mj`   | **储能**容量（mJ；电容/电池），当前电量 `charge_mj` |
| `cost_mj`    | **单次上报**耗电（mJ；唤醒+发帧+签名），按级别不同（ES256 比 HS256 贵） |

派生量：净功率 `net = harvest - sleep`（`sleep_mw` = 待机功耗，否则设备永不掉电）；
可维持间隔 `cost / net`；**还能撑多久**（`silence_in_s`）= 在吃储能时 `charge / 缺口`。

## ⚠ 参数是**演示标定值，不是实测**

`COST_MJ` / `SLEEP_MW` / `CELL_*_MV` / `STORE_MJ` 全是**凑出来能演示的量级**，
**没有**真机实测依据（真机标定要上机测唤醒/发帧/签名的能耗，属阶段二）。所以：
- 任何文档/页面上引用这些数都要标「演示参数」；
- 结论只用于演示**趋势**（采集越低 → 间隔越长 → 级别越低 → 最终沉默），不能当时长承诺。

## 级别与间隔策略（用户 2026-09-13 选「A. 允许降级，但必须显式标注」）

先说清楚 **`P = max(net, 0)` = 可用于上报的功率**（净功率：采集 − 待机）。规则表：

| `P` | 条件 | 级别 | 间隔 | `why` |
|---|---|---|---|---|
| `> 0` | ES256 维持的间隔 ≤ `MAX_USEFUL_INTERVAL_S` | ES256 | `cost_es/P` | `ok` |
| `> 0` | ES256 太长、HS256 够用 | **HS256（降级）** | `cost_hs/P` | `degraded_saves` |
| `> 0` | 两个级别都超过可用上限 | HS256 | `cost_hs/P` | `too_slow` |
| `= 0` | 还有点采集（`harvest > 0`） | HS256 | **`None`** | `deficit` |
| `= 0` | 完全没采集 | HS256 | **`None`** | `no_energy` |

1. **降级要"为了还能跟住人"，不是"为了省电而省电"**：省电本身不是目的，间隔长到
   `> MAX_USEFUL_INTERVAL_S` 就等于跟不住人（追踪失去意义），这时用便宜算法把间隔拉回可用区，
   是拿**一点信任度**换**还能找到人**。所以只有第 2 行叫 `degraded_saves`，且
   `degraded_reason="energy"` 明确标出 —— **不是偷偷降**（服务端据此出告警，页面写清"因省电而降级"）。
2. **不主动降到 L3（无签名）**：L3 按 §8.3 不能用于人员确认 —— 那是「找不到人时反而把人丢掉」
   的坏交易。能量再紧也只到 HS256；真到发不动，就**如实沉默**并让服务端看见
   （`silence_in_s` 告诉它"我预计什么时候没电"），而不是发一条不可信的裸报。
3. **`P = 0` 是一个独立的"没有可维持间隔"状态**（`interval_s=None`），
   不是"慢慢报"：采集连**待机**都不够时，任何固定间隔都在吃储能，"慢慢报"与"快点报"
   只是"把储能拿去发报"还是"把储能拿去待机"的分别 —— 模型不该替调用方拍这个板，
   而是**给事实**（`silence_in_s` = 还能撑多久）。想"宁可吃储能也要被听见"的调用方用
   `EMERGENCY_INTERVAL_S` + `survive_s()` 硬撑，并把截止时间告诉服务端。
   这样也让这条曲线**单调**（采集↑ → 间隔↓），不会在 `net ≈ 0` 处跳变。
4. **已知且有意**：采集增加到足以用 ES256 时会**升级算法**，而 ES256 比 HS256 贵 3 倍
   → 那一下间隔会**跳大一次**（实测：0.08 mW 时 HS256/167s → 0.10 mW 时 ES256/300s）。
   所以"间隔随采集单调下降"只在**同一级别内部**成立；跨级是"便宜的算法换密度"与
   "强的算法换安全"的取舍，本模型按**安全优先（只要还能跟得住人）**选。
   `test_energy.py` 把这个跳跃锁成已知行为，避免下次被当成 bug。
5. 覆盖规则：电量连**一次**上报都不够（`charge < cost`）→ `why="empty"`（现在发不动；
   长期收支可能仍然平衡，两者不矛盾）。

## 只算不改

本模块**不碰**客户端/服务端状态，也不改任何报文语义（能量状态沿用 Orpah ID §5 的
`payload.battery_mv`，用户 2026-09-13 选「A. 沿用该字段」）。`drain()` 只做电量推进，
由调用方（模拟器）决定何时用。
"""

# ---- 演示参数（**未按真机实测标定**；见模块头「⚠ 参数」） ----
SLEEP_MW = 0.05                      # 待机功耗（mW）：MCU 深睡眠 + 采集器静态损耗
COST_MJ = {"ES256": 15.0, "HS256": 5.0}   # 单次上报耗电（mJ）：ES256 比 HS256 贵约 3 倍
MIN_INTERVAL_S = 2.0                 # 间隔下限（再快服务器/空口也撑不住，且无意义）
MAX_USEFUL_INTERVAL_S = 300.0        # 间隔上限：超过就"跟不住人"（追踪语义上限）
EMERGENCY_INTERVAL_S = 60.0          # `interval_s=None`（采不敷出）时演示用的"硬撑"间隔：
#                                      调用方想"宁可吃储能也要被听见"时用它 + survive_s() 算能撑多久
STORE_MJ = 2000.0                    # 默认储能容量（mJ）
CHARGE0_MJ = 1500.0                  # 默认初始电量（mJ）
CELL_EMPTY_MV = 3000                 # 电压↔电量映射：空
CELL_FULL_MV = 4200                  # 电压↔电量映射：满（单节锂电/超级电容的演示近似）

LEVEL_ES = "ES256"
LEVEL_HS = "HS256"


def mv_of(charge_mj, store_mj=STORE_MJ, empty_mv=CELL_EMPTY_MV, full_mv=CELL_FULL_MV):
    """电量（mJ）→ 电压（mV，整数）。线性近似，只为让报文里的 `battery_mv` 有意义。

    **反过来说明**：服务端**不**从电压反推"还剩多少电"（电压曲线与电池类型强相关），
    它只用电压做低/临界两档判断（阈值可配）；精确的"还能撑多久"由设备侧模型给
    （页面/审计看 `silence_in_s`）。报文里沿用 `payload.battery_mv`，不新增字段。
    """
    if store_mj <= 0:
        return int(empty_mv)
    frac = max(0.0, min(1.0, float(charge_mj) / float(store_mj)))
    return int(round(empty_mv + (full_mv - empty_mv) * frac))


def plan(harvest_mw, charge_mj, store_mj=STORE_MJ, sleep_mw=SLEEP_MW, cost=None,
         min_interval_s=MIN_INTERVAL_S, max_useful_s=MAX_USEFUL_INTERVAL_S):
    """能量 → 可执行策略：用哪个级别、多久报一次、还能撑多久、会不会沉默。

    返回（字段都有明确含义，**无值给 `None` 不给 0**）：

    | 字段 | 含义 |
    |---|---|
    | `level` | 选定的算法级别（`ES256` / `HS256`） |
    | `degraded` / `degraded_reason` | 是否因能量降级 / 成因（`"energy"` 或 `None`） |
    | `interval_s` | 选定策略的可维持上报间隔（秒） |
    | `interval_es256_s` / `interval_hs256_s` | 两个候选级别的间隔（解释"为什么降级"用；`None`=净功率不足算不出） |
    | `net_mw` | 净功率（采集 − 待机） |
    | `budget_ok` | 当前策略是否收支平衡（`False` = 在吃储能，会走向沉默） |
    | `silence_in_s` | 还能撑多久（秒）；`None` = 收支平衡，不会因没电沉默 |
    | `usable` | 是否持续“跟得住人”（间隔 ≤ `max_useful_s` 且收支平衡且电量够发下一条） |
    | `why` | 机器码：`ok` / `degraded_saves` / `too_slow` / `deficit` / `no_energy` / `empty` |

    `interval_s=None` = **没有可维持的间隔**（采集连待机都不够）：调用方应让它**如实沉默**，
    或者（如果选择"宁可吃储能也要被听见"）用 `EMERGENCY_INTERVAL_S` + `survive_s()` 硬撑，
    并把硬撑的截止时间告诉服务端。
    """
    cost = cost or COST_MJ
    harvest_mw = float(harvest_mw)
    charge_mj = float(charge_mj)
    net = harvest_mw - float(sleep_mw)
    usable_mw = max(net, 0.0)          # 可用于上报的功率（净功率为负 → 一点都匀不出来）
    c_es, c_hs = float(cost[LEVEL_ES]), float(cost[LEVEL_HS])

    if usable_mw > 0:
        iv_es = max(c_es / usable_mw, min_interval_s)
        iv_hs = max(c_hs / usable_mw, min_interval_s)
        if iv_es <= max_useful_s:
            level, interval, why, degraded = LEVEL_ES, iv_es, "ok", False
        elif iv_hs <= max_useful_s:
            level, interval, why, degraded = LEVEL_HS, iv_hs, "degraded_saves", True
        else:
            level, interval, why, degraded = LEVEL_HS, iv_hs, "too_slow", True
    else:
        # 采不敷出 → **没有可维持的间隔**（保留 HS256：省一点是一点；不装出能持续的样子）
        level, interval, degraded = LEVEL_HS, None, True
        iv_es = iv_hs = None
        why = "deficit" if harvest_mw > 0 else "no_energy"

    # 收支：按选定间隔跑，缺口多大；有缺口就吃储能 → 还能撑多久
    spend_mw = 0.0 if interval is None else (c_hs if level == LEVEL_HS else c_es) / interval
    deficit = float(sleep_mw) + spend_mw - harvest_mw
    if deficit > 1e-9:
        budget_ok = False
        silence_in_s = (charge_mj / deficit) if charge_mj > 0 else 0.0
    else:
        budget_ok, silence_in_s = True, None

    # 电量连一次上报都不够 → 该沉默了（why 优先级最高：它决定“还能不能说上话”）
    can_afford_next = charge_mj >= (c_hs if level == LEVEL_HS else c_es)
    if not can_afford_next:
        why = "empty"
    usable = bool(interval is not None and interval <= max_useful_s
                  and budget_ok and can_afford_next)
    return {
        "level": level,
        "degraded": bool(degraded),
        "degraded_reason": "energy" if degraded else None,
        "interval_s": None if interval is None else round(interval, 2),
        "interval_es256_s": None if iv_es is None else round(max(iv_es, min_interval_s), 2),
        "interval_hs256_s": None if iv_hs is None else round(max(iv_hs, min_interval_s), 2),
        "net_mw": round(net, 4),
        "budget_ok": bool(budget_ok),
        "silence_in_s": None if silence_in_s is None else round(silence_in_s, 1),
        "usable": usable,
        "why": why,
    }


def survive_s(charge_mj, harvest_mw, interval_s, level, store_mj=STORE_MJ,
              sleep_mw=SLEEP_MW, cost=None):
    """**硬撑**：明知采不敷出，仍然按 `interval_s` 报 —— 还能撑多久（秒）？

    这是“宁可吃储能也要被听见”策略的代价计算（演示里 `plan()` 返回 `interval_s=None` 时用它）。
    返回 `None` = 收支平衡（不会因没电停）；返回 `0.0` = 已经没电。
    收支 = 待机 + 上报 − 采集（缺口 > 0 就在吃储能）。
    """
    cost = cost or COST_MJ
    spend_mw = float(cost.get(level, 0.0)) / float(interval_s) if interval_s else 0.0
    deficit = float(sleep_mw) + spend_mw - float(harvest_mw)
    if deficit <= 1e-9:
        return None
    return float(charge_mj) / deficit if charge_mj > 0 else 0.0


def drain(charge_mj, harvest_mw, interval_s, level, dt_s, store_mj=STORE_MJ,
          sleep_mw=SLEEP_MW, cost=None):
    """推进一拍：返回新的电量（mJ，钳在 [0, store_mj]）。

    收支 = 采集×dt − 待机×dt − 上报耗电×（dt/间隔）——**逐拍结算**，所以间隔比 dt 长时
    平均下来才是"每次上报摊一次"。间隔 ≤ 0 视为只付待机（不发报）。
    """
    cost = cost or COST_MJ
    charge = float(charge_mj) + float(harvest_mw) * dt_s - float(sleep_mw) * dt_s
    if interval_s and interval_s > 0:
        charge -= float(cost.get(level, 0.0)) * (dt_s / float(interval_s))
    return max(0.0, min(float(store_mj), charge))


def sweep(harvests, charge_mj=CHARGE0_MJ, store_mj=STORE_MJ, **kw):
    """扫采集功率（能量轴的横轴）→ 每个点的策略表 + **头条数字**。

    返回 `{"rows": [...], "min_harvest_mw": X|None, "n": len(rows)}`；
    `min_harvest_mw` = 最小"够用"的采集功率（第一行 `usable=True`）——
    这是这一项真正想回答的问题：**要多少采集功率才持续跟得住人**。
    全都不够用 → `None`（不编一个数）。
    """
    rows = []
    for h in harvests:
        p = plan(h, charge_mj, store_mj, **kw)
        rows.append({"harvest_mw": round(float(h), 3), **p})
    first = next((r["harvest_mw"] for r in rows if r["usable"]), None)
    return {"rows": rows, "min_harvest_mw": first, "n": len(rows)}


def axis(n=13, h_max=12.0, charge_mj=CHARGE0_MJ, store_mj=STORE_MJ, **kw):
    """默认能量轴：0…h_max 均匀 n 点（含 0）。页面直接画这张表。"""
    n = max(2, int(n))
    return sweep([h_max * i / (n - 1) for i in range(n)],
                 charge_mj=charge_mj, store_mj=store_mj, **kw)
