#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_keys.py — 密钥生命周期自检（生成→签发→轮换→宽限→退役→作废→持久化）。

纯内存 + 临时 SQLite，不依赖 IoTDB / 网页。
跑法：C:\\Python313\\python.exe test_keys.py
"""
import json
import os
import shutil
import sys
import tempfile

import keystore as kst
import orpah_id as oid

SN = "CN-WH01-9AF3C1D2"
FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


def verify(ks, dev, level=0, **kw):
    return oid.verify_report(dev.report(level=level, **kw), ks,
                            used_nonces=oid.NonceCache())


print("== 1. 签发（幂等） ==")
ks = oid.KeyStore()
dev1 = oid.Device(sn=SN, gen=1)
kid = ks.register(dev1, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
ck("首次签发 = 第 1 代", kid == SN + "#1", kid)
ck("状态 active", ks.active_of(SN)["state"] == oid.KEY_ACTIVE)
ck("带模型/固件", ks.active_of(SN)["model"].startswith("CH32V203"))
kid2 = ks.register(oid.Device(sn=SN, gen=1))
ck("重复 register 幂等（不造新钥）", kid2 == kid and len(ks.list_keys(SN)) == 1)

print("== 2. 验签（第 1 代） ==")
v = verify(ks, dev1)
ck("ES256 通过", v["accepted"] and v["trust"] == "high", str(v.get("error", "")))
ck("回报命中的代次", v.get("kid") == SN + "#1" and v.get("gen") == 1, str(v.get("kid")))

print("== 3. 轮换：旧钥进宽限、新旧都能验 ==")
dev2 = oid.Device(sn=SN, gen=2)
r = ks.rotate(SN, dev2)
ck("新钥 = 第 2 代 active", r["kid"] == SN + "#2" and ks.active_of(SN)["gen"] == 2)
ck("旧钥转 grace", ks.get_key(SN + "#1")["state"] == oid.KEY_GRACE)
ck("宽限期 = now+grace_sec", r["grace_until"] is not None and r["grace_sec"] > 0)
v1 = verify(ks, dev1)
ck("★ 宽限期内旧钥仍能验（轮换不断链）", v1["accepted"] and v1["kid"] == SN + "#1",
   str(v1.get("error", "")))
v2 = verify(ks, dev2)
ck("新钥能验", v2["accepted"] and v2["kid"] == SN + "#2", str(v2.get("error", "")))
vx = verify(ks, oid.Device(sn=SN, gen=9))
ck("不在库里的钥被拒", not vx["accepted"] and vx["error"] == "signature_invalid",
   str(vx.get("error")))

print("== 4. 宽限到期 → 退役 ==")
sw = ks.sweep(now=r["grace_until"])
ck("sweep 让到期 grace 退役", [k for k, _ in sw] == [SN + "#1"], str(sw))
ck("状态变 retired", ks.get_key(SN + "#1")["state"] == oid.KEY_RETIRED)
v1b = verify(ks, dev1)
ck("★ 退役后旧钥不再受理", not v1b["accepted"] and v1b["error"] == "signature_invalid",
   str(v1b.get("error")))
ck("新钥不受影响", verify(ks, dev2)["accepted"])
ck("未到期的 grace 不会被 sweep", ks.sweep(now=r["grace_until"] - 1) == [])

print("== 5. grace_sec=0：旧钥立即失效 ==")
ks0 = oid.KeyStore(grace_sec=0)
d0a = oid.Device(sn=SN, gen=1)
ks0.register(d0a)
d0b = oid.Device(sn=SN, gen=2)
ks0.rotate(SN, d0b)
ck("宽限 0 → 旧钥立刻不可验", not verify(ks0, d0a)["accepted"])
ck("新钥可验", verify(ks0, d0b)["accepted"])

print("== 6. 提前强制退役 ==")
ks1 = oid.KeyStore()
d1a = oid.Device(sn=SN, gen=1)
ks1.register(d1a)
rt = ks1.retire(SN, kid=SN + "#1")
ck("retire(kid) 退役该代", rt == [SN + "#1"], str(rt))
ck("退役后不可验", not verify(ks1, d1a)["accepted"])
ck("不带 kid 不静默退役 active",
   ks1.retire(SN) == [] and ks1.get_key(SN + "#1")["state"] == oid.KEY_RETIRED)

print("== 7. 作废（整机，不可逆） ==")
ks2 = oid.KeyStore()
d2a, d2b = oid.Device(sn=SN, gen=1), oid.Device(sn=SN, gen=2)
ks2.register(d2a)
ks2.rotate(SN, d2b)                       # 两代并存（active + grace）
ks2.revoke(SN, reason="设备失窃", actor="张警官")
ck("撤销表记录原因/操作者",
   ks2.revoked_info(SN)["reason"] == "设备失窃"
   and ks2.revoked_info(SN)["actor"] == "张警官")
ck("所有代转 revoked",
   {k["state"] for k in ks2.list_keys(SN)} == {oid.KEY_REVOKED})
va = verify(ks2, d2a)
vb = verify(ks2, d2b)
ck("★ 作废后新旧钥都立即被拒（error=revoked）",
   not va["accepted"] and not vb["accepted"] and vb["error"] == "revoked",
   str(vb.get("error")))
ck("重复 revoke 不覆盖原记录", ks2.revoke(SN, reason="再次")["reason"] == "设备失窃")

print("== 8. 撤销恢复（仅演示）→ 需重新签发 ==")
ks2.unrevoke(SN)
ck("恢复后不再标 revoked", not ks2.is_revoked(SN))
ck("恢复后代次一律 retired（不回到 active）",
   {k["state"] for k in ks2.list_keys(SN)} == {oid.KEY_RETIRED})
ck("此时验签报 unknown_device（无可用钥）",
   verify(ks2, d2b)["error"] == "unknown_device", str(verify(ks2, d2b).get("error")))
d2c = oid.Device(sn=SN, gen=3)
kidc = ks2.register(d2c)
ck("重新签发第 3 代可恢复服务",
   kidc == SN + "#3" and verify(ks2, d2c)["accepted"])

print("== 8b. 已作废设备不得重新发钥（端到端跑出来的真 bug） ==")
ks3 = oid.KeyStore()
d3 = oid.Device(sn=SN, gen=1)
ks3.register(d3)
ks3.revoke(SN, reason="失窃")
try:
    ks3.register(oid.Device(sn=SN, gen=2))
    ck("★ 作废后 register 被拒", False, "竟然签发成功了")
except ValueError as e:
    ck("★ 作废后 register 被拒", "已作废" in str(e), str(e))
try:
    ks3.rotate(SN, oid.Device(sn=SN, gen=2))
    ck("★ 作废后 rotate 也被拒", False, "竟然轮换成功了")
except ValueError as e:
    ck("★ 作废后 rotate 也被拒", "已作废" in str(e), str(e))
# 重复 revoke 必须仍然把「后冒出来的代」压回 revoked
ks3._gens[SN].append({"sn": SN, "kid": SN + "#9", "gen": 9, "pubkey": None,
                      "hmac_key": None, "se_sn": None, "model": None,
                      "firmware": None, "created_at": 0, "state": oid.KEY_ACTIVE,
                      "grace_until": None, "retired_at": None})
ks3.revoke(SN, reason="再次")
ck("★ 重复 revoke 也把所有代压回 revoked",
   {k["state"] for k in ks3.list_keys(SN)} == {oid.KEY_REVOKED}
   and ks3.revoked_info(SN)["reason"] == "失窃")

print("== 9. SQLite 持久化（重启不丢 + 公钥仍对得上） ==")
tmp = tempfile.mkdtemp(prefix="orpahkeys_")
try:
    db = os.path.join(tmp, "k.db")
    k1 = kst.KeyStoreDB(db, grace_sec=3600)
    da, db_ = oid.Device(sn=SN, gen=1), oid.Device(sn=SN, gen=2)
    k1.register(da, model="M1", firmware="1.0.3")
    k1.rotate(SN, db_)
    k1.revoke("CN-WH02-BBBBBBBB", reason="报废", actor="李四")
    ck("落库行数 = 2 代 + 1 撤销",
       k1.db.execute("SELECT COUNT(*) c FROM keys").fetchone()["c"] == 2
       and k1.db.execute("SELECT COUNT(*) c FROM key_revocations").fetchone()["c"] == 1)

    k2 = kst.KeyStoreDB(db)               # 模拟重启
    ck("重启后 2 代都在", len(k2.list_keys(SN)) == 2)
    ck("重启后 active/grace 状态保留",
       k2.get_key(SN + "#2")["state"] == oid.KEY_ACTIVE
       and k2.get_key(SN + "#1")["state"] == oid.KEY_GRACE)
    ck("重启后撤销表保留（含原因/操作者）",
       k2.revoked_info("CN-WH02-BBBBBBBB")["reason"] == "报废"
       and k2.revoked_info("CN-WH02-BBBBBBBB")["actor"] == "李四")
    ck("★ 重启后公钥仍对得上（确定派生）",
       verify(k2, db_)["accepted"] and verify(k2, da)["accepted"])
    ck("重启后撤销依然拒签",
       verify(k2, oid.Device(sn="CN-WH02-BBBBBBBB", gen=1))["error"] == "revoked")
    ck("grace 剩余时间可算", k2.to_dict(SN)["keys"][0]["state"] == oid.KEY_ACTIVE)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 10. JSON 导入导出（含旧格式兼容） ==")
tmp = tempfile.mkdtemp(prefix="orpahkeyj_")
try:
    p = os.path.join(tmp, "ks.json")
    ks3 = oid.KeyStore()
    ks3.register(oid.Device(sn=SN, gen=1), model="M1")
    ks3.rotate(SN, oid.Device(sn=SN, gen=2))
    ks3.revoke("CN-WH03-CCCCCCCC", reason="失窃")
    ks3.save(p)
    data = json.load(open(p, encoding="utf-8"))
    ck("导出含 2 代 + 撤销表",
       len(data["devices"]) == 2 and len(data["revocations"]) == 1)
    ks4 = oid.KeyStore()
    ks4.load(p)
    ck("导入后代次/状态/撤销都在",
       len(ks4.list_keys(SN)) == 2 and ks4.is_revoked("CN-WH03-CCCCCCCC"))
    ck("导入后仍能验签（grace）", verify(ks4, oid.Device(sn=SN, gen=1))["accepted"])

    # 旧格式（无 kid/gen/state/revocations）—— 早期 KeyStore.save 的产物
    d1 = oid.Device(sn=SN, gen=1)
    old = {"devices": [{"sn": SN,
                        "pubkey_pem": oid.pubkey_to_pem(d1.pubkey),
                        "hmac_key_b64": oid.b64url_encode(d1.hmac_key),
                        "se_sn": "ATECC608B-DEMO"}]}
    p2 = os.path.join(tmp, "old.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(old, f)
    ks5 = oid.KeyStore()
    ks5.load(p2)
    ck("旧格式 → 视作第 1 代 active",
       ks5.get_key(SN + "#1")["state"] == oid.KEY_ACTIVE)
    ck("旧格式导入后能验签", verify(ks5, d1)["accepted"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 11. 演示密钥的确定性（跨对象/跨进程仍对得上 = AGENTS.md §0 的坑） ==")
# 派生式密钥的**全部意义**：同一 (sn, gen) 在任何时刻、任何进程都得到同一把钥。
# 若派生前缀/算法/JCS 预像被改动、或代码落到随机分支，本节立刻红 —— 那等于作废整个密钥库
# （持久化库里的公钥/hmac 会全部对不上，表现为"重启后验签全失败"）。故两条都要锁：
# ① 同一个体两次构造相同；② 用 A 注册的库能验 B 签的报文（不同个体 = 模拟重启）。
a1 = oid.Device(sn=SN, gen=1)
a2 = oid.Device(sn=SN, gen=1)
ck("ES256 公钥逐位相同（同 sn+gen，两个不同对象）",
   oid.pubkey_to_pem(a1.pubkey) == oid.pubkey_to_pem(a2.pubkey))
ck("HMAC 降级密钥逐位相同（同 sn+gen）",
   a1.hmac_key == a2.hmac_key and len(a1.hmac_key) == 32)
g2 = oid.Device(sn=SN, gen=2)
ck("换一代 → 两把钥都不同", oid.pubkey_to_pem(g2.pubkey) != oid.pubkey_to_pem(a1.pubkey)
   and g2.hmac_key != a1.hmac_key)
ck("换 SN → HMAC 不同", oid.derive_demo_hmac("CN-WH02-BBBBBBBB", 1) != a1.hmac_key)
ck("derive_demo_hmac 返回 32 字节 bytes（函数完整、不是半截）",
   isinstance(oid.derive_demo_hmac(SN, 1), bytes) and len(oid.derive_demo_hmac(SN, 1)) == 32)
ck("gen 已是 int 归一（'1'/1.0 与 1 同钥，无需外部类型检查）",
   oid.derive_demo_hmac(SN, "1") == a1.hmac_key
   and oid.derive_demo_hmac(SN, 1.0) == a1.hmac_key)

ks_a = oid.KeyStore()
ks_a.register(a1, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
ck("★ 用 A 注册的库验 B（L0/ES256）签的报文 → 通过（重启后仍能验）",
   verify(ks_a, a2, level=0)["accepted"])
ck("★ 同上 L1（HS256 降级路径）→ 通过（HMAC 也跨对象一致）",
   verify(ks_a, a2, level=1)["accepted"])
ks_b = oid.KeyStore()
ks_b.register(a1, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
ck("另一代（gen=2）签的报文用第 1 代的库验 → 拒（代次不能串）",
   not verify(ks_b, g2, level=0)["accepted"])

print()
if FAIL:
    print(f"{len(FAIL)} 项失败: " + "; ".join(FAIL))
    sys.exit(1)
print("all key lifecycle tests passed")
