#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — TXW8301 模拟器 Web UI 后端
======================================
本地 HTTP + SSE 服务，把 1~2 台设备（模拟器/真实板）的控制台桥接到浏览器。

每台设备可独立指定「来源 × 目标」，目标档案/协议族见 host/devprofiles.py：
  来源 source : pc（PC 版模拟器，进程内） / serial（真机串口）
  目标 target : sim（CH32V203）/ tj45（T-Halow-RJ45）/ txah（TX-AH）/ hc01（HT-HC01 占位）
  协议族 family：native（本模拟器）/ tah（泰芯 AH：tj45+txah）/ hc01（占位，暂复用 tah 方言，待手册）

设备规格 --a/--b（缺省目标用 --target）：
    pc            PC 版 CH32V203 模拟器
    pc:tj45       PC 版 T-Halow-RJ45 兼容模拟器
    pc:hc01       PC 版 HT-HC01 兼容模拟器（占位）
    COM3          CH32V203 真机（串口）
    COM3:tj45     T-Halow-RJ45 真机（串口，自动关调试刷屏）
    COM3:hc01     HT-HC01 真机（串口）

零第三方依赖（仅 pyserial，纯 PC 模拟器时也不需要）。启动后自动打开浏览器：
    python server.py                     # 自动识别 CH340 串口（真机）
    python server.py --host-sim          # 等价 --a pc --b pc（无硬件，推荐）
    python server.py --host-sim --target tj45            # 两台都扮演 T-Halow-RJ45
    python server.py --a pc --b pc:tj45                  # A=CH32V203虚拟, B=T-Halow虚拟
    python server.py --a COM3 --b COM4 --target tj45     # 两块真实 T-Halow-RJ45
    python server.py --list              # 列出串口
    python server.py --port 8899         # 自定义 HTTP 端口

> 互联域说明：只有「PC↔PC」能通过虚拟空口(TCP)互联；「真机↔真机」靠物理
> UART2(模拟器板) 或 RF(T-Halow-RJ45) 互联。PC 与真机之间无法自动建链，
> 但 UI 可同时管理任意组合。

界面：http://127.0.0.1:8899/
"""
import argparse
import json
import os
import queue
import socket
import sys
import threading
import time
import webbrowser
import http.server
import socketserver


def sys_exit(msg):
    import sys
    sys.exit(msg)


try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys_exit("需要 pyserial：pip install pyserial")

BAUD = 115200
HTTP_PORT = 8899
STATIC_DIR = "static"

# 设备档案 / 协议族注册表（单一事实来源），与 host/sim.py 共用
_HOST_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "host"))
if _HOST_DIR not in sys.path:
    sys.path.insert(0, _HOST_DIR)
import devprofiles as dp

# 全局事件队列：设备线程 -> SSE 推送（有界，防消费慢/断连时无限堆积）
EVENTS = queue.Queue(maxsize=2000)
STOP = threading.Event()

# 状态轮询命令
POLL_STATUS = ["AT+CONN_STATE", "AT+RSSI"]
POLL_SLOW = ["AT+MODE?", "AT+SSID?"]

# 默认目标（未在设备规格中指定时）：sim=本模拟器，tj45=T-Halow-RJ45 兼容/真实板
TARGET = "sim"


def norm_target(t, default):
    """别名归一为规范 target key，委托 host/devprofiles.py（sim/tj45/txah/hc01）。"""
    return dp.norm_target(t, default)


def parse_device_spec(spec, default_target="sim"):
    """解析单台设备描述 → (source, target, port) 或 None。
       支持：pc / pc:sim / pc:tj45 / pc:txah / pc:hc01 / COM3 / COM3:sim / ...
       source: pc=PC 版模拟器，serial=真机串口
       target: 规范 key（见 devprofiles）sim=CH32V203，tj45=T-Halow-RJ45，
               txah=TX-AH-MODULE，hc01=HT-HC01（占位）
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    low = spec.lower()
    target = default_target
    if low == "pc" or low.startswith("pc:"):
        port = None
        source = "pc"
        if ":" in spec:
            target = norm_target(spec.split(":", 1)[1], default_target)
        return (source, target, port)
    port = spec
    source = "serial"
    if ":" in spec:
        p, t = spec.split(":", 1)
        port = p.strip()
        target = norm_target(t, default_target)
    return (source, target, port)


