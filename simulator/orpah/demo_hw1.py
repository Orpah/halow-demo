#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_hw1.py — 阶段二「真机自检」：把上机验证清单变成可执行步骤
================================================================================
⚠ **本脚本未经真机验证**（写它的时候手上没有板子）。它的价值是：
  ① 上机时把「哪些事必须确认」一条条打出来，不用对着文档手工核对；
  ② 能自动判的（固件代次/角色/关联/跨空口通路）自动判并给结论；
  ③ 不能自动判的（例如「自定义 ethertype 0x88B5 是否透传」）给出确切的测法与判据。

**不预设数据通路**（用户 2026-09-12 定）：只提供三种探测手段，哪条通就走哪条 ——
  · 读板卡状态（复用 tools UI 的 AT 逻辑，**不重复实现 AT/方言**）
  · 跨空口 UDP 通路探测（走 RJ45 透明桥；对端跑 `orpah/server.py`）
  · raw L2 探测（自定义 ethertype 0x88B5 是否透传；需 scapy + Npcap + 管理员）

运行（详细步骤见 docs/real-hw-stage2.md）：
  python demo_hw1.py                          # 环境 + 两块板状态自检（需 tools UI 在跑）
  python demo_hw1.py --peer 192.168.4.20      # 跨空口 UDP 探测（对端跑 orpah/server.py）
  python demo_hw1.py --listen                 # 当对端：收并打印 ORPAH 报文（Ctrl+C 退出）
  python demo_hw1.py --raw-send --iface 以太网  # 发 0x88B5 帧（对端跑 --raw-sniff）
  python demo_hw1.py --raw-sniff --iface 以太网 # 嗅探 0x88B5 帧

为什么读板卡走 tools UI 的 HTTP 而不是直接开串口：AT 方言探测（V1.6 vs V2.4）、逐条错开轮询、
LMAC/UMAC 块抑制这些坑都已经在 `tools/ui/server.py` 里踩过并修好了 —— 再抄一份必然漂移。
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ORPAH_DIR = os.path.dirname(os.path.abspath(__file__))
if ORPAH_DIR not in sys.path:
    sys.path.insert(0, ORPAH_DIR)

from orpah_proto import (MSG_ERROR, MSG_FOUND, MSG_LOST_TABLE,      # noqa: E402
                         MSG_REQ_CONNECT, MSG_REPORT, MSG_TRACKING_STATUS,
                         ORPAH_ETHERTYPE, build_eth_frame, build_report,
                         decode_msg, encode_msg)

TOOLS_UI = os.environ.get("ORPAH_TOOLS_UI", "http://127.0.0.1:8899")
SRV_PORT = 19447                      # Server UDP 端口（SPEC §6）
TEST_SN = "CN-WH01-9AF3C1D2"
OK, BAD, WARN, INFO = "[OK]", "[!!]", "[??]", "[--]"


