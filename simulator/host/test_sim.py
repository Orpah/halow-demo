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
import re
import socket
import sys
import threading
import time

# 中文输出统一 UTF-8（Windows 控制台默认 GBK：直接 print 中文会在管道里乱码，
# run_tests.py / run_checks.py 按 UTF-8 解读时也对不上）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim

PASS = []


def check(name, cond, detail=""):
    PASS.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def last_rssi(buf):
    """从控制台缓冲里取最后一个 RSSI 值（dBm）。"""
    ms = re.findall(r"RSSI:(-?\d+)", buf)
    return int(ms[-1]) if ms else None


def wait_until(cond, timeout=2.0, interval=0.02):
    """按**截止时间**等条件成立（先判一次）。不用“猜循环次数”那种写法：
    循环次数与环境快慢无关，机器一慢就变成假失败（或白等）。
    """
    end = time.time() + timeout
    while True:
        if cond():
            return True
        if time.time() >= end:
            return False
        time.sleep(interval)


class HostClient:
    """host 数据口客户端（对应真实 SPI MACBUS 的 DATA_TX / DATA_RX）。

    帧格式与空口 Link 完全一致：AA 55 TYPE LEN_H LEN_L CRC-8/ATM payload。
    这个类**故意在本文件里重写一份**（不 import 上层驱动）：它要独立验证模拟器
    侧的实现，若复用同一份编解码代码，两边一起错也测不出来。
    """

    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port))
        self.s.settimeout(0.05)
        self.buf = b""

    def send_frame(self, eth, crc_ok=True):
        p = bytes(eth)
        hdr = bytes([0xAA, 0x55, sim.LINK_TYPE_DATA, len(p) >> 8, len(p) & 0xFF])
        crc = sim.crc8(hdr[2:] + p)
        self.s.sendall(hdr + bytes([crc if crc_ok else (crc ^ 0xFF)]) + p)

    def recv_frame(self, secs=1.0):
        """取一帧（DATA 类型）的载荷；超时返回 None。"""
        end = time.time() + secs
        while time.time() < end:
            if len(self.buf) >= 6:
                if self.buf[0] != 0xAA or self.buf[1] != 0x55:
                    self.buf = self.buf[1:]
                    continue
                ln = (self.buf[3] << 8) | self.buf[4]
                if len(self.buf) >= 6 + ln:
                    body = self.buf[2:5] + self.buf[6:6 + ln]
                    if self.buf[2] == sim.LINK_TYPE_DATA and self.buf[5] == sim.crc8(body):
                        p = self.buf[6:6 + ln]
                        self.buf = self.buf[6 + ln:]
                        return p
                    self.buf = self.buf[1:]
                    continue
            try:
                d = self.s.recv(4096)
                if not d:
                    break
                self.buf += d
            except socket.timeout:
                continue
        return None

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


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
    # 端口一律传 0（内核自动分配，再用 core.console.port / core.link.link_port 回读）：
    # 固定端口会与「另一个模拟器 / 兄弟仓正在跑的 demo」撞上，而 **Windows 的
    # SO_REUSEADDR 允许两进程同时绑定同一端口** → 静默串扰（本仓真踩过：本文件旧版
    # 用 9401/9402，与 orpah-over-halow 的 ui_server 撞车，串口空口那条数据用例恒红，
    # 而“已连接”却是真的——连的是别人的模拟器）。
    # A/B 顺带开 host 数据口：第 7 节用它验证「上层程序走数据面」的通路
    coreA = sim.Core("A", "AP", 0, 0, None, host_port=0)
    coreB = sim.Core("B", "STA", 0, 0, ("127.0.0.1", coreA.link.link_port), host_port=0)

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
    a = Client(coreA.console.port)
    a.send("AT")
    check("A 返回 OK", a.contains("OK", 0.6))
    a.send("AT+VERSION?")
    check("A VERSION", a.contains("VERSION:", 0.6))
    a.send("AT+MODE?")
    check("A MODE=AP", a.contains("MODE:AP", 0.6))
    a.send("AT+SSID?")
    check("A SSID", a.contains("SSID:halowlink", 0.6))

    print("== 2. 自动连接（AP+STA 同 SSID） ==")
    b = Client(coreB.console.port)
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
    coreT = sim.Core("T", "AP", 0, 0, None, family=sim.FAMILY_TAH)
    threading.Thread(target=loop, args=(coreT,), daemon=True).start()
    time.sleep(0.4)
    t = Client(coreT.console.port)
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
    t.send("AT+STALIST")                  # 模拟器扩展命令在 tah 方言下也带 + 前缀、无 OK
    t.pump(0.4)
    check("T 无 STA 时 STALIST:0", "+STALIST:0" in t.buf)
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
        coreSA = sim.Core("SA", "AP", 0, 0, None, link_serial="SERA")
        coreSB = sim.Core("SB", "STA", 0, 0, None, link_serial="SERB")
    finally:
        _rs.Serial = _real_serial

    threading.Thread(target=loop, args=(coreSA,), daemon=True).start()
    threading.Thread(target=loop, args=(coreSB,), daemon=True).start()
    time.sleep(2.5)                     # 等串口打开 + beacon + 关联

    sa = Client(coreSA.console.port)
    sb = Client(coreSB.console.port)
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

    print("== 7. host 数据口（--host）：DATA_TX / DATA_RX ==")
    # 语义 = 真实 SPI MACBUS：host 注入的帧走空口转发出去，从空口收到、
    # 目的为本机/广播的帧推回 host。两端都开 host 口，所以可以端到端对拍。
    hA = HostClient(coreA.hostport.port)
    hB = HostClient(coreB.hostport.port)
    time.sleep(0.3)                       # 等 TCP 连上 + AP 侧 STA 表非空
    bcast = bytes([0xFF] * 6)
    f_a2b = bcast + coreA.cfg.mac + bytes([0x88, 0xB5]) + b"HOST-PORT-A2B"
    hA.send_frame(f_a2b)
    got = hB.recv_frame(2.0)
    check("A host 注入 -> 空口 -> B host 收到", got == f_a2b,
          f"len={len(got) if got else 0}")
    f_b2a = bcast + coreB.cfg.mac + bytes([0x88, 0xB5]) + b"HOST-PORT-B2A"
    hB.send_frame(f_b2a)
    got2 = hA.recv_frame(2.0)
    check("B host 注入 -> 空口 -> A host 收到", got2 == f_b2a,
          f"len={len(got2) if got2 else 0}")
    # 坏帧不能进空口，也不能把后面的好帧带歪：短帧(<14B)、CRC 错帧、非 DATA 类型都丢掉
    hA.send_frame(b"TOO-SHORT")                       # 10B：低于最小以太网帧长
    hA.send_frame(bcast + coreA.cfg.mac + bytes([0x88, 0xB5]) + b"BAD-CRC",
                  crc_ok=False)
    hA.s.sendall(bytes([0xAA, 0x55, sim.LINK_TYPE_BEACON, 0, 3, 0, 1, 2, 3]))  # 非 DATA 类型
    f_after = bcast + coreA.cfg.mac + bytes([0x88, 0xB5]) + b"AFTER-BAD"
    hA.send_frame(f_after)
    got3 = hB.recv_frame(2.0)
    check("短帧/坏 CRC/非 DATA 帧被丢弃，好帧仍按序到达", got3 == f_after,
          f"len={len(got3) if got3 else 0}")
    hA.close()
    hB.close()

    print("== 8. RSSI 距离模型 + STA 关联表（模拟器扩展 AT+DIST/AT+PATHLOSS/AT+STALIST） ==")
    # 默认关距离模型（distance=0）→ RSSI 就是注入值，行为与以前一致
    a.send("AT+DIST?")
    a.pump(0.4)
    check("默认距离模型关（DIST:0）", "DIST:0" in a.buf)
    b.send("AT+RSSI")
    b.pump(0.6)
    check("默认 RSSI = 注入值 -30", last_rssi(b.buf) == -30)
    # 开距离模型：10 m @908MHz、n=2 → PL≈51.6dB；AP 发 20dBm → B 应收 ≈ -32 dBm
    #（f=908MHz: 20lg908=59.16；PL=59.16-27.55+20lg10=51.61）
    # 距离是**链路属性**：每个方向各自算（本机拿对端自报的功率 − 本机设的距离），
    # 所以两端都要设（UI 的配置面板会把 AT+DIST 同时下发给 A/B）。
    for cli in (a, b):
        cli.send("AT+DIST=10")
    a.send("AT+TXPOWER=20")
    a.pump(0.4)
    b.pump(0.3)
    time.sleep(1.3)                        # 等下一个 beacon（0.5s 一次）
    r10 = (b.send("AT+RSSI"), b.pump(0.6), last_rssi(b.buf))[2]
    check("10m 距离模型：B 收到 ≈ -32 dBm（不再是注入的 -30）",
          r10 is not None and abs(r10 + 31.6) <= 1.5, f"rssi={r10}")
    # 发射功率真的影响对端（以前 AT+TXPOWER 只是存起来）：降 14dB → RSSI 也应降 ~14dB
    a.send("AT+TXPOWER=6")
    a.pump(0.3)
    time.sleep(1.3)
    b.send("AT+RSSI")
    b.pump(0.6)
    r6 = last_rssi(b.buf)
    check("AP 发射功率降低 14dB → B 收到信号同步降低（≈ -46 dBm）",
          r6 is not None and abs(r6 + 45.6) <= 1.5, f"rssi={r6}（原 {r10}）")
    # AP 侧关联表：按索引 / 按 MAC 查同一个 STA，且随该 STA 的发射功率变化
    a.send("AT+STALIST")
    a.pump(0.6)
    check("A 的 STA 表里有 B 的 MAC",
          ("STALIST:1," + sim.mac_str(coreB.cfg.mac) + "=") in a.buf)
    b.send("AT+TXPOWER=6")
    b.send("AT+MODE=STA")                 # 重新关联（清状态 → 立即带新功率重发 ASSOC_REQ）
    b.pump(0.4)
    time.sleep(1.6)
    a.send("AT+RSSI=1")
    a.pump(0.6)
    ap_rssi = last_rssi(a.buf)
    check("A 侧看到的 STA 信号随其发射功率变化（≈ -46 dBm）",
          ap_rssi is not None and abs(ap_rssi + 45.6) <= 1.5, f"rssi={ap_rssi}")
    a.send(f"AT+RSSI={sim.mac_str(coreB.cfg.mac)}")
    a.pump(0.6)
    check("按 MAC 查 RSSI 与按索引一致", last_rssi(a.buf) == ap_rssi)
    for cli in (a, b):                     # 关也是两端的事
        cli.send("AT+DIST=0")
    b.pump(0.4)
    time.sleep(0.3)                        # 等一次 beacon 刷新
    b.send("AT+RSSI")
    b.pump(0.6)
    check("关距离模型后 B 回到注入值 -30", last_rssi(b.buf) == -30)

    print("== 9. 行为模型：丢包 / 关联失败 / RAW 接入窗口 / TWT 唤醒（均默认关）==")
    # 先确保 A=AP、B=STA 处于连接态
    a.send("AT+MODE=AP")
    b.send("AT+MODE=STA")
    a.pump(0.4)
    b.pump(0.4)
    time.sleep(1.5)
    b.send("AT+CONN_STATE")
    b.pump(0.8)
    check("第 9 节起点：B 已连上", "CONN_STATE:CONNECTED" in b.buf)

    # (a) 丢包注入：只作用数据帧，且确定性（100% 必丢、0% 不丢）
    b.send("AT+LOSS=100")
    b.pump(0.3)
    n0 = coreA.wifi.rx_pkts
    b.send("AT+TXDATA=20")
    b.pump(0.3)
    b.send_raw(bytes([0xFF] * 6) + bytes(range(14)))
    b.pump(0.8)
    check("LOSS=100%：帧被丢（对端 rx 不变 + 本机回 TX DATA FAIL）",
          coreA.wifi.rx_pkts == n0 and coreB.wifi.loss_drops == 1,
          f"rx {n0}->{coreA.wifi.rx_pkts} drops={coreB.wifi.loss_drops}")
    b.send("AT+LOSS=0")
    b.pump(0.3)
    b.send("AT+TXDATA=20")
    b.pump(0.3)
    b.send_raw(bytes([0xFF] * 6) + bytes(range(14)))
    b.pump(0.8)
    check("LOSS=0%：帧正常送达", coreA.wifi.rx_pkts == n0 + 1,
          f"rx={coreA.wifi.rx_pkts}")

    # (b) 关联失败概率：100% → 一直连不上（状态机继续重试）
    b.send("AT+ASSOC_FAIL=100")
    b.send("AT+MODE=STA")
    b.pump(0.4)
    time.sleep(2.0)
    check("ASSOC_FAIL=100%：B 连不上且重试计数在涨",
          coreB.wifi.conn != sim.CONN_CONNECTED and coreB.wifi.assoc_fails > 0,
          f"conn={coreB.wifi.conn_str()} fails={coreB.wifi.assoc_fails}")
    b.send("AT+ASSOC_FAIL=0")
    b.pump(0.3)
    time.sleep(1.5)
    b.send("AT+CONN_STATE")
    b.pump(0.8)
    check("ASSOC_FAIL=0%：自动恢复连接", "CONN_STATE:CONNECTED" in b.buf)

    # (c) RAW 接入窗口：AP 定调度（AT+RAW 只在 AP 上有效），STA 从 ASSOC_RESP 学槽位
    a.send("AT+RAW=4")
    a.pump(0.3)
    b.send("AT+MODE=STA")          # 重新关联 → 收获槽位
    b.pump(0.4)
    time.sleep(1.5)
    check("RAW：STA 学到了 AP 的槽数与自己的槽位",
          coreB.wifi.raw_slots_ap == 4 and coreB.wifi.slot is not None,
          f"slots={coreB.wifi.raw_slots_ap} slot={coreB.wifi.slot}")
    # 窗口外发的帧要**排队等窗口**（不是丢），窗口一开就自动发出去。
    # 用进程内 send_data 直接验（不经控制台往返）→ 没有“发送途中窗口开了”的竞态。
    self_frame = bytes([0xFF] * 6) + coreB.cfg.mac + bytes([0x88, 0xB5]) + b"RAW-QUEUED"
    ok = wait_until(lambda: not coreB.wifi.raw_window_open(), timeout=1.5)
    q0, r0 = len(coreB.wifi.tx_queue), coreA.wifi.rx_pkts
    rc = coreB.wifi.send_data(self_frame)
    check("RAW：窗口外 send_data 受理但排队（不是丢）",
          ok and rc == 0 and len(coreB.wifi.tx_queue) == q0 + 1,
          f"rc={rc} q={len(coreB.wifi.tx_queue)} defer={coreB.wifi.raw_defer}")
    wait_until(lambda: coreA.wifi.rx_pkts > r0, timeout=2.0)
    check("RAW：窗口一开，排队的帧送达对端", coreA.wifi.rx_pkts > r0,
          f"rx {r0}->{coreA.wifi.rx_pkts}")
    a.send("AT+RAW=0")
    a.pump(0.3)

    # (d) TWT 唤醒窗口：用“现在醒/睡”这个判据选时刻，结果确定
    b.send("AT+TWT=2000,50")          # 每 2s 只醒 50ms
    b.pump(0.4)
    b.send("AT+TWT?")                 # 读回
    b.pump(0.4)
    check("TWT 配置读回 TWT:2000,50", "TWT:2000,50" in b.buf)
    b.send("AT+MODE=STA")
    b.pump(0.4)
    time.sleep(1.5)
    # 睡着时收到的下行帧丢掉
    wait_until(lambda: not coreB.wifi.twt_awake(), timeout=3.0)
    d0 = coreB.wifi.twt_sleep_drops
    coreA.wifi.send_data(bytes([0xFF] * 6) + coreB.cfg.mac + bytes([0x88, 0xB5]) + b"TWT-DL")
    time.sleep(0.3)
    check("TWT：睡着时下行数据帧被丢（计数 twt_drop 增加）",
          coreB.wifi.twt_sleep_drops > d0, f"drops={coreB.wifi.twt_sleep_drops}")
    # 睡着时自己要发的帧排队，醒来后送达
    wait_until(lambda: not coreB.wifi.twt_awake(), timeout=3.0)
    r1 = coreA.wifi.rx_pkts
    rc2 = coreB.wifi.send_data(bytes([0xFF] * 6) + coreB.cfg.mac + bytes([0x88, 0xB5]) + b"TWT-UL")
    check("TWT：睡着时 send_data 受理但排队",
          rc2 == 0 and len(coreB.wifi.tx_queue) >= 1,
          f"rc={rc2} q={len(coreB.wifi.tx_queue)} defer={coreB.wifi.twt_defer}")
    wait_until(lambda: coreA.wifi.rx_pkts > r1, timeout=4.0)
    check("TWT：醒来后排队帧送达对端", coreA.wifi.rx_pkts > r1,
          f"rx {r1}->{coreA.wifi.rx_pkts}")
    b.send("AT+TWT=0")
    b.pump(0.3)

    print("== 10. 收尾 ==")
    stop.set()
    a.s.close()
    b.s.close()
    print(f"\n结果: {sum(PASS)}/{len(PASS)} 通过")
    # 用 os._exit 干净退出：避免后台守护线程导致解释器关闭崩溃
    sys.stdout.flush()
    os._exit(0 if all(PASS) else 1)


if __name__ == "__main__":
    main()
