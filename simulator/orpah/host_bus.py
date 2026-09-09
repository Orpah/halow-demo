#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
host_bus.py — 模拟器 host 数据口驱动（host 侧）
================================================
连上 PC 模拟器（host/sim.py）的 host 数据口（--host <port>），按与模拟器一致的
帧格式收/发数据帧：

    帧 = AA 55 TYPE LEN_H LEN_L CRC payload      （CRC-8/ATM 0x07，同 sim.py crc8）
    TYPE = 0x01 (LINK_TYPE_DATA)，payload = 以太网帧（≥14B）

语义 = 真实 SPI MACBUS 的 DATA_TX（host→模块，注入走空口）/ DATA_RX（模块→host，推送收帧）。

本驱动只依赖 TCP 与帧格式，不 import sim.py —— 与真实 host 驱动解耦一致：
将来连真实 CH32V203 板的 SPI 时，仅替换底层 send/recv 即可。
"""
import socket
import threading

LINK_TYPE_DATA = 0x01
_HEAD = 6          # AA 55 TYPE LEN_H LEN_L CRC


def crc8(data):
    """CRC-8/ATM 多项式 0x07，MSB-first，初值 0 —— 与 sim.py / 固件 sim_link 一致。"""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def frame_data(payload):
    """payload(以太网帧 bytes) → host 口数据帧 bytes。"""
    p = bytes(payload)
    hdr = bytes([0xAA, 0x55, LINK_TYPE_DATA, len(p) >> 8, len(p) & 0xFF])
    return hdr + bytes([crc8(hdr[2:] + p)]) + p


class HostBus:
    """host 数据口客户端：注入帧 + 读收到的帧（双线程，帧缓冲有界）。"""

    def __init__(self, host="127.0.0.1", port=9101, name="host"):
        self.addr = (host, port)
        self.name = name
        self.sock = None
        self.rxbuf = b""
        self.rx_frames = []          # 收到的数据帧（payload，即以太网帧）
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = None

    # ---------------- 连接 ----------------
    def connect(self, retries=100, interval=0.1):
        for _ in range(retries):
            try:
                s = socket.create_connection(self.addr, timeout=1)
                s.settimeout(None)
                self.sock = s
                self._reader = threading.Thread(target=self._read_loop, daemon=True)
                self._reader.start()
                return True
            except OSError:
                time_sleep(interval)
        return False

    def close(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    # ---------------- host → 模块（DATA_TX） ----------------
    def send_frame(self, eth_frame):
        """注入一个以太网帧到模块（走空口转发到对端）。"""
        if self.sock is None:
            return False
        try:
            self.sock.sendall(frame_data(eth_frame))
            return True
        except OSError:
            self.sock = None
            return False

    # ---------------- 模块 → host（DATA_RX） ----------------
    def recv_frame(self, timeout=2.0):
        """取一帧收到的数据（无则 None）。带超时，便于轮询。"""
        end = time_now() + timeout
        while time_now() < end:
            with self._lock:
                if self.rx_frames:
                    return self.rx_frames.pop(0)
            time_sleep(0.01)
        return None

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            self._feed(data)

    def _feed(self, data):
        self.rxbuf += data
        while len(self.rxbuf) >= _HEAD:
            if self.rxbuf[0] != 0xAA or self.rxbuf[1] != 0x55:
                self.rxbuf = self.rxbuf[1:]
                continue
            t = self.rxbuf[2]
            ln = (self.rxbuf[3] << 8) | self.rxbuf[4]
            if len(self.rxbuf) < _HEAD + ln:
                break
            body = self.rxbuf[2:5] + self.rxbuf[6:6 + ln]
            if self.rxbuf[5] != crc8(body):
                self.rxbuf = self.rxbuf[1:]
                continue
            payload = self.rxbuf[6:6 + ln]
            self.rxbuf = self.rxbuf[_HEAD + ln:]
            if t == LINK_TYPE_DATA and len(payload) >= 14:
                with self._lock:
                    if len(self.rx_frames) < 64:
                        self.rx_frames.append(payload)


# 便于替换成真实时钟（测试注入）
def time_now():
    import time
    return time.monotonic()


def time_sleep(s):
    import time
    time.sleep(s)
