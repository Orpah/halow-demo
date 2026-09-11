#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tsdb.py — Apache IoTDB 时序库写入/查询封装（上报流 + 业务事件）。

- 设备上报：root.orpah.devices.<sn>，测点 rssi(FLOAT)/seq(INT64)/router_id(TEXT)
- 业务事件：root.orpah.events，字段 etype/sn/detail（全 TEXT）
- IoTDB 未启动时优雅降级：写入静默失败、定期重连，不影响 demo 其余功能
"""
import threading
import time

try:
    from iotdb.Session import Session
    from iotdb.utils.IoTDBConstants import TSDataType
    _HAS_IOTDB = True
except Exception:                       # 未装 apache-iotdb 时降级
    _HAS_IOTDB = False


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
        if self.enabled:
            self._connect()

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
        else:
            self._retry_delay = min(self._retry_delay * 2, 10.0)
        return self.available

    @staticmethod
    def _sn_path(sn):
        # SN 形如 CN-WH01-9AF3C1D2：'-' 不是合法路径节点，替换为 '_'
        return "root.orpah.devices." + (sn or "?").replace("-", "_")

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

    def write_event(self, etype, sn="", detail="", ts=None):
        """写一条业务事件（publish/found/id_report/case_mark/case_found/case_close）。

        ts 可选：传入业务发生时间（如 missing_at），否则用当前时间。
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
                    ["etype", "sn", "detail"],
                    [TSDataType.TEXT, TSDataType.TEXT, TSDataType.TEXT],
                    [etype, sn or "", detail or ""])
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
        """查询业务事件历史（时间倒序）→ [{t(ms), etype, sn, detail}]。

        etype / sn 为空则不过滤。过滤在本地做（多取一些再筛）：
        IoTDB 树模型对「非投影列」做值过滤不可靠，故不把条件写进 WHERE。
        无数据时返回空列表 []；IoTDB 未就绪/查询失败返回 None。
        """
        if not self._ensure() or self.session is None:
            return None
        limit = max(1, int(limit))
        fetch = limit if not (etype or sn) else min(limit * 10, 5000)
        rows = self._read_rows(
            f"SELECT etype, sn, detail FROM root.orpah.events "
            f"ORDER BY time DESC LIMIT {fetch}")
        if rows is None:
            return None
        out = [r for r in rows
               if (not etype or r.get("etype") == etype)
               and (not sn or r.get("sn") == sn)]
        return out[:limit]

    def close(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None
        self.available = False
