#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cases.py — 走失案件闭环（以人为单位，非单 SN）

状态机：
    立案 mark    某人走失 → 名下所有设备进入「丢失」态（每台都标记走失）
  → 发现 found   任一台设备被 Router 命中走失表（ORPAH-FOUND）→ 该人「已发现」
  → 结案 close   找回（closed，设备恢复启用）/ 撤销误报（revoked，设备恢复启用）

SQLite 持久化；不依赖 server。由 ui_server 负责与权威走失表（server.mark_tracked/
untrack）联动，并注入 Router 发现事件（ORPAH-FOUND）。
"""
import sqlite3
import threading
import time

from registry import STATUS_ACTIVE, STATUS_LOST, STATUS_SCRAPPED

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

    def __init__(self, case_id, person_id, ts,
                 missing_at="", missing_place="", possible_to="", clothing="",
                 contact_phone="", police="", police_case_no="", police_station="",
                 belongings="", vehicle=""):
        self.case_id = case_id
        self.person_id = person_id
        self.status = CASE_OPEN
        self.created = ts
        self.updated = ts
        self.closed_at = None
        self.outcome = None          # "found" / "revoked"（结案方式）
        self.events = []             # [{t, type, sn, detail}]
        self.found_sns = set()       # 已记录「发现」的设备 SN（按 case+sn 去重）
        # 走失信息（现实寻人启事要素）
        self.missing_at = missing_at
        self.missing_place = missing_place
        self.possible_to = possible_to
        self.clothing = clothing
        self.contact_phone = contact_phone
        self.police = police
        self.police_case_no = police_case_no
        self.police_station = police_station
        self.belongings = belongings
        self.vehicle = vehicle

    def note(self, ts, type_, sn="", detail=""):
        self.events.append({"t": ts, "type": type_, "sn": sn, "detail": detail})
        del self.events[:-MAX_EVENTS]


class CaseManager:
    """走失案件台账：case_id -> Case（SQLite 持久化）。"""

    def __init__(self, db_path=":memory:"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self._init_db()
        self.cases = {}
        self._seq = 0
        self._load()

    def _init_db(self):
        with self._lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY, person_id TEXT NOT NULL,
                status TEXT NOT NULL, outcome TEXT, created INTEGER NOT NULL,
                updated INTEGER NOT NULL, closed_at INTEGER,
                missing_at TEXT DEFAULT '', missing_place TEXT DEFAULT '',
                possible_to TEXT DEFAULT '', clothing TEXT DEFAULT '',
                contact_phone TEXT DEFAULT '', police TEXT DEFAULT '',
                police_case_no TEXT DEFAULT '', police_station TEXT DEFAULT '',
                belongings TEXT DEFAULT '', vehicle TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                t INTEGER NOT NULL, type TEXT NOT NULL,
                sn TEXT DEFAULT '', detail TEXT DEFAULT ''
            );
            """)
            self.db.commit()

    def _load(self):
        for r in self.db.execute("SELECT * FROM cases"):
            c = Case(r["case_id"], r["person_id"], r["created"],
                     r["missing_at"], r["missing_place"], r["possible_to"],
                     r["clothing"], r["contact_phone"], r["police"],
                     r["police_case_no"], r["police_station"], r["belongings"],
                     r["vehicle"])
            c.status = r["status"]
            c.updated = r["updated"]
            c.closed_at = r["closed_at"]
            c.outcome = r["outcome"]
            self.cases[c.case_id] = c
            n = int(c.case_id[1:]) if c.case_id[1:].isdigit() else 0
            self._seq = max(self._seq, n)
        for r in self.db.execute("SELECT * FROM case_events ORDER BY id"):
            c = self.cases.get(r["case_id"])
            if c is not None:
                ev = {"t": r["t"], "type": r["type"],
                      "sn": r["sn"], "detail": r["detail"]}
                c.events.append(ev)
                if r["type"] == "found" and r["sn"]:
                    c.found_sns.add(r["sn"])
        for c in self.cases.values():
            del c.events[:-MAX_EVENTS]

    def _persist_case(self, c):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO cases (case_id, person_id, status,"
                " outcome, created, updated, closed_at, missing_at, missing_place,"
                " possible_to, clothing, contact_phone, police, police_case_no,"
                " police_station, belongings, vehicle)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (c.case_id, c.person_id, c.status, c.outcome, c.created,
                 c.updated, c.closed_at, c.missing_at, c.missing_place,
                 c.possible_to, c.clothing, c.contact_phone, c.police,
                 c.police_case_no, c.police_station, c.belongings, c.vehicle))
            self.db.commit()

    def _add_event(self, c, ev):
        with self._lock:
            self.db.execute(
                "INSERT INTO case_events (case_id, t, type, sn, detail)"
                " VALUES (?,?,?,?,?)",
                (c.case_id, ev["t"], ev["type"], ev["sn"], ev["detail"]))
            self.db.commit()

    def _note(self, c, ts, type_, sn="", detail=""):
        c.note(ts, type_, sn, detail)
        self._add_event(c, c.events[-1])

    def active_case(self, person_id):
        """该走失者当前未结（open/found）案件；无则返回 None。"""
        for c in self.cases.values():
            if c.person_id == person_id and c.status in (CASE_OPEN, CASE_FOUND):
                return c
        return None

    def open_cases(self):
        """当前所有未结案件（open/found），供启动时同步走失表。"""
        return [c for c in self.cases.values()
                if c.status in (CASE_OPEN, CASE_FOUND)]

    def mark(self, person_id, registry, ts=None,
             missing_at="", missing_place="", possible_to="", clothing="",
             contact_phone="", police="", police_case_no="", police_station="",
             belongings="", vehicle=""):
        """立案：该走失者名下所有设备 → 丢失；可选填走失信息。

        返回 (case, sns, dup)：
          - 名下无设备：case=None；
          - 已有未结案件：返回已有案件，sns=[]，dup=True。
        """
        old = self.active_case(person_id)
        if old is not None:
            return old, [], True
        devs = [d for d in registry.devices_of(person_id)
                if d.status != STATUS_SCRAPPED]   # 报废设备不再参与案件
        if not devs:
            return None, [], False
        ts = ts if ts is not None else int(time.time())
        self._seq += 1
        cid = f"C{self._seq:03d}"
        c = Case(cid, person_id, ts, missing_at, missing_place, possible_to,
                 clothing, contact_phone, police, police_case_no,
                 police_station, belongings, vehicle)
        self.cases[cid] = c
        sns = [d.sn for d in devs]
        registry.set_statuses(sns, STATUS_LOST)   # 设备→丢失（写库）
        self._note(c, ts, "mark", sn=",".join(sns))
        self._persist_case(c)
        return c, sns, False

    def on_found(self, sn, registry, ts=None, detail=""):
        """某设备被上报/发现 → 找到其走失者案件 → 首次发现即转 found、写事件。

        同一设备重复出现只刷新 updated，不重复写事件（按 case+sn 去重）。
        """
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
        if sn not in c.found_sns:
            c.found_sns.add(sn)
            self._note(c, ts, "found", sn=sn, detail=detail)
        self._persist_case(c)
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
        sns = [d.sn for d in registry.devices_of(c.person_id)]
        registry.set_statuses(sns, STATUS_ACTIVE)   # 设备→启用（写库）
        self._note(c, ts, "close", sn=",".join(sns), detail=c.outcome)
        self._persist_case(c)
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
                "missing_at": c.missing_at,
                "missing_place": c.missing_place,
                "possible_to": c.possible_to,
                "clothing": c.clothing,
                "contact_phone": c.contact_phone,
                "police": c.police,
                "police_case_no": c.police_case_no,
                "police_station": c.police_station,
                "belongings": c.belongings,
                "vehicle": c.vehicle,
            })
        return {"cases": out}