def http_json(url, payload=None, timeout=4.0):
    """GET/POST JSON（只用标准库；tools UI 是自己人，不需要 requests）。"""
    try:
        if payload is None:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def local_ipv4():
    """本机 IPv4 列表（用 UDP connect 探默认出口 + 主机名解析，避免引入 psutil）。"""
    ips = set()
    for probe in ("8.8.8.8", "192.168.1.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ips.add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def parse_build(version):
    """固件版本串 → (代次 major.minor, 族)：族由版本第 4 段首位判定（3=WNB / 5=FMAC）。

    例：v2.4.1.3-40938 → 代次 2.4、族 WNB；v2.4.1.5-39777 → 代次 2.4、族 FMAC。
    这个「第 4 位」是本项目踩过的坑（WB 与 FMAC 刷错会 assert 重启），见 docs/real-hw-stage2.md。
    """
    v = (version or "").strip().lstrip("vV")
    if not v:
        return None, "?"
    num = v.split("-")[0].split(".")
    gen = ".".join(num[:2]) if len(num) >= 2 else v
    fam = "?"
    if len(num) >= 4 and num[3][:1] in ("3", "5"):
        fam = "WNB" if num[3][0] == "3" else "FMAC"
    return gen, fam


# ---------------------------------------------------------------------------
# 1) 环境自检
# ---------------------------------------------------------------------------
def check_env():
    print("=" * 78)
    print("1) 环境")
    print("-" * 78)
    print(f"  Python            : {sys.version.split()[0]}  ({sys.executable})")
    ips = local_ipv4()
    print(f"  本机 IPv4         : {', '.join(ips) if ips else '(只找到回环地址)'}")
    print("                      ↑ 其中应有一个是「接板子 RJ45 那一侧」的网段；两 PC 需同网段")
    scapy = None
    try:
        import scapy  # noqa: F401
        scapy = getattr(scapy, "__version__", "?")
    except Exception:
        pass
    if scapy:
        print(f"  scapy             : {scapy}  （raw L2 探测可用；还需 Npcap + 管理员权限）")
    else:
        print(f"  scapy             : 未安装 → 跳过 raw L2 探测（要测自定义 ethertype 透传就需装：")
        print("                      pip install scapy + 安装 Npcap，并以管理员运行）")
    info = http_json(f"{TOOLS_UI}/api/info")
    if info is None:
        print(f"{WARN} tools UI ({TOOLS_UI}) 不可达 → 读不到板卡状态。")
        print("      先启动它（VS Code 任务 sim-server-host-<型号>，或 python tools/ui/server.py），")
        print("      并在页面上把两块板子的串口连上（真机用 tj45/txah 档案，会自动探测固件代次）。")
    else:
        print(f"{OK} tools UI 可达：target={info.get('target')} devices={list((info.get('devices') or {}).keys())}")
    return info


# ---------------------------------------------------------------------------
# 2) 读板卡状态 + 硬规则判定
# ---------------------------------------------------------------------------
def check_boards(info):
    print()
    print("=" * 78)
    print("2) 两块板子（AT 状态由 tools UI 轮询维护）")
    print("-" * 78)
    if not info:
        print(f"{WARN} 跳过（tools UI 不可达）")
        return {}
    st = http_json(f"{TOOLS_UI}/api/status") or {}
    devs = info.get("devices") or {}
    rows = {}
    for k in sorted(devs.keys()):
        d, s = devs.get(k) or {}, st.get(k) or {}
        gen, fam = parse_build(s.get("version"))
        rows[k] = {"gen": gen, "fam": fam, "ver": s.get("version"),
                   "conn": s.get("conn"), "rssi": s.get("rssi"),
                   "mode": s.get("mode"), "ssid": s.get("ssid"),
                   "chan": s.get("chan"), "bw": s.get("bw"),
                   "source": d.get("source"), "link": d.get("link"),
                   "v2": d.get("v2"), "power": s.get("power")}
        print(f"  {k}: {d.get('type')} · {d.get('link')}")
        print(f"     固件 {s.get('version') or '(未知)'}  代次 {gen or '?'}  族 {fam}"
              f"  方言 {'V2(AH-SDK)' if d.get('v2') else 'V1.6/T-Halow'}")
        print(f"     电源 {s.get('power')}  连接 {s.get('conn')}  RSSI {s.get('rssi')}"
              f"  角色 {s.get('mode')}  SSID {s.get('ssid')}  信道 {s.get('chan')}  bw {s.get('bw')}")

    print()
    print("  硬规则核对：")
    ks = sorted(rows.keys())
    gens = {k: rows[k]["gen"] for k in ks}
    vs = [g for g in gens.values() if g]
    if len(vs) >= 2 and len(set(vs)) > 1:
        print(f"{BAD} 两块板**代次不同**（{gens}）→ 结论：**一定连不上**（同代才互通）。")
        print("      请把两块都升到同一代（推荐 V2.4）：TH-RJ45 刷 WNB、TX-AH 载体刷 FMAC。")
    elif len(vs) >= 2:
        print(f"{OK} 代次一致（{vs[0]}）→ 满足互通前提（同代必通，跨代必不通）。")
    else:
        print(f"{WARN} 代次读不全（{gens}）→ 等两板都上线后再看；页面上 AT+VERSION 可手动查。")

    fams = {k: rows[k]["fam"] for k in ks}
    for k, f in fams.items():
        if f == "WNB":
            print(f"{INFO} {k} = WNB 固件 → **必须带 RJ45 以太网 PHY 的载板**（TH-RJ45 那种）。")
            print("      无 PHY 的裸 TX-AH 载板刷 WNB 会 `hg_gmac_open` assert → 反复重启。")
        elif f == "FMAC":
            print(f"{INFO} {k} = FMAC 固件 → **无 AT 数据面**：payload 只能走 host SPI（需 MCU）。")
    roles = {rows[k].get("mode") for k in ks if rows[k].get("mode")}
    if len(roles) >= 2:
        print(f"{INFO} 角色={roles}（应一个 AP 一个 STA；同一网络 SSID/信道/带宽必须完全一致）")
    conn = [rows[k].get("conn") for k in ks]
    if all(c == "CONNECTED" for c in conn) and len(conn) >= 2:
        print(f"{OK} 两端都 CONNECTED → 空口链路已建立，可以测数据通路（第 3/4 组清单）。")
    elif len(conn) >= 2:
        print(f"{WARN} 连接状态 {conn} → 未双向连接：先查 SSID/信道/带宽/加密是否一致，"
              "再看是不是跨代（见上）。")
    return rows


# ---------------------------------------------------------------------------
# 3) 跨空口 UDP 通路探测（RJ45 透明桥路线）
# ---------------------------------------------------------------------------
def probe_udp(peer, port, sn, wait=4.0):
    print()
    print("=" * 78)
    print(f"3) 跨空口 UDP 通路探测 → {peer}:{port}")
    print("-" * 78)
    print("  原理：本机发一条真实 ORPAH-REPORT 到对端 Server。收到**任何** ORPAH 应答（哪怕")
    print("        是 ERROR）都说明「空口 + 桥 + IP」这条路通了；没有应答则说明不通（不是业务问题）。")
    msg = build_report(sn, rssi=-55, seq=1, extra={"hw_probe": "demo_hw1"})
    payload = encode_msg(msg)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(wait)
    try:
        s.sendto(payload, (peer, port))
        print(f"{INFO} 已发出 {len(payload)} B：{payload.decode('utf-8')}")
    except OSError as e:
        print(f"{BAD} 发送失败：{e}（先确认网线/IP 网段/防火墙）")
        s.close()
        return False
    t0 = time.time()
    try:
        data, addr = s.recvfrom(4096)
    except socket.timeout:
        print(f"{BAD} {wait:.0f}s 内没有应答。排查顺序（对应手册第 3 组清单）：")
        print("      ① 两 PC 是否在同一网段（各自 RJ45 侧拿到的 IP）")
        print("      ② `ping <对端>` 是否通（不通 = 空口/桥未通，先回第 2 组）")
        print("      ③ 对端是否真的跑了 orpah/server.py（缺它没人应答）")
        print("      ④ 对端防火墙是否放行 UDP 19447")
        s.close()
        return False
    rtt = (time.time() - t0) * 1000
    rep = decode_msg(data)
    kind = rep.get("type") if rep else "(非 ORPAH JSON)"
    print(f"{OK} 收到应答 {len(data)} B，来自 {addr[0]}:{addr[1]}，RTT≈{rtt:.0f} ms")
    print(f"     应答类型：{kind}  {json.dumps(rep, ensure_ascii=False) if rep else data[:80]!r}")
    if kind == MSG_TRACKING_STATUS:
        print(f"{OK} 业务侧也通了：Server 返回跟踪状态（status={rep.get('status')}）")
    elif kind == MSG_ERROR:
        print(f"{OK} 通路通；业务侧按规则拒绝（code={rep.get('code')}）—— 这是**预期**行为之一，"
              "不是失败（例如 SN 不在库 / 验签不过）。")
    s.close()
    return True


def do_listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    print(f"监听 UDP :{port}（Ctrl+C 退出）—— 任何到达的 ORPAH 报文都会打印。")
    try:
        while True:
            data, addr = s.recvfrom(4096)
            rep = decode_msg(data)
            t = time.strftime("%H:%M:%S")
            if rep:
                print(f"  [{t}] {addr[0]}:{addr[1]}  {rep.get('type')}  "
                      f"sn={rep.get('sn')}  ts={rep.get('ts')}  {len(data)}B")
            else:
                print(f"  [{t}] {addr[0]}:{addr[1]}  非 ORPAH 报文 {len(data)}B: {data[:60]!r}")
    except KeyboardInterrupt:
        print("\n停止监听。")
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 4) raw L2 探测：自定义 ethertype 0x88B5 是否透传（需对端配合）
# ---------------------------------------------------------------------------
def _scapy():
    try:
        from scapy.all import Ether, sendp, sniff  # noqa: F401
        return True
    except Exception as e:
        print(f"{BAD} scapy 不可用：{e}")
        print("      → 需要 `pip install scapy` + 安装 Npcap，并用**管理员**运行本脚本。")
        return False


