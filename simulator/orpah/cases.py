#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cases.py — 走失案件闭环（以人为单位，非单 SN）

状态机：
    立案 mark    某人走失 → 名下所有设备进入「丢失」态（每台都标记走失）
  → 发现 found   任一台设备被 Router 命中走失表（ORPAH-FOUND）→ 该人「已发现」
  → 结案 close   找回（closed，设备恢复启用）/ 撤销误报（revoked，设备恢复启用）

纯内存 demo 实现；不依赖 server。由 ui_server 负责与权威走失表（server.mark_tracked/
untrack）联动，并注入 Router 发现事件（ORPAH-FOUND）。
"""
import time

from registry import STATUS_ACTIVE, STATUS_LOST

CASE_OPEN = "open"        # 走失中（已立案）
CASE_FOUND = "found"      # 已发现（任一台设备命中走失表）
CASE_CLOSED = "closed"    # 已找回（结案）
CASE_REVOKED = "revoked"  # 已撤销（误报结案）
CASE_STATUSES = (CASE_OPEN, CASE_FOUND, CASE_CLOSED, CASE_REVOKED)

CASE_ZH = {
    CASE_OPEN: "走失中",
    CASE_FOUND: "已发现",
    CASE_CLOSED: "已找回",
    CASE_REVOKED: "已撤销",
}

MAX_EVENTS = 50


class Case:
    """一个走失案件：一个走失者（人）的多设备集合。"""

    def __init__(self, case_id, person_id, ts):
        self.case_id = case_id
        self.person_id = person_id
        self.status = CASE_OPEN
        self.created = ts
        self.updated = ts
        self.closed_at = None
        self.outcome = None          # "found" / "revoked"（结案方式）
        self.events = []             # [{t, type, sn, detail}]

    def note(self, ts, type_, sn="", detail=""):
        self.events.append({"t": ts, "type": type_, "sn": sn, "detail": detail})
        del self.events[:-MAX_EVENTS]


class CaseManager:
    """走失案件台账：case_id -> Case。"""

    def __init__(self):
        self.cases = {}
        self._seq = 0

    def active_case(self, person_id):
        """该走失者当前未结（open/found）案件；无则返回 None。"""
        for c in self.cases.values():
            if c.person_id == person_id and c.status in (CASE_OPEN, CASE_FOUND):
                return c
        return None

    def mark(self, person_id, registry, ts=None):
        """立案：该走失者名下所有设备 → 丢失。

        返回 (case, sns, dup)：
          - 名下无设备：case=None；
          - 已有未结案件：返回已有案件，sns=[]，dup=True。
        """
        old = self.active_case(person_id)
        if old is not None:
            return old, [], True
        devs = registry.devices_of(person_id)
        if not devs:
            return None, [], False
        ts = ts if ts is not None else int(time.time())
        self._seq += 1
        cid = f"C{self._seq:03d}"
        c = Case(cid, person_id, ts)
        self.cases[cid] = c
        sns = [d.sn for d in devs]
        for d in devs:
            d.status = STATUS_LOST
        c.note(ts, "mark", sn=",".join(sns))
        return c, sns, False

    def on_found(self, sn, registry, ts=None, detail=""):
        """某设备被 Router 发现（ORPAH-FOUND）→ 找到其走失者案件 → 状态→found。"""
        rec = registry.get(sn)
        if rec is None or not rec.person_id:
            return None
        c = self.active_case(rec.person_id)
        if c is None:
            return None
        ts = ts if ts is not None else int(time.time())
        if c.status == CASE_OPEN:
            c.status = CASE_FOUND
        c.updated = ts
        c.note(ts, "found", sn=sn, detail=detail)
        return c

    def close(self, case_id, registry, outcome, ts=None):
        """结案：outcome ∈ {CASE_CLOSED, CASE_REVOKED}。名下设备 → 启用。

        返回 (case, sns)；案件不存在返回 (None, [])。
        """
        c = self.cases.get(case_id)
        if c is None:
            return None, []
        if outcome not in (CASE_CLOSED, CASE_REVOKED):
            raise ValueError(f"非法结案方式: {outcome}")
        ts = ts if ts is not None else int(time.time())
        c.status = outcome
        c.closed_at = ts
        c.updated = ts
        c.outcome = "found" if outcome == CASE_CLOSED else "revoked"
        sns = []
        for d in registry.devices_of(c.person_id):
            d.status = STATUS_ACTIVE
            sns.append(d.sn)
        c.note(ts, "close", sn=",".join(sns), detail=c.outcome)
        return c, sns

    def to_dict(self, registry):
        out = []
        for c in sorted(self.cases.values(),
                        key=lambda x: x.created, reverse=True):
            devs = registry.devices_of(c.person_id)
            out.append({
                "case_id": c.case_id,
                "person_id": c.person_id,
                "person_name": registry.person_name(c.person_id) or c.person_id,
                "status": c.status,
                "created": c.created,
                "updated": c.updated,
                "closed_at": c.closed_at,
                "outcome": c.outcome,
                "devices": [d.sn for d in devs],
                "events": list(c.events),
            })
        return {"cases": out}
