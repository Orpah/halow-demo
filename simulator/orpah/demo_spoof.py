#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_spoof.py — 无认证空口防 spoof 端到端演示 + 验收（纯 PC，无硬件）

**演示什么**：ORPAH 的空口是**开放/无认证**的（低功耗客户端不做入网认证）—— 也就是说
**任何人都能把一条 ORPAH-ID-REPORT 扔进空口**。本脚本搭起真链路
（Client host → STA → 空口 → AP → Router 桥 → UDP → Server），把 `spoof.py` 里
每一种攻击**真的注入空口**，然后在 Server 侧断言裁决：

  · 合法报文（对照组）→ 验签通过、trust=high
  · 其余每一种伪造/篡改/重放/超窗/吊销 → 被拒，且**拒绝原因与预期一致**

为什么不直接调 `verify_report`：那是"离线自说自话"（`demo_id.py` 已覆盖）。
本脚本要证明的是**链路上任何人都能注入、而服务器不会被骗**，走的是同一套报文、
同一个验签入口（`server.py` 收到 ORPAH-ID-REPORT 的那条路）。

运行：C:\\Python313\\python.exe demo_spoof.py
端口：98xx / 19847（与 demo_l1/l2/l3/l4、ui_server 错开）
"""
import argparse
import os
import sys
import threading
import time

# Windows 控制台默认代码页 GBK/cp936：强制 stdout/stderr 用 UTF-8 编码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host")
if HOST_DIR not in sys.path:
    sys.path.insert(0, HOST_DIR)
ORPAH_DIR = os.path.dirname(os.path.abspath(__file__))
if ORPAH_DIR not in sys.path:
    sys.path.insert(0, ORPAH_DIR)

import sim                                  # noqa: E402
import orpah_id as oid                       # noqa: E402
import spoof                                 # noqa: E402
from server import OrpahServer                # noqa: E402
from router import RouterBridge               # noqa: E402
from client import ClientHost                 # noqa: E402

CONSOLE_A, LINK_A, HOST_A = 9801, 9811, 9821   # AP（Router 侧）
CONSOLE_B, LINK_B, HOST_B = 9802, 9812, 9822   # STA（Client 侧）
UDP_SRV = 19847

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK ] {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  {extra}" if extra else ""))


def loop_cores(cores, stop):
    while not stop.is_set():
        for c in cores:
            c.wifi.poll()
            c.link.poll()
        time.sleep(0.005)


class Verdicts:
    """Server 侧收到的验签结果（按**到达顺序**索引）。

    注意**不能按 nonce 索引**：「重放」用例故意复用一条已经用过的 nonce，
    按 nonce 查会取回那条旧的（合法）裁决 → 假 PASS。
    """

    def __init__(self):
        self.all = []
        self.lock = threading.Lock()

    def on_id_report(self, rec):
        with self.lock:
            self.all.append(rec)

    def count(self):
        with self.lock:
            return len(self.all)

    def wait_next(self, seen_before, timeout=5.0):
        """等第 seen_before 条之后的**下一条**记录（按到达顺序）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if len(self.all) > seen_before:
                    return self.all[seen_before]
            time.sleep(0.02)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sn", default="CN-WH01-9AF3C1D2",
                    help="被冒充设备（合法设备）的 SN")
    args = ap.parse_args()

    stop = threading.Event()
    verdicts = Verdicts()

    # ---- 密钥库：只登记合法设备一把钥（攻击者不在库里）----
    legit_dev = oid.Device(sn=args.sn, se_sn="ATECC608B-DEMO")
    attacker = oid.Device(cc="CN", org="WH01")      # 攻击者自造一对钥匙
    ks = oid.KeyStore()
    ks.register(legit_dev, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
    used = oid.NonceCache()

    print("=" * 74)
    print("  无认证空口防 spoof 端到端演示")
    print("=" * 74)
    print(f"  被冒充设备 SN : {legit_dev.sn}")
    print(f"  攻击者 SN    : {attacker.sn}（未登记 → 服务器不认识）")
    print(f"  链路          : Client→STA→空口→AP→Router→UDP:{UDP_SRV}→Server")
    print(f"  用例数        : {len(spoof.CASES)}（含 1 条合法对照）")
    print()

    # ⚠ 本脚本跑在**活密钥库**（server 拿着它）上：「已吊销」用例会留下吊销状态，
    #   而 `unrevoke` 会把各代置成 retired（之后验签全变 unknown_device）→ 它必须最后跑。
    #   顺序被改了就**当场报错**，不要静默给出错误结论。
    if spoof.CASES[-1][0] != "revoked":
        print("  [FATAL] spoof.CASES 的最后一项必须是 revoked（见 spoof.py 该条注释）")
        return 2

    # ---- 起链路（与 demo_l2 同构）----
    coreA = sim.Core("Router-AP", "AP", CONSOLE_A, LINK_A, None, host_port=HOST_A)
    coreB = sim.Core("Client-STA", "STA", CONSOLE_B, LINK_B,
                     ("127.0.0.1", LINK_A), host_port=HOST_B)
    threading.Thread(target=loop_cores, args=([coreA, coreB], stop), daemon=True).start()

    srv = OrpahServer(port=UDP_SRV, keystore=ks, id_nonces=used,
                      on_id_report=verdicts.on_id_report)
    srv.start()
    router = RouterBridge(ap_port=HOST_A, server_port=UDP_SRV)
    if not router.start():
        print("  Router 连不上 AP host 口，退出")
        return 2
    client = ClientHost(sta_port=HOST_B, sn=legit_dev.sn)
    if not client.connect():
        print("  Client 连不上 STA host 口，退出")
        return 2
    for _ in range(100):                      # 等 STA 关联 AP（关联前注入会被丢）
        if coreB.wifi.conn == sim.CONN_CONNECTED:
            break
        time.sleep(0.1)
    print(f"  链路就绪：STA conn = {coreB.wifi.conn_str()}\n")

    # ---- 逐条注入空口并断言 ----
    replay_nonce = None
    rows = []
    try:
        for kind, *_ in spoof.CASES:
            _, _, expect, note = spoof.case_info(kind)
            if kind == "revoked":
                ks.revoke(legit_dev.sn)       # 该用例需要"已吊销"这个状态
            report, expect, note = spoof.build_case(
                kind, legit_dev, int(time.time()), attacker=attacker,
                used_nonce=replay_nonce)
            nonce = report["payload"]["nonce"]
            if kind == "legit":
                replay_nonce = nonce          # 供「重放」用例复用（此时尚未被用过）
            n0 = verdicts.count()
            client.send_id_report(report)     # ★ 从 Client 侧注入，走真链路
            rec = verdicts.wait_next(n0, timeout=5.0)
            if rec is None:
                rows.append({"kind": kind, "zh": spoof.case_info(kind)[0],
                             "expect": expect, "got": "(超时未收到)",
                             "ok": False, "note": note})
                continue
            got = None if rec.get("accepted") else rec.get("error")
            rows.append({"kind": kind, "zh": spoof.case_info(kind)[0],
                         "expect": expect, "got": got, "ok": got == expect,
                         "trust": rec.get("trust"), "note": note})
            time.sleep(0.05)
    finally:
        stop.set()
        try:
            client.close()
        except Exception:
            pass
        try:
            router.stop()
        except Exception:
            pass
        try:
            srv.stop()
        except Exception:
            pass

    # ---- 结果表 ----
    print("-" * 74)
    print(f"  {'用例':<18}{'期望':<26}{'实际':<26}{'结果'}")
    print("-" * 74)
    for r in rows:
        print(f"  {r['kind']:<18}{str(r['expect']):<26}{str(r['got']):<26}"
              f"{'OK' if r['ok'] else 'FAIL'}")
    print("-" * 74)

    print("\n[1] 逐条裁决（经空口注入）")
    for r in rows:
        check(f"{r['kind']}（{r['zh']}）→ {r['expect'] or '接受'}",
              r["ok"], f"got={r['got']}")

    print("\n[2] 防线语义（不只是'被拒了'，而是'被哪道防线拒的'）")
    by = {r["kind"]: r for r in rows}
    check("合法对照确实通过（否则下面的拒绝毫无意义）",
          by["legit"]["got"] is None and by["legit"].get("trust") == "high",
          f"trust={by['legit'].get('trust')}")
    check("改 ts/改观测/改 hdr 都落在同一道防线（签名），不是靠时间窗兜的",
          all(by[k]["got"] == "signature_invalid"
              for k in ("ts_tamper", "obs_tamper", "level_downgrade")))
    check("乱编的 SN 不查库就被挡（校验位）", by["bad_check"]["got"] == "bad_check")
    check("合法格式但未登记 → 查库挡下", by["unknown_sn"]["got"] == "unknown_device")
    check("重放被 nonce 去重挡下", by["replay"]["got"] == "replay_detected")
    check("吊销优先于验签（钥匙对也不行）", by["revoked"]["got"] == "revoked")
    check("免签冒充被限制在 level3（不得冒充 level0）",
          by["alg_none"]["got"] == "none_requires_level3")
    check("已知边界如实展示：路由器侧 xport 不进签名 → 验签通过（需路由器身份来补）",
          by["xport_tamper"]["got"] is None)

    print("\n[3] 服务器侧记录")
    check("每条注入都在 Server 侧留下一条验签记录",
          len(verdicts.all) >= len(rows), f"{len(verdicts.all)} 条")
    n_rej = sum(1 for r in verdicts.all if not r.get("accepted"))
    check("被拒条数 = 攻击条数", n_rej == len(rows) - 2,
          f"拒 {n_rej} / 共 {len(rows)}（含 legit 与已知边界 xport_tamper 两条通过）")

    print("\n" + "=" * 74)
    print(f"  结果：{PASS} 通过 / {FAIL} 失败")
    print("  " + ("🎉 防 spoof 端到端验收全部通过" if FAIL == 0
                  else "⚠️ 存在失败用例，请检查"))
    print("=" * 74)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
