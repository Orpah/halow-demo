#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_server.py — OrpahServer 单元测试（unittest，仅标准库，无第三方依赖）
========================================================================
覆盖 server.py 各 mtype 分支的「不崩溃」冒烟 + 关键行为，锁死曾被审查点名的
作用域错误（LOST-TABLE-REQ 拉表路径）与 Orpah ID 验签/防重放。

运行（orpah 目录下）：
    C:\\Python313\\python.exe -m unittest test_server -v
或直接：
    C:\\Python313\\python.exe test_server.py
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import orpah_id as oid
import orpah_proto as op
from server import OrpahServer

ADDR = ("127.0.0.1", 12345)


class FakeSock:
    """替身 UDP socket：记录 sendto 的 (bytes, addr)，不发真包。"""

    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    # start()/stop() 用到的占位（本测试不 start，仅 _handle→_reply 路径需要 sendto）
    def setsockopt(self, *a):
        pass

    def bind(self, *a):
        pass

    def settimeout(self, *a):
        pass

    def recvfrom(self, *a):
        raise OSError

    def close(self):
        pass


def make_srv(**kw):
    srv = OrpahServer(**kw)
    srv.sock = FakeSock()
    return srv


def sent_types(srv):
    """srv.sock.sent 里各条已解码报文 type 列表（按发送顺序）。"""
    return [op.decode_msg(d)["type"] for d, _ in srv.sock.sent]


class TestLostTableReq(unittest.TestCase):
    """审查点名的核心路径：R→S 主动拉表（新 Router 追平）。"""

    def test_lost_table_req_does_not_crash(self):
        srv = make_srv()
        srv.mark_tracked("CN-WH01-9AF3C1D2", push=False)
        srv._handle(op.build_lost_table_req(), ADDR)      # 曾因 addrs NameError 崩溃
        self.assertEqual(srv.pull_count, 1)

    def test_lost_table_req_registers_router(self):
        srv = make_srv()
        srv._handle(op.build_lost_table_req(), ADDR)
        self.assertIn(ADDR, srv.routers)

    def test_lost_table_req_replies_only_to_requester(self):
        srv = make_srv()
        srv.mark_tracked("CN-WH01-9AF3C1D2", push=False)  # 走失库有 1 项，但不主动推
        srv.sock.sent.clear()
        srv._handle(op.build_lost_table_req(), ADDR)
        self.assertEqual(len(srv.sock.sent), 1)           # 只回请求方，不全量广播
        data, addr = srv.sock.sent[0]
        self.assertEqual(addr, ADDR)
        msg = op.decode_msg(data)
        self.assertEqual(msg["type"], op.MSG_LOST_TABLE)
        self.assertEqual(len(msg["entries"]), 1)

    def test_lost_table_reply_echoes_rid(self):
        """拉表关联号（v0.7.1）：**应答原样回显 rid**，主动推送不带。"""
        srv = make_srv()
        srv.sock.sent.clear()
        srv._handle(op.build_lost_table_req(rid="RID-XYZ"), ADDR)
        msg = op.decode_msg(srv.sock.sent[0][0])
        self.assertEqual(msg.get("rid"), "RID-XYZ")
        # 主动推送（mark 触发）不带 rid —— Router 靠这个区分「应答」与「推送」
        srv.sock.sent.clear()
        srv.mark_tracked("CN-WH01-9AF3C1D2", note="push")   # 默认 push=True
        pushed = [op.decode_msg(d) for d, _ in srv.sock.sent]
        self.assertTrue(pushed, "mark 应触发一次下发")
        self.assertTrue(all("rid" not in m for m in pushed), str(pushed))
        # 无 rid 的请求（旧对端兼容）：应答也不带 rid，但必须照常回表
        srv.sock.sent.clear()
        srv._handle(op.build_lost_table_req(), ADDR)
        msg = op.decode_msg(srv.sock.sent[0][0])
        self.assertNotIn("rid", msg)
        self.assertEqual(msg["type"], op.MSG_LOST_TABLE)


