#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — TXW8301 模拟器 Web UI 后端
======================================
本地 HTTP + SSE 服务，把 1~2 台模拟器的控制台桥接到浏览器。
支持两种设备源：
  * 真实模拟器（串口，pyserial）：接 CH32V203 固件板
  * PC 版模拟器（--host-sim，无硬件）：进程内跑 host/sim.py 的 AP+STA 两台

零第三方依赖（仅 pyserial）。启动后自动打开浏览器：
    python server.py                     # 自动识别 CH340 串口
    python server.py --a COM3 --b COM4   # 指定 AP/STA 两个口
    python server.py --host-sim          # PC 版模拟器（无硬件，推荐先试这个）
    python server.py --list              # 列出串口
    python server.py --port 8899         # 自定义 HTTP 端口

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

# 全局事件队列：设备线程 -> SSE 推送
EVENTS = queue.Queue()
STOP = threading.Event()

# 状态轮询命令
POLL_STATUS = ["AT+CONN_STATE", "AT+RSSI"]
POLL_SLOW = ["AT+MODE?", "AT+SSID?"]


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


def start_host_sims(console_a=9001, console_b=9002, link_a=9011):
    """进程内启动 PC 版模拟器 A(AP) 与 B(STA)，返回 (DeviceA, DeviceB, stop)。"""
    host_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "host"))
    if host_dir not in sys.path:
        sys.path.insert(0, host_dir)
    import sim as hsim

    coreA = hsim.Core("A", "AP", console_a, link_a, None)
    coreB = hsim.Core("B", "STA", console_b, link_a + 1, ("127.0.0.1", link_a))
    stop = threading.Event()

    def loop(c):
        while not stop.is_set():
            c.wifi.poll()
            c.link.poll()
            time.sleep(0.005)

    threading.Thread(target=loop, args=(coreA,), daemon=True).start()
    threading.Thread(target=loop, args=(coreB,), daemon=True).start()

    dev_a = Device("A", TcpTransport("127.0.0.1", console_a), f"PC:A(:{console_a})")
    dev_b = Device("B", TcpTransport("127.0.0.1", console_b), f"PC:B(:{console_b})")
    return dev_a, dev_b, stop


class Device:
    """一台模拟器：传输层(串口/TCP) + 状态轮询 + 行分类推送。"""

    def __init__(self, name, transport, label):
        self.name = name
        self.transport = transport
        self.label = label
        self.state = {
            "name": name, "port": label, "ok": False, "conn": "OFFLINE",
            "mode": "", "ssid": "", "rssi": 0,
            "version": "", "tx": 0, "rx": 0, "uptime": 0,
        }
        self.t0 = time.time()
        self.buf = b""

    def send(self, line):
        try:
            self.transport.send(line)
            return True
        except Exception:
            return False

    def push(self, etype, **kw):
        kw.update(type=etype, device=self.name)
        EVENTS.put(kw)

    # ---------------- line handling ----------------
    def handle_line(self, raw):
        line = raw.strip()
        if not line:
            return
        # 事件
        if line.startswith("+"):
            self.push("event", text=line)
            return
        # 帧监视
        if line.startswith("FRAME:RX ") or line.startswith("FRAME:TX "):
            parts = line.split(" ", 1)          # ["FRAME:TX", "<hex>"]
            if len(parts) == 2:
                self.push("frame", dir=parts[0][6:], hex=parts[1])
            return
        # 状态：KEY:value
        if ":" in line:
            key, _, val = line.partition(":")
            k = key.strip().upper()
            v = val.strip()
            if k == "CONN_STATE":
                self.state["conn"] = v
                self.state["ok"] = True
                self.state["uptime"] = int(time.time() - self.t0)
                self.push("status", state=dict(self.state))
                return
            if k == "RSSI":
                try:
                    self.state["rssi"] = int(v)
                except ValueError:
                    pass
                self.push("status", state=dict(self.state))
                return
            if k == "MODE":
                self.state["mode"] = v
                self.push("status", state=dict(self.state))
                return
            if k == "SSID":
                self.state["ssid"] = v
                self.push("status", state=dict(self.state))
                return
            if k == "VERSION":
                self.state["version"] = v
                self.push("status", state=dict(self.state))
                return
        # 其它控制台输出（含 OK/ERROR）
        self.push("console", text=line)

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
            # 按行拆分
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self.handle_line(line.decode("utf-8", "replace"))

    def poll_loop(self):
        last_slow = 0
        time.sleep(0.3)
        self.send("AT+SYSDBG=LMAC,0")
        self.send("AT+SYSDBG=WNB,0")
        self.send("AT+VERSION?")
        while not STOP.is_set():
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

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
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
        # 静态文件
        rel = self.path.lstrip("/")
        if rel == "":
            rel = "index.html"
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         STATIC_DIR, rel)
        if not os.path.isfile(p):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {"html": "text/html", "js": "application/javascript",
                 "css": "text/css"}.get(p.rsplit(".", 1)[-1], "text/plain")
        with open(p, "rb") as f:
            self._send(200, f.read(), ctype)

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
        ok = dev.send(line)
        dev.push("console", text="> " + line)
        self._send(200, json.dumps({"ok": ok}).encode())


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser(description="TXW8301 模拟器 Web UI")
    ap.add_argument("--list", action="store_true", help="列出串口")
    ap.add_argument("--a", dest="port_a", help="设备A串口，如 COM3")
    ap.add_argument("--b", dest="port_b", help="设备B串口，如 COM4")
    ap.add_argument("--host-sim", action="store_true",
                    help="PC 版模拟器（无硬件，进程内跑 AP+STA）")
    ap.add_argument("--port", type=int, default=HTTP_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"  {p.device:<10s} {p.description}")
        return

    global DEVICES
    DEVICES = {}
    stop_host = None

    if args.host_sim:
        try:
            dev_a, dev_b, stop_host = start_host_sims()
            DEVICES = {"A": dev_a, "B": dev_b}
        except Exception as e:
            sys_exit(f"启动 PC 模拟器失败: {e}")
    else:
        ports = [args.port_a, args.port_b]
        if not any(ports):
            found = find_ch340()
            if len(found) >= 2:
                ports = found[:2]
            elif len(found) == 1:
                ports = [found[0], None]
            print("自动检测到 CH340 串口:", found or "无")
        for name, port in zip(("A", "B"), ports):
            if port:
                try:
                    DEVICES[name] = Device(name, SerialTransport(port), port)
                except Exception as e:
                    print(f"[{name}] 打开 {port} 失败: {e}")

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
        if stop_host:
            stop_host.set()


if __name__ == "__main__":
    main()
