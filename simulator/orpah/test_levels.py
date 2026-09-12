#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_levels.py — §8 降级策略（多算法策略与降级）的离线自检。

覆盖四件事：
  1) **§8.2 选级流程**：`pick_level(se_ok, sign_ok, hmac_ok)` 的 8 种组合真值表
     （SE 通+签名通→L0 / 签名失败→L1 / SE 不通+有 HMAC→L2 / SE 不通+无 HMAC→L3）；
     `Device.report(level=None)` 自动选级（显式传 level 的旧用法不受影响）。
  2) **§8.3 服务端语义**：`verify_report` 返回 `degraded`（L2）/ `coverage_only`（L3）；
     `counts_as_presence()` = 能否当"人员出现"（L0/L1/L2 能，被拒与 L3 不能）。
  3) **降级告警**：L2→warn、L3→crit、同设备只一条取最高级、窗口外消警、被拒不参与。
  4) **两个 2026-09-12 修掉的 bug 回归锁**：
     ① `sig_fail_rate` 的 `since` 必须是 epoch 整数（原来传展示用字符串 "15:46:21"
        → `_alert` 里 `int(since)` 抛 ValueError → `/api/alerts` 整个不可用）；
     ② 排序不再因 since 类型混用而炸（签名失败率 crit 与案件超时 crit 同时在场）。

