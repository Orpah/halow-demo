#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_server.py — ORPAH-over-HaLow L1 demo Web UI（纯 PC，无硬件）
================================================================
一个进程内装好整条 L1 链路的可视化 demo：

    [Client 终端] --注入--> [STA 模块] ==HaLow 虚拟空口== [AP 模块]
        --host口--> [Router 桥] --真实UDP--> [Server]

- 内嵌 2 台 PC 模拟器（host/sim.py Core）：A=AP(Router 模块)、B=STA(Client 模块)
- 启动 OrpahServer（UDP 19447）+ RouterBridge + ClientHost（周期自动上报）
- 浏览器打开即看：三层拓扑 + ORPAH-REPORT 实时报文流 + 三端计数

运行：python ui_server.py [--port 8901] [--every 2] [--sn ORPAH-0001]
零第三方依赖（仅标准库）。启动后自动打开浏览器 http://127.0.0.1:8901/
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

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
HOST_DIR = os.path.join(HERE, "..", "host")
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)

import sim                                # noqa: E402
from server import OrpahServer            # noqa: E402
from router import RouterBridge           # noqa: E402
from client import ClientHost             # noqa: E402

# ---- 端口分配（默认，可 --port 改 HTTP；组件端口固定避免冲突） ----
HTTP_PORT = 8901
CONSOLE_A, LINK_A, HOST_A = 9401, 9411, 9421    # AP（Router 模块）
CONSOLE_B, LINK_B, HOST_B = 9402, 9412, 9422    # STA（Client 模块）
UDP_SRV = 19447

EVENTS = queue.Queue(maxsize=1000)   # SSE 事件（满丢最旧）


class OrpahApp:
    """装配整条 L1 链路 + 状态/计数（供 UI 轮询）。"""

    def __init__(self, every=2.0, sn="ORPAH-0001", rssi=-55):
        self.every = every
        self.sn = sn
        self.rssi = rssi
        self.paused = False
        self.stop = threading.Event()
        # 三端计数
        self.client_sent = 0
        self.router_up = 0
        self.server_recv = 0
        # 最近报文（按 seq 记，stage 点亮；最多 50 条）
        self.reports = {}
        self.order = []
        # 组件
        self.cores = []
        self.srv = None
        self.router = None
        self.client = None
        self.threads = []

    # ---------------- 事件（三端回调 → SSE） ----------------
    def _emit(self, stage, msg, **kw):
        ev = {"type": "report", "stage": stage, "msg": msg,
              "t": time.strftime("%H:%M:%S"), **kw}
        try:
            EVENTS.put_nowait(ev)
        except queue.Full:
            try:
                EVENTS.get_nowait()
            except queue.Empty:
                pass
            try:
                EVENTS.put_nowait(ev)
            except queue.Full:
                pass

    def _on_sent(self, msg, eth_len):
        self.client_sent += 1
        self._remember(msg, "client")
        self._emit("client", msg, eth_len=eth_len)

    def _on_up(self, msg):
        self.router_up += 1
        self._remember(msg, "router")
        self._emit("router", msg)

    def _on_report(self, msg):
        self.server_recv += 1
        self._remember(msg, "server")
        self._emit("server", msg)

    def _remember(self, msg, stage):
        seq = msg.get("seq")
        if seq is None:
            return
        if seq not in self.reports:
            self.reports[seq] = {"msg": msg, "seen": set()}
            self.order.append(seq)
            if len(self.order) > 50:
                old = self.order.pop(0)
                self.reports.pop(old, None)
        self.reports[seq]["seen"].add(stage)

    # ---------------- 装配 ----------------
    def start(self):
        # 1) 两台 PC 模拟器
        coreA = sim.Core("Router-AP", "AP", CONSOLE_A, LINK_A, None,
                         host_port=HOST_A)
        coreB = sim.Core("Client-STA", "STA", CONSOLE_B, LINK_B,
                         ("127.0.0.1", LINK_A), host_port=HOST_B)
        self.cores = [coreA, coreB]
        for c in self.cores:
            th = threading.Thread(target=self._loop, args=(c,), daemon=True)
            th.start()
            self.threads.append(th)

        # 2) Server（真实 UDP）
        self.srv = OrpahServer(port=UDP_SRV, on_report=self._on_report)
        self.srv.start()

        # 3) Router 桥（AP host 口 → UDP → Server）
        self.router = RouterBridge(ap_port=HOST_A, server_port=UDP_SRV,
                                   on_up=self._on_up)
        if not self.router.start():
            print("[ui] Router 连不上 AP host 口，退出")
            return False

        # 4) Client host（周期上报）
        self.client = ClientHost(sta_port=HOST_B, sn=self.sn or "ORPAH-0001",
                                 rssi=self.rssi, on_sent=self._on_sent)
        if not self.client.connect():
            print("[ui] Client 连不上 STA host 口，退出")
            return False

        # 5) 等 STA 关联 AP（关联前注入会被模块丢弃 → 先等连上再开始上报）
        for _ in range(100):
            if coreB.wifi.conn == sim.CONN_CONNECTED:
                break
            time.sleep(0.1)
        print(f"[ui] STA conn = {coreB.wifi.conn_str()}  链路就绪")

        # 6) 上报线程（自动持续）
        th = threading.Thread(target=self._report_loop, daemon=True)
        th.start()
        self.threads.append(th)
        return True

    def _loop(self, core):
        while not self.stop.is_set():
            core.wifi.poll()
            core.link.poll()
            time.sleep(0.005)

    def _report_loop(self):
        while not self.stop.is_set():
            if not self.paused:
                self.client.report_once()
            time.sleep(self.every)

    # ---------------- 控制（前端按钮） ----------------
    def status(self):
        conn_a = self.cores[0].wifi.conn_str() if self.cores else "-"
        conn_b = self.cores[1].wifi.conn_str() if len(self.cores) > 1 else "-"
        rows = []
        for seq in self.order:
            r = self.reports[seq]
            m = r["msg"]
            rows.append({
                "seq": seq, "sn": m.get("sn"), "ts": m.get("ts"),
                "rssi": m.get("rssi"), "client": "client" in r["seen"],
                "router": "router" in r["seen"], "server": "server" in r["seen"],
            })
        return {
            "client_sent": self.client_sent,
            "router_up": self.router_up,
            "server_recv": self.server_recv,
            "conn_a": conn_a, "conn_b": conn_b,
            "sn": self.client.sn if self.client else "-",
            "every": self.every, "paused": self.paused,
            "reports": list(reversed(rows)),
        }

    def cmd(self, action, sn=None, every=None):
        if action == "pause":
            self.paused = True
        elif action == "resume":
            self.paused = False
        elif action == "set_sn" and sn:
            if self.client:
                self.client.sn = sn
        elif action == "every" and every and every > 0:
            self.every = float(every)
        return {"ok": True}

    def stop_all(self):
        self.stop.set()
        if self.client:
            self.client.close()
        if self.router:
            self.router.stop()
        if self.srv:
            self.srv.stop()