def raw_send(iface, sn, count=5):
    print()
    print("=" * 78)
    print(f"4) raw L2 发送（iface={iface}，0x88B5 × {count}）")
    print("-" * 78)
    if not _scapy():
        return
    from scapy.all import Ether, sendp
    marker = f"ORPAH-HW-PROBE-{int(time.time())}"
    payload = encode_msg(build_report(sn, rssi=-55, seq=1, extra={"probe": marker}))
    frame = build_eth_frame(payload, src_mac=b"\x02\x00\x00\x00\x00\xa1")   # 本地管理 MAC
    print(f"{INFO} 标记 = {marker}")
    print(f"{INFO} 帧 = {len(frame)} B（14B 头 + {len(payload)}B payload），ethertype=0x{ORPAH_ETHERTYPE:04x}")
    try:
        sendp(Ether(frame), iface=iface, count=count, inter=0.3, verbose=False)
        print(f"{OK} 已发送 {count} 帧 → 请在对端 PC 跑 `--raw-sniff --iface <对端网卡>` 看能否收到")
        print("     判据：对端收到同标记 = **自定义 ethertype 可透传**（这条路就走得通）；")
        print("           对端收不到但 ping 通 = 桥只转发 IP，0x88B5 被丢弃（需改走 UDP 封装）。")
    except Exception as e:
        print(f"{BAD} 发送失败：{e}（网卡名要用 `--iface` 里的真实名字，管理员权限？）")


