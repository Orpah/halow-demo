#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stations.py — 定位站位（测点）表

「单台无人机多点悬停」的落地：每个站位 = 一个**已知坐标**的观测点。
补上「这个 RSSI 是在哪个已知位置测到的」这一维之后，单测点就不再只是距离环，
多点即可三边定位（并集最小二乘）。

观测来源两条路，写进同一张表、喂给同一个定位内核：
  - **时间窗**（t0/t1）：无人机悬停在某站位的时段。可事先手填（排练好的脚本），
    也可用「打点」实时生成——按一下 = 此刻到该站位，系统自动收尾上一个站位的窗口。
    落在窗内的 report 归给该站位，取 RSSI 中位数作为该站位的观测。
  - **手动绑定**（rssi）：把某一条 report 的 RSSI 直接指派给某站位，不需要时间窗。

本模块只管「站位 + 观测」的持久化；定位计算（trilaterate）复用 track.html 现成内核，
避免模拟与真实两套实现。

SQLite 持久化：内存对象为工作集，每次变更写库，启动时读库恢复。
"""
import sqlite3
import threading
import time


class Station:
    """一个观测站位（已知坐标）+ 它的一次观测（时间窗内聚合 或 手动绑定）。"""

    def __init__(self, sid, x=0.0, y=0.0, name="", t0=None, t1=None,
                 rssi=None, rssi_t=None):
        self.sid = sid
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.t0 = t0          # 时间窗起（epoch ms；None = 未设定）
        self.t1 = t1          # 时间窗止（None = 至今 / 未收尾）
        self.rssi = rssi      # 手动绑定观测（dBm；None = 走时间窗）
        self.rssi_t = rssi_t  # 手动绑定时间（epoch ms）

    def to_dict(self):
        return {"sid": self.sid, "name": self.name, "x": self.x, "y": self.y,
                "t0": self.t0, "t1": self.t1,
                "rssi": self.rssi, "rssi_t": self.rssi_t}


class StationTable:
    """站位表（全局一张；定位是环境配置，与具体设备无关）。"""

    def __init__(self, db_path=":memory:"):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self._init_db()
        self.stations = {}   # sid -> Station
        self._seq = 0
        self._load()

    def _init_db(self):
        with self._lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS stations (
                sid TEXT PRIMARY KEY, name TEXT DEFAULT '',
                x REAL DEFAULT 0, y REAL DEFAULT 0,
                t0 INTEGER, t1 INTEGER, rssi REAL, rssi_t INTEGER
            );
            """)
            self.db.commit()

    def _load(self):
        for r in self.db.execute("SELECT * FROM stations"):
            s = Station(r["sid"], r["x"], r["y"], r["name"],
                        r["t0"], r["t1"], r["rssi"], r["rssi_t"])
            self.stations[s.sid] = s
            n = int(s.sid[1:]) if s.sid[1:].isdigit() else 0
            self._seq = max(self._seq, n)

    def _persist(self, s):
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO stations"
                " (sid, name, x, y, t0, t1, rssi, rssi_t) VALUES (?,?,?,?,?,?,?,?)",
                (s.sid, s.name, s.x, s.y, s.t0, s.t1, s.rssi, s.rssi_t))
            self.db.commit()

    def _delete(self, sid):
        with self._lock:
            self.db.execute("DELETE FROM stations WHERE sid=?", (sid,))
            self.db.commit()

    # ---- 查询 ----
    def list(self):
        """按 sid 数字序返回全部站位。"""
        return sorted(self.stations.values(),
                      key=lambda s: int(s.sid[1:]) if s.sid[1:].isdigit() else 0)

    def get(self, sid):
        return self.stations.get(sid)

    def to_dict(self):
        return {"ok": True, "stations": [s.to_dict() for s in self.list()]}

    # ---- 增删改 ----
    def add(self, x=0.0, y=0.0, name=""):
        self._seq += 1
        s = Station(f"S{self._seq}", x, y, name)
        self.stations[s.sid] = s
        self._persist(s)
        return s

    def update(self, sid, **fields):
        """改站位字段（x/y/name/t0/t1/rssi）。未给的字段不动。"""
        s = self.stations.get(sid)
        if s is None:
            return None
        for k in ("name", "x", "y", "t0", "t1", "rssi"):
            if k in fields:
                v = fields[k]
                if k in ("x", "y") and v is not None:
                    v = float(v)
                elif k in ("t0", "t1") and v is not None:
                    v = int(v)
                elif k == "rssi" and v is not None:
                    v = float(v)
                setattr(s, k, v)
        self._persist(s)
        return s

    def remove(self, sid):
        if sid not in self.stations:
            return False
        del self.stations[sid]
        self._delete(sid)
        return True

    def clear(self):
        n = len(self.stations)
        for sid in list(self.stations):
            self._delete(sid)
        self.stations.clear()
        self._seq = 0
        return n

    def import_config(self, data):
        """导入悬停计划（覆盖式）：接受裸数组或 {"stations": [...]}。

        每项：{sid?, name?, x, y, t0?, t1?}。sid 缺省按顺序自动编号。
        坐标必填（没有坐标的站位无法参与定位）。
        """
        items = data.get("stations") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("配置格式应为 [{...}] 或 {\"stations\": [{...}]}")
        self.clear()
        n = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("x") is None or it.get("y") is None:
                continue
            if it.get("sid"):
                sid = str(it["sid"])
                s = Station(sid, it["x"], it["y"], it.get("name", ""),
                            it.get("t0"), it.get("t1"))
                self.stations[sid] = s
                k = int(sid[1:]) if sid[1:].isdigit() else 0
                self._seq = max(self._seq, k)
            else:
                self._seq += 1
                s = Station(f"S{self._seq}", it["x"], it["y"], it.get("name", ""),
                            it.get("t0"), it.get("t1"))
                self.stations[s.sid] = s
            self._persist(s)
            n += 1
        return n

    # ---- 观测 ----
    def punch(self, sid, t=None):
        """打点：记「此刻在该站位」。

        该站位 t0=t、t1=None；其它「已打点但还没收尾」的站位（t0 更早、t1 为空）
        视为已离开 → t1=t。于是各站位的时间窗就是两次打点之间的区间。
        """
        s = self.stations.get(sid)
        if s is None:
            return None
        t = int(t) if t else int(time.time() * 1000)
        for o in self.stations.values():
            if o.sid != sid and o.t1 is None and o.t0 is not None and o.t0 <= t:
                o.t1 = t
                self._persist(o)
        s.t0, s.t1 = t, None
        self._persist(s)
        return s

    def bind(self, sid, rssi, t=None):
        """手动绑定：把某条 report 的 RSSI 指派给该站位（优先于时间窗）。"""
        s = self.stations.get(sid)
        if s is None:
            return None
        s.rssi = float(rssi)
        s.rssi_t = int(t) if t else int(time.time() * 1000)
        self._persist(s)
        return s

    def unbind(self, sid):
        """取消手动绑定 → 该站位回落到时间窗聚合。"""
        s = self.stations.get(sid)
        if s is None:
            return None
        s.rssi, s.rssi_t = None, None
        self._persist(s)
        return s