APP = None


# ---------------------------------------------------------------------------
# HTTP / SSE
# ---------------------------------------------------------------------------
import http.server                                       # noqa: E402
import socketserver                                      # noqa: E402

STATIC_DIR = os.path.join(HERE, "ui", "static")


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
        global APP
        if self.path == "/api/status":
            self._send(200, json.dumps(APP.status()).encode())
            return
        if self.path == "/api/events":
            self._sse()
            return
        rel = self.path.lstrip("/")
        if "?" in rel:
            rel = rel.split("?", 1)[0]
        if rel == "":
            rel = "index.html"
        p = os.path.join(STATIC_DIR, rel)
        if not os.path.isfile(p):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {"html": "text/html", "js": "application/javascript",
                 "css": "text/css", "png": "image/png",
                 "svg": "image/svg+xml"}.get(p.rsplit(".", 1)[-1], "text/plain")
        with open(p, "rb") as f:
            self._send(200, f.read(), ctype,
                       headers={"Cache-Control": "no-store"})

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_hb = time.time()
        try:
            while not APP.stop.is_set():
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
            pass

    def do_POST(self):
        global APP
        if self.path != "/api/ctl":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "err": str(e)}).encode())
            return
        r = APP.cmd(req.get("action"), sn=req.get("sn"), every=req.get("every"))
        self._send(200, json.dumps(r).encode())


class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global APP
    ap = argparse.ArgumentParser(description="ORPAH-over-HaLow L1 demo Web UI")
    ap.add_argument("--port", type=int, default=HTTP_PORT)
    ap.add_argument("--every", type=float, default=2.0, help="自动上报间隔秒")
    ap.add_argument("--sn", default="ORPAH-0001", help="终端序列号/IMEI")
    ap.add_argument("--rssi", type=int, default=-55)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    APP = OrpahApp(every=args.every, sn=args.sn, rssi=args.rssi)
    if not APP.start():
        return 1

    httpd = Srv(("127.0.0.1", args.port), Handler)
    print(f"[ui] ORPAH L1 demo UI: http://127.0.0.1:{args.port}/  (Ctrl-C 退出)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(
            f"http://127.0.0.1:{args.port}/")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.stop_all()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
