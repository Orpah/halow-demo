#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_alerts.py — 告警规则单测（纯内存，不依赖 IoTDB / 网页）

运行：python test_alerts.py
"""
from collections import deque
from types import SimpleNamespace

import alerts as alr
import cases as cs
import registry as reg

NOW = 1_800_000_000     # 固定"现在"，测试可复现
FAILS = []


def dev(sn, status=reg.STATUS_ACTIVE, last_seen=None):
    return SimpleNamespace(sn=sn, status=status, last_seen=last_seen)


def regis(*devs):
    return SimpleNamespace(devices={d.sn: d for d in devs})


def case(cid, status=cs.CASE_OPEN, created=NOW, person_id="P001"):
    return SimpleNamespace(case_id=cid, person_id=person_id,
                           status=status, created=created)


def case_mgr(*cs_):
    """假的 CaseManager：**只**提供 open_cases()。
    刻意不提供 CASE_OPEN —— 真 CaseManager 也没有这个属性（常量在 cases 模块上），
    假对象多给一个属性会把真实的 AttributeError 掩盖掉（这次就踩了）。"""
    return SimpleNamespace(
        open_cases=lambda: [c for c in cs_ if c.status in (cs.CASE_OPEN, cs.CASE_FOUND)])


def rep(accepted, t=NOW):
    return {"accepted": accepted, "t": t}


def kinds(alerts):
    return [a["kind"] for a in alerts]


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)


# ---- 规则 1：长未上报 ------------------------------------------------------
r = regis(dev("A", last_seen=NOW - 100),                        # 超时 → 应告警
          dev("B", last_seen=NOW - 10),                         # 正常 → 不告警
          dev("C", last_seen=None),                             # 从未上报 → 不告警
          dev("D", status=reg.STATUS_LOST, last_seen=NOW - 100))  # 非启用 → 不告警
a = alr.evaluate(r, case_mgr(), deque(), now=NOW)
check("长未上报：只报超时的启用设备", [x["sn"] for x in a] == ["A"])
check("长未上报：带 gap 且等级 warn", a[0]["gap"] == 100 and a[0]["level"] == "warn")

# 边界：刚好等于阈值不算超时（用 > 比较）
a = alr.evaluate(regis(dev("A", last_seen=NOW - alr.NO_REPORT_SEC)), case_mgr(), deque(), now=NOW)
check("长未上报：等于阈值不告警", a == [])

# ---- 规则 2：走失超时 ------------------------------------------------------
a = alr.evaluate(regis(), case_mgr(case("C001", created=NOW - 300),                    # 超时
                                   case("C002", status=cs.CASE_FOUND, created=NOW - 300)),  # 已发现
                 deque(), now=NOW)
check("走失超时：只报 open 的案件", [x["case_id"] for x in a] == ["C001"])
check("走失超时：等级 crit", a[0]["level"] == "crit")
check("走失超时：case_key 可去重", a[0]["key"] == "case_overtime:C001")

# ---- 规则 3：签名失败率 ----------------------------------------------------
a = alr.evaluate(regis(), case_mgr(), deque([rep(False)] * 3 + [rep(True)] * 2), now=NOW)
check("签名失败率：3/5 被拒 → 告警", "sig_fail_rate" in kinds(a))
check("签名失败率：附 n/total", a and a[0]["n"] == 3 and a[0]["total"] == 5)

a = alr.evaluate(regis(), case_mgr(), deque([rep(False)] * 4), now=NOW)
check("签名失败率：样本不足窗口 → 不告警", "sig_fail_rate" not in kinds(a))

a = alr.evaluate(regis(), case_mgr(), deque([rep(False)] * 2 + [rep(True)] * 3), now=NOW)
check("签名失败率：2/5 未超阈 → 不告警", "sig_fail_rate" not in kinds(a))

# ---- 排序 / 计数 / 空态 ----------------------------------------------------
a = alr.evaluate(regis(dev("A", last_seen=NOW - 100)),
                 case_mgr(case("C001", created=NOW - 300)),
                 deque([rep(False)] * 5), now=NOW)
check("排序：crit 在 warn 之前", [x["level"] for x in a] == ["crit", "crit", "warn"])
check("summary：计数正确", alr.summary(a) == {"crit": 2, "warn": 1, "total": 3})
check("空态：无设备/无案件/无上报 → 空列表",
      alr.evaluate(regis(), case_mgr(), deque(), now=NOW) == [])

# ---- 用**真实** Registry / CaseManager（内存库）跑一遭 ----------------------
# 假对象能过不代表真对象能过（上一版就因为假对象多给了 CASE_OPEN 而漏掉 AttributeError）
r2 = reg.Registry(":memory:")
pid = r2.add_person("测试")
r2.register("CN-WH01-AAAAAAAA", person_id=pid)     # 会被立案 → 转 lost
r2.register("CN-WH02-BBBBBBBB")                     # 另一台，不入案
r2.touch("CN-WH02-BBBBBBBB", ts=NOW - 100)         # 超时
c2 = cs.CaseManager(":memory:")
c2.mark(pid, r2, ts=NOW - 300)                      # 立案 300s 前
real = alr.evaluate(r2, c2, deque(), now=NOW)
check("真实对象：长未上报 + 走失超时都能报",
      sorted(kinds(real)) == ["case_overtime", "no_report"])
check("真实对象：长未上报报的是没入案的那台",
      [x["sn"] for x in real if x["kind"] == "no_report"] == ["CN-WH02-BBBBBBBB"])

# ---- 阈值环境变量（进程内改了要重启才生效，这里用 reload 模拟重启）----------
import importlib                  # noqa: E402
import os                         # noqa: E402


def reload_with(**env):
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return importlib.reload(alr)


a = reload_with(ORPAH_ALERT_CASE_OVERTIME_SEC="600",
                ORPAH_ALERT_NO_REPORT_SEC=None, ORPAH_ALERT_SIG_WINDOW=None,
                ORPAH_ALERT_SIG_FAIL_RATIO=None)
check("env：未设的项保持默认",
      (a.NO_REPORT_SEC, a.SIG_WINDOW, a.SIG_FAIL_RATIO) == (30, 5, 0.5))
check("env：超时阈值被覆盖", a.CASE_OVERTIME_SEC == 600)
# 立案 300s 前：默认 180 会告警，改成 600 后不该告警
check("env：覆盖值切实用于评估",
      a.evaluate(regis(), case_mgr(case("C001", created=NOW - 300)),
                 deque(), now=NOW) == [])

a = reload_with(ORPAH_ALERT_CASE_OVERTIME_SEC="abc", ORPAH_ALERT_SIG_WINDOW="",
                ORPAH_ALERT_SIG_FAIL_RATIO="0.9")
check("env：非法值/空串回退默认", (a.CASE_OVERTIME_SEC, a.SIG_WINDOW) == (180, 5))
check("env：浮点阈值生效", a.SIG_FAIL_RATIO == 0.9)
# 4/5 = 0.8：默认 0.5 会告警，0.9 不该告警
a2 = a.evaluate(regis(), case_mgr(), deque([rep(False)] * 4 + [rep(True)]), now=NOW)
check("env：浮点阈值切实用于评估", a2 == [])

a = reload_with(ORPAH_ALERT_CASE_OVERTIME_SEC=None, ORPAH_ALERT_SIG_FAIL_RATIO=None)
check("env：清后恢复默认", (a.CASE_OVERTIME_SEC, a.SIG_FAIL_RATIO) == (180, 0.5))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
    raise SystemExit(1)
print("all alert tests passed")