def raw_sniff(iface, secs=20):
    print()
    print("=" * 78)
    print(f"4) raw L2 嗅探（iface={iface}，{secs}s，只看 ethertype 0x88B5）")
    print("-" * 78)
    if not _scapy():
        return
    from scapy.all import sniff
    print(f"{INFO} 开始嗅探…… 期间在对端 PC 跑 `--raw-send --iface <对端网卡>`")
    try:
        pkts = sniff(iface=iface, timeout=secs,
                     lfilter=lambda p: p.haslayer("Ether") and p["Ether"].type == ORPAH_ETHERTYPE)
    except Exception as e:
        print(f"{BAD} 嗅探失败：{e}（管理员权限/网卡名/Npcap）")
        return
    if not pkts:
        print(f"{BAD} {secs}s 内没嗅到任何 0x88B5 帧 → 该 ethertype **没有透传**"
              "（或对端没发/网卡选错）。")
        return
    print(f"{OK} 嗅到 {len(pkts)} 帧 0x88B5：")
    for p in pkts[:5]:
        raw = bytes(p.payload)
        rep = decode_msg(raw)
        print(f"     {p.src} → {p.dst}  {len(raw)}B  "
              f"{rep.get('type') if rep else raw[:40]!r}")
    print(f"{OK} 结论：自定义 ethertype 0x88B5 **可透传** → L2 路线可行（Client/Router 侧都不需要 UDP 封装）。")


# ---------------------------------------------------------------------------
def print_checklist(rows):
    print()
    print("=" * 78)
    print("5) 上机验证清单（脚本能自动判的已判；其余照 docs/real-hw-stage2.md 逐项做）")
    print("-" * 78)
    gens_known = [g for g in (r["gen"] for r in rows.values()) if g]
    auto = [
        ("环境/工具链", "tools UI 在跑 + 两板串口连上", bool(rows)),
        ("固件代次一致", "两板同代（跨代必不通）",
         len(gens_known) >= 2 and len(set(gens_known)) == 1),
        ("空口关联", "两端 CONNECTED",
         bool(rows) and all(r.get("conn") == "CONNECTED" for r in rows.values())),
    ]
    for name, how, ok in auto:
        print(f"  {OK if ok else WARN} {name:14s} {how}")
    manual = [
        "跨空口数据通路（UDP ping / --peer 探测）",
        "自定义 ethertype 0x88B5 是否透传（--raw-send + --raw-send 对端 --raw-sniff）",
        "广播/多播是否透传（Client 下行广播帧依赖它）",
        "RSSI 语义与数值（V1.6 = 档位小整数，V2.4 = dBm；拉开距离看是否变化）",
        "真实 router_id 落库（Server 侧事件/时序里已不再是空串）",
        "真实观测写入 root.orpah.routers.<sid>.<sn>（定位数据源换成真机测量）",
        "同代互通在**本项目固件组合**上复现（不是只测 ping）",
    ]
    for m in manual:
        print(f"  {INFO} {m}")
    print()
    print("⚠ 本脚本未经真机验证：若某步与手册不符，以**手册判据**为准并回来修脚本。")


def main():
    ap = argparse.ArgumentParser(description="阶段二真机自检（未真机验证；见 docs/real-hw-stage2.md）")
    ap.add_argument("--peer", help="对端 Server IP（跨空口 UDP 探测）")
    ap.add_argument("--port", type=int, default=SRV_PORT, help=f"对端 UDP 端口（默认 {SRV_PORT}）")
    ap.add_argument("--sn", default=TEST_SN, help=f"探测用 SN（默认 {TEST_SN}）")
    ap.add_argument("--listen", action="store_true", help="当接收端：打印收到的 ORPAH 报文")
    ap.add_argument("--iface", help="raw L2 用的网卡名（如 以太网 / Ethernet）")
    ap.add_argument("--raw-send", action="store_true", help="发 0x88B5 帧（需 scapy+Npcap+管理员）")
    ap.add_argument("--raw-sniff", action="store_true", help="嗅探 0x88B5 帧")
    ap.add_argument("--secs", type=int, default=20, help="嗅探秒数（默认 20）")
    a = ap.parse_args()

    if a.listen:
        do_listen(a.port)
        return 0
    if a.raw_send:
        raw_send(a.iface or "以太网", a.sn)
        return 0
    if a.raw_sniff:
        raw_sniff(a.iface or "以太网", a.secs)
        return 0

    info = check_env()
    rows = check_boards(info)
    if a.peer:
        probe_udp(a.peer, a.port, a.sn)
    print_checklist(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
