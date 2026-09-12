#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics.py — 指标面板的**纯计算**（不碰 IoTDB / HTTP / 文件，便于单测）

ROADMAP §五「指标面板」的四个指标，输入一律是**已经取好的快照**：

    事件流   events  = [{t(ms), etype, sn, detail, actor}]   ← root.orpah.events
    上报流   reports = [{t(ms), rssi, seq, router_id}]       ← root.orpah.devices.<sn>
    案件     cases   = Case 对象列表（或用得上的字段子集）    ← cases.CaseManager

    1. 签名校验失败率  id_reject / (id_report + id_reject)
    2. 签名算法分布    按审计 detail 里的 `alg=` 统计
    3. 平均 RSSI       设备上报流均值 / 最小 / 最大 + 样本数
    4. 走失处置时长    立案→首次发现、立案→结案（均值/最小/最大 + 逐案明细）

三条口径纪律（与「别把不同口径混在一起显示」同源）：

- **无样本就不给数**：`avg=None` 而不是 0（0 dBm 是个真实强度，不能拿来冒充"没有样本"）。
- **未结案的案件不进均值**：否则均值随等待时间漂移（案子挂得越久，"平均处置时长"越大）。
  未结案单列 `open` 计数；逐案明细里带 `elapsed_sec`（到现在为止多久），只给读者判断。
- **算法分布是从审计 detail 解析的**（`alg=ES256` 这种）—— 审计里本来就没有结构化列。
  解析不出来归 `unknown`，**不猜**；这样将来加了新算法，面板会显示 unknown 而不是静默归类。

⚠ **`verify.total` 与 `rssi.n` 不必相等**（面板上就是两个数，别去"对齐"它们）：
它们来自**两条不同的序列** —— `rssi.n` 数的是 `root.orpah.devices.<sn>` 的**上报点**，
`verify.total` 数的是 `root.orpah.events` 里的 **id_report/id_reject 事件**。合理差异的来源：
服务端按 seq 去重时丢掉的重复 REPORT 不会写设备点（但那一轮的 ID 上报事件照写），
且事件时间戳会被单调化钳成严格递增（同设备同毫秒会互相覆盖，见 API.md）。实测差约 1~2%。
"""
import re

ALG_UNKNOWN = "unknown"
_ALG_RE = re.compile(r"(?:^|\s)alg=(\S+)")


def _num(x):
    """转 float；None/非法 → None（不要 0 兜底）。"""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _stats(vals):
    """[v, ...] → {n, avg, min, max}；空列表 → avg/min/max 全 None。"""
    vs = [v for v in vals if v is not None]
    if not vs:
        return {"n": 0, "avg": None, "min": None, "max": None}
    return {"n": len(vs), "avg": round(sum(vs) / len(vs), 2),
            "min": min(vs), "max": max(vs)}


def alg_of(detail):
    """从审计 detail 里取 `alg=` 值；取不到 → 'unknown'。"""
    m = _ALG_RE.search(detail or "")
    return m.group(1) if m else ALG_UNKNOWN


def verify_stats(events):
    """签名校验：失败率 + 算法分布（只统计 id_report / id_reject 两类事件）。"""
    reports = rejects = 0
    by_alg = {}
    for e in events or []:
        et = e.get("etype")
        if et not in ("id_report", "id_reject"):
            continue
        if et == "id_report":
            reports += 1
        else:
            rejects += 1
        alg = alg_of(e.get("detail"))
        by_alg[alg] = by_alg.get(alg, 0) + 1
    total = reports + rejects
    return {
        "total": total, "reports": reports, "rejected": rejects,
        # 没有样本 → None（不是 0：0% 失败率会让人以为"验过了都没问题"）
        "fail_ratio": (round(rejects / total, 4) if total else None),
        "by_alg": by_alg,
    }


def rssi_stats(reports):
    """设备上报流的 RSSI 统计（窗口内）。"""
    return _stats([_num(r.get("rssi")) for r in (reports or [])])


def _first_ts(case, type_):
    for ev in getattr(case, "events", None) or []:
        if ev.get("type") == type_:
            return ev.get("t")
    return None


def case_stats(cases, now=None):
    """走失处置时长：立案→首次发现 / 立案→结案。

    只把**已结束**的案件计入 avg/min/max；未结案的给 elapsed（若给了 now）。
    时长单位秒；逐案明细按立案时间升序。
    """
    rows, to_found, to_close = [], [], []
    open_n = 0
    for c in cases or []:
        created = getattr(c, "created", None)
        if created is None:
            continue
        found_at = _first_ts(c, "found")
        closed_at = getattr(c, "closed_at", None)
        f_sec = (found_at - created) if found_at else None
        c_sec = (closed_at - created) if closed_at else None
        if f_sec is not None:
            to_found.append(f_sec)
        if c_sec is not None:
            to_close.append(c_sec)
        if closed_at is None:
            open_n += 1
        rows.append({
            "case_id": getattr(c, "case_id", "-"),
            "person_id": getattr(c, "person_id", ""),
            "status": getattr(c, "status", ""),
            "created": created,
            "to_found_sec": f_sec,          # 立案→首次发现
            "to_close_sec": c_sec,          # 立案→结案
            # 未结案才给 elapsed：让读者自己判断"已经等了多久"（不进均值）
            "elapsed_sec": (int(now - created) if now and closed_at is None else None),
        })
    rows.sort(key=lambda r: r["created"])
    return {
        "total": len(rows), "open": open_n, "ended": len(rows) - open_n,
        "to_found": _stats(to_found), "to_close": _stats(to_close),
        "rows": rows,
    }


def summarize(events=None, reports=None, cases=None, now=None,
              window=None, tsdb=True):
    """四项指标一把算完（`tsdb=False` 表示时序库没连上，事件/上报流是空的）。

    window 原样回带（前端要显示"最近 N 分钟"）；显示口径由调用方决定。
    """
    return {
        "ok": True,
        "tsdb": bool(tsdb),
        "window": window or {},
        "verify": verify_stats(events),
        "rssi": rssi_stats(reports),
        "cases": case_stats(cases, now=now),
    }
