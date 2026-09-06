#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sim_config.py — 配置 / 调试 TXW8301 模拟器（CH32V203）

支持两种总线访问模拟器：
  * UART（默认，推荐）: 走 CH340C AT 控制台，115200 8N1，与真实模块 AT 一致。
  * SPI（实验性）    : 走 CH341A/CH347A (USB-SPI 适配器) 宿主接口，
                      实现 docs/spi_protocol.md 的帧协议（需 pyusb）。

用法示例：
  # UART
  python sim_config.py list
  python sim_config.py COM3 ap  --ssid halowlink --freq 9080 --bw 8 --open
  python sim_config.py COM4 sta --ssid halowlink --freq 9080 --bw 8 --open
  python sim_config.py COM4 status
  python sim_config.py COM4 reset
  python sim_config.py COM4 at  "AT+CHAN_LIST=9080,9160"

  # T-Halow-RJ45 真实板（同一套命令，--variant tj45 自动关调试刷屏）
  python sim_config.py COM3 status --variant tj45
  python sim_config.py COM3 ap --ssid halowlink --freq 9080 --bw 8 --open --variant tj45

  # TX-AH 泰芯原厂模组（AH-SDK V2.x 方言，--variant txah）：
  #   AT+WIFIMODE / AT+ENCRYPT / AT+KEY，查询带 '?'；--psk 作 KEY（≥8 个 ASCII 字符）
  python sim_config.py COM3 status --variant txah
  python sim_config.py COM3 ap --ssid halowlink --freq 9080 --bw 8 --open --variant txah

  # HT-HC01 真实板（占位：命令集待手册，先按泰芯 AH 同款处理并关调试刷屏）
  python sim_config.py COM3 status --variant hc01

  # SPI（CH341A，实验性）
  python sim_config.py spi ap  --ssid halowlink --freq 9080 --bw 8 --open
  python sim_config.py spi status
  python sim_config.py spi ping
