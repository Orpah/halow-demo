#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_spoof.py — 防 spoof 攻击清单的自检（离线裁决，不占端口/不起链路）。

验三件事：
  1) 每种攻击都**只**被预期的那道防线拦下（错误码逐条对得上）；
  2) 清单本身自洽（每项都有 zh/en/expect，UI 子集不含改密钥库状态的用例）；
  3) "合法对照"确实通过 —— 否则所有"拒绝"都说明不了问题。
端到端（经空口真注入）见 demo_spoof.py。
跑法：C:\\Python313\\python.exe test_spoof.py
"""
import copy
import sys
import time

import orpah_id as oid
import spoof

FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


print("== 1. 清单自洽 ==")
ck("用例数 >= 10（覆盖面）", len(spoof.CASES) >= 10, f"{len(spoof.CASES)} 条")
ck("kind 不重复", len(set(spoof.KINDS)) == len(spoof.KINDS))
ck("每项都有 kind/zh/en/expect/说明",
   all(len(c) == 5 and c[0] and c[1] and c[2] for c in spoof.CASES))
ck("期望通过的用例恰好 2 条（合法对照 + 已知边界 xport）",
   sum(1 for c in spoof.CASES if c[3] is None) == 2)
ck("UI 子集排除会改密钥库状态的 revoked",
   "revoked" not in spoof.UI_KINDS and "revoked" in spoof.KINDS)
ck("revoked 排在最后（它改状态，后面不能再有用例）",
   spoof.CASES[-1][0] == "revoked", spoof.CASES[-1][0])
ck("未知 kind 回落到 legit", spoof.case_info("nope")[0] == spoof.case_info("legit")[0])

print("== 2. 逐条裁决（离线） ==")
dev = oid.Device(sn="CN-WH01-9AF3C1D2", se_sn="ATECC608B-DEMO")
attacker = oid.Device(cc="CN", org="WHOFF")
ks = oid.KeyStore()
ks.register(dev, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
now = int(time.time())
rows = spoof.run(dev, ks, now, attacker=attacker)
for r in rows:
    ck(f"{r['kind']:16s} → {str(r['expect'])}", r["ok"], f"got={r['got']}")

print("== 3. 防线语义 ==")
by = {r["kind"]: r for r in rows}
ck("合法对照通过且 trust=high",
   by["legit"]["got"] is None and by["legit"].get("trust") == "high",
   f"trust={by['legit'].get('trust')}")
ck("改 ts / 改观测 / 改 hdr 都落在签名这一道（不是靠时间窗兜）",
   all(by[k]["got"] == "signature_invalid"
       for k in ("ts_tamper", "obs_tamper", "level_downgrade")))
ck("用别人钥匙签受害者 SN → signature_invalid",
   by["sig_foreign"]["got"] == "signature_invalid")
ck("校验位错不查库就被挡", by["bad_check"]["got"] == "bad_check")
ck("免签冒充被压到 level3", by["alg_none"]["got"] == "none_requires_level3")
ck("吊销优先于验签", by["revoked"]["got"] == "revoked")
ck("重放被 nonce 去重挡下", by["replay"]["got"] == "replay_detected")
ck("超窗被时间窗挡下", by["stale"]["got"] == "timestamp_out_of_window")
ck("已知边界如实展示：路由器侧 xport 不进签名 → 通过",
   by["xport_tamper"]["got"] is None)

print("== 4. 攻击确实改动了报文（不是把合法报文原样发了一遍） ==")
legit, _, _ = spoof.build_case("legit", dev, now)
for kind in ("sig_foreign", "ts_tamper", "obs_tamper", "level_downgrade",
             "alg_none", "bad_check", "unknown_sn", "stale"):
    r, _, _ = spoof.build_case(kind, dev, now, attacker=attacker)
    diff = (r.get("hdr") != legit.get("hdr")
            or r.get("payload") != legit.get("payload")
            or r.get("sig") != legit.get("sig"))
    ck(f"{kind:16s} 与合法报文不同", diff)
base, _, _ = spoof.build_case("legit", dev, now)
before = {k: copy.deepcopy(base[k]) for k in ("hdr", "payload", "sig")}
r_xt = oid.attach_xport(base, "DE:AD:BE:EF:00:02", "FAKE_AP", -20)
ck("xport 只加在最外层（hdr/payload/sig 逐个不变 → 所以验签照样通过）",
   bool(r_xt.get("xport")) and all(r_xt[k] == before[k] for k in before),
   str(r_xt.get("xport"))[:60])

print()
if FAIL:
    print(f"失败 {len(FAIL)} 项：" + "；".join(FAIL))
    sys.exit(1)
print("全部通过")
