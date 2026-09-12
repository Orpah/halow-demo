#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_alerts.py — 告警规则单测（纯内存，不依赖 IoTDB / 网页）

运行：python test_alerts.py
"""
import os
from collections import deque
from types import SimpleNamespace

# 本文件要断言「默认阈值」（如 B 的 24h），所以**先清掉环境里可能存在的 ORPAH_ALERT_***
# 再 import alerts —— 否则本机 shell 里设过阈值（例如验证 B 方案时留下的
# ORPAH_ALERT_CASE_HANDLED_SEC=5）会让一堆默认值断言假失败（2026-09-12 实际踩到）。
for _k in [k for k in os.environ if k.startswith("ORPAH_ALERT_")]:
    os.environ.pop(_k)

import alerts as alr       # noqa: E402
import cases as cs         # noqa: E402
import registry as reg     # noqa: E402

NOW = 1_800_000_000     # 固定"现在"，测试可复现
FAILS = []


def dev(sn, status=reg.STATUS_ACTIVE, last_seen=None):
    return SimpleNamespace(sn=sn, status=status, last_seen=last_seen)


def regis(*devs):
    return SimpleNamespace(devices={d.sn: d for d in devs})


def case(cid, status=cs.CASE_OPEN, created=NOW, person_id="P001", handler="",
         handled_at=None):
    # handler/handled_at 是「处置态」维度（2026-09-12 新增）：真 Case 有，假 Case 也必须给 ——
    # 假对象**少**给属性会让测试直接崩（多给属性则会掩盖真实的 AttributeError，见 case_mgr 注释）
    return SimpleNamespace(case_id=cid, person_id=person_id,
                           status=status, created=created, handler=handler,
                           handled_at=handled_at)


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
# 口径（2026-09-12 复核修正）：工作态 = 启用 **或 走失**，且**曾经上报过**。
# 走失者的追踪器最该盯（掉线往往就是找不到人的原因）；停用/报废不盯。
r = regis(dev("A", last_seen=NOW - 100),                        # 启用+超时 → 应告警
          dev("B", last_seen=NOW - 10),                         # 启用+正常 → 不告警
          dev("C", last_seen=None),                             # 从未上报 → 不告警
          dev("D", status=reg.STATUS_LOST, last_seen=NOW - 100),   # 走失中+超时 → **应告警**
          dev("E", status=reg.STATUS_DISABLED, last_seen=NOW - 100),  # 停用 → 不告警
          dev("F", status=reg.STATUS_SCRAPPED, last_seen=NOW - 100))  # 报废 → 不告警
a = alr.evaluate(r, case_mgr(), deque(), now=NOW)
check("长未上报：启用/走失中的都报，停用/报废不报",
      [x["sn"] for x in a] == ["A", "D"])
check("长未上报：带 gap 且等级 warn", a[0]["gap"] == 100 and a[0]["level"] == "warn")

# 走失设备的告警单独确认（避免以后又被“非启用就不报”改回去）
a_lost = alr.evaluate(regis(dev("D", status=reg.STATUS_LOST, last_seen=NOW - 100)),
                      case_mgr(), deque(), now=NOW)
check("长未上报：走失中的追踪器掉线要报（2026-09-12 修正）",
      [x["sn"] for x in a_lost] == ["D"])
check("长未上报：停用的设备不报",
      alr.evaluate(regis(dev("E", status=reg.STATUS_DISABLED, last_seen=NOW - 100)),
                   case_mgr(), deque(), now=NOW) == [])

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

# 处置态（2026-09-12 用户定 A 方案）：超时 **且无人接手** 才告警 ——
# 否则只要案件还开着就永远 crit，红点恒亮被淹没（分不出“刚超时没人管”与“已在找人”）
a = alr.evaluate(regis(),
                 case_mgr(case("C001", created=NOW - 300),                       # 无人接手 → 告警
                          case("C002", created=NOW - 300, handler="张警官")),  # 已接手 → 不告警
                 deque(), now=NOW)
check("处置态：已接手的超时案件不告警", [x["case_id"] for x in a] == ["C001"])

# 接手 → 红点消失（同一案件前后对比）
a = alr.evaluate(regis(), case_mgr(case("C001", created=NOW - 300, handler="张警官")),
                 deque(), now=NOW)
check("处置态：接手后该条告警消失", kinds(a) == [])
# 取消接手 → 告警回来（handler 清空即回到未处置）
a = alr.evaluate(regis(), case_mgr(case("C001", created=NOW - 300, handler="")),
                 deque(), now=NOW)
check("处置态：取消接手后告警回来", kinds(a) == ["case_overtime"])

# ---- 规则 2b（B 方案）：接手后仍超时 → 再提醒 -------------------------------
# 语义：从**接手时刻**起算。默认 86400s（真实 24h），演示把阈值调小看效果。
HOV = alr.CASE_HANDLED_SEC
check("B：默认接手阈值是 24h", HOV == 86400)

a = alr.evaluate(regis(),
                 case_mgr(case("C001", created=NOW - 99999, handler="张警官",
                               handled_at=NOW - HOV - 10)),
                 deque(), now=NOW)
check("B：接手超阈值 → 报 case_handled_overtime", kinds(a) == ["case_handled_overtime"])
check("B：级别 warn（不盖过“没人接”的 crit）", a[0]["level"] == "warn")
check("B：since = 接手时刻（不是立案时刻）", a[0]["since"] == NOW - HOV - 10)
check("B：带 handler / case_id / gap（前端模板要用）",
      a[0]["handler"] == "张警官" and a[0]["case_id"] == "C001"
      and a[0]["gap"] == HOV + 10)
check("B：key 可与 A 区分", a[0]["key"] == "case_handled_overtime:C001")

# 刚好等于阈值不报（用 > 比较）；没超过接手阈值也不报（A 方案的“不扰”行为保留）
a = alr.evaluate(regis(), case_mgr(case("C001", handler="张警官",
                                        handled_at=NOW - HOV)), deque(), now=NOW)
check("B：等于接手阈值不报", kinds(a) == [])
a = alr.evaluate(regis(), case_mgr(case("C001", created=NOW - 99999,
                                        handler="张警官", handled_at=NOW - 10)),
                 deque(), now=NOW)
check("B：刚接手（未超阈值）不报，即使立案已很久", kinds(a) == [])

# 已发现或已结案的案件不算（open_cases 已过滤 found，这里守一下别回归）
a = alr.evaluate(regis(), case_mgr(case("C001", status=cs.CASE_FOUND,
                                        handler="张警官", handled_at=NOW - HOV - 10)),
                 deque(), now=NOW)
check("B：已发现的案件不报", kinds(a) == [])

# 老库/手工对象没有 handled_at → 回落到 created（不能因为缺属性就崩或默默不报）
a = alr.evaluate(regis(), case_mgr(case("C001", created=NOW - HOV - 10,
                                        handler="张警官", handled_at=None)),
                 deque(), now=NOW)
check("B：handled_at 缺失时回落到 created", kinds(a) == ["case_handled_overtime"]
      and a[0]["since"] == NOW - HOV - 10)

# A 与 B 同时存在：无人接手的 crit 应排在已接手的 warn 之前
a = alr.evaluate(regis(),
                 case_mgr(case("C001", created=NOW - 300),                       # A: crit
                          case("C002", created=NOW - 300, handler="张警官",
                               handled_at=NOW - HOV - 10)),              # B: warn
                 deque(), now=NOW)
check("A+B：crit 在前、warn 在后", [x["level"] for x in a] == ["crit", "warn"])
check("A+B：两种 kind 各自独立", sorted(kinds(a)) == ["case_handled_overtime", "case_overtime"])

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
# 真实对象上验证处置态：真的调 cases.assign（不是假装改字段）
# ⚠ assign 不传 ts 会用**真实** time.time()，而本测试的 NOW 是固定值（1.8e9，比真实现在早 ~126 天）
#   → 那会让 B 方案（接手后超 24h）当场成立、把这条"接手后不再报"的断言弄假。
#   测试要控制时钟：显式传 ts（这也是 B 方案引入后暴露出来的夹具问题）。
cid_real = list(c2.cases)[0]
real_take = c2.assign(cid_real, "王警官", ts=NOW - 10)
check("真实对象：assign 成功", real_take[1] is None and c2.cases[cid_real].handler == "王警官")
real2 = alr.evaluate(r2, c2, deque(), now=NOW)
check("真实对象：接手后 case_overtime 消失（只剩长未上报）",
      kinds(real2) == ["no_report"])
# 真实对象上把接手时间往前推（真调 assign 带 ts）→ B 方案应报出来
c2.assign(cid_real, "王警官", ts=NOW - alr.CASE_HANDLED_SEC - 10)
real3 = alr.evaluate(r2, c2, deque(), now=NOW)
check("真实对象：接手超阈值 → 出现 case_handled_overtime（B 方案）",
      sorted(kinds(real3)) == ["case_handled_overtime", "no_report"])
check("真实对象：B 告警带真实接手人与接手时刻",
      [(x["handler"], x["since"]) for x in real3
       if x["kind"] == "case_handled_overtime"] == [("王警官", NOW - alr.CASE_HANDLED_SEC - 10)])
c2.assign(cid_real, "", ts=NOW)        # 还原（取消接手）

# ---- 阈值环境变量（进程内改了要重启才生效，这里用 reload 模拟重启）----------
import importlib                  # noqa: E402


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
check("env：未设时 B 的接手阈值保持默认 24h", a.CASE_HANDLED_SEC == 86400)

# B 的阈值也要能用环境变量压小（演示里 24h 看不到效果）
b = reload_with(ORPAH_ALERT_CASE_HANDLED_SEC="120")
check("env：B 接手阈值可覆盖", b.CASE_HANDLED_SEC == 120)
check("env：B 覆盖值切实用于评估",
      [x["kind"] for x in b.evaluate(
          regis(), case_mgr(case("C001", handler="张警官",
                                 handled_at=NOW - 130)), deque(), now=NOW)]
      == ["case_handled_overtime"])
check("env：B 未超新阈值则不报",
      b.evaluate(regis(), case_mgr(case("C001", handler="张警官",
                                        handled_at=NOW - 110)), deque(), now=NOW) == [])
a = reload_with(ORPAH_ALERT_CASE_HANDLED_SEC=None)
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
check("env：清后恢复默认",
      (a.CASE_OVERTIME_SEC, a.SIG_FAIL_RATIO, a.CASE_HANDLED_SEC) == (180, 0.5, 86400))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
    raise SystemExit(1)
print("all alert tests passed")