def device_type(source, target):
    """设备类型中文标签：档案名（CH32V203/T-Halow-RJ45/TX-AH/HT-HC01）× 虚拟机/真机。"""
    loc = "虚拟机" if source == "pc" else "真机"
    return f"{dp.name(target)} {loc}"


def banner_sub(devices):
    """顶部标题副文字：按设备类型组合显示（虚拟/真机 × 档案名）。"""
    if not devices:
        return "CH32V203 · 无射频 · 虚拟空口"
    dtypes = [device_type(d.source, d.target) for d in devices.values()]
    if len(set(dtypes)) == 1:
        t = dtypes[0]
        if t == "CH32V203 虚拟机":
            return "CH32V203 · 无射频 · 虚拟空口"
        if t.endswith("虚拟机"):
            base = t[:-len("虚拟机")].rstrip()          # 如 T-Halow-RJ45 / HT-HC01
            return f"{base} 兼容 · 无射频 · 虚拟空口"
        return t                       # 真机
    # 混合来源/目标：逐台列出
    return " · ".join(f"{n}: {device_type(d.source, d.target)}"
                      for n, d in devices.items())


def find_ch340():
    """自动找出 WCH USB-UART 串口（CH340/CH341/CH343/CH9102，VID=0x1A86）。"""
    found = []
    for p in list_ports.comports():
        if p.vid == 0x1A86:      # WCH
            found.append(p.device)
        else:
            desc = (p.description or "").lower()
            if "ch340" in desc or "usb-serial" in desc:
                found.append(p.device)
    return found


# ---------------------------------------------------------------------------
# 传输层：串口 / TCP（PC 版模拟器）
# ---------------------------------------------------------------------------
class SerialTransport:
    def __init__(self, port):
        self.port = port
        self.ser = serial.Serial(port, BAUD, timeout=0.05, write_timeout=1.0)
        self.ser.reset_input_buffer()

    def send(self, line):
        self.ser.write((line + "\r\n").encode())

    def send_raw(self, data):
        self.ser.write(data)

    def read(self, maxbytes=4096):
        return self.ser.read(maxbytes)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class TcpTransport:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(0.05)

    def send(self, line):
        self.sock.sendall((line + "\r\n").encode())

    def send_raw(self, data):
        self.sock.sendall(data)

    def read(self, maxbytes=4096):
        try:
            return self.sock.recv(maxbytes)
        except socket.timeout:
            return b""
        except OSError:
            return None          # 已断开

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class HostSims:
    """管理一组进程内 PC 版模拟器实例，共享同一 stop 事件。
    target='tj45' 时以 T-Halow-RJ45 兼容模式响应（+MODE:AP 等）。"""

    def __init__(self):
        self.stop = threading.Event()
        self.cores = []
        self._sim = None

    def _hsim(self):
        if self._sim is None:
            if _HOST_DIR not in sys.path:      # 导入 devprofiles 时已加入
                sys.path.insert(0, _HOST_DIR)
            import sim as hsim
            self._sim = hsim
        return self._sim

    def add(self, name, role, console_port, link_port, peer_link, target,
            link_serial=None):
        hsim = self._hsim()
        core = hsim.Core(name, role, console_port, link_port, peer_link,
                         family=dp.family(target),   # 协议族由档案表决定（tah/hc01/native）
                         link_serial=link_serial)
        self.cores.append(core)

        def loop(c):
            while not self.stop.is_set():
                c.wifi.poll()
                c.link.poll()
                time.sleep(0.005)

        threading.Thread(target=loop, args=(core,), daemon=True).start()
        return core


