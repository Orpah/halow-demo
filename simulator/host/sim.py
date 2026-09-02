#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sim.py — TXW8301 模拟器 PC 版（无硬件）
=====================================
把固件（CH32V203）的模拟器核心逻辑移植为纯 Python，在 PC 上跑 1~2 个实例：
  * 虚拟 AT 控制台：TCP 端口（行文本 AT 命令，响应/事件实时回发）
  * 虚拟空口：两台实例经 TCP 互联，走与固件 sim_link 相同的帧格式
  * 行为与固件一致：AP/STA/APSTA/GROUP、配对、RSSI、+事件、数据帧转发、
    AT+SYSDBG=WNB 时输出 FRAME:TX / FRAME:RX

用法：
  # 实例 A（AP）：监听 AT 控制台 9001，监听虚拟空口 9011
  python sim.py --name A --role AP --console 9001 --link 9011
  # 实例 B（STA）：监听 AT 控制台 9002，连到 A 的空口 9011
  python sim.py --name B --role STA --console 9002 --link 9012 --peer 127.0.0.1:9011

也可以用 telnet 直接连控制台测试：
  telnet 127.0.0.1 9001   ->  AT+MODE=AP ...
"""
import argparse
import queue
import socket
import threading
import time

# 协议族（AT 方言）定义在 devprofiles.py：native=本模拟器，tah=泰芯 AH，hc01=HT-HC01 占位
from devprofiles import FAMILY_NATIVE, FAMILY_TAH, FAMILY_HC01, tah_style

# ---------------------------------------------------------------------------
# 与固件一致的常量与工具
# ---------------------------------------------------------------------------
MODE_AP, MODE_STA, MODE_APSTA, MODE_GROUP = 0, 1, 2, 3
KEY_NONE, KEY_WPA_PSK = 0, 1
CONN_IDLE, CONN_SCANNING, CONN_ASSOCIATING, CONN_CONNECTED, CONN_DISCONNECTED = 0, 1, 2, 3, 4
CONN_STR = {0: "IDLE", 1: "SCANNING", 2: "ASSOCIATING", 3: "CONNECTED", 4: "DISCONNECTED"}
MODE_STR = {0: "AP", 1: "STA", 2: "APSTA", 3: "GROUP"}

LINK_TYPE_DATA = 0x01
LINK_TYPE_BEACON = 0x02
LINK_TYPE_ASSOC_REQ = 0x03
LINK_TYPE_ASSOC_RESP = 0x04
LINK_TYPE_PAIR_PSK = 0x05
LINK_TYPE_DEAUTH = 0x06

VERSION = "TXW8301-SIM-pc-v0.1.0"
MAX_FRAME = 1700
MAX_STA = 8


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def hexs(b):
    return "".join("%02x" % x for x in b)


def atoi(s):
    try:
        return int(s.strip() or 0)
    except ValueError:
        return 0


def is_hex64(s):
    return len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s)


def parse_mac(s):
    """'11:22:33:44:55:66' -> bytes(6) or None"""
    parts = s.replace("-", ":").split(":")
    if len(parts) != 6:
        return None
    out = bytearray()
    for p in parts:
        try:
            out.append(int(p, 16))
        except ValueError:
            return None
    return bytes(out)


def mac_str(b):
    return ":".join("%02x" % x for x in b)


# ---------------------------------------------------------------------------
# 配置（对应固件 sim_cfg）
# ---------------------------------------------------------------------------
class SimCfg:
    def __init__(self):
        self.mode = MODE_STA
        self.keymgmt = KEY_NONE
        self.bss_bw = 8
        self.chan_list = [9080]
        self.txpower = 20
        self.tx_mcs = 255
        self.heart_int = 500
        self.ack_tmo = 0
        self.roam = 0
        self.ps_mode = 0
        self.mac = bytes([0x4A, 0x06, 0x59, 0x7B, 0x6C, 0x98])
        self.ssid = ""
        self.psk = ""
        self.r_ssid = ""
        self.r_psk = ""
        self.rssi = -30
        self.group = bytes(6)
        self.aid = 0

    def chan_in_list(self, freq):
        return freq in self.chan_list

    def snapshot(self):
        return {
            "mode": self.mode, "keymgmt": self.keymgmt, "bss_bw": self.bss_bw,
            "chan_list": list(self.chan_list), "txpower": self.txpower,
            "tx_mcs": self.tx_mcs, "heart_int": self.heart_int,
            "ack_tmo": self.ack_tmo, "roam": self.roam, "ps_mode": self.ps_mode,
            "mac": mac_str(self.mac), "ssid": self.ssid, "psk": self.psk,
            "rssi": self.rssi,
        }


# ---------------------------------------------------------------------------
# AT 控制台（TCP，行文本）
# ---------------------------------------------------------------------------
class Console:
    def __init__(self, port, on_line, data_mode=None, on_byte=None):
        self.port = port
        self.on_line = on_line      # callable(line)
        self.data_mode = data_mode or (lambda: False)
        self.on_byte = on_byte or (lambda b: None)
        self.clients = []
        self.history = []
        self.lock = threading.Lock()
        self.srv = None
        # 数据模式归属：只有进入数据模式的连接才喂原始字节，避免其它连接
        # （如 UI 轮询）的字节劫持当前数据帧。
        self.data_owner = None

    def start(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", self.port))
        self.srv.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with self.lock:
                self.clients.append(c)
            # 新客户端先收到历史
            try:
                for line in self.history[-100:]:
                    c.sendall((line + "\r\n").encode())
            except OSError:
                pass
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        buf = b""
        try:
            while True:
                data = c.recv(4096)
                if not data:
                    break
                if self.data_owner is c:        # 本连接正处于 AT+TXDATA 数据模式
                    for b in data:
                        if self.on_byte(b):     # 帧完成 -> 解除归属
                            self.data_owner = None
                    continue
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip(b"\r")
                    if line:
                        self.on_line(line.decode("utf-8", "replace"))
                    # 一行处理完若进入数据模式（如 AT+TXDATA=20），本连接成为
                    # 数据归属者；缓冲中剩余字节作为原始数据喂入。
                    if self.data_mode() and self.data_owner is None:
                        self.data_owner = c
                    if self.data_owner is c and buf:
                        for b in buf:
                            if self.on_byte(b):
                                self.data_owner = None
                                break
                        buf = b""
        except OSError:
            pass
        finally:
            with self.lock:
                if c in self.clients:
                    self.clients.remove(c)
            if self.data_owner is c:
                self.data_owner = None          # 数据模式连接断开则重置
            try:
                c.close()
            except OSError:
                pass

    def write(self, text):
        line = text.rstrip("\r\n")
        with self.lock:
            self.history.append(line)
            if len(self.history) > 300:
                self.history = self.history[-300:]
            for c in list(self.clients):
                try:
                    c.sendall((line + "\r\n").encode())
                except OSError:
                    try:
                        self.clients.remove(c)
                    except ValueError:
                        pass


# ---------------------------------------------------------------------------
# 空口串口适配：把 pyserial 包装成与 socket 兼容的接口（帧格式同 TCP 空口）
# ---------------------------------------------------------------------------
class _SerialPeer:
    """把 pyserial 包装成与 socket 兼容的 recv/sendall 接口，供 Link 使用。
    帧格式与 TCP 空口完全一致（AA 55 TYPE LEN CRC），因此 PC 模拟器可直接
    接到真实 CH32V203 板的 UART2 上（需 USB 转串口）自动建链。"""
    is_serial = True

    def __init__(self, ser, port, baud):
        self.ser = ser
        self.link_port = port
        self.link_baud = baud

    def recv(self, n):
        return self.ser.read(n)

    def sendall(self, data):
        self.ser.write(data)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 虚拟空口（TCP 或串口，帧格式与固件 sim_link 一致）
# ---------------------------------------------------------------------------
class Link:
    def __init__(self, core):
        self.core = core
        self.sock = None
        self.rxbuf = b""
        self.pending = []
        self.tx_pkts = 0
        self.rx_pkts = 0

    def listen(self, port):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(1)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        c, _ = self.srv.accept()
        c.settimeout(None)                 # 阻塞模式：避免空闲超时误断
        self.sock = c
        threading.Thread(target=self._reader, args=(c,), daemon=True).start()

    def connect(self, addr):
        for _ in range(100):
            try:
                c = socket.create_connection(addr, timeout=1)
                c.settimeout(None)         # 阻塞模式：避免空闲超时误断
                self.sock = c
                threading.Thread(target=self._reader, args=(c,), daemon=True).start()
                return True
            except OSError:
                time.sleep(0.1)
        self.core.out("log", "[link] 连接对端失败")
        return False

    def open_serial(self, port, baud=115200):
        """打开串口空口，连接真实 CH32V203 板的 UART2。
        真机未插/端口未就绪时，后台每 2s 自动重试（自动建链）。"""
        def _try():
            while True:
                try:
                    import serial
                    ser = serial.Serial(port, baud, timeout=0.05, write_timeout=1.0)
                    ser.reset_input_buffer()
                    self.sock = _SerialPeer(ser, port, baud)
                    self.core.out("log", f"[{self.core.name}] 串口空口已连接 {port} @{baud}")
                    threading.Thread(target=self._reader, args=(self.sock,),
                                     daemon=True).start()
                    return
                except Exception:
                    self.core.out("log", f"[{self.core.name}] 等待串口空口 {port} …")
                    time.sleep(2)

        threading.Thread(target=_try, daemon=True).start()

    def _reader(self, c):
        try:
            while True:
                data = c.recv(4096)
                if not data:
                    if getattr(c, "is_serial", False):
                        time.sleep(0.01)    # 串口空闲（无数据）不算断开
                        continue
                    break
                self.feed(data)
        except OSError:
            pass          # 对端断开或连接错误
        self.sock = None
        # 串口空口断开后自动重连（如真机掉线/重新上电）
        if getattr(c, "is_serial", False):
            self.open_serial(c.link_port, c.link_baud)

    def _frame(self, t, payload):
        p = bytes(payload)
        hdr = bytes([0xAA, 0x55, t, len(p) >> 8, len(p) & 0xFF])
        return hdr + bytes([crc8(hdr[2:] + p)]) + p

    def send(self, t, payload):
        if self.sock is None:
            return
        try:
            self.sock.sendall(self._frame(t, payload))
            self.tx_pkts += 1
            if t == LINK_TYPE_DATA:
                self.core.frame_monitor("TX", bytes(payload))
        except OSError:
            self.sock = None

    def feed(self, data):
        self.rxbuf += data
        while len(self.rxbuf) >= 6:
            if self.rxbuf[0] != 0xAA or self.rxbuf[1] != 0x55:
                self.rxbuf = self.rxbuf[1:]
                continue
            t = self.rxbuf[2]
            ln = (self.rxbuf[3] << 8) | self.rxbuf[4]
            if len(self.rxbuf) < 6 + ln:
                break
            body = self.rxbuf[2:5] + self.rxbuf[6:6 + ln]
            if self.rxbuf[5] != crc8(body):
                self.rxbuf = self.rxbuf[1:]
                continue
            self.pending.append((t, self.rxbuf[6:6 + ln]))
            self.rx_pkts += 1
            if t == LINK_TYPE_DATA:
                self.core.frame_monitor("RX", self.rxbuf[6:6 + ln])
            self.rxbuf = self.rxbuf[6 + ln:]

    def poll(self):
        while self.pending:
            t, p = self.pending.pop(0)
            self.core.wifi.handle_frame(t, p)


# ---------------------------------------------------------------------------
# 无线状态机（对应固件 sim_wifi）
# ---------------------------------------------------------------------------
class Wifi:
    def __init__(self, core):
        self.core = core
        self.cfg = core.cfg
        self.conn = CONN_IDLE
        self.pairing = False
        self.sta = []               # [(mac_bytes, rssi)]
        self.tx_pkts = 0
        self.rx_pkts = 0
        self.last_ap = None         # (ssid, freq, bw, rssi)
        self.rx_queue = []          # 待 host 读取的帧
        self.evt_queue = []
        self._next_beacon = 0
        self._next_retry = 0
        self._next_keepalive = 0
        self._last_peer = 0

    # ---------------- 查询 ----------------
    def mode(self):
        return self.cfg.mode

    def conn_str(self):
        return CONN_STR.get(self.conn, "UNKNOWN")

    def sta_count(self):
        return len(self.sta)

    def get_rssi(self, index=0):
        if self.cfg.mode == MODE_AP:
            if 0 <= index < len(self.sta):
                return self.sta[index][1]
            return 0
        return self.cfg.rssi if self.conn == CONN_CONNECTED else 0

    def emit(self, text):
        self.core.out("event", text)

    # ---------------- 帧处理 ----------------
    def handle_frame(self, t, p):
        c = self.cfg
        if t == LINK_TYPE_BEACON:
            if c.mode not in (MODE_STA, MODE_APSTA):
                return
            if len(p) < 5:
                return
            ssid_len = p[0]
            if ssid_len > 32 or len(p) < 5 + ssid_len:
                return
            ssid = p[1:1 + ssid_len].decode("utf-8", "replace")
            freq = (p[1 + ssid_len] << 8) | p[2 + ssid_len]
            bw = p[3 + ssid_len]
            enc = p[4 + ssid_len]
            if not (c.ssid == "" or c.ssid.lower() == ssid.lower()):
                return
            if not c.chan_in_list(freq) or bw != c.bss_bw:
                return
            self._last_peer = self.core.now()
            self.last_ap = (ssid, freq, bw, c.rssi)
            if self.conn in (CONN_IDLE, CONN_DISCONNECTED):
                self.conn = CONN_SCANNING
            if self.conn == CONN_SCANNING:
                self.conn = CONN_ASSOCIATING
                self._next_retry = self.core.now() + 0.02

        elif t == LINK_TYPE_ASSOC_RESP:
            if c.mode not in (MODE_STA, MODE_APSTA):
                return
            if len(p) < 2 or p[0] != 0:
                return
            if self.conn != CONN_CONNECTED:      # 去重
                self.emit("+CONNECTED")
            self.conn = CONN_CONNECTED
            self._last_peer = self.core.now()

        elif t == LINK_TYPE_ASSOC_REQ:
            if c.mode not in (MODE_AP, MODE_APSTA):
                return
            if len(p) < 7:
                return
            ssid_len = p[0]
            if len(p) < 1 + ssid_len + 6:
                return
            req_ssid = p[1:1 + ssid_len].decode("utf-8", "replace")
            sta_mac = p[1 + ssid_len:1 + ssid_len + 6]
            if not (c.ssid == "" or req_ssid == "" or
                    req_ssid.lower() == c.ssid.lower()):
                return
            # 配对：STA 无 SSID 时，AP 下发 SSID+PSK（变长：ssid_len|ssid|psk_len|psk）
            if req_ssid == "" and self.pairing and c.ssid:
                psk_b = c.psk.encode()
                payload = bytes([len(c.ssid)]) + c.ssid.encode() + \
                    bytes([len(psk_b)]) + psk_b
                self.core.link.send(LINK_TYPE_PAIR_PSK, payload)
            # 加入 STA 表
            if sta_mac not in [s[0] for s in self.sta] and len(self.sta) < MAX_STA:
                self.sta.append((sta_mac, 0 - c.rssi))
                self.emit("+STA_CONNECTED")
            self.conn = CONN_CONNECTED
            self._last_peer = self.core.now()
            self.core.link.send(LINK_TYPE_ASSOC_RESP, bytes([0, 0 - c.rssi]))

        elif t == LINK_TYPE_PAIR_PSK:
            if len(p) < 3:
                return
            ssid_len = p[0]
            if len(p) < 1 + ssid_len + 1:
                return
            psk_len = p[1 + ssid_len]
            if len(p) < 1 + ssid_len + 1 + psk_len:
                return
            if c.ssid == "":
                c.ssid = p[1:1 + ssid_len].decode("utf-8", "replace")
            if psk_len > 0:
                c.psk = p[1 + ssid_len + 1:1 + ssid_len + 1 + psk_len].decode(
                    "ascii", "replace")
                c.keymgmt = KEY_WPA_PSK
            self.emit("+PAIR SUCCESS")

        elif t == LINK_TYPE_DEAUTH:
            if self.conn == CONN_CONNECTED:
                self.conn = CONN_DISCONNECTED
                self.emit("+DISCONNECTED")

        elif t == LINK_TYPE_DATA:
            if len(p) < 14:
                return
            dst = p[:6]
            me = c.mac
            is_bcast = dst == bytes([0xFF] * 6)
            is_group = (c.mode == MODE_GROUP and dst == c.group) or (dst[0] & 1)
            if not (is_bcast or dst == me or is_group):
                return
            if len(self.rx_queue) < 4:
                self.rx_queue.append(p)
                self.rx_pkts += 1

    # ---------------- 周期轮询 ----------------
    def poll(self):
        c = self.cfg
        now = self.core.now()
        if c.mode in (MODE_AP, MODE_APSTA):
            if now >= self._next_beacon:
                b = bytes([len(c.ssid)]) + c.ssid.encode()
                b += bytes([c.chan_list[0] >> 8, c.chan_list[0] & 0xFF, c.bss_bw, c.keymgmt])
                self.core.link.send(LINK_TYPE_BEACON, b)
                self._next_beacon = now + 0.5
            if self.sta and now - self._last_peer > 8:
                self.sta = []
                self.conn = CONN_IDLE
                self.emit("+STA_DISCONNECTED")
        if c.mode in (MODE_STA, MODE_APSTA) and self.conn == CONN_ASSOCIATING:
            if now >= self._next_retry:
                req = bytes([len(c.ssid)]) + c.ssid.encode() + c.mac
                self.core.link.send(LINK_TYPE_ASSOC_REQ, req)
                self._next_retry = now + 0.5
        if c.mode in (MODE_STA, MODE_APSTA) and self.conn == CONN_CONNECTED:
            if now - self._last_peer > 3:
                self.conn = CONN_DISCONNECTED
                self.emit("+DISCONNECTED")
            # 保活：周期重发关联请求，避免被 AP 当作静默 STA 丢弃
            if now >= self._next_keepalive:
                req = bytes([len(c.ssid)]) + c.ssid.encode() + c.mac
                self.core.link.send(LINK_TYPE_ASSOC_REQ, req)
                self._next_keepalive = now + 2.0

    # ---------------- 数据通路 ----------------
    def send_data(self, frame):
        c = self.cfg
        if len(frame) < 14 or len(frame) > MAX_FRAME:
            return -1
        if c.mode in (MODE_STA, MODE_APSTA) and self.conn != CONN_CONNECTED:
            return -1
        if c.mode == MODE_AP and not self.sta:
            return -1
        self.core.link.send(LINK_TYPE_DATA, frame)
        self.tx_pkts += 1
        return 0

    def take_rx(self):
        return self.rx_queue.pop(0) if self.rx_queue else None

    def take_event(self):
        return self.evt_queue.pop(0) if self.evt_queue else None

    def has_rx(self):
        return len(self.rx_queue) > 0

    def has_event(self):
        return len(self.evt_queue) > 0

    def last_ap(self):
        return self.last_ap

    def reset(self):
        self.conn = CONN_IDLE
        self.pairing = False
        self.sta = []
        self.tx_pkts = self.rx_pkts = 0
        self.last_ap = None
        self.rx_queue = []
        self.evt_queue = []
        self._next_beacon = 0
        self._next_retry = 0
        self._next_keepalive = 0
        self._last_peer = 0


# ---------------------------------------------------------------------------
# AT 引擎（对应固件 sim_at）
# ---------------------------------------------------------------------------
class At:
    def __init__(self, core, family=FAMILY_NATIVE):
        self.core = core
        self.family = family          # native / tah / hc01（见 devprofiles.py）
        self.tah = tah_style(family)  # 泰芯 AH 风格：+ 前缀 / 裸查询 / 状态行不追加 OK
        self.dbg_lmac = 0
        self.dbg_wnb = 0
        self.txdata = None       # None 或 (len, buf)

    def out(self, text):
        self.core.out("console", text)

    def ok(self):
        self.out("OK")

    def err(self):
        self.out("ERROR")

    def resp(self, key, val):
        # 泰芯 AH 族（tah：tj45/txah；hc01 占位暂同）状态响应带 + 前缀（如 +MODE:AP），
        # 便于 thalow_config.py 等真实板工具直接对 PC 模拟器使用。查询只回状态行、不再
        # 追加 OK：否则 UI 轮询（AT+CONN_STATE/AT+RSSI/AT+MODE?/AT+SSID?）会刷屏。
        self.out(f"{'+' if self.tah else ''}{key}:{val}")
        if not self.tah:
            self.ok()

    # ---------------- handlers ----------------
    def h_mode(self, a):
        c = self.core.cfg
        # 泰芯 AH 族用裸 AT+MODE 查询当前模式（thalow_config.py 的 resync/status）
        if a == "?" or (self.tah and a == ""):
            self.resp("MODE", MODE_STR.get(c.mode, "?"))
            return
        m = {"AP": MODE_AP, "STA": MODE_STA, "APSTA": MODE_APSTA, "GROUP": MODE_GROUP}.get(a.upper())
        if m is None:
            self.err()
            return
        c.mode = m
        self.core.wifi.reset()
        self.ok()

    def h_ssid(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("SSID", c.ssid)
            return
        if not 1 <= len(a) <= 32:
            self.err()
            return
        c.ssid = a
        self.ok()

    def h_keymgmt(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("KEYMGMT", "WPA-PSK" if c.keymgmt == KEY_WPA_PSK else "NONE")
            return
        if a.upper() == "WPA-PSK":
            c.keymgmt = KEY_WPA_PSK
            self.ok()
        elif a.upper() == "NONE":
            c.keymgmt = KEY_NONE
            self.ok()
        else:
            self.err()

    def h_psk(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("PSK", c.psk)
            return
        if not is_hex64(a):
            self.err()
            return
        c.psk = a
        self.ok()

    def h_pair(self, a):
        v = atoi(a)
        if v == 1:
            self.core.wifi.pairing = True
            self.ok()
        elif v == 0:
            self.core.wifi.pairing = False
            self.out("PAIR STOP")
            self.ok()
        else:
            self.err()

    def h_bss_bw(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("BSS_BW", str(c.bss_bw))
            return
        v = atoi(a)
        if v not in (1, 2, 4, 8):
            self.err()
            return
        c.bss_bw = v
        self.ok()

    def h_freq_range(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("FREQ_RANGE", f"{c.chan_list[0]},{c.chan_list[-1]}")
            return
        if "," not in a:
            self.err()
            return
        start_s, end_s = a.split(",", 1)
        start, end = atoi(start_s), atoi(end_s)
        if start <= 0 or end < start:
            self.err()
            return
        step = c.bss_bw * 10
        lst = list(range(start, end + 1, step))[:16]
        if not lst:
            self.err()
            return
        c.chan_list = lst
        self.ok()

    def h_chan_list(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("CHAN_LIST", ",".join(str(x) for x in c.chan_list))
            return
        parts = a.split(",")
        lst = [atoi(x) for x in parts]
        if not lst or not all(1000 <= x <= 20000 for x in lst):
            self.err()
            return
        c.chan_list = lst[:16]
        self.ok()

    def h_rssi(self, a):
        idx = 0
        if a and a != "?":
            idx = atoi(a)
            if idx > 0:
                idx -= 1
        self.resp("RSSI", str(self.core.wifi.get_rssi(idx)))

    def h_conn_state(self, a):
        self.resp("CONN_STATE", self.core.wifi.conn_str())

    def h_wnbcfg(self, a):
        c = self.core.cfg
        self.out(f"WIFI MODE:{c.mode}")
        self.out(f"SSID:{c.ssid}")
        self.out(f"BSS_BW:{c.bss_bw}")
        self.out(f"CHAN_LIST:{','.join(str(x) for x in c.chan_list)}")
        self.out("KEYMGMT:" + ("WPA-PSK" if c.keymgmt == KEY_WPA_PSK else "NONE"))
        self.out(f"TXPOWER:{c.txpower}")
        self.out(f"TX_MCS:{c.tx_mcs}")
        self.out(f"HEART_INT:{c.heart_int}")
        self.out(f"ACKTMO:{c.ack_tmo}")
        self.out(f"ROAM:{c.roam}")
        self.out("CONN_STATE:" + self.core.wifi.conn_str())
        self.out("RSSI:" + str(self.core.wifi.get_rssi(0)))
        self.out("MAC_ADDR:" + mac_str(c.mac))
        self.ok()

    def h_scan_ap(self, a):
        secs = atoi(a)
        self.out(f"SCAN START {secs if 0 < secs <= 30 else 2}s")
        self.ok()

    def h_bsslist(self, a):
        la = self.core.wifi.last_ap()
        if la:
            self.out(f"BSS:SSID={la[0]},FREQ={la[1]},BW={la[2]},RSSI={la[3]}")
        else:
            self.out("BSSLIST:0")
        self.ok()

    def h_mac_addr(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("MAC_ADDR", mac_str(c.mac))
            return
        m = parse_mac(a)
        if m:
            c.mac = m
            self.ok()
        else:
            self.err()

    def h_version(self, a):
        self.resp("VERSION", VERSION)

    def h_txpower(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("TXPOWER", str(c.txpower))
            return
        v = atoi(a)
        if 6 <= v <= 20:
            c.txpower = v
            self.ok()
        else:
            self.err()

    def h_ack_tmo(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("ACKTMO", str(c.ack_tmo))
            return
        c.ack_tmo = atoi(a)
        self.ok()

    def h_tx_mcs(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("TX_MCS", str(c.tx_mcs))
            return
        v = atoi(a)
        if 0 <= v <= 7 or v == 255:
            c.tx_mcs = v
            self.ok()
        else:
            self.err()

    def h_heart_int(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("HEART_INT", str(c.heart_int))
            return
        v = atoi(a)
        if 1 <= v <= 60000:
            c.heart_int = v
            self.ok()
        else:
            self.err()

    def h_roam(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("ROAM", str(c.roam))
            return
        v = atoi(a)
        if v in (0, 1):
            c.roam = v
            self.ok()
        else:
            self.err()

    def h_joingroup(self, a):
        c = self.core.cfg
        if c.mode != MODE_GROUP:
            self.err()
            return
        if "," not in a:
            self.err()
            return
        macs, aid = a.split(",", 1)
        m = parse_mac(macs)
        if not m:
            self.err()
            return
        c.group = m
        c.aid = atoi(aid)
        self.ok()

    def h_ps_mode(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("PS_MODE", str(c.ps_mode))
            return
        v = atoi(a)
        if 0 <= v <= 4:
            c.ps_mode = v
            self.ok()
        else:
            self.err()

    def h_r_ssid(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("R_SSID", c.r_ssid)
            return
        if 0 < len(a) <= 32:
            c.r_ssid = a
            self.ok()
        else:
            self.err()

    def h_r_psk(self, a):
        c = self.core.cfg
        if a == "?":
            self.resp("R_PSK", c.r_psk)
            return
        if is_hex64(a):
            c.r_psk = a
            self.ok()
        else:
            self.err()

    def h_loaddef(self, a):
        if atoi(a) != 1:
            self.err()
            return
        self.out("RESTORE FACTORY")
        self.core.cfg = SimCfg()
        self.core.wifi.cfg = self.core.cfg
        self.core.wifi.reset()
        self.ok()

    def h_sysdbg(self, a):
        if a == "?":
            self.out(f"SYSDBG:LMAC={self.dbg_lmac},WNB={self.dbg_wnb}")
            self.ok()
            return
        if "," not in a:
            self.err()
            return
        which, val = a.split(",", 1)
        v = 1 if atoi(val) else 0
        if which.lower() == "lmac":
            self.dbg_lmac = v
            self.ok()
        elif which.lower() == "wnb":
            self.dbg_wnb = v
            self.ok()
        else:
            self.err()

    def h_txdata(self, a):
        ln = atoi(a)
        if ln < 14 or ln > MAX_FRAME:
            self.err()
            return
        self.ok()
        self.txdata = (ln, bytearray())

    def h_rst(self, a):
        self.out("RESET")
        raise SystemExit(0)

    # ---------------- 分发 ----------------
    def run(self, line):
        if line.strip().upper() == "AT":
            self.ok()
            return
        if not line.upper().startswith("AT+"):
            self.err()
            return
        rest = line[3:]                     # 形如 "VERSION?" 或 "MODE=AP"
        cmd, args = rest, ""
        if "=" in rest:
            cmd, args = rest.split("=", 1)
        elif rest.endswith("?"):
            cmd, args = rest[:-1], "?"
        name = self.TABLE.get("AT+" + cmd.upper())
        if name:
            getattr(self, name)(args)
        else:
            self.err()

    # ---------------- 数据模式 ----------------
    def data_byte(self, b):
        if not self.txdata:
            return False
        ln, buf = self.txdata
        buf.append(b)
        if len(buf) >= ln:
            self.txdata = None
            if self.core.wifi.send_data(bytes(buf)) == 0:
                self.out("TX DATA OK")
            else:
                self.out("TX DATA FAIL")
            return True
        return False


# 命令表（存方法名，运行时 getattr 绑定 self）
At.TABLE = {
    "AT+MODE": "h_mode", "AT+SSID": "h_ssid", "AT+KEYMGMT": "h_keymgmt",
    "AT+PSK": "h_psk", "AT+PAIR": "h_pair", "AT+BSS_BW": "h_bss_bw",
    "AT+FREQ_RANGE": "h_freq_range", "AT+CHAN_LIST": "h_chan_list",
    "AT+RSSI": "h_rssi", "AT+CONN_STATE": "h_conn_state",
    "AT+WNBCFG": "h_wnbcfg", "AT+SCAN_AP": "h_scan_ap",
    "AT+BSSLIST": "h_bsslist", "AT+MAC_ADDR": "h_mac_addr",
    "AT+VERSION": "h_version", "AT+TXPOWER": "h_txpower",
    "AT+ACKTMO": "h_ack_tmo", "AT+ACK_TO": "h_ack_tmo",
    "AT+TX_MCS": "h_tx_mcs", "AT+HEART_INT": "h_heart_int",
    "AT+ROAM": "h_roam", "AT+JOINGROUP": "h_joingroup",
    "AT+PS_MODE": "h_ps_mode", "AT+R_SSID": "h_r_ssid",
    "AT+R_PSK": "h_r_psk", "AT+LOADDEF": "h_loaddef",
    "AT+SYSDBG": "h_sysdbg", "AT+TXDATA": "h_txdata", "AT+RST": "h_rst",
}


# ---------------------------------------------------------------------------
# 核心：组装 + 主循环
# ---------------------------------------------------------------------------
class Core:
    def __init__(self, name, role, console_port, link_port, peer_link,
                 autoconf=True, family=FAMILY_NATIVE, link_serial=None,
                 link_baud=115200):
        self.name = name
        self.family = family
        self.cfg = SimCfg()
        if role.upper() in ("AP", "STA", "APSTA", "GROUP"):
            self.cfg.mode = {"AP": MODE_AP, "STA": MODE_STA,
                             "APSTA": MODE_APSTA, "GROUP": MODE_GROUP}[role.upper()]
        self.at = At(self, family=family)
        self.wifi = Wifi(self)
        self.link = Link(self)
        self.console = Console(console_port, self.at.run,
                               data_mode=lambda: self.at.txdata is not None,
                               on_byte=self.at.data_byte)
        self._t0 = time.monotonic()
        self._last5 = 0.0
        self._last_stats = 0.0
        if link_serial:
            # 串口空口：直接连真实 CH32V203 板的 UART2（自动重连），不走 TCP
            self.link.open_serial(link_serial, link_baud)
            self.link_port_desc = f"serial:{link_serial}"
        else:
            self.link.listen(link_port)
            self.link_port_desc = f"tcp:{link_port}"
            if peer_link:
                threading.Thread(target=self.link.connect, args=(peer_link,),
                                 daemon=True).start()
        self.console.start()
        self.out("log", f"[{self.name}] TXW8301 模拟器 PC 版启动 (AT 控制台 :{console_port}, 空口 {self.link_port_desc})")
        if autoconf:
            self._autoconf()

    def _autoconf(self):
        # 默认：AP 播 halowlink，STA 也设同名 SSID，便于直接演示
        self.cfg.ssid = "halowlink"
        self.cfg.bss_bw = 8
        self.cfg.chan_list = [9080]

    def now(self):
        return time.monotonic() - self._t0

    def out(self, kind, text):
        if kind == "event":
            self.wifi.evt_queue.append(text)
        if kind in ("console", "event", "log"):
            self.console.write(text)

    def frame_monitor(self, direction, payload):
        if self.at.dbg_wnb:
            self.console.write(f"FRAME:{direction} {hexs(payload)}")

    def loop(self):
        while True:
            now = self.now()
            if now - self._last5 >= 0.005:
                self._last5 = now
                self.wifi.poll()
                self.link.poll()
                if (self.at.dbg_lmac or self.at.dbg_wnb) and now - self._last_stats >= 1:
                    self._last_stats = now
                    if self.at.dbg_wnb:
                        self.out("console",
                                 f"WNB: tx={self.wifi.tx_pkts} rx={self.wifi.rx_pkts} "
                                 f"stacnt={self.wifi.sta_count()} state={self.wifi.conn_str()}")
                    if self.at.dbg_lmac:
                        self.out("console",
                                 f"LMAC: link_tx={self.link.tx_pkts} link_rx={self.link.rx_pkts}")
            time.sleep(0.002)


def main():
    ap = argparse.ArgumentParser(description="TXW8301 模拟器 PC 版（无硬件）")
    ap.add_argument("--name", default="A")
    ap.add_argument("--role", default="STA", choices=["AP", "STA", "APSTA", "GROUP"])
    ap.add_argument("--console", type=int, default=9001, help="AT 控制台 TCP 端口")
    ap.add_argument("--link", type=int, default=9011, help="虚拟空口 TCP 端口")
    ap.add_argument("--peer", default=None, help="对端空口 host:port（连接方）")
    ap.add_argument("--ssid", default="halowlink")
    ap.add_argument("--tj45", action="store_true",
                    help="[兼容旧用法] T-Halow-RJ45 兼容模式，等价 --family tah："
                         "状态响应带 + 前缀（+MODE:AP 等）")
    ap.add_argument("--family", default=FAMILY_NATIVE,
                    choices=[FAMILY_NATIVE, FAMILY_TAH, FAMILY_HC01],
                    help="协议族/AT 方言：native=本模拟器(CH32V203)，"
                         f"tah=泰芯 AH(T-Halow-RJ45/TX-AH)，hc01=HT-HC01(占位)")
    ap.add_argument("--link-serial", default=None,
                    help="串口空口（连真实 CH32V203 板的 UART2，需 USB 转串口），如 COM5；"
                         "设置后不再使用 TCP 空口")
    ap.add_argument("--link-baud", type=int, default=115200)
    args = ap.parse_args()

    peer = None
    if args.peer:
        host, _, port = args.peer.partition(":")
        peer = (host, int(port))

    family = FAMILY_TAH if args.tj45 else args.family
    core = Core(args.name, args.role, args.console, args.link, peer,
                family=family, link_serial=args.link_serial,
                link_baud=args.link_baud)
    core.cfg.ssid = args.ssid
    print(f"[{args.name}] 就绪 (family={family}): AT 控制台 127.0.0.1:{args.console}  空口 :{args.link}")
    core.loop()


if __name__ == "__main__":
    main()
