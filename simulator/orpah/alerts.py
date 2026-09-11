#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alerts.py — 告警规则引擎（供页面红点消费）

设计取舍：

- **无状态**：每次用当前快照重新评估，返回「活跃告警」列表，**不落库**。
  告警表达的是"当前状态"，不是"历史"——历史由 IoTDB 事件流（`root.orpah.events`）负责。
- 阈值是**演示压缩时间**（真实部署要调大）：客户端本来 2s 一包，所以"长未上报"取 30s。
- 每条告警带 `key`（kind + 对象）供前端判断"是否是新告警"；`msg` 是 **i18n 键**，
  由前端本地化 —— 后端不拼中文/英文，免得又变成"后端文案不跟语言走"。
- 时间戳单位统一为**秒**（与 `registry.touch` / `cases.mark` 一致）。

已实现（第一批 3 条）：
    no_report       启用中的设备超过 no_report_sec 无上报
    case_overtime   案件立案超过 case_overtime_sec 仍未发现（只算 open；已 found 不算）
    sig_fail_rate   最近 sig_window 条签名上报里被拒比例 > sig_fail_ratio

第二批可加：RSSI 突变、校验位连续失败（需要历史序列，本模块暂不做）。
"""
import time

import cases as cs
import registry as reg

LEVEL_CRIT = "crit"
LEVEL_WARN = "warn"

NO_REPORT_SEC = 30        # 超过这么久没上报 → 告警
CASE_OVERTIME_SEC = 180   # 立案后这么久还没发现 → 告警
SIG_WINDOW = 5            # 签名失败率统计窗口（条）
SIG_FAIL_RATIO = 0.5      # 窗口内被拒比例超过它 → 告警


def _alert(kind, level, key_obj, msg, since, **data):
    a = {"kind": kind, "level": level, "key": f"{kind}:{key_obj}",
         "msg": msg, "since": int(since or 0)}
    a.update(data)
    return a


def evaluate(registry, cases, id_reports, now=None, **th):
    """返回活跃告警列表（crit 在前，同级按触发时间）。

    参数与阈值都可注入，便于单测（见 test_alerts.py）。
    """
    now = int(now if now is not None else time.time())
    no_rep = th.get("no_report_sec", NO_REPORT_SEC)
    case_ov = th.get("case_overtime_sec", CASE_OVERTIME_SEC)
    win = th.get("sig_window", SIG_WINDOW)
    fail_ratio = th.get("sig_fail_ratio", SIG_FAIL_RATIO)
    out = []

    # 1) 长未上报：只看「启用中**且曾经上报过**」的设备 ——
    #    从未上报的新设备不告警，否则一开机就一片红，反而盖住真问题。
    for rec in registry.devices.values():
        if rec.status != reg.STATUS_ACTIVE or not rec.last_seen:
            continue
        gap = now - int(rec.last_seen)
        if gap > no_rep:
            out.append(_alert("no_report", LEVEL_WARN, rec.sn,
                              "alert_no_report", rec.last_seen,
                              sn=rec.sn, gap=gap))

    # 2) 走失超时：只有「还没被发现」的 open 案件算超时
    for c in cases.open_cases():
        if c.status != cs.CASE_OPEN:      # 常量在 cases 模块上，不在 CaseManager 实例上
            continue
        gap = now - int(c.created)
        if gap > case_ov:
            out.append(_alert("case_overtime", LEVEL_CRIT, c.case_id,
                              "alert_case_overtime", c.created,
                              case_id=c.case_id, person_id=c.person_id, gap=gap))

    # 3) 签名失败率：样本不足不告警（避免误报）
    recent = list(id_reports)[:win]          # deque 最新在前
    if len(recent) >= win:
        bad = [r for r in recent if not r.get("accepted")]
        if len(bad) / len(recent) > fail_ratio:
            out.append(_alert("sig_fail_rate", LEVEL_CRIT, "recent",
                              "alert_sig_fail", recent[0].get("t") or now,
                              n=len(bad), total=len(recent)))

    out.sort(key=lambda a: (0 if a["level"] == LEVEL_CRIT else 1, a["since"]))
    return out


def summary(alert_list):
    """计数，供前端徽标直接使用。"""
    return {"crit": sum(1 for a in alert_list if a["level"] == LEVEL_CRIT),
            "warn": sum(1 for a in alert_list if a["level"] == LEVEL_WARN),
            "total": len(alert_list)}