class Device:
    """一台模拟器：传输层(串口/TCP) + 状态轮询 + 行分类推送。"""

    def __init__(self, name, transport, port, source="serial", target="sim",
                 link_desc=""):
        self.name = name
        self.transport = transport
        self.port = port               # 简短端口描述（TCP :9011 / 串口 COM5 / COM3）
        self.source = source            # pc / serial
        self.target = target            # sim / tj45
        self.link_desc = link_desc      # 空口描述
        self.label = f"{device_type(source, target)} · {port}"
        self.state = {
            "name": name, "port": port, "type": device_type(source, target),
            "ok": False, "conn": "OFFLINE",
            "mode": "", "ssid": "", "rssi": 0,
            "version": "", "tx": 0, "rx": 0, "uptime": 0,
        }
        self.t0 = time.time()
        self.buf = b""
        self.poll_paused_until = 0.0   # 数据模式（AT+TXDATA）期间暂停轮询的时间戳
        self._poll_until = 0.0         # 轮询响应窗口：窗口内到达的状态行不进控制台（避免刷屏）

    def send(self, line):
        try:
            self.transport.send(line)
            return True
        except Exception:
            return False

    def send_hex(self, hexstr):
        """HEX 串（可含空格）→ 原始字节，直接写入传输（数据模式/二进制帧，如广播 FF*6）。"""
        try:
            raw = bytes.fromhex(hexstr)
        except ValueError:
            return False
        if not hasattr(self.transport, "send_raw"):
            return False
        try:
            self.transport.send_raw(raw)
            return True
        except Exception:
            return False

    def push(self, etype, **kw):
        kw.update(type=etype, device=self.name)
        # 有界入队：满时丢弃最旧事件（界面永远显示最新，防内存爆）
        try:
            EVENTS.put_nowait(kw)
        except queue.Full:
            try:
                EVENTS.get_nowait()
            except queue.Empty:
                pass
            try:
                EVENTS.put_nowait(kw)
            except queue.Full:
                pass

    # ---------------- line handling ----------------
    def handle_line(self, raw):
        line = raw.strip()
        if not line:
            return
        # 帧监视：进帧监视器，同时显示到控制台（像真实串口：收发都在窗口）
        if line.startswith("FRAME:RX ") or line.startswith("FRAME:TX "):
            parts = line.split(" ", 1)          # ["FRAME:TX", "<hex>"]
            if len(parts) == 2:
                d = parts[0][6:]                # "TX" / "RX"
                if d == "TX":
                    self.state["tx"] += 1       # 顶部卡片 TX/RX 计数
                    cdir = "tx"                 # 控制台样式：自己发出的帧
                else:
                    self.state["rx"] += 1
                    cdir = "rx"                 # 控制台样式：收到的帧
                self.push("status", state=dict(self.state))
                self.push("frame", dir=d, hex=parts[1])
                self.push("console", text=line, dir=cdir)
            return
        # 状态：兼容 "KEY:value"（本模拟器）与 "+KEY:value"（T-Halow-RJ45）
        had_plus = line.startswith("+")
        probe = line[1:] if had_plus else line
        if ":" in probe:
            key, _, val = probe.partition(":")
            k = key.strip().upper()
            v = val.strip()
            if k == "CONN_STATE":
                self.state["conn"] = v
                self.state["ok"] = True
                self.state["uptime"] = int(time.time() - self.t0)
                self.push("status", state=dict(self.state))
                if time.time() >= self._poll_until:
                    self.push("console", text=line, dir="rx")
                return
            if k == "RSSI":
                try:
                    self.state["rssi"] = int(v)
                except ValueError:
                    pass
                self.push("status", state=dict(self.state))
                if time.time() >= self._poll_until:
                    self.push("console", text=line, dir="rx")
                return
            if k == "MODE":
                self.state["mode"] = v
                self.push("status", state=dict(self.state))
                if time.time() >= self._poll_until:
                    self.push("console", text=line, dir="rx")
                return
            if k == "SSID":
                self.state["ssid"] = v
                self.push("status", state=dict(self.state))
                if time.time() >= self._poll_until:
                    self.push("console", text=line, dir="rx")
                return
            if k == "VERSION":
                self.state["version"] = v
                self.push("status", state=dict(self.state))
                if time.time() >= self._poll_until:
                    self.push("console", text=line, dir="rx")
                return
        # 事件：+CONNECTED / +PAIR SUCCESS 等（无冒号或非状态键）
        if had_plus:
            self.push("event", text=line, dir="rx")
            return
        # 数据模式结束（TXDATA 帧完成）→ 恢复轮询
        if line in ("TX DATA OK", "TX DATA FAIL"):
            self.poll_paused_until = 0
        # 其它控制台输出（含 OK/ERROR）——均为接收
        self.push("console", text=line, dir="rx")

    # ---------------- threads ----------------
    def reader_loop(self):
        while not STOP.is_set():
            data = self.transport.read(4096)
            if data is None:
                break                     # 传输断开
            if not data:
                time.sleep(0.01)
                continue
            self.buf += data
            # 防无换行数据无限累积（二进制 flood）：超阈值只留尾部，给下一条换行机会
            if len(self.buf) > 65536:
                self.buf = self.buf[-4096:]
            # 按行拆分
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self.handle_line(line.decode("utf-8", "replace"))

    def poll_loop(self):
        last_slow = 0
        time.sleep(0.3)
        self.send("AT+SYSDBG=LMAC,0")
        self.send("AT+SYSDBG=WNB,0")
        # 泰芯 AH 族/占位族（tah/hc01）用裸 AT+VERSION 查询（AT+VERSION? 可能不被接受）；
        # 本模拟器(native)用 AT+VERSION?
        self.send("AT+VERSION" if dp.family(self.target) in (dp.FAMILY_TAH, dp.FAMILY_HC01)
                  else "AT+VERSION?")
        while not STOP.is_set():
            if time.time() < self.poll_paused_until:   # 数据模式中暂停轮询，避免污染 TXDATA 字节
                time.sleep(0.5)
                continue
            self._poll_until = time.time() + 1.5        # 进入轮询响应窗口（状态行不进控制台）
            for c in POLL_STATUS:
                self.send(c)
            now = time.time()
            if now - last_slow > 5:
                last_slow = now
                for c in POLL_SLOW:
                    self.send(c)
            time.sleep(2)

    def start(self):
        threading.Thread(target=self.reader_loop, daemon=True).start()
        threading.Thread(target=self.poll_loop, daemon=True).start()
        self.push("log", text=f"[{self.name}] 已连接 {self.label}")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/events":
            self.sse_loop()
            return
        if self.path == "/api/status":
            self._send(200, json.dumps(
                {d: DEVICES[d].state for d in DEVICES if DEVICES[d]}).encode())
            return
        if self.path == "/api/info":
            self._send(200, json.dumps({
                "target": TARGET,
                "sub": banner_sub(DEVICES),
                "devices": {
                    n: {"source": d.source, "target": d.target,
                        "type": device_type(d.source, d.target),
                        "link": d.link_desc}
                    for n, d in DEVICES.items()
                },
            }).encode())
            return
        # 静态文件
        rel = self.path.lstrip("/")
        if "?" in rel:                     # 支持版本号查询串（style.css?v=xxx）
            rel = rel.split("?", 1)[0]
        if rel == "":
            rel = "index.html"
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         STATIC_DIR, rel)
        if not os.path.isfile(p):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {"html": "text/html", "js": "application/javascript",
                 "css": "text/css", "png": "image/png", "svg": "image/svg+xml",
                 "ico": "image/x-icon"}.get(p.rsplit(".", 1)[-1], "text/plain")
        with open(p, "rb") as f:
            # no-store：静态文件不缓存，改样式/脚本刷新即生效（防浏览器旧缓存）
            self._send(200, f.read(), ctype,
                       headers={"Cache-Control": "no-store"})

    def sse_loop(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_hb = time.time()
        try:
            while not STOP.is_set():
                try:
                    item = EVENTS.get(timeout=1)
                except queue.Empty:
                    item = None
                if item is None:
                    if time.time() - last_hb > 15:
                        last_hb = time.time()
                        self.wfile.write(b": hb\n\n")
                        self.wfile.flush()
                    continue
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.flush()
        except OSError:
            pass   # 客户端断开（含 ConnectionAborted/Reset/BrokenPipe）

    def do_POST(self):
        if self.path != "/api/command":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "err": str(e)}).encode())
            return
        dev = DEVICES.get(req.get("device", "").upper())
        line = (req.get("line") or "").strip()
        if not dev or not line:
            self._send(400, json.dumps({"ok": False}).encode())
            return
        if req.get("hex"):
            ok = dev.send_hex(line)
            dev.push("console", text="> HEX: " + line, dir="tx")
        else:
            ok = dev.send(line)
            dev.push("console", text="> " + line, dir="tx")
            dev._poll_until = 0                       # 用户命令：响应立即显示控制台
            # 进入数据模式：暂停轮询，避免 AT+CONN_STATE 等字节污染 TXDATA
            if line.strip().upper().startswith("AT+TXDATA="):
                dev.poll_paused_until = time.time() + 30
        self._send(200, json.dumps({"ok": ok}).encode())


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description="TXW8301 模拟器 Web UI")
    ap.add_argument("--list", action="store_true", help="列出串口")
    ap.add_argument("--a", dest="spec_a",
                    help="设备A：pc | pc:sim | pc:tj45 | pc:txah | pc:hc01 | COM3 | COM3:sim | ...")
    ap.add_argument("--b", dest="spec_b",
                    help="设备B：同上（格式同 --a）")
    ap.add_argument("--a-link", dest="link_a",
                    help="设备A的空口串口（A 为 PC 模拟器时连真实板 UART2），如 COM5")
    ap.add_argument("--b-link", dest="link_b",
                    help="设备B的空口串口（B 为 PC 模拟器时连真实板 UART2），如 COM5")
    ap.add_argument("--host-sim", action="store_true",
                    help="等价于 --a pc --b pc（PC 版模拟器，无硬件）")
    ap.add_argument("--target", default="sim", choices=dp.ORDER,
                    help="未在设备规格中指定时的默认目标：" + "/".join(dp.ORDER)
                        + "（见 host/devprofiles.py）")
    ap.add_argument("--port", type=int, default=HTTP_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"  {p.device:<10s} {p.description}")
        return

    global DEVICES
    DEVICES = {}
    hosts = HostSims()

    # 确定 A/B 规格
    specs = [args.spec_a, args.spec_b]
    if not any(specs):
        if args.host_sim:
            specs = ["pc", "pc"]
        else:
            found = find_ch340()
            print("自动检测到 CH340 串口:", found or "无")
            specs = [found[0] if len(found) >= 1 else None,
                     found[1] if len(found) >= 2 else None]

    # PC 版模拟器的固定端口：A 控制台/空口 9001/9011，B 9002/9012
    PC_PORTS = {"A": (9001, 9011), "B": (9002, 9012)}

    for name, spec in zip(("A", "B"), specs):
        parsed = parse_device_spec(spec, args.target) if spec else None
        if not parsed:
            continue
        source, target, port = parsed
        role = "AP" if name == "A" else "STA"
        try:
            if source == "pc":
                console_p, link_p = PC_PORTS[name]
                # 该 PC 模拟器的空口：可用串口（--x-link，连真实板 UART2）或 TCP
                link_serial = (args.link_a if name == "A" else args.link_b)
                peer = None
                if not link_serial:
                    # 只有对端也是 PC 模拟器且本侧用 TCP 时，才做虚拟空口互联
                    other = DEVICES.get("A" if name == "B" else "B")
                    if other and getattr(other, "source", None) == "pc":
                        peer = ("127.0.0.1", PC_PORTS["A"][1])
                hosts.add(name, role, console_p, link_p, peer, target,
                          link_serial=link_serial)
                link_hint = f"串口 {link_serial}" if link_serial else f"TCP :{link_p}"
                dev = Device(name, TcpTransport("127.0.0.1", console_p), link_hint,
                             source="pc", target=target, link_desc=link_hint)
            else:
                dev = Device(name, SerialTransport(port), port,
                             source="serial", target=target,
                             link_desc="UART2 物理空口")
            DEVICES[name] = dev
        except Exception as e:
            print(f"[{name}] 初始化失败: {e}")

    if not DEVICES:
        sys_exit("没有可用设备。用 --a/--b、--host-sim，或 --list 查看。")

    for d in DEVICES.values():
        d.start()

    httpd = Server(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"TXW8301 模拟器 UI 已启动: {url}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        hosts.stop.set()          # 停掉所有进程内 PC 模拟器


if __name__ == "__main__":
    main()