class TestReport(unittest.TestCase):
    def test_report_valid_replies_tracking_status(self):
        srv = make_srv()
        srv._handle(op.build_report(sn="CN-WH01-9AF3C1D2", seq=1), ADDR)
        self.assertEqual(srv.count, 1)
        self.assertIn(op.MSG_TRACKING_STATUS, sent_types(srv))

    def test_report_bad_sn_replies_format_err(self):
        srv = make_srv()
        srv._handle(op.build_report(sn="BAD", seq=1), ADDR)
        self.assertEqual(srv.count, 0)
        self.assertIn(op.MSG_ERROR, sent_types(srv))

    def test_report_dedup_same_seq(self):
        srv = make_srv()
        srv._handle(op.build_report(sn="CN-WH01-9AF3C1D2", seq=7), ADDR)
        srv._handle(op.build_report(sn="CN-WH01-9AF3C1D2", seq=7), ADDR)
        self.assertEqual(srv.count, 1)
        self.assertEqual(srv.dup_dropped, 1)

    def test_report_hit_lost_table_tracked(self):
        srv = make_srv()
        srv.mark_tracked("CN-WH01-9AF3C1D2", push=False)
        srv._handle(op.build_report(sn="CN-WH01-9AF3C1D2", seq=1), ADDR)
        # 回执状态应 TRACKED
        st = [m for m in (op.decode_msg(d) for d, _ in srv.sock.sent)
              if m["type"] == op.MSG_TRACKING_STATUS]
        self.assertTrue(st and st[0]["status"] == op.ST_TRACKED)


class TestOtherBranches(unittest.TestCase):
    def test_req_connect_records_router(self):
        srv = make_srv()
        srv._handle({"type": op.MSG_REQ_CONNECT, "sn": "CN-WH01-9AF3C1D2"}, ADDR)
        self.assertEqual(srv.router_for.get("CN-WH01-9AF3C1D2"), ADDR)

    def test_req_connect_records_router_for_but_does_not_register(self):
        """REQ-CONNECT 误达 Server 时**只记 router_for，不注册 Router**（2026-09-12 明确语义）。

        REQ-CONNECT 本该由 Router 查本地缓存就地应答；到 Server 属异常路径。
        正式注册（进 `routers` 集合 → 以后走失表变更会推给它）只认 Router 真正上行的那几种：
        REPORT / ORPAH-FOUND / LOST-TABLE-REQ。本测试把这个**有意为之**的选择锁住。
        """
        srv = make_srv()
        srv._handle({"type": op.MSG_REQ_CONNECT, "sn": "CN-WH01-9AF3C1D2"}, ADDR)
        self.assertEqual(srv.router_for.get("CN-WH01-9AF3C1D2"), ADDR)   # 记了
        self.assertNotIn(ADDR, srv.routers)                              # 没注册
        self.assertEqual(len(srv.sock.sent), 0)                          # 也没推任何东西
        # 对照：三种真正的上行都会注册
        for msg in (op.build_report(sn="CN-WH01-9AF3C1D2", seq=1),
                    op.build_found("CN-WH01-9AF3C1D2"),
                    op.build_lost_table_req(rid="RID-1")):
            s2 = make_srv()
            s2._handle(msg, ADDR)
            self.assertIn(ADDR, s2.routers, msg.get("type"))

    def test_found_increments(self):
        srv = make_srv()
        srv._handle(op.build_found("CN-WH01-9AF3C1D2"), ADDR)
        self.assertEqual(srv.found_count, 1)

    def test_unknown_type_ignored(self):
        srv = make_srv()
        srv._handle({"type": "ORPAH-NOPE", "sn": "X"}, ADDR)   # 不崩溃
        self.assertEqual(srv.count, 0)


