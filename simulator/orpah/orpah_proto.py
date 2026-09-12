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
import os
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
MSG_LOST_TABLE_REQ = "ORPAH-LOST-TABLE-REQ"   # R→S 请求当前走失表（Router 主动拉取）
MSG_FOUND = "ORPAH-FOUND"                  # R→S 发现走失（业务告警：命中走失表）
MSG_ID_REPORT = "ORPAH-ID-REPORT"          # C→R→S 已签 orpah-id-report（《Orpah ID 协议规范》）

MSG_TYPES = {MSG_REQ_CONNECT, MSG_ACCESS_INFO, MSG_REPORT,
             MSG_TRACKING_STATUS, MSG_ERROR, MSG_LOST_TABLE,
             MSG_LOST_TABLE_REQ, MSG_FOUND, MSG_ID_REPORT}

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
# SN（Orpah ID 码号）规则（对齐《Orpah ID 协议规范》v1.7，2026-09-10）
# ---------------------------------------------------------------------------
# 格式：CC-ORG-UNIQUE[-CHECK]
#   CC     = ISO 3166-1 alpha-2（A–Z；不套用 Crockford 限制）
#   ORG    = 2–6 位 Crockford Base32
#   UNIQUE = 8–16 位 Crockford Base32
#   CHECK  = 0/1/2 位 Crockford Base32（可选）
# Crockford Base32：0-9 A-Z（去除易混的 I L O U）。
# 中文/Unicode（姓名等）不进 SN，放 payload 的业务字段。
# 用于 Server 端格式校验（非法 → ERROR code=FORMAT-ERR）。
SN_MAX_LEN = 32
_SN_RE = re.compile(
    r"^[A-Z]{2}-[0-9A-HJKMNP-TV-Z]{2,6}-[0-9A-HJKMNP-TV-Z]{8,16}"
    r"(-[0-9A-HJKMNP-TV-Z]{1,2})?$")


def sn_ok(sn):
    """SN 是否合法（Orpah ID：CC-ORG-UNIQUE[-CHECK]，Crockford Base32）。"""
    return (isinstance(sn, str) and 0 < len(sn) <= SN_MAX_LEN
            and bool(_SN_RE.match(sn)))


def sn_err(sn):
    """SN 校验失败原因；合法返回 None。原因：empty / too-long / bad-format。"""
    if not isinstance(sn, str) or not sn:
        return "empty"
    if len(sn) > SN_MAX_LEN:
        return "too-long"
    if not _SN_RE.match(sn):
        return "bad-format"
    return None


# ---------------------------------------------------------------------------
# 设备时间可信度（时钟可信，2026-09-12）
# ---------------------------------------------------------------------------
# 背景：**免电池客户端没有 RTC**，协议 §5.5 规定「ts=0 表示未知 → 跳过时间窗判断，仅靠 nonce 防重放」。
# 但「跳过窗口」只解决了**收不收**，没解决**存什么时间**：一个 ts=0 的上报如果按字面写库，
# 就会落在 1970 → 设备流与路由器观测序列时刻对不上（定位/回放按时间对齐 → 匹配不到），
# 审计里也分不清「设备说的时间」和「服务器看到的时间」。
# 故本模块提供**唯一**的归一化点：`effective_ts()`，各层（写库/案件/审计/展示）一律用它。
#
# **不改报文**：ts 在签名预像里，改了验签就不过 —— 归一化只用于我们**记录**的时间。
TS_SRC_DEVICE = "device"      # 时间来自设备
TS_SRC_SERVER = "server"      # 时间来自服务器接收时刻（设备无时钟/时钟荒谬）
TS_MIN = 946684800            # 2000-01-01 之前视为荒谬时钟
TS_MAX_SKEW_S = 86400         # 允许超前服务器 1 天（时区/轻微漂移），再多视为时钟错乱


def effective_ts(ts, rx=None):
    """(ts_int, src)：设备时间可用则用设备时间；ts=0/缺失/非整数/荒谬 → 用 rx（服务器接收时刻）。

    第二个返回值是**留痕**用的：src=server 表示这条记录的时间来自服务器而非设备，
    调用方应把它写进审计（`ts_src=server`），否则事后无从分辨两种时间。
    """
    rx_i = int(rx if rx is not None else time.time())
    if isinstance(ts, bool) or not isinstance(ts, int):
        return rx_i, TS_SRC_SERVER
    if ts == 0 or ts < TS_MIN or ts > rx_i + TS_MAX_SKEW_S:
        return rx_i, TS_SRC_SERVER
    return ts, TS_SRC_DEVICE



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


def new_rid():
    """生成一个**拉表关联号**（随机 token，6 字节 hex）。

    用途（2026-09-12）：`ORPAH-LOST-TABLE-REQ` 带上它，Server 的应答**原样回显**;
    Router 靠它区分「我拉表的应答」与「Server 主动推送」—— 两者是不同事件
    （前者不占“收到走失表下发”计数，后者占）。
    为什么必须显式配对：原来用“发出 REQ 后 ≤1.5s 内收到的 LOST-TABLE 算应答”的
    **时间窗猜测**，推送恰好落在窗口内会被误算（少计 1 次），反之也会多计。
    幂等/重试：同一 rid 可重发（Server 每次都会回全量表）。
    """
    return os.urandom(6).hex()


def build_lost_table(entries, version=None, ts=None, rid=None):
    """S→R ORPAH-LOST-TABLE：走失表下发/更新。

    entries：[{sn, tracked, note?}]；tracked=False 表示撤销走失。
    version：表版本（单调递增，可选）。
    rid：**仅应答主动拉表时**带上（原样回显请求里的 rid）；Server 主动推送不带 ——
         Router 以此区分“拉表应答”与“主动推送”。
    """
    m = _base(MSG_LOST_TABLE, None, ts, entries=list(entries))
    if version is not None:
        m["version"] = int(version)
    if rid:
        m["rid"] = str(rid)
    return m


def build_lost_table_req(ts=None, rid=None):
    """R→S ORPAH-LOST-TABLE-REQ：Router 请求 Server 下发当前走失表全量。

    用途（真机前续 / F-03）：Router 重启后本地缓存为空、或 REQ-CONNECT 时
    缓存未命中——即使 Server 近期无走失表变更（不会主动推），Router 也能主动
    拉取追平。Server 收到后回 build_lost_table(当前表, rid=<原样回显>)。
    rid：关联号（见 new_rid）；不带也能工作（旧对端兼容），但就退回到“时间窗猜测”。
    """
    return _base(MSG_LOST_TABLE_REQ, None, ts, **({"rid": str(rid)} if rid else {}))


def build_found(sn, ts=None):
    """R→S ORPAH-FOUND：Router 发现走失设备（业务告警）。

    sn：被发现的走失 sn。Router 在 REQ-CONNECT 命中本地走失缓存（tracked）时
    上报（每次命中都发，供业务端记录/告警）。Server 记录并可用于 UI「发现记录」。
    """
    return _base(MSG_FOUND, sn, ts)


def build_id_report(signed_report, ts=None):
    """C→R→S ORPAH-ID-REPORT：把已签的 orpah-id-report（{hdr,payload,sig}）
    包一层既有链路报文（公共头 v/type/sn/ts + report 字段）走原数据通路。

    签名的校验在 Server 侧按《Orpah ID 协议规范》§9.3 进行（见 server.py）。
    """
    payload = (signed_report or {}).get("payload") or {}
    msg = _base(MSG_ID_REPORT, payload.get("sn"), ts)
    msg["report"] = signed_report
    return msg


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
