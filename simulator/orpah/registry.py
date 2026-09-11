#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
registry.py — 设备清册（SN ↔ 走失者绑定、状态、时间戳）

Orpah ID 的客户端台账：一个「走失者/被保护对象」可绑定多个客户端（项链/鞋/眼镜等）。
字段：SN、所属组织、CC、绑定走失者（一对多）、状态（启用/停用/丢失/报废）、
首次入网时间、最近见时间。

SQLite 持久化：内存对象（Person/DeviceRecord）为工作集，每次变更写库，启动时读库恢复。
"""
import re
import sqlite3
import threading
import time

# SN 格式（协议 §2：CC-ORG-UNIQUE[-CHECK]；CC=ISO 3166-1 alpha-2，ORG/UNIQUE=Crockford Base32）
_SN_RE = re.compile(
    r"^[A-Z]{2}-[0-9A-HJKMNP-TV-Z]{2,6}-[0-9A-HJKMNP-TV-Z]{8,16}"
    r"(-[0-9A-HJKMNP-TV-Z]{1,2})?$")


def parse_sn(sn):
    """解析 SN → {cc, org, unique, check}；非法返回 None。"""
    if not isinstance(sn, str) or not _SN_RE.match(sn):
        return None
    parts = sn.split("-")
    return {"cc": parts[0], "org": parts[1],
            "unique": parts[2], "check": parts[3] if len(parts) == 4 else ""}


# 设备状态（生命周期）
STATUS_ACTIVE = "active"      # 启用
STATUS_DISABLED = "disabled"  # 停用
STATUS_LOST = "lost"          # 丢失（已标记走失）
STATUS_SCRAPPED = "scrapped"  # 报废
STATUSES = (STATUS_ACTIVE, STATUS_DISABLED, STATUS_LOST, STATUS_SCRAPPED)

STATUS_ZH = {
    STATUS_ACTIVE: "启用",
    STATUS_DISABLED: "停用",
    STATUS_LOST: "丢失",
    STATUS_SCRAPPED: "报废",
}


class Person:
    """走失者/被保护对象（可挂多个客户端）。"""

    def __init__(self, pid, name, note="", gender="", age="", photo="",
                 height="", build="", features="", health="", mental="",
                 communicate=""):
        self.pid = pid
        self.name = name
        self.note = note
        self.gender = gender
        self.age = age
        self.photo = photo
        self.height = height
        self.build = build
        self.features = features
        self.health = health
        self.mental = mental
        self.communicate = communicate

    def to_dict(self):
        return {"pid": self.pid, "name": self.name, "note": self.note,
                "gender": self.gender, "age": self.age, "photo": self.photo,
                "height": self.height, "build": self.build,
                "features": self.features, "health": self.health,
                "mental": self.mental, "communicate": self.communicate}


class DeviceRecord:
    """客户端台账条目。"""

    def __init__(self, sn, org="WH01", cc="CN", person_id=None,
                 status=STATUS_ACTIVE, first_seen=None, last_seen=None):
        self.sn = sn
        self.org = org
        self.cc = cc
        self.person_id = person_id
        self.status = status
        self.first_seen = first_seen
        self.last_seen = last_seen

    def to_dict(self):
        return {
            "sn": self.sn, "org": self.org, "cc": self.cc,
            "person_id": self.person_id, "status": self.status,
            "first_seen": self.first_seen, "last_seen": self.last_seen,
        }


class Registry:
    """设备清册：走失者（Person）与客户端（DeviceRecord）的一对多绑定（SQLite 持久化）。"""

    def __init__(self, db_path=":memory:"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self._init_db()
        self.persons = {}    # pid -> Person
        self.devices = {}    # sn -> DeviceRecord
        self._pid_seq = 0
        self._load()

    def _init_db(self):
        with self._lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                pid TEXT PRIMARY KEY, name TEXT NOT NULL, note TEXT DEFAULT '',
                gender TEXT DEFAULT '', age TEXT DEFAULT '', height TEXT DEFAULT '',
                build TEXT DEFAULT '', features TEXT DEFAULT '', health TEXT DEFAULT '',
                mental TEXT DEFAULT '', communicate TEXT DEFAULT '', photo TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS devices (
                sn TEXT PRIMARY KEY, person_id TEXT, cc TEXT DEFAULT '', org TEXT DEFAULT '',
                status TEXT DEFAULT 'active', first_seen INTEGER, last_seen INTEGER
            );
            """)
            self.db.commit()

    def _load(self):
        for r in self.db.execute("SELECT * FROM persons"):
            p = Person(r["pid"], r["name"], r["note"], r["gender"], r["age"],
                       r["photo"], r["height"], r["build"], r["features"],
                       r["health"], r["mental"], r["communicate"])
            self.persons[p.pid] = p
            n = int(p.pid[1:]) if p.pid[1:].isdigit() else 0
            self._pid_seq = max(self._pid_seq, n)
        for r in self.db.execute("SELECT * FROM devices"):
            d = DeviceRecord(r["sn"], r["org"], r["cc"], r["person_id"],
                             r["status"], r["first_seen"], r["last_seen"])
            self.devices[d.sn] = d

    def _persist_person(self, p):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO persons (pid, name, note, gender, age,"
                " height, build, features, health, mental, communicate, photo)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.pid, p.name, p.note, p.gender, p.age, p.height, p.build,
                 p.features, p.health, p.mental, p.communicate, p.photo))
            self.db.commit()

    def _persist_device(self, d):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO devices (sn, person_id, cc, org, status,"
                " first_seen, last_seen) VALUES (?,?,?,?,?,?,?)",
                (d.sn, d.person_id, d.cc, d.org, d.status, d.first_seen, d.last_seen))
            self.db.commit()

    def _delete_person(self, pid):
        with self._lock:
            self.db.execute("DELETE FROM persons WHERE pid=?", (pid,))
            self.db.commit()

    def _delete_device(self, sn):
        with self._lock:
            self.db.execute("DELETE FROM devices WHERE sn=?", (sn,))
            self.db.commit()

    # ---- 走失者 ----
    def add_person(self, name, note="", gender="", age="", photo="",
                   height="", build="", features="", health="", mental="",
                   communicate=""):
        self._pid_seq += 1
        pid = f"P{self._pid_seq:03d}"
        p = Person(pid, name, note, gender, age, photo,
                   height, build, features, health, mental, communicate)
        self.persons[pid] = p
        self._persist_person(p)
        return pid

    # ---- 设备 ----
    def register(self, sn, person_id=None, org=None, cc=None,
                 status=STATUS_ACTIVE):
        """登记一台设备；sn 已存在则更新绑定/组织/状态。

        org/cc 缺省时从 SN（CC-ORG-UNIQUE）解析，保证「组织」列自动回填。
        """
        if not sn:
            raise ValueError("sn 不能为空")
        parsed = parse_sn(sn)
        if org is None:
            org = parsed["org"] if parsed else "????"
        if cc is None:
            cc = parsed["cc"] if parsed else "??"
        rec = self.devices.get(sn)
        if rec is None:
            rec = DeviceRecord(sn, org, cc, person_id, status)
            self.devices[sn] = rec
        else:
            rec.org, rec.cc = org, cc
            rec.person_id = person_id
            rec.status = status
        self._persist_device(rec)
        return rec

    def get(self, sn):
        return self.devices.get(sn)

    def set_status(self, sn, status):
        if status not in STATUSES:
            raise ValueError(f"非法状态: {status}")
        rec = self.devices.get(sn)
        if rec is None:
            raise KeyError(f"未知 SN: {sn}")
        rec.status = status
        self._persist_device(rec)
        return rec

    def touch(self, sn, ts=None):
        """上报到达 → 更新 first_seen/last_seen；未知 SN 自动登记（未绑定）。"""
        ts = ts if ts is not None else int(time.time())
        rec = self.devices.get(sn)
        if rec is None:
            parsed = parse_sn(sn)
            rec = DeviceRecord(sn,
                              org=parsed["org"] if parsed else "????",
                              cc=parsed["cc"] if parsed else "??")
            self.devices[sn] = rec
        if rec.first_seen is None:
            rec.first_seen = ts
        rec.last_seen = ts
        self._persist_device(rec)
        return rec

    def remove_device(self, sn):
        """删除设备；存在返回 True。"""
        if sn in self.devices:
            del self.devices[sn]
            self._delete_device(sn)
            return True
        return False

    def update_person(self, pid, name=None, note=None, gender=None, age=None,
                      photo=None, height=None, build=None, features=None,
                      health=None, mental=None, communicate=None):
        """编辑走失者档案：姓名/备注/性别/年龄/照片/身高/体型/体貌/健康/精神/沟通。"""
        p = self.persons.get(pid)
        if p is None:
            raise KeyError(f"未知 pid: {pid}")
        if name is not None and name.strip():
            p.name = name.strip()
        if note is not None:
            p.note = note
        for k in ("gender", "age", "photo", "height", "build", "features",
                  "health", "mental", "communicate"):
            v = locals().get(k)
            if v is not None:
                setattr(p, k, v)
        self._persist_person(p)
        return p

    def remove_person(self, pid):
        """删除走失者；其名下设备全部解绑（person_id=None）。返回解绑设备数。"""
        self.persons.pop(pid, None)
        self._delete_person(pid)
        n = 0
        for rec in self.devices.values():
            if rec.person_id == pid:
                rec.person_id = None
                self._persist_device(rec)
                n += 1
        return n

    def set_statuses(self, sns, status):
        """批量设置状态；返回 (成功数, 未找到的 sn 列表)。"""
        if status not in STATUSES:
            raise ValueError(f"非法状态: {status}")
        ok, missing = 0, []
        for sn in sns:
            rec = self.devices.get(sn)
            if rec is None:
                missing.append(sn)
            else:
                rec.status = status
                self._persist_device(rec)
                ok += 1
        return ok, missing

    def devices_of(self, person_id):
        return [r for r in self.devices.values() if r.person_id == person_id]

    def unbound(self):
        return [r for r in self.devices.values() if r.person_id is None]

    def person_name(self, person_id):
        p = self.persons.get(person_id)
        return p.name if p else None

    def get_person(self, pid):
        """按 pid 取 Person；不存在返回 None。"""
        return self.persons.get(pid)

    def lost_sns(self):
        """当前「丢失」态设备 SN 列表（供 index 标红）。"""
        return [d.sn for d in self.devices.values() if d.status == STATUS_LOST]

    def to_dict(self):
        return {
            "persons": [p.to_dict() for p in self.persons.values()],
            "devices": [d.to_dict() for d in self.devices.values()],
        }
