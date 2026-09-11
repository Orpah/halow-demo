#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tsdb.py — Apache IoTDB 时序库写入/查询封装（上报流 + 业务事件）。

- 设备上报：root.orpah.devices.<sn>，测点 rssi(FLOAT)/seq(INT64)/router_id(TEXT)
- 业务事件：root.orpah.events，字段 etype/sn/detail/actor（全 TEXT）
  actor = 操作者（审计「谁」），自动事件记 "system"；操作者未填则记空串
- 事件保留期限：ORPAH_EVENT_RETENTION_DAYS（默认 30 天，0 = 不清理）
- IoTDB 未启动时优雅降级：写入静默失败、定期重连，不影响 demo 其余功能
"""
import os
import threading
import time

try:
    from iotdb.Session import Session
    from iotdb.utils.IoTDBConstants import TSDataType
    _HAS_IOTDB = True
except Exception:                       # 未装 apache-iotdb 时降级
    _HAS_IOTDB = False


def _env_int(name, default):
    """取整数环境变量，非法值回退默认（空串也算非法）。"""
    try:
        return int(str(os.environ.get(name, "") or default).strip())
    except (TypeError, ValueError):
        return default


# 事件保留期限（天）：启动连上 IoTDB 后清理超过该期限的事件历史。0 = 不清理。
EVENT_RETENTION_DAYS = _env_int("ORPAH_EVENT_RETENTION_DAYS", 30)


class Tsdb:
    """IoTDB 写入器（线程安全，带优雅降级与自动重连）。"""

    def __init__(self, host="127.0.0.1", port=6667, user="root", pwd="root",
                 enabled=True):
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.enabled = enabled and _HAS_IOTDB
        self.session = None
        self.available = False
        self._lock = threading.Lock()
        self._evt_lock = threading.Lock()
        self._evt_last_ms = 0            # 事件时间戳单调递增游标
        self._last_try = 0.0
        self._retry_delay = 1.0
        self.event_retention_days = EVENT_RETENTION_DAYS
        self.purged_upto = None          # 最近一次清理的截止时间(ms)
        self._purged = False             # 本次进程是否已执行过启动清理
        if self.enabled:
            self._connect()
            # 首次连上即按保留期限清理一次；IoTDB 比本进程晚起时由 _ensure 补跑
            self.purge_events()

    # ---------------- 连接 ----------------
    def _connect(self):
        if not self.enabled:
            return
        try:
            s = Session(self.host, self.port, self.user, self.pwd,
                        fetch_size=1024, zone_id="UTC+8")
            s.open(enable_rpc_compression=False)
            try:
                s.execute_non_query_statement("CREATE DATABASE root.orpah")
            except Exception:
                pass                       # 已存在则忽略
            self.session = s
            self.available = True
        except Exception:
            self.session = None
            self.available = False

    def _ensure(self):
        """确保连接可用；不可用则指数退避重连（1s→2s→…→10s 上限）。"""
        if self.available:
            return True
        if not self.enabled:
            return False
        if time.time() - self._last_try < self._retry_delay:
            return False
        self._last_try = time.time()
        self._connect()
        if self.available:
            self._retry_delay = 1.0
            self.purge_events()          # 连上后按保留期限清理一次（仅首次生效）
        else:
            self._retry_delay = min(self._retry_delay * 2, 10.0)
        return self.available

    @staticmethod
    def _sn_path(sn):
        # SN 形如 CN-WH01-9AF3C1D2：'-' 不是合法路径节点，替换为 '_'
        return "root.orpah.devices." + (sn or "?").replace("-", "_")

    @staticmethod
    def _router_path(sid, sn):
        """路由器侧测量路径：root.orpah.routers.<sid>.<sn>。

        每台路由器自己一条设备路径（下一级是「在观测谁」）—— 多路由器定位要的是
        「第 sid 台路由器此刻听到该设备的强度」，与设备自己报的链路值是两个东西，
        分开存才不会互相覆盖，也才能各取各的时间序列。
        """
        return ("root.orpah.routers." + (sid or "?").replace("-", "_")
                + "." + (sn or "?").replace("-", "_"))

    # ---------------- 写入 ----------------
    def write_report(self, sn, ts=None, rssi=None, seq=None, router_id=""):
        """写一条设备上报点（rssi/seq/router_id）。返回是否成功。"""
        if not self._ensure() or self.session is None:
            return False
        try:
            ts_ms = int((ts or time.time()) * 1000)
            with self._lock:
                self.session.insert_record(
                    self._sn_path(sn), ts_ms,
                    ["rssi", "seq", "router_id"],
                    [TSDataType.FLOAT, TSDataType.INT64, TSDataType.TEXT],
                    [float(rssi) if rssi is not None else 0.0,
                     int(seq) if seq is not None else 0,
                     router_id or ""])
            return True
        except Exception:
            self.available = False
            return False

    def write_event(self, etype, sn="", detail="", ts=None, actor=""):
        """写一条业务事件（publish/found/id_report/id_reject/case_mark/case_found/case_close）。

        ts 可选：传入业务发生时间（如 missing_at），否则用当前时间。
        actor 可选：操作者（审计「谁」）；自动事件不传 → 记 "system"，
        操作者留空则记空串（展示为「—」）。
        注意：所有事件共用 root.orpah.events 这一个设备路径，IoTDB 同设备同时间戳
        为 last-write-wins → 同一毫秒的多条事件会互相覆盖。故未显式传 ts 时把
        时间戳钳成单调递增（最多偏移几毫秒），不丢事件。
        """
        if not self._ensure() or self.session is None:
            return False
        try:
            ms = int((ts or time.time()) * 1000)
            if ts is None:                       # 仅自动时间参与单调化
                with self._evt_lock:
                    if ms <= self._evt_last_ms:
                        ms = self._evt_last_ms + 1
                    self._evt_last_ms = ms
            with self._lock:
                self.session.insert_record(
                    "root.orpah.events", ms,
                    ["etype", "sn", "detail", "actor"],
                    [TSDataType.TEXT, TSDataType.TEXT, TSDataType.TEXT,
                     TSDataType.TEXT],
                    [etype, sn or "", detail or "",
                     (actor or "").strip() or "system"])
            return True
        except Exception:
            self.available = False
            return False

    # ---------------- 查询 ----------------
    def _read_rows(self, sql):
        """执行查询 → [{t(ms), <列名>: 值}]（TEXT 自动解码）。失败返回 None。"""
        try:
            with self._lock:
                ds = self.session.execute_query_statement(sql)
            cols = ds.get_column_names()
            rows = []
            while ds.has_next():
                rr = ds.next()
                fields = rr.get_fields()          # 不含 Time 列
                rec = {"t": int(rr.get_timestamp())}
                for i, c in enumerate(cols[1:]):  # cols[0]=Time
                    v = fields[i].value
                    if isinstance(v, bytes):      # TEXT 返回 bytes → 解码
                        v = v.decode("utf-8", "replace")
                    rec[c.split(".")[-1]] = v
                rows.append(rec)
            ds.close_operation_handle()
            return rows
        except Exception:
            self.available = False
            return None

    # ---------------- 路由器侧测量（多路由器定位用） ----------------
    def write_router_obs(self, sid, sn, ts=None, rssi=None, seq=None):
        """写一条路由器测量：第 sid 台路由器此刻测到 sn 的 RSSI。

        **ts = epoch 秒**（与 write_report 一致；传毫秒会被当成天文数字的时间戳），
        None = 用当前时间。
        与 write_report 的区别：那是**设备自己**报的链路值（root.orpah.devices.<sn>），
        这是**某台路由器听到它**的强度（root.orpah.routers.<sid>.<sn>）。
        多路由器定位需要同一时刻多台各自的测量 —— 每台一条序列，互不覆盖。
        """
        if not self._ensure() or self.session is None:
            return False
        try:
            ts_ms = int((ts or time.time()) * 1000)
            with self._lock:
                self.session.insert_record(
                    self._router_path(sid, sn), ts_ms,
                    ["rssi", "seq"],
                    [TSDataType.FLOAT, TSDataType.INT64],
                    [float(rssi) if rssi is not None else 0.0,
                     int(seq) if seq is not None else 0])
            return True
        except Exception:
            self.available = False
            return False

    def query_router_range(self, sid, sn, t0_ms, t1_ms, limit=20000):
        """某路由器在某时间窗内对某设备的测量，**按时间升序** → [{t, rssi, seq}]。"""
        if not self._ensure() or self.session is None:
            return None
        lo, hi = int(min(t0_ms, t1_ms)), int(max(t0_ms, t1_ms))
        return self._read_rows(
            f"SELECT rssi, seq FROM {self._router_path(sid, sn)} "
            f"WHERE time >= {lo} AND time <= {hi} "
            f"ORDER BY time ASC LIMIT {max(1, int(limit))}")

    def query_router_recent(self, sid, sn, limit=500):
        """某路由器最近 N 条测量，**返回时按时间升序**（与 query_report 同风格）。"""
        if not self._ensure() or self.session is None:
            return None
        rows = self._read_rows(
            f"SELECT rssi, seq FROM {self._router_path(sid, sn)} "
            f"ORDER BY time DESC LIMIT {max(1, int(limit))}")
        if rows is None:
            return None
        rows.reverse()
        return rows

    # ---------------- 设备上报流查询 ----------------
    def query_report(self, sn, limit=100):
        """查询某设备最近上报点 → [{t(ms), rssi, seq, router_id}]。

        无数据时返回空列表 []；IoTDB 未就绪/查询失败返回 None。
        """
        if not self._ensure() or self.session is None:
            return None
        rows = self._read_rows(
            f"SELECT rssi, seq, router_id FROM {self._sn_path(sn)} "
            f"ORDER BY time DESC LIMIT {int(limit)}")
        return rows

    def query_events(self, limit=50, etype="", sn=""):
        """查询业务事件历史（时间倒序）→ [{t(ms), etype, sn, detail, actor}]。

        etype / sn 为空则不过滤。过滤在本地做（多取一些再筛）：
        IoTDB 树模型对「非投影列」做值过滤不可靠，故不把条件写进 WHERE。
        actor 列为后加：更早的行回读为 None → 统一成空串（展示为「—」）。
        无数据时返回空列表 []；IoTDB 未就绪/查询失败返回 None。
        """
        if not self._ensure() or self.session is None:
            return None
        limit = max(1, int(limit))
        fetch = limit if not (etype or sn) else min(limit * 10, 5000)
        rows = self._read_rows(
            f"SELECT etype, sn, detail, actor FROM root.orpah.events "
            f"ORDER BY time DESC LIMIT {fetch}")
        if rows is None:
            return None
        out = []
        for r in rows:
            if etype and r.get("etype") != etype:
                continue
            if sn and r.get("sn") != sn:
                continue
            if not r.get("actor"):               # 老行无该列 → None
                r["actor"] = ""
            out.append(r)
        return out[:limit]

    # ---------------- 时间窗查询（回放用） ----------------
    # 注意：值过滤（etype/sn）不能写进 WHERE（树模型对非投影列不可靠，见 query_events 注释），
    # 但**时间**过滤是 IoTDB 的原生索引，写 WHERE 既准又快 —— 回放必须靠它按窗口取数。
    def query_report_range(self, sn, t0_ms, t1_ms, limit=20000):
        """某时间窗内的上报点，**按时间升序**（回放按时间轴顺序消费）。

        返回 [{t(ms), rssi, seq, router_id}]；无数据 []；IoTDB 未就绪 None。
        """
        if not self._ensure() or self.session is None:
            return None
        lo, hi = int(min(t0_ms, t1_ms)), int(max(t0_ms, t1_ms))
        return self._read_rows(
            f"SELECT rssi, seq, router_id FROM {self._sn_path(sn)} "
            f"WHERE time >= {lo} AND time <= {hi} "
            f"ORDER BY time ASC LIMIT {max(1, int(limit))}")

    def query_events_range(self, t0_ms, t1_ms, limit=5000, etype="", sn=""):
        """某时间窗内的事件，**按时间升序**。etype/sn 仍本地过滤（多取 5 倍再筛）。"""
        if not self._ensure() or self.session is None:
            return None
        lo, hi = int(min(t0_ms, t1_ms)), int(max(t0_ms, t1_ms))
        fetch = max(1, int(limit)) * (5 if (etype or sn) else 1)
        rows = self._read_rows(
            f"SELECT etype, sn, detail, actor FROM root.orpah.events "
            f"WHERE time >= {lo} AND time <= {hi} "
            f"ORDER BY time ASC LIMIT {fetch}")
        if rows is None:
            return None
        out = []
        for r in rows:
            if etype and r.get("etype") != etype:
                continue
            if sn and r.get("sn") != sn:
                continue
            if not r.get("actor"):               # 老行无 actor 列 → None
                r["actor"] = ""
            out.append(r)
        return out[:max(1, int(limit))]

    def purge_events(self, days=None):
        """按保留期限清理事件历史 → 返回截止时间(ms)，未执行返回 None。

        IoTDB `delete_data(paths, end_time)` 删除 ts <= end_time 的数据，
        故保留最近 days 天、删掉更早的。days <= 0 = 保留全部（不清理）。
        只在本进程首次连上库后自动跑一次（见 _ensure），也可手动调用。
        """
        d = self.event_retention_days if days is None else int(days)
        if d <= 0 or self._purged:
            return None
        if not self.available or self.session is None:
            return None
        cutoff = int((time.time() - d * 86400) * 1000)
        try:
            with self._lock:
                self.session.delete_data(["root.orpah.events"], cutoff)
            self.purged_upto = cutoff
            self._purged = True
            return cutoff
        except Exception:
            self.available = False
            return None

    def close(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None
        self.available = False
