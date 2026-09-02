#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_sim.py — PC 版模拟器自测
=============================
进程内创建两台模拟器（A=AP, B=STA），走真实 TCP 路径（控制台 + 空口），
验证：AT 响应、自动连接(+CONNECTED)、数据帧转发(AT+TXDATA)。

运行：python test_sim.py   （无硬件、无第三方依赖）
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim

PASS = []


def check(name, cond, detail=""):
    PASS.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


class Client:
    """TCP 控制台客户端：累积接收缓冲，按需 pump。"""

    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port))
        self.s.settimeout(0.05)
        self.buf = ""

    def send(self, line):
        self.s.sendall((line + "\r\n").encode())

    def send_raw(self, data):
        self.s.sendall(data)

    def pump(self, secs=0.5):
        end = time.time() + secs
        while time.time() < end:
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            self.buf += d.decode("utf-8", "replace")
        return self.buf

    def contains(self, text, secs=1.0):
        self.pump(secs)
        return text in self.buf


def main():
    coreA = sim.Core("A", "AP", 9201, 9211, None)
    coreB = sim.Core("B", "STA", 9202, 9212, ("127.0.0.1", 9211))

    stop = threading.Event()

    def loop(c):
        while not stop.is_set():
            t = c.now()
            c.wifi.poll()
            c.link.poll()
            time.sleep(0.005)

    threading.Thread(target=loop, args=(coreA,), daemon=True).start()
    threading.Thread(target=loop, args=(coreB,), daemon=True).start()
    time.sleep(0.5)

    print("== 1. AT 基础 ==")
    a = Client(9201)
    a.send("AT")
    check("A 返回 OK", a.contains("OK", 0.6))
    a.send("AT+VERSION?")
    check("A VERSION", a.contains("VERSION:", 0.6))
    a.send("AT+MODE?")
    check("A MODE=AP", a.contains("MODE:AP", 0.6))
    a.send("AT+SSID?")
    check("A SSID", a.contains("SSID:halowlink", 0.6))

    print("== 2. 自动连接（AP+STA 同 SSID） ==")
    b = Client(9202)
    b.send("AT+MODE?")
    check("B MODE=STA", b.contains("MODE:STA", 0.6))
    time.sleep(2.0)                       # 等 beacon + 关联
    b.send("AT+CONN_STATE")
    b.pump(1.0)
    check("B CONNECTED", "CONN_STATE:CONNECTED" in b.buf)
    check("B 收到 +CONNECTED 事件", "+CONNECTED" in b.buf)
    a.send("AT+CONN_STATE")
    a.pump(1.0)
    check("A CONNECTED(有STA)", "CONN_STATE:CONNECTED" in a.buf)

    print("== 3. 数据转发（B 发 -> A 收） ==")
    b.send("AT+SYSDBG=WNB,1")
    a.send("AT+SYSDBG=WNB,1")
    time.sleep(0.3)
    frame = bytes([0xFF] * 6) + coreB.cfg.mac + bytes([0x08, 0x00]) + b"HELLO-TXW8301"
    b.send(f"AT+TXDATA={len(frame)}")
    b.pump(0.3)
    b.send_raw(frame)                     # 数据模式直发
    time.sleep(0.6)
    rx = coreA.wifi.take_rx()
    check("A 收到数据帧", rx is not None and rx[12:14] == bytes([0x08, 0x00]),
          f"len={len(rx) if rx else 0}")
    a.pump(1.0)
    check("A 控制台输出 FRAME:RX", "FRAME:RX" in a.buf)
    b.pump(1.0)
    check("B 控制台输出 FRAME:TX", "FRAME:TX" in b.buf)

    print("== 4. 配对（清配置后 PAIR=1） ==")
    b.send("AT+LOADDEF=1")
    b.pump(0.4)
    a.send("AT+LOADDEF=1")
    a.pump(0.4)
    time.sleep(0.5)
    a.send("AT+SSID=pairnet")
    a.send("AT+MODE=AP")
    a.send("AT+PAIR=1")
    b.send("AT+MODE=STA")
    b.send("AT+PAIR=1")
    time.sleep(2.5)
    b.pump(1.0)
    check("B 收到 +PAIR SUCCESS", "+PAIR SUCCESS" in b.buf)
    b.send("AT+SSID?")
    b.pump(0.6)
    check("B 已获取 AP 的 SSID", "SSID:pairnet" in b.buf)
    b.send("AT+CONN_STATE")
    b.pump(1.0)
    check("B 配对后连接", "CONN_STATE:CONNECTED" in b.buf)

    print("== 5. 泰芯 AH 兼容模式（family=tah：状态带 + 前缀） ==")
    coreT = sim.Core("T", "AP", 9301, 9311, None, family=sim.FAMILY_TAH)
    threading.Thread(target=loop, args=(coreT,), daemon=True).start()
    time.sleep(0.4)
    t = Client(9301)
    t.send("AT+MODE")                     # 裸命令查询（thalow_config.py resync/status 用）
    check("T 裸 AT+MODE -> +MODE:AP", t.contains("+MODE:AP", 0.6))
    t.send("AT+VERSION")
    t.pump(0.4)
    check("T AT+VERSION -> +VERSION:", "+VERSION:" in t.buf)
    t.send("AT+CONN_STATE")
    t.pump(0.4)
    check("T AT+CONN_STATE -> +CONN_STATE:", "+CONN_STATE:" in t.buf)
    t.send("AT+RSSI")
    t.pump(0.4)
    check("T AT+RSSI -> +RSSI:", "+RSSI:" in t.buf)
    t.send("AT+RSSI?")                    # 查询形式也兼容
    t.pump(0.4)
    check("T AT+RSSI? 兼容", "+RSSI:" in t.buf)
    t.send("AT+VERSION=?")                # 真实板文档写法
    t.pump(0.4)
    check("T AT+VERSION=? 兼容", "+VERSION:" in t.buf)
    t.close = None
    t.s.close()

    print("== 6. 串口空口（PC <-> 真实 CH32V203 板 UART2） ==")
    # 用 socketpair 模拟串口线：A/B 两个 core 都走 Link 的串口传输（_SerialPeer）。
    # 只关心链路是否通过"串口"建立（beacon/assoc/连接 + 数据帧）。
    import serial as _rs
    _real_serial = _rs.Serial
    _sa, _sb = socket.socketpair()
    _sa.setblocking(False)
    _sb.setblocking(False)

    class _FakeSerial:
        def __init__(self, port, baud=115200, **kw):
            self.s = _sa if port == "SERA" else _sb
        def reset_input_buffer(self):
            pass
        def read(self, n):
            try:
                return self.s.recv(n)
            except BlockingIOError:
                return b""
        def write(self, data):
            self.s.sendall(data)
        def close(self):
            pass

    _rs.Serial = _FakeSerial            # 让 Link.open_serial 用假串口
    try:
        coreSA = sim.Core("SA", "AP", 9401, 9411, None, link_serial="SERA")
        coreSB = sim.Core("SB", "STA", 9402, 9412, None, link_serial="SERB")
    finally:
        _rs.Serial = _real_serial

    threading.Thread(target=loop, args=(coreSA,), daemon=True).start()
    threading.Thread(target=loop, args=(coreSB,), daemon=True).start()
    time.sleep(2.5)                     # 等串口打开 + beacon + 关联

    sa = Client(9401)
    sb = Client(9402)
    sb.send("AT+CONN_STATE")
    sb.pump(1.0)
    check("串口空口 B(STA) CONNECTED", "CONN_STATE:CONNECTED" in sb.buf)
    sa.send("AT+CONN_STATE")
    sa.pump(1.0)
    check("串口空口 A(AP) CONNECTED", "CONN_STATE:CONNECTED" in sa.buf)

    # 数据帧经串口空口转发（广播帧 dst=FF*6，模拟器会正确过滤单播）
    sa.send("AT+SYSDBG=WNB,1")
    sb.send("AT+SYSDBG=WNB,1")
    time.sleep(0.3)
    sa.send("AT+TXDATA=20")
    sa.pump(0.3)
    sa.send_raw(bytes([0xFF] * 6) + bytes(range(14)))   # 20B：广播目的MAC + 载荷
    time.sleep(0.6)
    rx = coreSB.wifi.take_rx()
    check("串口空口 B 收到数据帧", rx is not None and len(rx) == 20,
          f"len={len(rx) if rx else 0}")
    sa.pump(1.0)
    check("串口空口 A 输出 FRAME:TX", "FRAME:TX" in sa.buf)
    sa.s.close()
    sb.s.close()

    print("== 7. 收尾 ==")
    stop.set()
    a.s.close()
    b.s.close()
    print(f"\n结果: {sum(PASS)}/{len(PASS)} 通过")
    # 用 os._exit 干净退出：避免后台守护线程导致解释器关闭崩溃
    sys.stdout.flush()
    os._exit(0 if all(PASS) else 1)


if __name__ == "__main__":
    main()
