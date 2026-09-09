#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orpah_proto.py — ORPAH-over-HaLow 报文定义与封装（L1 + L2）
============================================================
本文件是 orpah demo 的公共常量与报文封装。纯 PC 模拟器阶段：STA/AP 用
host/sim.py（HaLow 二层透明桥），Client/Router/Server 是独立 Python 进程。

L1 = 数据通路最小骨架（单向上行 ORPAH-REPORT）。
L2 = 全消息流（SPEC §9）：REQ-CONNECT / ACCESS-INFO / REPORT /
     TRACKING-STATUS / ERROR / LOST-TABLE，端到端跑通 SPEC §4 时序
     （含走失表命中/未命中两分支 + Server→Client 下行回执）。

分层（对齐 SPEC §6 选项 A）：
    Client host --(以太网帧, ethertype=0x88B5, payload=ORPAH JSON)--> STA 模块
      --> HaLow 二层桥 --> AP 模块 --> Router 桥
      --> (真实 UDP, payload=同一 ORPAH JSON) --> Server 固定端口
    Server --(UDP 应答/走失表)--> Router 桥 --> 注入 AP 空口 --> STA 模块
      --> host 口 --> Client host（L2 下行）

链路报文统一为单行 JSON：公共头 {v, type, sn?, ts}；Router↔Server 的 UDP
载荷与 Client→STA 的以太网帧 payload 是同一 JSON bytes（桥/网透传不改写）。
"""
import json
import re
import time

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# ORPAH 以太网类型（Local Experimental，IEEE 802 保留段；标记 HaLow 桥内 ORPAH 载荷）
ORPAH_ETHERTYPE = 0x88B5
# Server 固定 UDP 端口（SPEC §6 F-02 未定，先取不常用高位；可被 --port 覆盖）
ORPAH_UDP_PORT = 19447
# 广播 MAC
MAC_BCAST = bytes([0xFF] * 6)

# 协议版本
PROTO_VERSION = 1

# 报文类型（SPEC §5）
MSG_REQ_CONNECT = "ORPAH-REQ-CONNECT"      # C→R 请求连接（无认证）
MSG_ACCESS_INFO = "ORPAH-ACCESS-INFO"      # R→C 路由器访问信息（含是否被跟踪）
MSG_REPORT = "ORPAH-REPORT"                # C→R/S IMEI/序列号上报
MSG_TRACKING_STATUS = "ORPAH-TRACKING-STATUS"  # R→C / S→R 跟踪状态回执
MSG_ERROR = "ORPAH-ERROR"                  # 任→任 错误
MSG_LOST_TABLE = "ORPAH-LOST-TABLE"        # S→R 走失表下发/更新

MSG_TYPES = {MSG_REQ_CONNECT, MSG_ACCESS_INFO, MSG_REPORT,
             MSG_TRACKING_STATUS, MSG_ERROR, MSG_LOST_TABLE}

# 跟踪状态码（TRACKING-STATUS 的 status 字段；ERROR 的 code 复用部分）
ST_NOT_TRACKED = "NOT-TRACKED"      # 走失库中无该 sn（未在跟踪）
ST_TRACKED = "TRACKED"              # 走失库命中（正在跟踪）
ST_LOG_OK = "LOG-OK"                # 上报已记录
ST_FMT_ERR = "FORMAT-ERR"           # 报文格式错误
ST_DECODE_ERR = "DECODE-ERR"        # 报文解码错误
ST_LOG_ERR = "LOG-ERR"              # 服务器日志/记录失败

# 错误码（ERROR 报文的 code 字段）
ERR_FORMAT = "FORMAT-ERR"
ERR_DECODE = "DECODE-ERR"
ERR_LOG = "LOG-ERR"
ERR_SERVER = "SERVER-ERR"


# ---------------------------------------------------------------------------
# SN（被追踪设备标识）规则（F-01 定稿 2026-09-10）
# ---------------------------------------------------------------------------
# 不用真实 IMEI15/Luhn（用户定：不引入 IMEI 结构）。身份 = 自定义 SN，字符集：
# 中文汉字 + 英文(大小写) + 数字；另保留 '-' 作分隔符，兼容既有示范值
# （如 ORPAH-0001）。用于 Server 端格式校验（非法 → ERROR code=FORMAT-ERR）。
SN_MIN_LEN = 1
SN_MAX_LEN = 32
_SN_RE = re.compile(r"^[0-9A-Za-z\u4e00-\u9fff-]+$")


def sn_ok(sn):
    """SN 是否合法：非空、≤{SN_MAX_LEN} 字符、仅含中/英/数字（与 '-'）。"""
    return (isinstance(sn, str) and SN_MIN_LEN <= len(sn) <= SN_MAX_LEN
            and bool(_SN_RE.match(sn)))


def sn_err(sn):
    """SN 校验失败原因；合法返回 None。原因：empty / too-long / bad-charset。"""
    if not isinstance(sn, str) or not sn:
        return "empty"
    if len(sn) > SN_MAX_LEN:
        return "too-long"
    if not _SN_RE.match(sn):
        return "bad-charset"
    return None


# ---------------------------------------------------------------------------
# 通用 JSON 编解码（L1/L2 所有报文）
# ---------------------------------------------------------------------------
def encode_msg(msg):
    """dict → 单行 JSON bytes（链路载荷 / UDP 载荷）。"""
    return json.dumps(msg, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def decode_msg(data):
    """bytes → dict；非 JSON / 非已知报文类型返回 None。"""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict) or msg.get("type") not in MSG_TYPES:
        return None
    return msg


def _base(mtype, sn=None, ts=None, **kw):
    """构造带公共头的报文 dict。"""
    msg = {"v": PROTO_VERSION, "type": mtype,
           "ts": int(ts if ts is not None else time.time())}
    if sn is not None:
        msg["sn"] = str(sn)
    msg.update(kw)
    return msg


# ---------------------------------------------------------------------------
# 各报文构造（build_*）
# ---------------------------------------------------------------------------
def build_req_connect(sn, mac=None, hw=None, ts=None):
    """C→R ORPAH-REQ-CONNECT：客户端请求接入（无认证）。"""
    msg = _base(MSG_REQ_CONNECT, sn, ts)
    if mac:
        msg["mac"] = mac                    # 客户端标识 MAC（字符串，可选）
    if hw:
        msg["hw"] = hw                      # 硬件/设备描述（可选）
    return msg


def build_access_info(sn, tracked, server_ok=True, status=None, ts=None):
    """R→C ORPAH-ACCESS-INFO：路由器访问信息（§4 查走失表后应答）。

    tracked：走失表中是否有该客户端（R 按本地缓存表判断）
    server_ok：服务器可达性（R 与 S 的 UDP 是否通）
    status：走失表中命中时的跟踪状态（可选）
    """
    msg = _base(MSG_ACCESS_INFO, sn, ts,
                tracked=bool(tracked), server_ok=bool(server_ok))
    if status:
        msg["status"] = status
    return msg


def build_report(sn, ts=None, rssi=None, seq=1, extra=None):
    """C→R/S ORPAH-REPORT：IMEI/序列号上报。

    sn：被追踪设备序列号/IMEI（F-01 未定，先用字符串 sn，将来可换 15 位 IMEI）
    ts：unix 秒（缺省 now）
    rssi：Client 侧听到的 AP 信号（dBm，可选）
    """
    msg = _base(MSG_REPORT, sn, ts, seq=int(seq))
    if rssi is not None:
        msg["rssi"] = int(rssi)
    if extra:
        msg.update(extra)
    return msg


def build_tracking_status(sn, status, msg_text=None, ts=None):
    """R→C（经 S→R→C 下行）ORPAH-TRACKING-STATUS：跟踪状态回执。

    status：ST_* 状态码（TRACKED / NOT-TRACKED / LOG-OK / 各 ERR）
    """
    m = _base(MSG_TRACKING_STATUS, sn, ts, status=status)
    if msg_text:
        m["msg"] = msg_text
    return m


def build_error(code, sn=None, msg_text=None, ts=None):
    """任→任 ORPAH-ERROR：格式/解码/服务器错误。"""
    m = _base(MSG_ERROR, sn, ts, code=code)
    if msg_text:
        m["msg"] = msg_text
    return m


def build_lost_table(entries, version=None, ts=None):
    """S→R ORPAH-LOST-TABLE：走失表下发/更新。

    entries：[{sn, tracked, note?}]；tracked=False 表示撤销走失。
    version：表版本（单调递增，可选）。
    """
    m = _base(MSG_LOST_TABLE, None, ts, entries=list(entries))
    if version is not None:
        m["version"] = int(version)
    return m


# ---------------------------------------------------------------------------
# 兼容旧名（L1 遗留，orpah_proto 早期只有 REPORT）
# ---------------------------------------------------------------------------
def encode_report_json(msg):
    return encode_msg(msg)


def decode_report_json(data):
    m = decode_msg(data)
    return m if (m and m.get("type") == MSG_REPORT) else None


# ---------------------------------------------------------------------------
# 以太网帧封装（HaLow 桥内透传的 L2 帧；Client/Router 两侧共用）
# ---------------------------------------------------------------------------
def build_eth_frame(payload, src_mac, dst_mac=None, ethertype=ORPAH_ETHERTYPE):
    """payload(bytes) → 以太网帧（14B 头 + payload）。

    dst_mac 缺省=广播：Client 不知道 AP 地址时用广播，桥/AP 必收。
    src_mac：发送侧自身 MAC（6B）。
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
