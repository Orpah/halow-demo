#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
registry.py — 设备清册（SN ↔ 走失者绑定、状态、时间戳）

Orpah ID 的客户端台账：一个「走失者/被保护对象」可绑定多个客户端（项链/鞋/眼镜等）。
字段：SN、所属组织、CC、绑定走失者（一对多）、状态（启用/停用/丢失/报废）、
首次入网时间、最近见时间。

纯内存实现（demo 用），后续 P0 审计/告警/案件闭环都挂在这个清册上。
"""
import time

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

    def __init__(self, pid, name, note=""):
        self.pid = pid
        self.name = name
        self.note = note

    def to_dict(self):
        return {"pid": self.pid, "name": self.name, "note": self.note}


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
    """设备清册：走失者（Person）与客户端（DeviceRecord）的一对多绑定。"""

    def __init__(self):
        self.persons = {}    # pid -> Person
        self.devices = {}    # sn -> DeviceRecord
        self._pid_seq = 0

    # ---- 走失者 ----
    def add_person(self, name, note=""):
        self._pid_seq += 1
        pid = f"P{self._pid_seq:03d}"
        self.persons[pid] = Person(pid, name, note)
        return pid

    # ---- 设备 ----
    def register(self, sn, person_id=None, org="WH01", cc="CN",
                 status=STATUS_ACTIVE):
        """登记一台设备；sn 已存在则更新绑定/组织/状态。"""
        if not sn:
            raise ValueError("sn 不能为空")
        rec = self.devices.get(sn)
        if rec is None:
            rec = DeviceRecord(sn, org, cc, person_id, status)
            self.devices[sn] = rec
        else:
            rec.org, rec.cc = org, cc
            rec.person_id = person_id
            rec.status = status
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
        return rec

    def touch(self, sn, ts=None):
        """上报到达 → 更新 first_seen/last_seen；未知 SN 自动登记（未绑定）。"""
        ts = ts if ts is not None else int(time.time())
        rec = self.devices.get(sn)
        if rec is None:
            rec = DeviceRecord(sn)
            self.devices[sn] = rec
        if rec.first_seen is None:
            rec.first_seen = ts
        rec.last_seen = ts
        return rec

    def devices_of(self, person_id):
        return [r for r in self.devices.values() if r.person_id == person_id]

    def unbound(self):
        return [r for r in self.devices.values() if r.person_id is None]

    def person_name(self, person_id):
        p = self.persons.get(person_id)
        return p.name if p else None

    def to_dict(self):
        return {
            "persons": [p.to_dict() for p in self.persons.values()],
            "devices": [d.to_dict() for d in self.devices.values()],
        }