class TestIdReport(unittest.TestCase):
    """Orpah ID 验签路径（需 keystore + nonce 缓存）。"""

    def setUp(self):
        self.ks = oid.KeyStore()
        self.dev = oid.Device(sn="CN-WH01-9AF3C1D2")
        self.ks.register(self.dev)
        self.srv = OrpahServer(keystore=self.ks, id_nonces=oid.NonceCache())
        self.srv.sock = FakeSock()

    def _send(self, report):
        self.srv._handle(op.build_id_report(report), ADDR)
        return self.srv.id_reports[0]

    def test_id_report_valid(self):
        rec = self._send(self.dev.report(level=0))
        self.assertTrue(rec["accepted"])
        self.assertEqual(rec["trust"], "high")

    def test_id_report_tampered(self):
        r = self.dev.report(level=0)
        r["payload"]["battery_mv"] = 1
        rec = self._send(r)
        self.assertFalse(rec["accepted"])
        self.assertEqual(rec["error"], "signature_invalid")

    def test_id_report_replay(self):
        r = self.dev.report(level=0)
        self._send(r)
        rec = self._send(r)                       # 同 nonce 重放
        self.assertEqual(rec["error"], "replay_detected")

    def test_id_report_revoked(self):
        self.ks.revoke(self.dev.sn)
        rec = self._send(self.dev.report(level=0))
        self.assertEqual(rec["error"], "revoked")

    def test_id_report_stale(self):
        r = self.dev.report(level=0, ts=int(time.time()) - 3600)
        rec = self._send(r)
        self.assertEqual(rec["error"], "timestamp_out_of_window")

    def test_id_report_level3_none(self):
        rec = self._send(self.dev.report(level=3))
        self.assertTrue(rec["accepted"])
        self.assertEqual(rec["trust"], "none")

    def test_id_report_cap_rtc_is_tristate_bool(self):
        """能力声明落进记录时必须是**三态布尔**（True/False/None），不是规范化后的 dict。

        2026-09-13 实测踩到的坑：server 里误把 `cap_of()`（返回 `{"rtc": true}`）当 `rtc` 传给
        `effective_ts` / 写进 `cap_rtc` → `rtc is False` 永不成立（"声明无 RTC → 一律用服务器时刻"
        静默失效），且 `alerts.id_cap_mismatch` 的 `cap_rtc is True` 永远对不上（告警永不出）。
        """
        rec = self._send(self.dev.report(level=0, cap={"rtc": True}))
        self.assertIs(rec["cap_rtc"], True)
        self.assertIs(rec["ts_ok"], True)          # 有 RTC 且 ts 正常 → 可用设备时间
        rec = self._send(self.dev.report(level=0, cap={"rtc": False}))
        self.assertIs(rec["cap_rtc"], False)
        self.assertEqual(rec["ts_src"], "server")  # 声明无 RTC → 一律服务器时刻
        self.assertIs(rec["ts_ok"], False)
        rec = self._send(self.dev.report(level=0))  # 未声明 → None（沿用老行为）
        self.assertIsNone(rec["cap_rtc"])
        self.assertEqual(rec["ts_src"], "device")

    def test_id_report_cap_no_rtc_uses_server_time_even_with_plausible_ts(self):
        """声明无 RTC 的设备，即使 ts 看着完全正常，也不当时间基准（那是它自己编的）。"""
        now = int(time.time())
        rec = self._send(self.dev.report(level=0, ts=now - 120, cap={"rtc": False}))
        self.assertTrue(rec["accepted"])
        self.assertEqual(rec["ts_src"], "server")
        # 设备说 now-120，但落的是服务器接收时刻（别用 ==now 断言：同一秒内本来就可能相等）
        self.assertGreaterEqual(rec["ts_eff"], now - 5)
        self.assertLessEqual(rec["ts_eff"], now + 5)
        self.assertNotEqual(rec["ts_eff"], now - 120)
        self.assertIs(rec["ts_ok"], False)

    def test_id_report_cap_rtc_true_with_broken_ts(self):
        """有 RTC 却送 ts=0：照收（缺省仍要能收），但标记 ts_ok=False 供告警判定。"""
        rec = self._send(self.dev.report(level=0, ts=0, cap={"rtc": True}))
        self.assertTrue(rec["accepted"])
        self.assertIs(rec["cap_rtc"], True)
        self.assertIs(rec["ts_ok"], False)
        self.assertEqual(rec["ts_src"], "server")

    def test_id_report_cap_unknown_field_dropped(self):
        """只归一化已知能力位；未知字段既不报错也不写进记录。"""
        rec = self._send(self.dev.report(level=0, cap={"rtc": True, "gps": True}))
        self.assertTrue(rec["accepted"])
        self.assertIs(rec["cap_rtc"], True)

    def test_id_report_cap_tamper_breaks_signature(self):
        """`cap` 在 JCS 预像里 → 改它就验签失败（能力声明防篡改，见 spoof.cap_downgrade）。"""
        r = self.dev.report(level=0, cap={"rtc": True})
        r["payload"]["cap"]["rtc"] = False
        rec = self._send(r)
        self.assertFalse(rec["accepted"])
        self.assertEqual(rec["error"], "signature_invalid")


    def test_id_report_energy_fields(self):
        """能量轴（2026-09-13）：电量入记录 + **成因推导**（能量 vs 密钥故障）。

        成因不新增报文字段：设备同时签了两个事实（级别 + 电量），服务端据此区分——
        低电量 + HS256 → `energy`；电量正常 + 降级 → `key`。
        """
        now = int(time.time())
        rec = self._send(self.dev.report(level=0, ts=now, battery_mv=3700))
        self.assertEqual(rec["battery_mv"], 3700)
        self.assertIsNone(rec["degraded_reason"])          # L0 不降级 → 无成因
        rec = self._send(self.dev.report(level=1, ts=now, battery_mv=3200))   # 低电 + HS256
        self.assertEqual(rec["degraded_reason"], "energy")
        rec = self._send(self.dev.report(level=1, ts=now, battery_mv=3700))   # 电量正常 + HS256
        self.assertEqual(rec["degraded_reason"], "key")
        rec = self._send(self.dev.report(level=3, ts=now))                    # L3 + 没报电量
        self.assertEqual(rec["degraded_reason"], "key")
        self.assertIsNone(rec["battery_mv"])
        # 恶意/异常设备：直接塞进签名预像（`report()` 的 int() 会挡程序错误，
        # 所以用 extra 绕过设备侧强制转型，专门考验**服务端对不可信输入**的容忍）
        rec = self._send(self.dev.report(level=0, ts=now, extra={"battery_mv": "x"}))
        self.assertIsNone(rec["battery_mv"])               # 非整数 → 当没报（不猜）
        rec = self._send(self.dev.report(level=0, ts=now, extra={"battery_mv": True}))
        self.assertIsNone(rec["battery_mv"])               # bool 是 int 子类 → 也得当没报


