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
        self._last_try = 0.0
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
        """确保连接可用；不可用则节流重连（每 10s 最多一次）。"""
        if self.available:
            return True
        if not self.enabled:
            return False
        if time.time() - self._last_try < 10:
            return False
        self._last_try = time.time()
        self._connect()
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

    def write_event(self, etype, sn="", detail=""):
        """写一条业务事件（case_mark/case_found/case_close/found 等）。"""
        if not self._ensure() or self.session is None:
            return False
        try:
            with self._lock:
                self.session.insert_str_record(
                    "root.orpah.events", int(time.time() * 1000),
                    ["etype", "sn", "detail"],
                    [etype, sn or "", detail or ""])
            return True
        except Exception:
            self.available = False
            return False

    # ---------------- 查询 ----------------
    def query_report(self, sn, limit=100):
        """查询某设备最近上报点 → [{t(ms), rssi, seq, router_id}]。"""
        if not self._ensure() or self.session is None:
            return None
        try:
            with self._lock:
                ds = self.session.execute_query_statement(
                    f"SELECT rssi, seq, router_id FROM {self._sn_path(sn)} "
                    f"ORDER BY time DESC LIMIT {int(limit)}")
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

    def close(self):
        if self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = None
        self.available = False
