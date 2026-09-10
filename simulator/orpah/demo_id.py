#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_id.py — Orpah ID 端到端验收（纯 Python，无硬件）
======================================================
验证《Orpah ID 协议规范》v1.12 的完整身份/真实性链路：
  - SN 生成 + CHECK（Mod 97 / Luhn mod 32）
  - 报文构建与签名：L0=ES256、L1/L2=HS256、L3=none
  - server 验签（§9.3）：alg 白名单 / 时间窗口(ts=0 跳过) / nonce 去重 /
    SN+CHECK / 撤销 / 密钥检索 / 签名
  - 负向：篡改、重放、超窗、none+level≠3、未知设备、撤销、坏 CHECK、坏 SN
  - router xport 附加观测（不参与验签，§5.7）

运行：C:\\Python313\\python.exe simulator/orpah/demo_id.py
（现有 L1–L4 业务流不动；本 demo 只演示 orpah_id 层。）
"""
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import orpah_id as oid

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}" + (f"  — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f"  — {detail}" if detail else ""))


def main():
    now = int(time.time())

    # ---- 1. SN + CHECK ------------------------------------------------
    print("\n[1] SN 与 CHECK 校验码")
    sn = oid.gen_sn(check="mod97")
    print(f"  生成 SN(Mod97) = {sn}")
    check("SN 格式合法", oid.sn_ok(sn))
    check("Mod97 校验通过", oid.verify_check(sn))

    sn2 = oid.gen_sn(check="luhn32")
    print(f"  生成 SN(Luhn32) = {sn2}")
    check("Luhn32 校验通过", oid.verify_check(sn2))

    sn3 = oid.gen_sn(check="")
    check("无校验 SN 通过", oid.verify_check(sn3))

    # 篡改 UNIQUE 一位 → CHECK 应失败（Mod97 能检出任意单字符替换）
    p = oid.parse_sn(sn)
    last = p["unique"][-1]
    repl = "1" if last == "0" else "0"
    bad = f"{p['cc']}-{p['org']}-{p['unique'][:-1]}{repl}-{p['check']}"
    check("篡改后 CHECK 失败", not oid.verify_check(bad), f"改后={bad}")

    # 非法 SN 格式
    check("坏 SN 拒绝(非法字符 I)", not oid.sn_ok("CN-WH0I-9AF3C1D2"))
    check("坏 SN 拒绝(UNIQUE 过短)", not oid.sn_ok("CN-WH01-9AF3C1"))

    # ---- 2. 设备 + 密钥库 --------------------------------------------
    print("\n[2] 设备与密钥库")
    dev = oid.Device(sn=sn)
    ks = oid.KeyStore()
    ks.register(dev, model="CH32V203+TX-AH+ATECC608B", firmware="1.0.3")
    used = oid.NonceCache()
    check("密钥库注册成功", ks.get_by_sn(dev.sn) is not None)

    seen = [{"bssid": "AA:BB:CC:DD:EE:FF", "ssid": "ORPAHID_ZONE_A", "rssi": -42}]

    # ---- 3. L0/L1/L2/L3 签名验签 -------------------------------------
    print("\n[3] 四级降级：签名 + 验签")

    r0 = dev.report(level=0, ts=now, seen_routers=seen, battery_mv=3700)
    v0 = oid.verify_report(r0, ks, now=now, used_nonces=used)
    check("L0 ES256 验签通过(high)", v0["accepted"] and v0["trust"] == "high",
          f"trust={v0.get('trust')}")

    r1 = dev.report(level=1, ts=now, seen_routers=seen)
    v1 = oid.verify_report(r1, ks, now=now, used_nonces=used)
    check("L1 HS256 验签通过(medium)", v1["accepted"] and v1["trust"] == "medium")

    r2 = dev.report(level=2, ts=now, seen_routers=seen)
    v2 = oid.verify_report(r2, ks, now=now, used_nonces=used)
    check("L2 HS256 验签通过(low)", v2["accepted"] and v2["trust"] == "low")

    r3 = dev.report(level=3, ts=now, seen_routers=seen)
    v3 = oid.verify_report(r3, ks, now=now, used_nonces=used)
    check("L3 none 覆盖发现(none)", v3["accepted"] and v3.get("coverage_only"))

    # ---- 4. 负向：篡改 / 重放 / 超窗 / none 混用 ----------------------
    print("\n[4] 负向用例")

    # 篡改 payload（签名外）→ signature_invalid
    tampered = dev.report(level=0, ts=now, seen_routers=seen, battery_mv=9999)
    tampered["payload"]["battery_mv"] = 1234
    vt = oid.verify_report(tampered, ks, now=now, used_nonces=used)
    check("篡改 payload → signature_invalid",
          not vt["accepted"] and vt["error"] == "signature_invalid")

    # 重放同一 nonce → replay_detected
    rrep = dev.report(level=0, ts=now, seen_routers=seen)
    used2 = oid.NonceCache()
    oid.verify_report(rrep, ks, now=now, used_nonces=used2)
    vr = oid.verify_report(rrep, ks, now=now, used_nonces=used2)
    check("nonce 重放 → replay_detected",
          not vr["accepted"] and vr["error"] == "replay_detected")

    # ts 超窗 → timestamp_out_of_window
    rout = dev.report(level=0, ts=now - 10000, seen_routers=seen)
    vo = oid.verify_report(rout, ks, now=now, used_nonces=used)
    check("ts 超窗 → timestamp_out_of_window",
          not vo["accepted"] and vo["error"] == "timestamp_out_of_window")

    # ts=0（未知）→ 跳过窗口，接受
    r0t = dev.report(level=0, ts=0, seen_routers=seen)
    v0t = oid.verify_report(r0t, ks, now=now, used_nonces=used)
    check("ts=0 跳过窗口(接受)", v0t["accepted"])

    # alg=none 但 level=2 → 拒绝
    rbad = dev.report(level=0, ts=now, seen_routers=seen)
    rbad["hdr"]["alg"] = "none"
    rbad["hdr"]["level"] = 2
    del rbad["sig"]
    vbad = oid.verify_report(rbad, ks, now=now, used_nonces=used)
    check("alg=none+level≠3 → 拒绝",
          not vbad["accepted"] and vbad["error"] == "none_requires_level3")

    # 未知算法 → bad_alg
    rua = dev.report(level=0, ts=now, seen_routers=seen)
    rua["hdr"]["alg"] = "RS256"
    vua = oid.verify_report(rua, ks, now=now, used_nonces=used)
    check("未知算法 → bad_alg",
          not vua["accepted"] and vua["error"] == "bad_alg")

    # ---- 5. SN 级负向：坏 CHECK / 坏 SN / 未知设备 / 撤销 ------------
    print("\n[5] SN / 密钥库负向")

    # 坏 CHECK（篡改 UNIQUE 使校验失效）→ bad_check
    dev_badcheck = oid.Device(sn=sn3, check="")  # 无校验设备，再手动构造坏 CHECK
    rbc = dev_badcheck.report(level=0, ts=now, seen_routers=seen)
    # 构造一个「有 2 位校验位但校验错」的 SN：给 sn3 追加错误的 Mod97
    fake_sn = sn3 + "-" + "%02d" % ((int(oid.compute_check_mod97(sn3)) + 1) % 97)
    rbc["payload"]["sn"] = fake_sn
    vbc = oid.verify_report(rbc, ks, now=now, used_nonces=used)
    check("坏 CHECK → bad_check",
          not vbc["accepted"] and vbc["error"] == "bad_check",
          f"error={vbc.get('error')}")

    # 未知设备 → unknown_device
    dev_unknown = oid.Device()
    runk = dev_unknown.report(level=0, ts=now, seen_routers=seen)
    vunk = oid.verify_report(runk, ks, now=now, used_nonces=used)
    check("未知设备 → unknown_device",
          not vunk["accepted"] and vunk["error"] == "unknown_device")

    # 撤销 → revoked
    ks.revoke(dev.sn)
    rrev = dev.report(level=0, ts=now, seen_routers=seen)
    vrev = oid.verify_report(rrev, ks, now=now, used_nonces=used)
    check("已撤销设备 → revoked",
          not vrev["accepted"] and vrev["error"] == "revoked")

    # ---- 6. xport 观测（router 侧，不参与验签） ----------------------
    print("\n[6] router xport 观测")
    dev2 = oid.Device()
    ks2 = oid.KeyStore()
    ks2.register(dev2)
    r2x = dev2.report(level=0, ts=now, seen_routers=seen)
    r2x = oid.attach_xport(r2x, "AA:BB:CC:DD:EE:FF", "ORPAHID_ZONE_A", -58)
    vx2 = oid.verify_report(r2x, ks2, now=now, used_nonces=used)
    check("xport 附加后验签仍通过(预像不变)", vx2["accepted"],
          f"trust={vx2.get('trust')}")

    # ---- 汇总 --------------------------------------------------------
    print("\n" + "=" * 50)
    print(f"  结果：{PASS} 通过 / {FAIL} 失败")
    if FAIL == 0:
        print("  🎉 Orpah ID 端到端验收全部通过")
    else:
        print("  ⚠️ 存在失败用例，请检查")
    print("=" * 50)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
