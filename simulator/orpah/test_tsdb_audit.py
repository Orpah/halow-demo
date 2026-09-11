#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tsdb_audit.py — 审计补全的自检：actor 字段 + 事件保留期限。

不依赖真实 IoTDB：用假 Session/Dataset 顶替，只验我们自己的代码路径
（列名、默认值、保留期算术、只清理一次的守卫）。
跑法：C:\\Python313\\python.exe test_tsdb_audit.py
"""
import sys
import time

import tsdb

FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


class FakeSession:
    """只记调用，行为对齐真实 Session 的签名。"""

    def __init__(self):
        self.inserts = []
        self.deletes = []
        self.query_sql = []
        self.rows = []            # [(ts, [etype, sn, detail, actor])]
        self.cols = ["etype", "sn", "detail", "actor"]

    def insert_record(self, path, ts, meas, types, vals):
        self.inserts.append((path, ts, list(meas), list(vals)))

    def delete_data(self, paths, end_time):
        self.deletes.append((list(paths), end_time))

    def execute_query_statement(self, sql):
        self.query_sql.append(sql)
        # 列名随 SQL 变：上报点取 3 列，事件取 4 列（_read_rows 靠列名建字段）
        self.cols = (["rssi", "seq", "router_id"] if "rssi" in sql
                     else ["etype", "sn", "detail", "actor"])
        return FakeDataset(self.rows, self.cols)


class FakeField:
    def __init__(self, v):
        if v is None or isinstance(v, (int, float)):
            self.value = v                      # 数值列（rssi/seq）原样返回
        else:
            self.value = str(v).encode()


class FakeRow:
    def __init__(self, ts, vals):
        self._ts, self._vals = ts, vals

    def get_timestamp(self):
        return self._ts

    def get_fields(self):
        return [FakeField(v) for v in self._vals]


class FakeDataset:
    def __init__(self, rows, cols=None):
        self._rows = [FakeRow(t, v) for t, v in rows]
        self._i = 0
        self._cols = cols or ["etype", "sn", "detail", "actor"]

    def get_column_names(self):
        return ["Time"] + ["root.orpah.events." + c for c in self._cols]

    def has_next(self):
        return self._i < len(self._rows)

    def next(self):
        r = self._rows[self._i]
        self._i += 1
        return r

    def close_operation_handle(self):
        pass


def fresh(days=30, rows=None):
    """造一个「已连上库」的 Tsdb（不真连）。"""
    t = tsdb.Tsdb(enabled=False)
    t.session = FakeSession()
    t.session.rows = rows or []
    t.available = True
    t.event_retention_days = days
    return t


print("== 1. actor 字段 ==")
t = fresh()
t.write_event("case_mark", sn="CN-WH01-A", detail="C1", actor=" shijh ")
_, _, meas, vals = t.session.inserts[-1]
ck("measurements 含 actor", "actor" in meas, str(meas))
ck("actor 去空格落地", vals[meas.index("actor")] == "shijh", vals[meas.index("actor")])
t.write_event("publish", detail="n=1")
vals = t.session.inserts[-1][3]
ck("自动事件 actor=system", vals[3] == "system", vals[3])
t.write_event("case_close", detail="C1:closed", actor="   ")
ck("空白 actor 也记 system", t.session.inserts[-1][3][3] == "system")

print("== 2. query_events 回读 actor ==")
rows = [(1000, ["case_mark", "CN-WH01-A", "C1", "shijh"]),
        (900, ["publish", "", "n=1", None])]        # 老行无 actor 列 → None
t = fresh(rows=rows)
out = t.query_events(limit=10)
ck("返回 2 行", len(out) == 2, str(len(out)))
ck("人为操作带回 actor", out[0].get("actor") == "shijh", out[0].get("actor"))
ck("老行 actor 归一为空串", out[1].get("actor") == "", repr(out[1].get("actor")))
ck("SELECT 带 actor 列", "actor" in t.session.query_sql[0], t.session.query_sql[0])
out = t.query_events(limit=10, etype="publish")
ck("etype 过滤仍然生效", len(out) == 1 and out[0]["etype"] == "publish", str(len(out)))

print("== 3. 保留期限清理 ==")
NOW = time.time()
t = fresh(days=30)
cut = t.purge_events()
ck("执行了清理", cut is not None)
if cut is not None:
    want = int((NOW - 30 * 86400) * 1000)
    ck("截止时间 ≈ now-30d", abs(cut - want) < 5000, f"{cut} vs {want}")
paths, end = t.session.deletes[-1]
ck("删的是事件路径", paths == ["root.orpah.events"], str(paths))
ck("delete_data 收到截止时间", end == cut, f"{end} vs {cut}")
ck("清理截止时间可查", t.purged_upto == cut)
n_before = len(t.session.deletes)
t.purge_events()
ck("同进程只清理一次", len(t.session.deletes) == n_before, str(len(t.session.deletes)))

t = fresh(days=0)
ck("days=0 → 不清理", t.purge_events() is None and not t.session.deletes)
t = fresh(days=7)
t.purge_events()
want = int((time.time() - 7 * 86400) * 1000)
ck("days=7 生效", abs(t.session.deletes[-1][1] - want) < 5000)

print("== 4. 时间窗查询（回放用） ==")
t = fresh()
out = t.query_report_range("CN-WH01-A", 1000, 2000)
ck("上报点窗：时间写进 WHERE（索引原生）",
   "WHERE time >= 1000 AND time <= 2000" in t.session.query_sql[-1], t.session.query_sql[-1])
ck("上报点窗：按时间升序（回放按序消费）",
   "ORDER BY time ASC" in t.session.query_sql[-1], t.session.query_sql[-1])
ck("无数据返回空列表（非 None）", out == [], repr(out))

t = fresh(rows=[(1000, [-55, 7, "R1"]), (1500, [-60, 8, "R2"])])
out = t.query_report_range("CN-WH01-A", 2000, 1000)          # 上下界传反
ck("上下界传反自动纠正", "time >= 1000 AND time <= 2000" in t.session.query_sql[-1],
   t.session.query_sql[-1])
ck("上报点字段映射 rssi/seq/router_id",
   out and out[0] == {"t": 1000, "rssi": -55, "seq": 7, "router_id": "R1"}, str(out[:1]))

rows = [(1000, ["publish", "", "n=1", None]),
        (2000, ["case_mark", "CN-WH01-A", "C1", "shijh"])]
t = fresh(rows=rows)
out = t.query_events_range(500, 1500)
ck("事件窗：时间写进 WHERE", "WHERE time >= 500 AND time <= 1500" in t.session.query_sql[-1],
   t.session.query_sql[-1])
ck("事件窗：升序", "ORDER BY time ASC" in t.session.query_sql[-1])
ck("事件窗：老行 actor 归一为空串", out and out[0].get("actor") == "", repr(out[:1]))
out = t.query_events_range(500, 2500, etype="case_mark")
ck("事件窗：etype 仍本地过滤", len(out) == 1 and out[0]["etype"] == "case_mark", str(out))
ck("事件窗：limit 截断", len(t.query_events_range(500, 2500, limit=1)) == 1)

t = fresh()
t.available = False
ck("未就绪 → 两个窗查询都返回 None（页面据此提示 IoTDB 不可达）",
   t.query_report_range("X", 0, 1) is None and t.query_events_range(0, 1) is None)
t = fresh(days=30)
t.available = False
t.session = None
ck("未连库 → 不清理不报错", t.purge_events() is None)

print("== 5. 环境变量解析 ==")
ck("默认 30 天", tsdb.EVENT_RETENTION_DAYS == 30, str(tsdb.EVENT_RETENTION_DAYS))
ck("空串回退默认", tsdb._env_int("ORPAH_NOT_SET_XYZ", 30) == 30)
import os
os.environ["ORPAH_TEST_INT"] = ""
ck("空环境变量回退默认", tsdb._env_int("ORPAH_TEST_INT", 30) == 30)
os.environ["ORPAH_TEST_INT"] = "abc"
ck("非法值回退默认", tsdb._env_int("ORPAH_TEST_INT", 30) == 30)
os.environ["ORPAH_TEST_INT"] = "7"
ck("合法值生效", tsdb._env_int("ORPAH_TEST_INT", 30) == 7)
del os.environ["ORPAH_TEST_INT"]

print()
if FAIL:
    print(f"{len(FAIL)} 项失败: " + ", ".join(FAIL))
    sys.exit(1)
print("全部通过")
