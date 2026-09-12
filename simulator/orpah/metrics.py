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

⚠ **时间单位：两个域，本模块只拿 Case 域算时长**（2026-09-12 review 提出要写明）

    Case 域（created / closed_at / events.t）  = **秒**（与 cases.py / registry / alerts.py 同一约定：
                                                全部来自 `int(time.time())`，见 cases.py 四处默认 ts）
    IoTDB 域（events.t / reports.t）             = **毫秒**（测点时间，回放/时间窗用）

本模块的时长计算（第 4 项指标）**只用 Case 域**；IoTDB 那一侧只取 `rssi` 值、不拿它的 `t` 做减法。
所以这里不会出现“秒 - 毫秒”静默差 1000 倍；真要改约定的单位，得同时改 `cases.py`、`registry.touch`
与 `alerts.py`（三处同一个秒约定），而 `test_metrics.py` 真实对象那条用例会把偏差吐出来。
"""
import re

ALG_UNKNOWN = "unknown"
# 算法名是**令牌**（ES256 / HS256 / none 这种），不是任意文本 —— 只收 [A-Za-z0-9_.-]，
# 其余一律归 unknown。两个理由（2026-09-12 review 发现存储型 XSS 风险）：
#   ① **这个值是外部输入**：`server.py:_on_id_report` 直接取 `hdr.get("alg")` 落审计
#      （连被拒的报文也落）→ `alg=<img onerror=…>` 会一路进到事件 detail；
#      旧正则 `\S+` 会把 `<`/`>`/引号一起吃进去，再被前端拼进 innerHTML 就是 XSS。
#   ② 语义上更对：不是合法令牌就不是“算法名”，归 unknown 比原样透传更诚实。
# 注：**不去改服务端落库**——审计保留“攻击者当时发的是什么”有取证价值，
#      要在**派生层（本模块）与展示层（页面 esc()）**收口。
_ALG_RE = re.compile(r"(?:^|\s)alg=([A-Za-z0-9_.\-]{1,24})(?:\s|$)")


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
    """从审计 detail 里取 `alg=` 值；**只收令牌字符**，取不到或不像令牌 → 'unknown'。"""
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
    """该类事件里**时间最早**的一个（不是“列表里第一个”）。

    为什么取 min 而不是直接返回第一个匹配项：`Case.events` 是**追加**写的，而写入时用的 ts 可以由
    调用方指定（例如 `assign(..., ts=…)` 回填/导入/回放）。一旦有回填，列表就不再按时间有序 ——
    那时“列表第一个 found”会得到比真实“首次发现”更晚的时刻（时长算小）。
    """
    ts = [ev.get("t") for ev in (getattr(case, "events", None) or [])
          if ev.get("type") == type_ and ev.get("t") is not None]
    return min(ts) if ts else None


def case_stats(cases, now=None):
    """走失处置时长：立案→首次发现 / 立案→结案（**单位秒**，见模块头的时间单位说明）。

    只把**已结束**的案件计入 avg/min/max；未结案的给 elapsed（若给了 now）。
    逐案明细按立案时间升序。

    `invalid` = **时长不可用的条数**，两种情形都算（不猜、不静默、也不报负数）：
      ① 缺 `created`（脏数据，整行跳过）；
      ② 时间回拨 —— 发现/结案时刻早于立案（导入历史数据、手工回填 ts 都可能）
         此时该字段置 `None` 而非负数：负的“处置时长”没意义，报出来只会被当成真实值。
    """
    rows, to_found, to_close = [], [], []
    open_n = invalid = 0

    def _dur(a, b):
        """b - a（秒）；回拨（负数）→ None + 计入 invalid。"""
        nonlocal invalid
        d = b - a
        if d < 0:
            invalid += 1
            return None
        return d

    for c in cases or []:
        created = getattr(c, "created", None)
        if created is None:            # 脏数据：不能编一个时长，但要报个数出来
            invalid += 1
            continue
        found_at = _first_ts(c, "found")
        closed_at = getattr(c, "closed_at", None)
        f_sec = _dur(created, found_at) if found_at else None
        c_sec = _dur(created, closed_at) if closed_at else None
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
        "invalid": invalid,
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
