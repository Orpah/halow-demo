#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mod97.py — Mod 97 校验（IBAN 思路）参考实现
==================================================================
对齐《Orpah ID 协议规范》§3.2：SN 校验码 CHECK 的 2 位兜底算法。
校验位只算 `ORG-UNIQUE`（**不含 CC**；CC=ISO 3166-1 alpha-2，不参与校验）。

字母→数字映射：**IBAN 规则** `A=10, B=11, …, Z=35`（字符序数值，**非** Crockford Base32
索引；二者对 J/K/M/N/P/Q/R/S/T/V/W/X/Y/Z 的取值不同）。
完整校验规则：`N` = 字母数字串（去 `-` 分隔符）按上述映射拼成的十进制数，末尾追加 `"00"`；
`CHECK = 98 − (N mod 97)`，不足两位补零。输出范围 `02`–`98`（不可能为 00/01）。

与 `orpah_id.py` 的 `compute_check_mod97` / `verify_check_mod97` 同算法，
与 `c/mod97.c` 为同一实现（跨语言一致性由 `c/run_cross_test.py` 验证）。

运行：C:\\Python313\\python.exe mod97.py
"""
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _mod97(s):
    """对字母数字串（跳过 '-'）取模 97：字母 A=10..Z=35，数字 0–9。

    小写按大写处理；其它字符（非字母数字、非 '-'）抛 ValueError。
    """
    r = 0
    for ch in s:
        if ch == "-":
            continue
        if "0" <= ch <= "9":
            r = (r * 10 + (ord(ch) - 48)) % 97
        elif "A" <= ch <= "Z":
            r = (r * 100 + (ord(ch) - 55)) % 97
        elif "a" <= ch <= "z":
            r = (r * 100 + (ord(ch.upper()) - 55)) % 97
        else:
            raise ValueError(f"非法字符: {ch!r}")
    return r


def mod97_check(org_unique):
    """给 ORG-UNIQUE（不含 CC）算 2 位 Mod97 校验码（输出 02–98）。

    含非法字符抛 ValueError（调用方自行处理）。
    """
    return "%02d" % (98 - _mod97(org_unique + "00"))


def mod97_verify(org_unique_check):
    """校验 ORG-UNIQUE-CHECK（不含 CC，含 2 位校验码）。

    含非法字符视为校验不通过，返回 False。
    """
    try:
        return _mod97(org_unique_check) == 1
    except ValueError:
        return False


def self_test():
    org_unique = "WH01-9AF3C1D2"          # ORG-UNIQUE（不含 CC）
    c = mod97_check(org_unique)
    body = org_unique + "-" + c
    ok = mod97_verify(body)
    bad = org_unique[:-1] + ("1" if org_unique[-1] == "0" else "0") + "-" + c
    bad_ok = mod97_verify(bad)
    print("== Mod97 示例 ==")
    print(f"  ORG-UNIQUE: {org_unique}")
    print(f"  Mod97 校验位: {c}")
    print(f"  ORG-UNIQUE-CHECK {body} 校验: {'通过' if ok else '失败'}")
    print(f"  整串 SN: CN-{body}（CC=CN 固定，样例统一用 CN）")
    print(f"  改一位后 {bad} 校验: {'通过(异常!)' if bad_ok else '失败 ✓（单错检出）'}")
    return ok and not bad_ok and c == "21"


if __name__ == "__main__":
    raise SystemExit(0 if self_test() else 1)
