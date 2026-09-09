#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orpah_proto.py — ORPAH-over-HaLow L1 报文定义与封装
====================================================
本文件是 orpah demo（L1 数据通路骨架）的公共常量与报文封装。
纯 PC 模拟器阶段：STA/AP 用 host/sim.py（HaLow 二层透明桥），Client/Router/Server
是独立 Python 进程。ORPAH-REPORT 以 JSON 承载，链路层封装成以太网帧经桥透传，
Router 侧以真实 UDP 转交 Server。

分层（对齐 Protocol/docs/orpah-over-halow/SPEC.md §6 选项 A）：
    Client host --(以太网帧, ethertype=0x88B5, payload=ORPAH JSON)--> STA 模块
      --> HaLow 二层桥 --> AP 模块 --> Router 桥
      --> (真实 UDP, payload=同一 ORPAH JSON) --> Server 固定端口

L1 只做上行（Client→Server），报文只有 ORPAH-REPORT；TRACKING-STATUS /
LOST-TABLE 等留 L2。
"""
import json
import time

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# ORPAH-L1 以太网类型（Local Experimental，IEEE 802 保留段；标记 HaLow 桥内 ORPAH 载荷）
ORPAH_ETHERTYPE = 0x88B5
# Server 固定 UDP 端口（SPEC §6 F-02 未定，先取不常用高位；可被 --port 覆盖）
ORPAH_UDP_PORT = 19447
# 广播 MAC
MAC_BCAST = bytes([0xFF] * 6)

# 报文类型
MSG_REPORT = "ORPAH-REPORT"
PROTO_VERSION = 1


# ---------------------------------------------------------------------------
# ORPAH-REPORT JSON
# ---------------------------------------------------------------------------
def build_report(sn, ts=None, rssi=None, seq=1, extra=None):
    """构造 ORPAH-REPORT 报文 dict。

    sn：被追踪设备序列号/IMEI（F-01 未定，先用字符串 sn，将来可换 15 位 IMEI）
    ts：unix 秒（缺省 now）
    rssi：Client 侧听到的 AP 信号（dBm，可选）
    """
    msg = {
        "v": PROTO_VERSION,
        "type": MSG_REPORT,
        "sn": sn,
        "ts": int(ts if ts is not None else time.time()),
        "seq": int(seq),
    }
    if rssi is not None:
        msg["rssi"] = int(rssi)
    if extra:
        msg.update(extra)
    return msg


def encode_report_json(msg):
    """dict → 单行 JSON bytes（链路载荷）。"""
    return json.dumps(msg, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def decode_report_json(data):
    """bytes → dict；非法 JSON / 类型不符返回 None。"""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != MSG_REPORT:
        return None
    return msg


# ---------------------------------------------------------------------------
# 以太网帧封装（HaLow 桥内透传的 L2 帧）
# ---------------------------------------------------------------------------
def build_eth_frame(payload, src_mac, dst_mac=None, ethertype=ORPAH_ETHERTYPE):
    """payload(bytes) → 以太网帧（14B 头 + payload）。

    dst_mac 缺省=广播：Client 不知道 AP 地址时用广播，桥/AP 必收。
    src_mac：Client 侧自身 MAC（6B）。
    """
    dst = bytes(dst_mac) if dst_mac is not None else MAC_BCAST
    return dst + bytes(src_mac) + ethertype.to_bytes(2, "big") + bytes(payload)


def parse_eth_frame(frame, want_ethertype=ORPAH_ETHERTYPE):
    """以太网帧 → (ethertype, payload)；长度不足 / 类型不符返回 None。"""
    if len(frame) < 14:
        return None
    ethertype = (frame[12] << 8) | frame[13]
    if want_ethertype is not None and ethertype != want_ethertype:
        return None
    return ethertype, frame[14:]