"""
import argparse
import sys
import time

try:
    import serial
    from serial.tools import list_ports
    HAS_PYSERIAL = True
except ImportError:
    HAS_PYSERIAL = False

BAUD = 115200

# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def crc8_update(crc, data):
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF   # CRC-8/ATM, poly 0x07
            else:
                crc = (crc << 1) & 0xFF
    return crc

def crc8(data):
    return crc8_update(0, data)

# ---------------------------------------------------------------------------
# UART 传输（AT 控制台）
# ---------------------------------------------------------------------------

class UartTransport:
    def __init__(self, port):
        if not HAS_PYSERIAL:
            sys.exit("需要 pyserial：pip install pyserial")
        self.ser = serial.Serial(port, BAUD, timeout=0.1, write_timeout=1.0)
        self.ser.reset_input_buffer()

    def read_for(self, secs):
        end = time.time() + secs
        buf = b""
        while time.time() < end:
            n = self.ser.in_waiting
            if n:
                buf += self.ser.read(n)
                end = time.time() + 0.25
            else:
                time.sleep(0.01)
        return buf

    def cmd(self, line, wait=1.2):
        self.ser.write(line.encode() + b"\r\n")
        return self.read_for(wait).decode("utf-8", "replace")

    def resync(self):
        for _ in range(5):
            self.ser.write(b"\x55" * 1700)
            time.sleep(0.2)
            self.read_for(0.4)
            # 泰芯真机 TX-AH(txah) 用 V2.x 查询 AT+WIFIMODE=?；其余（模拟器/tj45）用 AT+MODE
            if getattr(self, "variant", "sim") == "txah":
                r = self.cmd("AT+WIFIMODE=?", 1.0)
                if "+WIFIMODE" in r or "WIFIMODE:" in r:
                    return True
            else:
                r = self.cmd("AT+MODE", 1.0)
                # 兼容本模拟器(MODE:AP) 与 T-Halow-RJ45(+MODE:AP)
                if "+MODE" in r or "MODE:" in r:
                    return True
        return False

    def quiet(self):
        """关闭 T-Halow-RJ45 / TX-AH 的 LMAC/WNB 周期调试刷屏。"""
        self.cmd("AT+SYSDBG=LMAC,0")
        self.cmd("AT+SYSDBG=WNB,0")
        if getattr(self, "variant", "sim") == "txah":
            self.cmd("AT+SYSDBG=UMAC,0")   # 泰芯真机还有 UMAC 刷屏

    def close(self):
        self.ser.close()


# ---------------------------------------------------------------------------
# SPI 传输（CH341A / CH347A，实验性）
# ---------------------------------------------------------------------------

# CH341A USB 协议常量（参考 flashrom ch341a_spi；极性若不符可翻转）
SPI_CMD_STREAM = 0xAA
SPI_CMD_CS     = 0xAB
SPI_CS_LOW     = 0x01   # assert (低有效) —— 若硬件反相改为 0x00
SPI_CS_HIGH    = 0x00   # deassert
SPI_EP_OUT     = 0x02
SPI_EP_IN      = 0x82
SPI_VID        = 0x1A86
SPI_PIDS       = [0x5512, 0x55DB, 0x55D4, 0x55DE]  # CH341A / CH347x

# 模拟器 SPI 帧协议
MAX_FRAME = 1700
CMD_AT = 0x01
CMD_GET_STATE = 0x02
CMD_DATA_TX = 0x03
CMD_DATA_RX = 0x04
CMD_EVENT = 0x05
CMD_PING = 0x06
CMD_RESET = 0x07
CMD_SET_CFG = 0x08
CMD_GET_CFG = 0x09
RESP_FLAG = 0x80


class SpiTransport:
    """CH341A/CH347A USB-SPI 适配器（实验性）。"""
    def __init__(self, pid=None):
        try:
            import usb.core
            import usb.util
        except ImportError:
            sys.exit("SPI 模式需要 pyusb：pip install pyusb")
        self.usb = usb.core
        self.dev = None
        for p in ([pid] if pid else SPI_PIDS):
            if p is None:
                continue
            d = usb.core.find(idVendor=SPI_VID, idProduct=p)
            if d is not None:
                self.dev = d
                break
        if self.dev is None:
            sys.exit("未找到 CH341A/CH347A（VID=0x1A86）；请插上并确认驱动为 libusb")
        try:
            self.dev.set_configuration()
        except Exception:
            pass

    def _wr(self, data):
        self.dev.write(SPI_EP_OUT, data, timeout=2000)

    def _rd(self, n):
        return bytes(self.dev.read(SPI_EP_IN, n, timeout=2000))

    def cs(self, level_low):
        self._wr(bytes([SPI_CMD_CS, SPI_CS_LOW if level_low else SPI_CS_HIGH]))

    def stream(self, data):
        self._wr(bytes([SPI_CMD_STREAM]) + data)
        return self._rd(len(data))

    def exchange(self, cmd, payload=b""):
        """单 CS 事务：先发请求帧，紧接着读回定长响应。"""
        hdr = bytes([cmd, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF,
                     crc8(bytes([cmd, (len(payload) >> 8) & 0xFF,
                                  len(payload) & 0xFF]) + payload)])
        req = hdr + payload
        resp_len = 4 + MAX_FRAME
        total = len(req) + resp_len
        self.cs(True)
        readback = self.stream(req + bytes([0xFF]) * resp_len)
        self.cs(False)
        if len(readback) < total:
            sys.exit("SPI 读回长度不足（%d < %d）" % (len(readback), total))
        resp = readback[len(req):len(req) + resp_len]
        return parse_resp(resp)

    def close(self):
        pass


def parse_resp(resp):
    if len(resp) < 4:
        return {"ok": False, "cmd": 0, "payload": b""}
    cmd = resp[0] & 0x7F
    ln = (resp[1] << 8) | resp[2]
    payload = resp[4:4 + ln]
    crc = crc8(bytes([resp[0] & 0x7F, resp[1], resp[2]]) + payload)
    ok = (crc == resp[3]) and (resp[0] & RESP_FLAG)
    return {"ok": ok, "cmd": cmd, "payload": payload}


# ---------------------------------------------------------------------------
# 命令实现（UART 与 SPI 共用）
# ---------------------------------------------------------------------------

def _at(t, line, wait=1.2):
    if isinstance(t, UartTransport):
        return t.cmd(line, wait)
    # SPI: 发 AT_CMD 帧
    r = t.exchange(CMD_AT, line.encode() + b"\r\n")
    if not r["ok"]:
        return "ERROR (crc)"
    return r["payload"].decode("utf-8", "replace")


def configure(t, role, args):
    if isinstance(t, UartTransport) and not t.resync():
        sys.exit("ERROR: 串口无 AT 响应（设备/波特率不对？）")
    v2 = getattr(t, "variant", "sim") == "txah"
    if v2:
        # 泰芯 V2.x：AT+WIFIMODE（小写） + AT+ENCRYPT/AT+KEY
        steps = [f"AT+WIFIMODE={role}", f"AT+SSID={args.ssid}"]
        if args.psk:
            if len(args.psk) < 8:
                sys.exit("ERROR: --psk 作为 KEY 需 ≥8 个 ASCII 字符")
            steps += ["AT+ENCRYPT=1", f"AT+KEY={args.psk}"]
        else:
            steps += ["AT+ENCRYPT=0"]
    else:
        steps = [f"AT+MODE={role}", f"AT+SSID={args.ssid}"]
        if args.psk:
            steps += ["AT+KEYMGMT=WPA-PSK", f"AT+PSK={args.psk}"]
        else:
            steps += ["AT+KEYMGMT=NONE"]
    steps += [f"AT+CHAN_LIST={args.freq}", f"AT+BSS_BW={args.bw}"]
    for s in steps:
        r = _at(t, s).strip().splitlines()
        ok = any("OK" in x for x in r)
        print(f"  {s:28s} -> {'OK' if ok else r}")
    print(f"\n已配置为 {role.upper()}。稍等几秒后用 status 查看连接。")


def status(t):
    if isinstance(t, UartTransport) and not t.resync():
        sys.exit("ERROR: 串口无 AT 响应")
    v2 = getattr(t, "variant", "sim") == "txah"
    if v2:
        qs = ["AT+VERSION", "AT+WIFIMODE=?", "AT+RSSI=?", "AT+SSID=?"]
        tail = "AT+SYSCFG"
    else:
        qs = ["AT+VERSION", "AT+MODE", "AT+CONN_STATE", "AT+RSSI"]
        tail = "AT+WNBCFG"
    for c in qs:
        print(f"{c:16s}: {_at(t, c).strip()}")
    print("\n" + _at(t, tail, 2.0).strip())


def do_at(t, line):
    print(_at(t, line).rstrip())


def do_reset(t):
    if isinstance(t, UartTransport) and not t.resync():
        sys.exit("ERROR: 串口无 AT 响应")
    print(_at(t, "AT+LOADDEF=1", 3.0).strip())
    print("已恢复出厂设置，模拟器重启。")


def do_ping(t):
    if isinstance(t, UartTransport):
        print("UART 模式无 PING 命令；用 'at AT' 测试。")
        return
    r = t.exchange(CMD_PING)
    print("PING ->", r)


def do_getstate(t):
    if isinstance(t, UartTransport):
        print("UART 模式无 GET_STATE；用 'status'。")
        return
    r = t.exchange(CMD_GET_STATE)
    if not r["ok"]:
        print("GET_STATE 失败"); return
    p = r["payload"]
    modes = {0: "AP", 1: "STA", 2: "APSTA", 3: "GROUP"}
    conns = {0: "IDLE", 1: "SCANNING", 2: "ASSOCIATING", 3: "CONNECTED",
             4: "DISCONNECTED"}
    if len(p) < 24:
        print("state 长度异常", len(p)); return
    mode, conn, sta_cnt, rssi, pairing, encrypt = p[0], p[1], p[2], p[3], p[4], p[5]
    mac = p[6:12]
    ssid = bytes(p[13:13 + p[12]]).decode("utf-8", "replace")
    print(f"mode={modes.get(mode, mode)} conn={conns.get(conn, conn)} "
          f"stacnt={sta_cnt} rssi={rssi} pairing={pairing} encrypt={encrypt}")
    print(f"mac={'%02x:%02x:%02x:%02x:%02x:%02x' % tuple(mac)} ssid={ssid}")


def list_ports():
    if not HAS_PYSERIAL:
        sys.exit("需要 pyserial：pip install pyserial")
    ports = list(list_ports.comports())
    if not ports:
        print("未检测到串口。")
        return
    print("检测到的串口：")
    for p in ports:
        print(f"  {p.device:<10s} {p.description}")
    print("\n模拟器的 CH340C 会显示为 USB-SERIAL。")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="TXW8301 模拟器配置工具")
    ap.add_argument("target", nargs="?", help="COM口(如 COM3) 或 'spi'（CH341A）或 'list'")
    ap.add_argument("action", nargs="?", choices=["ap", "sta", "status", "reset", "at", "list", "ping", "getstate"])
    ap.add_argument("--ssid", default="halowlink")
    ap.add_argument("--freq", default="9080")
    ap.add_argument("--bw", default="8", choices=["1", "2", "4", "8"])
    ap.add_argument("--open", action="store_true", help="无加密（默认）")
    ap.add_argument("--psk", metavar="KEY/HEX64", help="加密密钥：tj45/模拟器=WPA-PSK 64位hex；txah=KEY≥8个ASCII字符")
    ap.add_argument("--line", default="", help="at 动作要发送的命令")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None, help="CH341A PID（SPI）")
    ap.add_argument("--variant", default="sim", choices=["sim", "tj45", "txah", "hc01"],
                    help="sim=本模拟器；tj45=T-Halow-RJ45 真实板；txah=TX-AH 泰芯原厂模组（AH-SDK V2.x 方言）；"
                         "hc01=HT-HC01 真实板（后三者自动关闭调试刷屏；hc01 为占位）")
    args = ap.parse_args()

    if args.action == "list":
        list_ports()
        return

    if not args.target or not args.action:
        ap.print_help()
        return

    if args.target.lower() == "spi":
        t = SpiTransport(pid=args.pid)
        print("SPI 模式（CH341A，实验性）。\n")
    else:
        if not HAS_PYSERIAL:
            sys.exit("需要 pyserial：pip install pyserial")
        t = UartTransport(args.target)
        t.variant = args.variant
        if args.variant in ("tj45", "txah", "hc01"):
            label = {"tj45": "T-Halow-RJ45", "txah": "TX-AH(泰芯原厂,AH-SDK V2.x)",
                     "hc01": "HT-HC01(占位)"}[args.variant]
            print(f"目标{label}：关闭 LMAC/WNB 调试输出。")
            t.quiet()

    try:
        if args.action in ("ap", "sta"):
            configure(t, args.action, args)
        elif args.action == "status":
            status(t)
        elif args.action == "reset":
            do_reset(t)
        elif args.action == "at":
            if not args.line:
                sys.exit("at 动作需要 --line 'AT+XXX'")
            do_at(t, args.line)
        elif args.action == "ping":
            do_ping(t)
        elif args.action == "getstate":
            do_getstate(t)
    finally:
        t.close()


if __name__ == "__main__":
    main()
