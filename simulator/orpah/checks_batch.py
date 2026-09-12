#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checks_batch.py — 表驱动的批量合规用例（黄金样本 / SN 边界 / 解析 / 报文编解码）

为什么单独一个文件：`test_*.py` 是**按模块**逐个验（顺手写断言），这里是**表驱动**地
把「边界取值 → 期望结果」铺开跑 —— 两类互补，别互相抄。
**算法全部调既有单一源**（`damm32` / `luhn32` / `mod97` / `orpah_proto` / `registry`），
本文件只提供**用例表**，不重新实现任何算法（否则就是给自己造第二个真相）。

被 `run_checks.py` 调用，也可单独跑：C:\\Python313\\python.exe checks_batch.py
"""
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import damm32                                    # noqa: E402
import luhn32                                    # noqa: E402
import mod97                                     # noqa: E402
import orpah_proto as P                          # noqa: E402
from registry import parse_sn                    # noqa: E402

FAILS = []


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name + (f"  [{extra}]" if extra else ""))


# ---------------------------------------------------------------------------
print("== 1. 黄金样本（校验位只算 ORG-UNIQUE，不含 CC）==")
GOLD_ORG_UNIQUE = "WH01-9AF3C1D2"          # 黄金样本的 ORG-UNIQUE 部分
GOLD_SN = "CN-" + GOLD_ORG_UNIQUE
GOLD = {"damm32": "B", "luhn32": "E", "mod97": "21"}   # 《Orpah ID 协议规范》v1.7 黄金样本

ck("黄金样本 SN 语法合法", P.sn_ok(GOLD_SN), GOLD_SN)
ck("黄金样本 SN 无错", P.sn_err(GOLD_SN) is None)
ck("damm32 校验位 == B", damm32.damm32_check(GOLD_ORG_UNIQUE) == GOLD["damm32"],
   damm32.damm32_check(GOLD_ORG_UNIQUE))
ck("luhn32 校验位 == E", luhn32.luhn32_check(GOLD_ORG_UNIQUE) == GOLD["luhn32"],
   luhn32.luhn32_check(GOLD_ORG_UNIQUE))
ck("mod97 校验位 == 21", mod97.mod97_check(GOLD_ORG_UNIQUE) == GOLD["mod97"],
   mod97.mod97_check(GOLD_ORG_UNIQUE))
ck("三种算法 verify 都通过",
   damm32.damm32_verify(GOLD_ORG_UNIQUE + "-B")
   and luhn32.luhn32_verify(GOLD_ORG_UNIQUE + "-E")
   and mod97.mod97_verify(GOLD_ORG_UNIQUE + "-21"))

# 语义断言：把 CC 混进校验输入 → 结果必须变（否则说明实现偷偷算了 CC）
ck("校验输入不含 CC（把 CC 拼进去结果就不同）",
   damm32.damm32_check("CN" + GOLD_ORG_UNIQUE) != GOLD["damm32"]
   and luhn32.luhn32_check("CN" + GOLD_ORG_UNIQUE) != GOLD["luhn32"]
   and mod97.mod97_check("CN" + GOLD_ORG_UNIQUE) != GOLD["mod97"])

# 单字符改动必须被检出（每个算法都要能挡下来）
for algo, verify, org_unique_check in (
        ("damm32", damm32.damm32_verify, GOLD_ORG_UNIQUE + "-B"),
        ("luhn32", luhn32.luhn32_verify, GOLD_ORG_UNIQUE + "-E"),
        ("mod97", mod97.mod97_verify, GOLD_ORG_UNIQUE + "-21")):
    bad = org_unique_check.replace("9AF3", "9AF4")
    ck(f"{algo}：改一位后校验失败（单错检出）", verify(bad) is False, bad)

# 相邻换位也必须被检出（Damm/Luhn 的设计目标之一）
ck("damm32：相邻换位被检出",
   damm32.damm32_verify("WH01-9A3FC1D2-B") is False
   and damm32.damm32_verify(GOLD_ORG_UNIQUE + "-B") is True)
ck("luhn32：相邻换位被检出",
   luhn32.luhn32_verify("WH01-9A3FC1D2-E") is False
   and luhn32.luhn32_verify(GOLD_ORG_UNIQUE + "-E") is True)

# ---------------------------------------------------------------------------
print("== 2. SN 边界（格式：CC-ORG-UNIQUE[-CHECK]，Crockford Base32 去 I L O U）==")
# (sn, 期望 sn_err 结果；None = 合法)
SN_CASES = [
    (GOLD_SN, None, "黄金样本"),
    (GOLD_SN + "-B", None, "带 1 位校验码"),
    (GOLD_SN + "-B0", None, "带 2 位校验码"),
    ("CN-AB-01234567", None, "ORG 最短 2 位、UNIQUE 最短 8 位"),
    ("CN-ABCDEF-0123456789ABCDEF", None, "ORG 最长 6 位、UNIQUE 最长 16 位"),
    ("CN-AB-01234567-B0", None, "长度 18+3"),
    ("CN-" + "A" * 6 + "-" + "0" * 16 + "-B0", None, "恰好 SN_MAX_LEN 附近"),
    (None, "empty", "None"),
    ("", "empty", "空串"),
    (123, "empty", "非字符串"),
    ("CN-WH01-9AF3C1D2-X" + "0" * 32, "too-long", f"超过 {P.SN_MAX_LEN} 字符"),
    ("cn-wh01-9af3c1d2", "bad-format", "小写 CC（CC 必须大写 A-Z）"),
    ("C-WH01-9AF3C1D2", "bad-format", "CC 只 1 位"),
    ("CHN-WH01-9AF3C1D2", "bad-format", "CC 有 3 位"),
    ("C1-WH01-9AF3C1D2", "bad-format", "CC 含数字"),
    ("CN-A-01234567", "bad-format", "ORG 只 1 位"),
    ("CN-ABCDEFG-01234567", "bad-format", "ORG 有 7 位"),
    ("CN-AB-0123456", "bad-format", "UNIQUE 只 7 位"),
    ("CN-AB-0123456789ABCDEFG", "bad-format", "UNIQUE 有 17 位"),
    ("CN-WH0I-9AF3C1D2", "bad-format", "含 Crockford 排除字符 I"),
    ("CN-WH0L-9AF3C1D2", "bad-format", "含排除字符 L"),
    ("CN-WH0O-9AF3C1D2", "bad-format", "含排除字符 O"),
    ("CN-WH0U-9AF3C1D2", "bad-format", "含排除字符 U"),
    ("CN-小明-9AF3C1D2", "bad-format", "中文不进 SN"),
    ("CN-WH01-9AF3C1D2-B-C", "bad-format", "多一段（校验最多 2 位且不分两段）"),
    ("CN-WH01-9AF3C1D2-", "bad-format", "分隔符结尾无校验位"),
    ("CNWH019AF3C1D2", "bad-format", "缺分隔符"),
    ("CN-WH01-9AF3C1D2-!", "bad-format", "非法字符"),
    (" CN-WH01-9AF3C1D2", "bad-format", "前导空格"),
]
for sn, want, why in SN_CASES:
    got = P.sn_err(sn)
    ck(f"sn_err({sn!r}) == {want}  ({why})", got == want, f"got={got!r}")
ck("sn_ok 与 sn_err 互为一致（合法 ⟺ 无错）",
   all(P.sn_ok(sn) == (P.sn_err(sn) is None) for sn, _, _ in SN_CASES))

# ---------------------------------------------------------------------------
print("== 3. SN 解析（注册时按 SN 回填 cc/org，不信任前端传值）==")
for sn, want, why in [
        (GOLD_SN, {"cc": "CN", "org": "WH01", "unique": "9AF3C1D2", "check": ""}, "无校验位"),
        (GOLD_SN + "-B", {"cc": "CN", "org": "WH01", "unique": "9AF3C1D2", "check": "B"}, "1 位校验位"),
        ("ZZ-AB-01234567", {"cc": "ZZ", "org": "AB", "unique": "01234567", "check": ""},
         "语法合法但未登记国（解析仍给出 CC，是否受理由业务决定）"),
        ("CN-小明-9AF3C1D2", None, "中文 SN 解析失败"),
        ("", None, "空串解析失败")]:
    got = parse_sn(sn)
    ck(f"parse_sn({sn!r})  ({why})", got == want, f"got={got!r}")

# ---------------------------------------------------------------------------
print("== 4. 报文编解码边界（通用 JSON 公共头）==")
msg = P.build_report(GOLD_SN, rssi=-55, seq=7)
raw = P.encode_msg(msg)
ck("REPORT 往返一致", P.decode_msg(raw) == msg)
ck("decode_msg：非 JSON → None", P.decode_msg(b"not json") is None)
ck("decode_msg：JSON 但缺 type → None", P.decode_msg(b'{"v":1}') is None)
ck("decode_msg：未知 type → None", P.decode_msg(b'{"v":1,"type":"ORPAH-NOPE"}') is None)
ck("encode_msg：单行（不含换行）", b"\n" not in raw)
ck("encode_msg：UTF-8 中文直出（ensure_ascii=False）", "小明" in P.encode_msg({"n": "小明"}).decode("utf-8"))
eth = P.build_eth_frame(raw, src_mac=b"\x02\x00\x00\x00\x00\x01")
ck("以太网帧：默认目的 = 广播", eth[:6] == b"\xff" * 6)
ck("以太网帧：ethertype 解析回来一致", P.parse_eth_frame(eth)[0] == P.ORPAH_ETHERTYPE)
ck("以太网帧：payload 往返一致", P.parse_eth_frame(eth)[1] == raw)
ck("parse_eth_frame：长度不足 → None", P.parse_eth_frame(b"\x00" * 13) is None)
ck("parse_eth_frame：ethertype 不符 → None",
   P.parse_eth_frame(b"\xff" * 6 + b"\x00" * 6 + b"\x08\x00" + b"x") is None)

# ---------------------------------------------------------------------------
print()
if FAILS:
    print(f"批量用例：{len(FAILS)} 项失败")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("批量用例：全部通过")
