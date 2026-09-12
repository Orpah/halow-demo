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

# ---- XSS 防护（2026-09-12）：alg 是**外部输入**（空口报文头 hdr.alg 直接落审计）----
# 旧正则 `\S+` 会把 < > " ' 一起吃进去，前端再拼 innerHTML 就是存储型 XSS。
# 现在只放行令牌字符，其余归 unknown。
for bad in ('alg=<img src=x onerror=alert(1)>', 'alg=<svg/onload=1>',
            'alg="quoted"', "alg=a'b", 'alg=<script>'):
    got = mt.alg_of(bad)
    check(f"XSS：恶意 alg 归 unknown（{bad[:24]}…）", got == "unknown")

# 不变量：无论输入什么，by_alg 的键都不含能构成 HTML 的字符
import string as _str      # noqa: E402
_forbidden = set('<>"\'&')
_keys = set()
for probe in ('alg=ES256', 'alg=none', 'alg=<b>', 'alg="x"', 'alg=x&y',
              'alg=', 'alg= a b', 'alg=HS256,ES256', 'alg=<', 'alg="'):
    _keys |= set(mt.verify_stats([ev("id_report", probe)])["by_alg"])
check("XSS：by_alg 的键集不含 HTML 元字符（不变量）",
      not (_keys & _forbidden))
check("XSS：合法令牌仍能解析",
      mt.alg_of("alg=ES256") == "ES256" and mt.alg_of("alg=none") == "none"
      and mt.alg_of("alg=HS256.1") == "HS256.1")

# ---- 1b) 降级级别分布 / 降级占比（§8.3，2026-09-12） -------------------------
# `level` 与 alg 同源（都来自审计 detail 的报文头字段）→ 同样只认 0..3 单个数字。
s = mt.verify_stats([ev("id_report", "alg=ES256 level=0 trust=high accepted=True"),
                     ev("id_report", "alg=ES256 level=0 trust=high accepted=True"),
                     ev("id_report", "alg=HS256 level=1 trust=medium accepted=True"),
                     ev("id_report", "alg=HS256 level=2 trust=low accepted=True"),
                     ev("id_report", "alg=none level=3 trust=none accepted=True"),
                     ev("id_reject", "alg=none level=0 trust=none accepted=False")])
check("级别：by_level 只数通过（L0×2 / L1×1 / L2×1 / L3×1）",
      s["by_level"] == {0: 2, 1: 1, 2: 1, 3: 1})
check("级别：degraded = L2+L3，不含 L1", s["degraded"] == {"l2": 1, "l3": 1, "total": 2})
check("级别：占比分母 = 通过总数（5），不是总条数（6）",
      s["degraded_ratio"] == round(2 / 5, 4))
check("级别：被拒的那条（level=0）不进 by_level（那是攻击者宣称的级别）",
      s["by_level"].get(0) == 2 and s["total"] == 6 and s["reports"] == 5)
check("级别：解析函数——能认 0..3、取不到/越界/非数字 → None",
      mt.level_of("alg=ES256 level=0 x=1") == 0
      and mt.level_of("alg=x level=3") == 3
      and mt.level_of("alg=x level=4") is None
      and mt.level_of("alg=x level=x") is None
      and mt.level_of("alg=x") is None
      and mt.level_of("") is None)
# 缺级别 ≠ 级别 0：算成 0 会抬高分母、压低降级占比（假乐观）。这里单独数出来。
s = mt.verify_stats([ev("id_report", "alg=ES256 accepted=True"),
                     ev("id_report", "alg=HS256 level=2 accepted=True")])
check("级别：通过但无级别 → level_unknown 计数（不当成 L0）",
      s["level_unknown"] == 1 and s["by_level"] == {2: 1})
check("级别：分母含无级别行 → ratio 是下界（1/2）", s["degraded_ratio"] == 0.5)
s = mt.verify_stats([ev("id_report", "alg=ES256 level=0 accepted=True")])
check("级别：全正常 → 占比 0.0（有样本就不编 None）",
      s["degraded_ratio"] == 0.0 and s["degraded"]["total"] == 0)
s = mt.verify_stats([])
check("级别：无样本 → 占比 None（不是 0）",
      s["degraded_ratio"] is None and s["by_level"] == {} and s["level_unknown"] == 0)
# 不变量：级别是整数键，永远不可能是字符串（下游直接当数字用/排序）
_keys_lv = set()
for probe in ("level=<b>", 'level="3"', "level=3 ", "level=3x", "level=03", "level=-1"):
    _keys_lv |= set(mt.verify_stats([ev("id_report", probe)])["by_level"])
check("级别：by_level 的键都是 int 且在 0..3（恶意/脏值被挡）",
      _keys_lv <= {0, 1, 2, 3} and all(isinstance(k, int) for k in _keys_lv))

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

# 时间回拨（导入历史数据 / 手工回填 ts）：发现或结案早于立案 → 时长不可用，
# 置 None 并计入 invalid；**绝不报负数**（负的“处置时长”会被当成真实值）。
c5 = case("C005", created=NOW - 100, closed_at=NOW - 50, status="closed",
          events=[{"t": NOW - 600, "type": "found"},      # 比立案早 500s → 回拨
                  {"t": NOW - 100, "type": "mark"}])
st = mt.case_stats([c5], now=NOW)
check("回拨：发现早于立案 → to_found_sec=None 且 invalid=1",
      st["rows"][0]["to_found_sec"] is None and st["invalid"] == 1)
check("回拨：不把负数算进均值（n 不计该样本）", st["to_found"]["n"] == 0
      and st["to_found"]["avg"] is None)
check("回拨：结案时长正常的那部分不受影响", st["to_close"]["avg"] == 50.0)
st = mt.case_stats([case("C006", created=NOW - 100, closed_at=NOW - 500,
                         events=[{"t": NOW - 100, "type": "mark"}])], now=NOW)
check("回拨：结案早于立案 → to_close_sec=None 且 invalid=1",
      st["rows"][0]["to_close_sec"] is None and st["invalid"] == 1)

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
