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

运行：python ui_server.py [--port 8901] [--every 2] [--sn CN-WH01-9AF3C1D2]
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
from collections import deque

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
import orpah_id as oid                    # noqa: E402  Orpah ID 身份/真实性层
import registry as reg                    # noqa: E402  设备清册（SN↔走失者）
import cases                              # noqa: E402  走失案件闭环（以人为单位）

# ---- 端口分配（默认，可 --port 改 HTTP；组件端口固定避免冲突） ----
HTTP_PORT = 8901
CONSOLE_A, LINK_A, HOST_A = 9401, 9411, 9421    # AP（Router 模块）
CONSOLE_B, LINK_B, HOST_B = 9402, 9412, 9422    # STA（Client 模块）
UDP_SRV = 19447

EVENTS = queue.Queue(maxsize=1000)   # SSE 事件（满丢最旧）


class OrpahApp:
    """装配整条 L1 链路 + 状态/计数（供 UI 轮询）。"""

    def __init__(self, every=2.0, sn="CN-WH01-9AF3C1D2", rssi=-55):
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
        # L2 消息流日志（环形，dir=up/down；供前端面板展示）
        self.flow = []
        # Server 权威走失表快照（前端展示 + mark/untrack 控制）
        self.lost = {}
        # 服务器发布走失表记录（每次下发 LOST-TABLE 记一条，最新在前）
        self.publishes = []
        self.publish_total = 0             # 服务器发布走失表总次数（单调累加）
        # 发现记录（Router 命中走失表 → ORPAH-FOUND，最新在前）
        self.founds = []
        # Orpah ID 层演示：设备 + 密钥库 + nonce 缓存（设备按 Client SN 创建，懒初始化）
        self.id_ks = oid.KeyStore()
        self.id_dev = None
        self.id_used = oid.NonceCache()
        self.id_demo = {}
        self.id_reports = deque(maxlen=20)     # 环形（appendleft 自动截断，线程安全）
        self.id_report_total = 0
        self._last_id_report = None        # 最近一条已签上报（供“重放”演示）
        # 数字签名工具：临时密钥对（供 /api/sig 演示 ES256/HS256）
        self.sig_dev = None
        # 设备清册（P0：SN↔走失者一对多绑定、状态、首/最近见时间）
        self.registry = reg.Registry()
        # 走失案件闭环（P0：以人为单位的状态机）
        self.cases = cases.CaseManager()
        self._seed_registry()
        # 组件
        self.cores = []
        self.srv = None
        self.router = None
        self.client = None
        self.threads = []

    def _seed_registry(self):
        """演示种子：一个走失者绑多台客户端（项链/鞋），另一走失者一台已丢失。"""
        p1 = self.registry.add_person("小明", "演示：被保护对象（项链 + 鞋）")
        self.registry.register("CN-WH01-9AF3C1D2", person_id=p1, org="WH01", cc="CN")
        self.registry.register("CN-WH01-8K3M2P7Q", person_id=p1, org="WH01", cc="CN")
        p2 = self.registry.add_person("小红", "演示：走失中（手表）")
        self.registry.register("CN-WH02-5T9V1B4C", person_id=p2, org="WH02", cc="CN",
                               status=reg.STATUS_LOST)
        # 演示：小红已立案走失（open 案件）
        self.cases.mark(p2, self.registry)

    # ---------------- 消息流日志 ----------------
    def _push_flow(self, dirn, msg, stage=""):
        """记一条 L2 消息流日志（最多 200 条，新的在前）。"""
        ent = {
            "dir": dirn,                 # "up" 上行 / "down" 下行
            "stage": stage,              # client/router/server（可选）
            "type": msg.get("type", "?"),
            "sn": msg.get("sn", "-"),
            "status": msg.get("status", msg.get("code", msg.get("tracked", "-"))),
            "t": time.strftime("%H:%M:%S"),
        }
        self.flow.insert(0, ent)
        del self.flow[200:]

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
        """Client 注入上行（REQ-CONNECT / REPORT）。"""
        self.client_sent += 1
        self._remember(msg, "client")
        self._push_flow("up", msg, "client")
        self._emit("client", msg, eth_len=eth_len)

    def _on_recv(self, msg):
        """Client 收到下行（ACCESS-INFO / TRACKING-STATUS / ERROR）。"""
        self._push_flow("down", msg, "client")
        # 表无 seq，不点亮三列；发 SSE 供控制台类日志
        self._emit("log", msg, dir="rx")

    def _on_up(self, msg):
        """Router 上行转发（REPORT → Server）。"""
        self.router_up += 1
        self._remember(msg, "router")
        self._push_flow("up", msg, "router")
        self._emit("router", msg)

    def _on_down(self, msg):
        """Router 注入下行（回 Client：ACCESS-INFO/TRACKING-STATUS/ERROR）。"""
        self._push_flow("down", msg, "router")
        self._emit("log", msg, dir="tx")

    def _on_report(self, msg):
        """Server 收到 REPORT。"""
        self.server_recv += 1
        self._remember(msg, "server")
        self._push_flow("up", msg, "server")
        self._emit("server", msg)
        # 设备清册：更新最近见时间
        if msg.get("sn"):
            self.registry.touch(msg["sn"])

    def _on_lost(self, snap):
        """Server 走失表变更 → 存快照（前端展示）。"""
        self.lost = snap

    def _on_publish(self, entries, targets):
        """Server 发布/更新 LOST-TABLE（下发给 Router）→ 记发布记录（供前端展示）。"""
        self.publish_total += 1
        rec = {"t": time.strftime("%H:%M:%S"), "n": len(entries),
               "targets": targets, "entries": list(entries)}
        self.publishes.insert(0, rec)
        del self.publishes[20:]
        self._emit("publish", {"n": len(entries), "targets": targets})

    def _on_found_router(self, msg):
        """Router 发送 ORPAH-FOUND（发现走失）→ 消息流记 Router 段。"""
        self._push_flow("up", msg, "router")

    def _on_found_server(self, msg, addr):
        """Server 收到 ORPAH-FOUND → 消息流记 Server 段 + 发现记录列表 + 案件联动。"""
        self._push_flow("up", msg, "server")
        rec = {"t": time.strftime("%H:%M:%S"), "sn": msg.get("sn", "-")}
        self.founds.insert(0, rec)
        del self.founds[20:]
        self._emit("found", rec)
        # 走失案件：任一台设备被 Router 发现 → 该人案件进入「已发现」
        c = self.cases.on_found(msg.get("sn", "-"), self.registry,
                                detail=f"router {addr[0]}:{addr[1]}")
        if c is not None:
            self._emit("case", {"case_id": c.case_id, "status": c.status,
                                "sn": msg.get("sn", "-")})

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

        # 2) Server（真实 UDP，权威走失库）
        self.srv = OrpahServer(port=UDP_SRV, on_report=self._on_report,
                               on_lost=self._on_lost, on_push=self._on_publish,
                               on_found=self._on_found_server,
                               keystore=self.id_ks, id_nonces=self.id_used,
                               on_id_report=self._on_id_report)
        self.srv.start()

        # 2.5) 已立案案件名下设备同步进权威走失表（种子案件等）
        for c in self.cases.cases.values():
            if c.status in (cases.CASE_OPEN, cases.CASE_FOUND):
                for d in self.registry.devices_of(c.person_id):
                    self.srv.mark_tracked(d.sn, note=f"case:{c.case_id}")

        # 3) Router 桥（AP host 口 ⇄ UDP ⇄ Server；双向）
        self.router = RouterBridge(ap_port=HOST_A, server_port=UDP_SRV,
                                   on_up=self._on_up, on_down=self._on_down,
                                   on_found=self._on_found_router)
        if not self.router.start():
            print("[ui] Router 连不上 AP host 口，退出")
            return False

        # 4) Client host（双向会话：注入上行 + 收下行）
        self.client = ClientHost(sta_port=HOST_B, sn=self.sn or "CN-WH01-9AF3C1D2",
                                 rssi=self.rssi, on_sent=self._on_sent,
                                 on_recv=self._on_recv)
        if not self.client.connect():
            print("[ui] Client 连不上 STA host 口，退出")
            return False

        # 5) 等 STA 关联 AP（关联前注入会被模块丢弃 → 先等连上再开始上报）
        for _ in range(100):
            if coreB.wifi.conn == sim.CONN_CONNECTED:
                break
            time.sleep(0.1)
        print(f"[ui] STA conn = {coreB.wifi.conn_str()}  链路就绪")

        # 6) 会话线程（L2：REQ-CONNECT → REPORT 自动周期）
        th = threading.Thread(target=self._report_loop, daemon=True)
        th.start()
        self.threads.append(th)
        self._id_tick()          # 立即填充一次，不必等首个周期
        return True

    def _loop(self, core):
        while not self.stop.is_set():
            core.wifi.poll()
            core.link.poll()
            time.sleep(0.005)

    def _report_loop(self):
        while not self.stop.is_set():
            if not self.paused:
                self.client.send_req_connect()
                time.sleep(0.25)
                self.client.report_once()
                self._id_tick()
            time.sleep(self.every)

    def _ensure_id_device(self):
        """让 Orpah ID 演示设备与当前 Client SN 一致（SN 变更时重建+重注册）。"""
        sn = self.client.sn if self.client else self.sn
        if self.id_dev is not None and self.id_dev.sn == sn:
            return
        self.id_dev = oid.Device(sn=sn, se_sn="ATECC608B-DEMO")
        self.id_ks.register(self.id_dev, model="CH32V203+TX-AH+ATECC608B",
                            firmware="1.0.3")

    def _id_tick(self):
        """周期生成真实签名的 orpah-id-report 并经既有链路上行（Server 验签）。"""
        try:
            self._send_id_report()
        except Exception as e:  # 无 cryptography 时退化为错误展示
            self.id_demo = {"t": time.strftime("%H:%M:%S"), "err": str(e)}

    def _send_id_report(self, ts=None):
        """生成一条已签 orpah-id-report 并注入上行；ts 可指定（演示超窗）。"""
        self._ensure_id_device()
        r = self.id_dev.report(
            level=0, ts=ts,
            seen_routers=[{"bssid": "AA:BB:CC:DD:EE:FF",
                           "ssid": "ORPAHID_ZONE_A", "rssi": -42}],
            battery_mv=3700, firmware="1.0.3")
        self._last_id_report = r
        self.client.send_id_report(r)
        return r

    def _on_id_report(self, rec):
        """Server 验签结果回调：更新卡片 + 签名上报流（带 trust）。"""
        self.id_demo = {
            "t": rec["t"], "sn": rec["sn"], "alg": rec["alg"],
            "level": rec["level"], "trust": rec["trust"],
            "accepted": rec["accepted"], "sig": rec.get("sig", ""),
            "nonce": rec.get("nonce", ""), "error": rec.get("error"),
        }
        self.id_report_total += 1
        self.id_reports.appendleft(rec)
        self._emit("id_report", rec)
        if rec.get("sn"):
            self.registry.touch(rec["sn"])

    # ---------------- 控制（前端按钮） ----------------
    def status(self):
        conn_a = self.cores[0].wifi.conn_str() if self.cores else "-"
        conn_b = self.cores[1].wifi.conn_str() if len(self.cores) > 1 else "-"
        # 模块空口数据帧计数：wifi.tx_pkts/rx_pkts 只计 DATA 帧（不含 beacon/关联帧），
        # 反映真实数据面。coreA=AP(Router 侧)、coreB=STA(Client 侧)；单向上行 → STA 发/
        # AP 收增长，反向恒 0（真实）。
        tx_ap = self.cores[0].wifi.tx_pkts if self.cores else 0
        rx_ap = self.cores[0].wifi.rx_pkts if self.cores else 0
        tx_sta = self.cores[1].wifi.tx_pkts if len(self.cores) > 1 else 0
        rx_sta = self.cores[1].wifi.rx_pkts if len(self.cores) > 1 else 0
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
            "tx_sta": tx_sta, "rx_sta": rx_sta,
            "tx_ap": tx_ap, "rx_ap": rx_ap,
            "conn_a": conn_a, "conn_b": conn_b,
            "sn": self.client.sn if self.client else "-",
            "router_lost_recv": self.router.lost_push_recv if self.router else 0,
            "every": self.every, "paused": self.paused,
            "reports": list(reversed(rows)),
            "flow": list(self.flow),
            "lost": self.lost,
            "publishes": list(self.publishes),
            "publish_total": self.publish_total,
            "founds": list(self.founds),
            "found_total": self.router.found_count if self.router else 0,
            "found_recv": self.srv.found_count if self.srv else 0,
            "id_demo": self.id_demo,
            "id_reports": list(self.id_reports),
            "id_report_total": self.id_report_total,
            "id_revoked": (self.id_ks.is_revoked(self.client.sn)
                           if self.client else False),
        }

    def cmd(self, action, sn=None, every=None, note=""):
        if action == "pause":
            self.paused = True
        elif action == "resume":
            self.paused = False
        elif action == "set_sn" and sn:
            if self.client:
                self.client.sn = sn
        elif action == "every" and every and every > 0:
            self.every = float(every)
        elif action == "mark" and sn and self.srv:
            self.srv.mark_tracked(sn, note=note or "ui")
        elif action == "untrack" and sn and self.srv:
            self.srv.untrack(sn)
        elif action == "revoke" and self.client:
            self.id_ks.revoke(self.client.sn)
        elif action == "unrevoke" and self.client:
            self.id_ks.unrevoke(self.client.sn)
        elif action == "replay" and self._last_id_report:
            self.client.send_id_report(self._last_id_report)
        elif action == "stale":
            self._send_id_report(ts=int(time.time()) - 3600)
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
# ui_i18n.js 单一源在 halow-demo 主 UI（simulator/tools/ui/static），这里只读不复制
TOOLS_STATIC_DIR = os.path.join(HERE, "..", "tools", "ui", "static")


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
        if self.path == "/api/registry":
            self._send(200, json.dumps(APP.registry.to_dict()).encode())
            return
        if self.path == "/api/cases":
            self._send(200, json.dumps(APP.cases.to_dict(APP.registry)).encode())
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
            # ui_i18n.js 是单一源共享字典，放在 halow-demo 主 UI（tools/ui/static）：
            # 两个 UI 引用同一文件，改一处两边生效（避免复制两份不同步）。
            if rel == "ui_i18n.js":
                p = os.path.join(TOOLS_STATIC_DIR, "ui_i18n.js")
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

    def _api_registry(self):
        """设备清册增删改：add_person / add_device / remove_device /
        update_person / remove_person / set_status / set_status_many。"""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "err": str(e)}).encode())
            return
        action = req.get("action")
        try:
            if action == "add_person":
                pid = APP.registry.add_person(req.get("name", ""), req.get("note", ""))
                self._send(200, json.dumps({"ok": True, "pid": pid}).encode())
            elif action == "add_device":
                APP.registry.register(req.get("sn", ""),
                                      person_id=req.get("person_id") or None,
                                      org=req.get("org"), cc=req.get("cc"))
                self._send(200, json.dumps({"ok": True}).encode())
            elif action == "remove_device":
                APP.registry.remove_device(req.get("sn", ""))
                self._send(200, json.dumps({"ok": True}).encode())
            elif action == "update_person":
                APP.registry.update_person(req.get("pid", ""),
                                           req.get("name"), req.get("note"))
                self._send(200, json.dumps({"ok": True}).encode())
            elif action == "remove_person":
                pid = req.get("pid", "")
                if APP.cases.active_case(pid) is not None:
                    self._send(200, json.dumps({"ok": False,
                        "err": "该走失者有未结案件，请先在「走失案件」页结案"}).encode())
                else:
                    APP.registry.remove_person(pid)
                    self._send(200, json.dumps({"ok": True}).encode())
            elif action == "set_status":
                APP.registry.set_status(req.get("sn", ""), req.get("status", ""))
                self._send(200, json.dumps({"ok": True}).encode())
            elif action == "set_status_many":
                APP.registry.set_statuses(req.get("sns", []), req.get("status", ""))
                self._send(200, json.dumps({"ok": True}).encode())
            else:
                self._send(200, json.dumps({"ok": False,
                                            "err": f"unknown action: {action}"}).encode())
        except Exception as e:
            self._send(200, json.dumps({"ok": False, "err": str(e)}).encode())

    def _api_cases(self):
        """走失案件：mark 立案 / close 结案（找回或撤销）。"""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "err": str(e)}).encode())
            return
        action = req.get("action")
        try:
            if action == "mark":
                c, sns, dup = APP.cases.mark(req.get("person_id", ""), APP.registry)
                if c is None:
                    self._send(200, json.dumps({"ok": False,
                                                "err": "该走失者名下无设备"}).encode())
                else:
                    if not dup:
                        for sn in sns:
                            if APP.srv:
                                APP.srv.mark_tracked(sn, note=f"case:{c.case_id}")
                    self._send(200, json.dumps({"ok": True, "dup": dup,
                                                "case_id": c.case_id}).encode())
            elif action == "close":
                c, sns = APP.cases.close(req.get("case_id", ""), APP.registry,
                                         req.get("outcome", ""))
                if c is None:
                    self._send(200, json.dumps({"ok": False,
                                                "err": "案件不存在"}).encode())
                else:
                    for sn in sns:
                        if APP.srv:
                            APP.srv.untrack(sn)
                    self._send(200, json.dumps({"ok": True}).encode())
            else:
                self._send(200, json.dumps({"ok": False,
                                            "err": f"unknown action: {action}"}).encode())
        except Exception as e:
            self._send(200, json.dumps({"ok": False, "err": str(e)}).encode())

    def _api_sig(self):
        """数字签名工具：newkey 生成临时密钥对；sign 算预像+签名；verify 验签。"""
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "err": str(e)}).encode())
            return
        action = req.get("action")
        if action == "newkey":
            APP.sig_dev = oid.Device(cc="CN", org="WH01", check="mod97")
            dev = APP.sig_dev
            self._send(200, json.dumps({
                "ok": True,
                "sn": dev.sn,
                "pubkey_pem": oid.pubkey_to_pem(dev.pubkey) if dev.pubkey else None,
                "hmac_hex": dev.hmac_key.hex(),
            }).encode())
            return
        dev = APP.sig_dev
        if dev is None:
            self._send(200, json.dumps({"ok": False, "err": "请先生成密钥"}).encode())
            return
        if action in ("sign", "verify"):
            alg = req.get("alg", "ES256")
            hdr, payload = req.get("hdr"), req.get("payload")
            if not isinstance(hdr, dict) or not isinstance(payload, dict):
                self._send(200, json.dumps({"ok": False,
                                            "err": "hdr/payload 必须是 JSON 对象"}).encode())
                return
            preimage = oid.preimage_of({"hdr": hdr, "payload": payload})
            if action == "sign":
                sig = oid.sign_preimage(alg, preimage, dev)
                self._send(200, json.dumps({
                    "ok": True,
                    "preimage": preimage.decode("utf-8"),
                    "sig": oid.b64url_encode(sig) if sig is not None else None,
                }).encode())
                return
            sig = req.get("sig")
            if alg == "ES256":
                ok = bool(sig) and dev.pubkey is not None and oid._verify_es256(dev.pubkey, preimage, sig)
            elif alg == "HS256":
                ok = bool(sig) and oid._verify_hs256(dev.hmac_key, preimage, sig)
            elif alg == "none":
                ok = sig is None
            else:
                ok = False
            self._send(200, json.dumps({"ok": True, "verified": ok}).encode())
            return
        self._send(200, json.dumps({"ok": False, "err": f"unknown action: {action}"}).encode())

    def do_POST(self):
        global APP
        if self.path == "/api/registry":
            self._api_registry()
            return
        if self.path == "/api/cases":
            self._api_cases()
            return
        if self.path == "/api/sig":
            self._api_sig()
            return
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
    ap.add_argument("--sn", default="CN-WH01-9AF3C1D2",
                    help="终端序列号（Orpah ID：CC-ORG-UNIQUE[-CHECK]）")
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