class TestUiQueryArgs(unittest.TestCase):
    """ui_server 的**查询参数解析**（HTTP 层最外层输入）。

    背景（2026-09-13 实测）：`do_GET` 没有外层 try，参数解析一旦抛异常，连接线程直接崩、
    客户端只看到「Failed to fetch」（不是 400）。而原来用的是 `str.isdigit()` 当校验 ——
    `"²".isdigit()` 与 `"--123".lstrip("-").isdigit()` 都为 True，但 `int()` 两个都抛。
    现在统一走 `ui_server._int_arg()`（唯一入口），本类同时锁住「源码里不再出现 isdigit 调用」。
    """

    def setUp(self):
        self.ui = __import__("ui_server")

    def test_int_arg_normal(self):
        self.assertEqual(self.ui._int_arg("1789217468000"), 1789217468000)
        self.assertEqual(self.ui._int_arg(" 42 "), 42)
        self.assertEqual(self.ui._int_arg("0"), 0)
        self.assertEqual(self.ui._int_arg("+5"), 5)
        self.assertEqual(self.ui._int_arg("-123"), -123)   # `from=-123` 语义保留（回退到窗口上限）

    def test_int_arg_rejects_isdigit_traps(self):
        """这两条是报告/实测点名的坑：`isdigit()` 为真但 `int()` 抛。"""
        self.assertIsNone(self.ui._int_arg("--123"))
        self.assertIsNone(self.ui._int_arg("\u00b2"))       # 上标二
        for bad in ("", "abc", "12.5", None, "1e3", "0x10"):
            self.assertIsNone(self.ui._int_arg(bad), bad)

    def test_int_arg_default(self):
        self.assertEqual(self.ui._int_arg("--123", 99), 99)
        self.assertIsNone(self.ui._int_arg("abc"))

    def test_no_isdigit_calls_left_in_ui_server(self):
        """单一入口守卫：源码里不该再有 `*.isdigit()` **调用**（注释/文档字符串里提到不算）。"""
        import ast
        with open(os.path.join(HERE, "ui_server.py"), encoding="utf-8") as f:
            src = f.read()
        calls = [n.lineno for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "isdigit"]
        self.assertEqual(calls, [], f"改回 isdigit 校验会重新引入崩溃路径，见 _int_arg 注释：行 {calls}")

    def test_upload_finally_guards_settimeout(self):
        """上传读超时后的 `settimeout(None)` 必须被 try/except OSError 包住（评审 #1 的点）。

        评审担心“连接已关时 settimeout(None) 抛 OSError 盖掉 400 响应” —— 代码里本来就吞了，
        这里把**该防护存在**锁住：对已关闭的 socket 调 settimeout 确实抛 OSError（下面顺手实测），
        所以那层 except 不能删。
        """
        import socket
        s = socket.socket()
        s.close()
        with self.assertRaises(OSError):
            s.settimeout(None)          # 证明这个 OSError 真的会发生
        with open(os.path.join(HERE, "ui_server.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("except OSError:\n                    pass", text,
                      "上传路径 finally 里的 settimeout(None) 防护被我删掉了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
