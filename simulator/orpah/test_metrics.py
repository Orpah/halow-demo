#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_metrics.py — 指标面板纯计算单测（不依赖 IoTDB / 网页）

运行：python test_metrics.py
覆盖：签名失败率与算法分布（含解析失败的 unknown）、RSSI 统计（含无样本不给 0）、
      走失处置时长（立案→发现 / 立案→结案、未结案不进均值、elapsed 只给未结案）、
      以及"空输入不编数"这条口径纪律。
"""
from types import SimpleNamespace

import metrics as mt

FAILS = []
# 时间单位约定（与 metrics.py 模块头一致）：**Case 域是秒**（cases.py / registry / alerts.py 同一约定，
# 都来自 int(time.time())）；IoTDB 域的 t 是毫秒，但本模块只用它的 rssi 值。
# 下面所有 created/closed_at/events.t 都用秒。
NOW = 1_800_000_000


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)


def ev(etype, detail="", t=0):
    return {"t": t, "etype": etype, "sn": "CN-WH01-9AF3C1D2", "detail": detail,
            "actor": "system"}


def rep(rssi, t=0):
    return {"t": t, "rssi": rssi, "seq": 1, "router_id": ""}


def case(cid, created=NOW - 100, closed_at=None, status="closed",
         events=None):
    return SimpleNamespace(case_id=cid, person_id="P001", status=status,
                           created=created, closed_at=closed_at,
                           events=events if events is not None else [])


# ---- 1) 签名失败率 + 算法分布 ---------------------------------------------
s = mt.verify_stats([ev("id_report", "alg=ES256 level=0 trust=ok accepted=True"),
                     ev("id_report", "alg=ES256 level=0 trust=ok accepted=True"),
                     ev("id_report", "alg=HS256 level=1 trust=warn accepted=True"),
                     ev("id_reject", "alg=none level=0 trust=none accepted=False err=bad")])
check("签名：总数/通过/被拒", (s["total"], s["reports"], s["rejected"]) == (4, 3, 1))
check("签名：失败率 1/4", s["fail_ratio"] == 0.25)
check("签名：算法分布", s["by_alg"] == {"ES256": 2, "HS256": 1, "none": 1})

# 只统计两类事件：其它事件不进分母（否则 publish/found 会被算成"用某种算法上报"）
s = mt.verify_stats([ev("publish", "n=2"), ev("found", "router 127.0.0.1:1"),
                     ev("id_report", "alg=ES256")])
check("签名：其它类型事件不进统计", (s["total"], s["by_alg"]) == (1, {"ES256": 1}))

# 解析不出来的算法 → unknown（不猜）
s = mt.verify_stats([ev("id_report", "accepted=True"), ev("id_report", "alg=")])
check("签名：取不到 alg → unknown（不猜）", s["by_alg"] == {"unknown": 2})

# 无样本 → 失败率 None（不是 0：0% 会被读成"验过都没问题"）
s = mt.verify_stats([])
check("签名：无样本 → fail_ratio=None（不编 0）",
      s["total"] == 0 and s["fail_ratio"] is None and s["by_alg"] == {})

check("签名：alg 解析（前后有别的字段也认）",
      mt.alg_of("level=0 trust=ok accepted=True alg=ES256 gen=1") == "ES256"
      and mt.alg_of("") == "unknown")

# ---- 2) 平均 RSSI ----------------------------------------------------------
r = mt.rssi_stats([rep(-60), rep(-70), rep(-65)])
check("RSSI：均值/最小/最大/样本数",
      (r["n"], r["avg"], r["min"], r["max"]) == (3, -65.0, -70, -60))
r = mt.rssi_stats([rep(-60), rep(None), rep("-70")])       # None 与非数值要跳过
check("RSSI：跳过 None/非法值", (r["n"], r["avg"]) == (2, -65.0))
r = mt.rssi_stats([])
check("RSSI：无样本 → avg=None（不编 0，0 dBm 是真实强度）",
      r["n"] == 0 and r["avg"] is None and r["min"] is None)

# ---- 3) 走失处置时长 -------------------------------------------------------
c1 = case("C001", created=NOW - 1000, closed_at=NOW - 400, status="closed",
          events=[{"t": NOW - 1000, "type": "mark"}, {"t": NOW - 700, "type": "found"},
                  {"t": NOW - 400, "type": "close"}])
c2 = case("C002", created=NOW - 500, closed_at=NOW - 200, status="closed",
          events=[{"t": NOW - 500, "type": "mark"}, {"t": NOW - 300, "type": "found"}])
c3 = case("C003", created=NOW - 100, closed_at=None, status="found",
          events=[{"t": NOW - 100, "type": "mark"}])        # 未结案
st = mt.case_stats([c1, c2, c3], now=NOW)
check("案件：总数/未结案/已结案", (st["total"], st["open"], st["ended"]) == (3, 1, 2))
check("案件：立案→首次发现（300s / 200s）",
      (st["to_found"]["n"], st["to_found"]["min"], st["to_found"]["max"])
      == (2, 200, 300))
check("案件：立案→结案只算已结案（600s / 300s）",
      (st["to_close"]["n"], st["to_close"]["min"], st["to_close"]["max"])
      == (2, 300, 600))
check("案件：未结案不进均值", st["to_found"]["n"] == 2)
rows = {r["case_id"]: r for r in st["rows"]}
check("案件：未结案给 elapsed、不给 to_close",
      rows["C003"]["to_close_sec"] is None and rows["C003"]["elapsed_sec"] == 100)
check("案件：已结案不给 elapsed", rows["C001"]["elapsed_sec"] is None)
check("案件：明细按立案时间升序",
      [r["case_id"] for r in st["rows"]] == ["C001", "C002", "C003"])

# 没有 found 事件（直接结案：撤销走失）→ to_found 不参与统计，但不能崩
st = mt.case_stats([case("C009", created=NOW - 10, closed_at=NOW - 5,
                         events=[{"t": NOW - 10, "type": "mark"},
                                 {"t": NOW - 5, "type": "close"}])], now=NOW)
check("案件：没有发现事件（撤销结案）→ to_found 无样本、to_close 有值",
      st["to_found"]["n"] == 0 and st["to_found"]["avg"] is None
      and st["to_close"]["avg"] == 5.0)

# 事件乱序（回填/导入/回放时 ts 可由调用方指定）→ 必须取**时间最早**的 found，
# 而不是列表里第一个（取错会把时长算小）。这条是 _first_ts 的回归锁。
c4 = case("C004", created=NOW - 1000, closed_at=NOW - 100, status="closed",
          events=[{"t": NOW - 100, "type": "found"},      # 后写入但时间最晚
                  {"t": NOW - 900, "type": "found"},      # 后写入且时间最早 ← 应取它
                  {"t": NOW - 1000, "type": "mark"}])
st = mt.case_stats([c4], now=NOW)
check("案件：乱序事件里取“时间最早的发现”（而非列表第一个）",
      st["to_found"]["avg"] == 100.0 and st["rows"][0]["to_found_sec"] == 100)
check("案件：乱序不影响结案时长", st["to_close"]["avg"] == 900.0)

# 脏数据（缺 created）→ 跳过、不编时长，但报出条数（不静默）
st = mt.case_stats([case("C001", created=NOW - 10),
                    SimpleNamespace(case_id="C099", person_id="", status="x",
                                    created=None, closed_at=None, events=[])], now=NOW)
check("案件：缺 created 的行被跳过并计入 invalid",
      st["total"] == 1 and st["invalid"] == 1)
check("案件：无脏数据时 invalid=0", mt.case_stats([c1], now=NOW)["invalid"] == 0)

# ---- 4) 汇总 / 空输入 ------------------------------------------------------
d = mt.summarize(events=[], reports=[], cases=[], now=NOW,
                 window={"minutes": 60}, tsdb=False)
check("汇总：四项都在，空输入不编数",
      d["ok"] is True and d["tsdb"] is False
      and d["verify"]["fail_ratio"] is None and d["rssi"]["avg"] is None
      and d["cases"]["total"] == 0 and d["window"] == {"minutes": 60})
d = mt.summarize(None, None, None)
check("汇总：全 None 输入也不崩", d["verify"]["total"] == 0 and d["cases"]["rows"] == [])

# ---- 5) 用**真实** CaseManager 跑一遭（内存库）-----------------------------
import cases as cs          # noqa: E402
import registry as reg      # noqa: E402

r2 = reg.Registry(":memory:")
pid = r2.add_person("指标测试")
r2.register("CN-WH01-AAAAAAAA", person_id=pid)
cm = cs.CaseManager(":memory:")
c, _, _ = cm.mark(pid, r2, ts=NOW - 900)
cm.on_found("CN-WH01-AAAAAAAA", r2, ts=NOW - 500, detail="report")
real = mt.case_stats(cm.open_cases(), now=NOW)
row = [x for x in real["rows"] if x["case_id"] == c.case_id][0]
check("真实对象：立案→发现 400s（用真 CaseManager 的 events）",
      row["to_found_sec"] == 400 and real["to_found"]["avg"] == 400.0)
check("真实对象：invalid=0（真对象不会缺 created）", real["invalid"] == 0)

# **单位约定的端到端锁**：不传 ts（用 cases.py 的默认值 int(time.time())）走一遍，
# 断言算出的时长是“几秒”而不是“几万秒”。若哪天 cases.py 改成毫秒、而这里没跟着换算，
# 这条会直接吐出来（而不是静默放大 1000 倍）。
cm2 = cs.CaseManager(":memory:")
r3 = reg.Registry(":memory:")
pid3 = r3.add_person("单位锁")
r3.register("CN-WH02-CCCCCCCC", person_id=pid3)
c3, _, _ = cm2.mark(pid3, r3)                     # 默认 ts = int(time.time())
cm2.on_found("CN-WH02-CCCCCCCC", r3, detail="report")
st3 = mt.case_stats(cm2.open_cases(), now=int(__import__("time").time()))
sec = st3["rows"][0]["to_found_sec"]
check(f"单位锁：默认 ts 算出的“立案→发现”是 {sec}s（应为 0~5s，不是 1000 倍）",
      sec is not None and 0 <= sec <= 5)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
    raise SystemExit(1)
print("全部通过")