跑法：C:\\Python313\\python.exe test_levels.py
"""
import os
import sys

# 阈值走环境变量：先清掉，否则 shell 里留过的值会让"默认值"断言假失败（test_alerts 的教训）
for _k in [k for k in os.environ if k.startswith("ORPAH_ALERT_")]:
    del os.environ[_k]

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import time                                                    # noqa: E402

import alerts as alr                                           # noqa: E402
import cases as cs                                             # noqa: E402
import orpah_id as oid                                         # noqa: E402

FAIL = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


print("== 1. §8.2 选级流程（真值表） ==")
# (se_ok, sign_ok, hmac_ok) → (level, reason)，照 §8.2 的文字流程
TABLE = [((True, True, True), (0, "normal")),
         ((True, False, True), (1, "slot0_sign_failed")),      # Step2 签名失败 → L1
         ((True, False, False), (1, "slot0_sign_failed")),     # SE 通：仍走 L1（不看 HMAC）
         ((False, True, True), (2, "se_unavailable")),         # Step1 SE 不通 → 有 HMAC → L2
         ((False, True, False), (3, "no_key")),                # Step3 无密钥 → L3
         ((False, False, True), (2, "se_unavailable")),
         ((False, False, False), (3, "no_key"))]
for args, want in TABLE:
    got = oid.pick_level(*args)
    ck(f"pick_level{args} → {want}", got == want, f"得到 {got}")

print("== 2. §8.1 映射表与级别取值域 ==")
ck("LEVEL_TO_ALG 覆盖 0..3", set(oid.LEVEL_TO_ALG) == {0, 1, 2, 3}, str(oid.LEVEL_TO_ALG))
ck("TRUST_BY_LEVEL 覆盖 0..3", set(oid.TRUST_BY_LEVEL) == {0, 1, 2, 3})
ck("L0=ES256 / L1,L2=HS256 / L3=none",
   (oid.LEVEL_TO_ALG[0], oid.LEVEL_TO_ALG[1], oid.LEVEL_TO_ALG[2], oid.LEVEL_TO_ALG[3])
   == (oid.ALG_ES256, oid.ALG_HS256, oid.ALG_HS256, oid.ALG_NONE))
_combos = [(a, b, c) for a in (True, False) for b in (True, False) for c in (True, False)]
ck("任何组合都落在 0..3", all(oid.pick_level(*c)[0] in (0, 1, 2, 3) for c in _combos))

print("== 3. Device.report 自动选级 ==")
dev = oid.Device(sn="CN-WH01-9AF3C1D2")
for args, want_lv in [({}, 0), ({"sign_ok": False}, 1),
                      ({"se_ok": False}, 2), ({"se_ok": False, "hmac_ok": False}, 3)]:
    hdr = dev.report(**args)["hdr"]
    ck(f"report({args}) → level={want_lv}",
       hdr["level"] == want_lv and hdr["alg"] == oid.LEVEL_TO_ALG[want_lv], str(hdr))
ck("显式 level=2 仍按传的级别（自动选级不覆盖显式）",
   dev.report(level=2)["hdr"]["level"] == 2)
ck("L3 报文不带签名（alg=none 无 sig 字段）",
   "sig" not in dev.report(level=3))

print("== 4. §8.3 verify_report 的 degraded / coverage_only ==")
ks = oid.KeyStore()
ks.register(dev)
used = oid.NonceCache()
NOW = int(time.time())


def vfy(level, **kw):
    return oid.verify_report(dev.report(level=level, ts=NOW, **kw), ks,
                             now=NOW, used_nonces=used)


v0, v1, v2, v3 = vfy(0), vfy(1), vfy(2), vfy(3)
ck("L0/L1/L2/L3 都被接受", all(v["accepted"] for v in (v0, v1, v2, v3)))
ck("L0：不降级（degraded=False, coverage_only=False）",
   v0["degraded"] is False and v0["coverage_only"] is False, str(v0))
ck("L1：不标 degraded（§8.3 只把 L2 标 degraded）",
   v1["degraded"] is False and v1["coverage_only"] is False, str(v1))
ck("L2：degraded=True 且 trust=low", v2["degraded"] is True and v2["trust"] == "low", str(v2))
ck("L3：coverage_only=True 且 trust=none",
   v3["coverage_only"] is True and v3["trust"] == "none", str(v3))
ck("L3：degraded=False（它走覆盖发现，不是「降级但可信」）", v3["degraded"] is False)
bad = oid.verify_report({"hdr": {"typ": "orpah-id-report", "ver": 1,
                                 "alg": oid.ALG_NONE, "level": 0},
                         "payload": {"sn": dev.sn, "ts": NOW, "nonce": "x"}}, ks, now=NOW)
ck("alg=none 且 level≠3 → 拒（none_requires_level3）", bad["error"] == "none_requires_level3")

print("== 5. counts_as_presence（能不能当“人员出现”） ==")
ck("L0/L1/L2 都能", [oid.counts_as_presence(v) for v in (v0, v1, v2)] == [True] * 3)
ck("L3 不能（§8.3：不用于人员确认）", oid.counts_as_presence(v3) is False)
ck("被拒的不能（伪造/重放等都算）",
   oid.counts_as_presence(bad) is False
   and oid.counts_as_presence({"accepted": False, "error": "signature_invalid"}) is False)
ck("空/脏输入不炸也不当出现",
   oid.counts_as_presence(None) is False and oid.counts_as_presence({}) is False)


class _Reg:
    """只要 devices 恒等即可（本文件不测 no_report）。"""
    devices = {}


class _Cases:
    def __init__(self, items=None):
        self.items = items or []

    def open_cases(self):
        return self.items


class _Case:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def deg_rec(sn, level, accepted=True, ts_eff=None):
    return {"t": "15:00:00", "sn": sn, "level": level, "accepted": accepted,
            "ts_eff": NOW if ts_eff is None else ts_eff, "alg": oid.LEVEL_TO_ALG.get(level, "-")}


def ev(reports, **th):
    th.setdefault("id_degraded_sec", 300)
    return alr.evaluate(_Reg(), _Cases(), reports, now=NOW, **th)


print("== 6. 降级告警（§8.3） ==")
a = ev([deg_rec("SN-1", 2)])
ck("L2 → 一条 warn", [(x["kind"], x["level"]) for x in a] == [("id_degraded", "warn")], str(a))
ck("L2 文案键 = alert_id_degraded 且带 sn/lv",
   a and a[0]["msg"] == "alert_id_degraded" and a[0]["sn"] == "SN-1" and a[0]["lv"] == 2)
ck("since 是 epoch 整数（前端要拿它算“持续多久”）", isinstance(a[0]["since"], int) and a[0]["since"] > 1e9)

a = ev([deg_rec("SN-1", 3)])
ck("L3 → 一条 crit（无可用密钥）",
   [(x["kind"], x["level"]) for x in a] == [("id_degraded", "crit")]
   and a[0]["msg"] == "alert_id_no_key", str(a))

a = ev([deg_rec("SN-1", 2), deg_rec("SN-1", 3)])
ck("同一设备 L2+L3 → 只一条、取最高级（crit）",
   len(a) == 1 and a[0]["level"] == "crit", str(a))

a = ev([deg_rec("SN-1", 2), deg_rec("SN-2", 2)])
ck("两台设备 → 两条", len(a) == 2, str(a))

a = ev([deg_rec("SN-1", 2, ts_eff=NOW - 400)])
ck("窗口外（400s > 300s）→ 自动消警", not a, str(a))

a = ev([deg_rec("SN-1", 2, accepted=False)])
ck("被拒的记录不算降级（那是 sig_fail_rate 的事）", not a, str(a))

a = ev([deg_rec("SN-1", 0), deg_rec("SN-1", 1)])
ck("L0/L1 不告警（§8.3：L0/L1 正常处理）", not a, str(a))

print("== 7. 回归锁：since 类型（2026-09-12 修的 bug） ==")
# ① 签名失败率命中（原来传字符串 t）→ 必须不抛、since 为整数
bad5 = [{"t": "15:46:21", "accepted": False, "level": 0, "sn": "SN-1",
         "ts_eff": NOW} for _ in range(5)]
try:
    a = ev(bad5, sig_window=5, sig_fail_ratio=0.5)
    ck("签名失败率命中不抛异常", True)
    ck("sig_fail_rate 的 since 是 epoch 整数",
       isinstance(a[0]["since"], int) and a[0]["since"] > 1e9, str(a[0]))
except Exception as e:                                   # noqa: BLE001
    ck("签名失败率命中不抛异常", False, f"{type(e).__name__}: {e}")
# ② 与案件超时（crit，int since）同场 → 排序不炸
case = _Case(case_id="C001", person_id="P001", status=cs.CASE_OPEN,
             handler="", created=NOW - 1000, handled_at=None)
try:
    a = alr.evaluate(_Reg(), _Cases([case]), bad5, now=NOW,
                     case_overtime_sec=180, sig_window=5, sig_fail_ratio=0.5)
    kinds = [x["kind"] for x in a]
    ck("签名失败率 + 案件超时同场排序不炸", True, str(kinds))
    ck("两条 crit 都在（顺序：同级按 since）",
       set(kinds) == {"sig_fail_rate", "case_overtime"}, str(kinds))
except Exception as e:                                   # noqa: BLE001
    ck("签名失败率 + 案件超时同场排序不炸", False, f"{type(e).__name__}: {e}")

print()
if FAIL:
    print(f"失败 {len(FAIL)} 项：" + "；".join(FAIL))
    raise SystemExit(1)
print("全部通过")
