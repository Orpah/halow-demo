# -*- coding: utf-8 -*-
"""spi_frame.py — 模拟器 SPI 宿主接口的**协议层**（纯逻辑，不碰 USB/串口）。

单一源 = `docs/spi_protocol.md` §2（帧格式）/ §3（命令字）：

    偏移 0   CMD      1 字节（bit7=1 表示应答）
    偏移 1   LEN_H    1 字节
    偏移 2   LEN_L    1 字节
    偏移 3   CRC      1 字节 = CRC-8/ATM(poly 0x07, init 0x00) over CMD..LEN_L + 全部载荷
    偏移 4.. PAYLOAD  LEN 字节

为什么单独一个模块：帧格式原来在 `sim_config.py` 里（主机驱动）和固件
`Periph/spi_slave.c` 里**各写一份** —— 两份漂移了不会报错，只会在真机上"发出去没反应"。
现在：主机侧用本模块，设备侧用 `firmware/Simulator/spi_proto.c`，两边靠
`tools/check_spi_proto.py`（同一批向量逐字节对拍）守住一致；本模块同时是**向量生成器**
（`--refresh` 的参照）。

⚠ 本模块**不**做 USB/CH341A 那层（那在 `sim_config.py` 的 `SpiTransport` 里）。
"""
import sys

# ---- 协议常量（与 docs/spi_protocol.md §2/§3 一致） ----
MAX_FRAME = 1700            # = MACBUS DATA_AREA_SIZE（含以太网头）
HDR = 4
RESP_FLAG = 0x80

CMD_AT = 0x01
CMD_GET_STATE = 0x02
CMD_DATA_TX = 0x03
CMD_DATA_RX = 0x04
CMD_EVENT = 0x05
CMD_PING = 0x06
CMD_RESET = 0x07
CMD_SET_CFG = 0x08
CMD_GET_CFG = 0x09
CMDS = (CMD_AT, CMD_GET_STATE, CMD_DATA_TX, CMD_DATA_RX, CMD_EVENT,
        CMD_PING, CMD_RESET, CMD_SET_CFG, CMD_GET_CFG)

# 事件类型（设备侧装配状态机喂字节后的结果）
RX_NEED_MORE = "need_more"
RX_FRAME = "frame"
RX_BAD_CRC = "bad_crc"
RX_TOO_LONG = "too_long"
RX_IGNORED = "ignored"


def crc8_update(crc, data):
    """CRC-8/ATM 增量更新（poly 0x07、init 0x00、MSB-first）。"""
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def crc8(data):
    return crc8_update(0, data)


def frame_header(cmd, payload_len):
    return bytes([cmd & 0xFF, (payload_len >> 8) & 0xFF, payload_len & 0xFF])


def frame_crc(cmd, payload=b""):
    """帧校验 = CRC-8/ATM(CMD..LEN_L + 载荷)。请求用**原 cmd**，应答用**去掉 bit7 的 cmd**。"""
    return crc8_update(crc8(frame_header(cmd, len(payload))), payload)


def encode_request(cmd, payload=b""):
    """host → sim 的请求帧（4 + LEN 字节）。"""
    return frame_header(cmd, len(payload)) + bytes([frame_crc(cmd, payload)]) + payload


def encode_response(cmd, payload=b""):
    """sim → host 的应答帧：头一字节 = CMD|0x80，CRC 覆盖**去掉 bit7 的 CMD** + 载荷。"""
    return (bytes([(cmd & 0x7F) | RESP_FLAG]) + frame_header(cmd, len(payload))[1:]
            + bytes([frame_crc(cmd & 0x7F, payload)]) + payload)


def parse_response(buf):
    """解析应答帧（host 侧）。返回 {ok, cmd, payload, why}；`ok=False` 时 `why` 说明原因。

    与固件 `spi_proto_build_resp` 的产物**逐字节可比**（check_spi_proto.py 就是这么比的）。
    """
    if len(buf) < HDR:
        return {"ok": False, "cmd": 0, "payload": b"", "why": "short"}
    if not (buf[0] & RESP_FLAG):
        return {"ok": False, "cmd": buf[0] & 0x7F, "payload": b"", "why": "no_resp_flag"}
    cmd = buf[0] & 0x7F
    ln = (buf[1] << 8) | buf[2]
    payload = bytes(buf[HDR:HDR + ln])
    if frame_crc(cmd, payload) != buf[3]:
        return {"ok": False, "cmd": cmd, "payload": payload, "why": "bad_crc"}
    return {"ok": True, "cmd": cmd, "payload": payload, "why": None}


