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


if __name__ == "__main__":
    unittest.main(verbosity=2)