def parse_request(buf):
    """解析请求帧（模型用；设备侧则由状态机逐字节收）。"""
    if len(buf) < HDR:
        return {"ok": False, "cmd": 0, "payload": b"", "why": "short"}
    cmd = buf[0] & 0x7F
    ln = (buf[1] << 8) | buf[2]
    payload = bytes(buf[HDR:HDR + ln])
    if len(buf) < HDR + ln:
        return {"ok": False, "cmd": cmd, "payload": payload, "why": "short"}
    if frame_crc(cmd, payload) != buf[3]:
        return {"ok": False, "cmd": cmd, "payload": payload, "why": "bad_crc"}
    return {"ok": True, "cmd": cmd, "payload": payload, "why": None}


class RxDecoder(object):
    """**设备侧**接收状态机的 Python 模型（照 `spi_proto.c` 写，用于对拍）。

    与固件的语义要点（`docs/spi_protocol.md` §2）：
      · 一帧 = 4 字节头 + LEN 字节载荷；头 4 字节到齐就先查 CRC（LEN=0 时无载荷）；
      · `len > MAX_FRAME` → `too_long`（不当成帧，回 ERROR）；
      · 一帧收完（`frame_done`）后，**同一 CS 事务里后面的字节一律忽略**（响应阶段）；
      · NSS 上升沿 = 事务结束 → `cs_end()` 复位；下降沿 = 新事务 → `cs_start()`。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.hdr = []
        self.cmd = 0
        self.length = 0
        self.payload = bytearray()
        self.frame_done = False

    def cs_start(self):
        """NSS 下降沿：开始新事务（清接收状态）。"""
        self.reset()

    def cs_end(self):
        """NSS 上升沿：事务结束（此后到下次 cs_start 前的字节都忽略）。"""
        self.frame_done = True
        self.hdr = []

    def feed(self, b):
        """喂一个 MOSI 字节 → 返回事件字符串（见 RX_* 常量）。"""
        if self.frame_done:
            return RX_IGNORED
        if len(self.hdr) < HDR:
            self.hdr.append(b & 0xFF)
            if len(self.hdr) == HDR:
                self.cmd = self.hdr[0] & 0x7F
                self.length = (self.hdr[1] << 8) | self.hdr[2]
                self.payload = bytearray()
                if self.length > MAX_FRAME:
                    self.frame_done = True
                    return RX_TOO_LONG
                if self.length == 0:
                    self.frame_done = True
                    ok = crc8(bytes(self.hdr[:3])) == self.hdr[3]
                    return RX_FRAME if ok else RX_BAD_CRC
            return RX_NEED_MORE
        self.payload.append(b & 0xFF)
        if len(self.payload) >= self.length:
            self.frame_done = True
            ok = crc8_update(crc8(bytes(self.hdr[:3])), self.payload) == self.hdr[3]
            return RX_FRAME if ok else RX_BAD_CRC
        return RX_NEED_MORE


def rx_decode_stream(data):
    """便利函数：把一串字节喂进模型，返回事件列表 [(idx, event, cmd, payload_hex)]。"""
    d = RxDecoder()
    out = []
    for i, b in enumerate(data):
        ev = d.feed(b)
        if ev in (RX_FRAME, RX_BAD_CRC, RX_TOO_LONG):
            out.append((i, ev, d.cmd, bytes(d.payload).hex()))
    return out


if __name__ == "__main__":                      # 自检（不依赖任何硬件/编译器）
    for _s in (sys.stdout, sys.stderr):
        _s.reconfigure(encoding="utf-8", errors="replace")
    ok = 0
    # ① 文档 §2 给的校验值：CRC-8/ATM("0xF4" 是 §2 里写明的示例校验值) —— 这里核"实现自洽"
    req = encode_request(CMD_PING)
    ok += 1 if req == bytes([0x06, 0x00, 0x00, frame_crc(CMD_PING)]) else 0
    # ② 请求 → 设备侧逐字节收 → 应得 frame
    ev = rx_decode_stream(req)
    ok += 1 if len(ev) == 1 and ev[0][1] == RX_FRAME and ev[0][2] == CMD_PING else 0
    # ③ 应答自洽（encode ↔ parse 往返）
    r = encode_response(CMD_PING, b"PONG")
    ok += 1 if parse_response(r)["ok"] and parse_response(r)["payload"] == b"PONG" else 0
    # ④ 翻转一个载荷字节 → bad_crc
    bad = bytearray(encode_request(CMD_DATA_TX, b"\x01\x02\x03"))
    bad[-1] ^= 0xFF
    ev = rx_decode_stream(bytes(bad))
    ok += 1 if ev and ev[0][1] == RX_BAD_CRC else 0
    print("spi_frame selfcheck %d/4" % ok)
