#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
luhn32.py — Luhn mod 32 校验（Crockford Base32）参考实现
==================================================================
对齐《Orpah ID 协议规范》§3.2：SN 校验码 CHECK 的 1 位兜底算法之一。
校验位只算 `ORG-UNIQUE`（**不含 CC**；CC=ISO 3166-1 alpha-2，不套 Crockford 限制）。

算法：Luhn（从右往左隔位翻倍），模 32。检出大部分单错与相邻换位。
与 `orpah_id.py` 的 `compute_check_luhn32` / `verify_check_luhn32` 同算法，
与 `c/luhn32.c` 为同一实现（跨语言一致性由 `c/run_cross_test.py` 验证）。

运行：C:\\Python313\\python.exe luhn32.py
"""
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Crockford Base32 字母表（去易混 I L O U）
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {c: i for i, c in enumerate(CROCKFORD)}


def crockford_index(ch):
    """Crockford 字符 → 0–31；非法字符（含 I/L/O/U）返回 None。"""
    if not isinstance(ch, str) or len(ch) != 1:
        return None
    return _CROCKFORD_INDEX.get(ch.upper())


def crockford_encode(n):
    """0–31 → Crockford 字符。"""
    if not 0 <= n < 32:
        raise ValueError("crockford_encode: n must be 0..31")
    return CROCKFORD[n]


def sn_digits(org_unique):
    """ORG-UNIQUE 串（不含 CC）→ 数字序列（跳过分隔符 '-'，Crockford 索引）。

    遇非法字符（含 Crockford 排除的 I/L/O/U）抛 ValueError。
    """
    out = []
    for c in org_unique:
        if c == "-":
            continue
        idx = crockford_index(c)
        if idx is None:
            raise ValueError(f"非法 Crockford 字符: {c!r}")
        out.append(idx)
    return out


def luhn_sum(digits):
    """Luhn 校验和（从右往左隔位翻倍，模 32）。"""
    s = 0
    double = False
    for d in reversed(digits):
        if double:
            d2 = d * 2
            s += d2 // 32 + d2 % 32
        else:
            s += d
        double = not double
    return s


def luhn32_check(org_unique):
    """给 ORG-UNIQUE（不含 CC）算 1 位 Luhn32 校验字符（Crockford 字母表）。

    含非法字符抛 ValueError（调用方自行处理）。
    """
    digits = sn_digits(org_unique)
    for c in range(32):
        if luhn_sum(digits + [c]) % 32 == 0:
            return crockford_encode(c)
    return "0"  # 理论不可达


def luhn32_verify(org_unique_check):
    """校验 ORG-UNIQUE-CHECK（不含 CC，含 1 位校验码）。

    含非法字符（I/L/O/U 或非 Crockford 字符）视为校验不通过，返回 False。
    """
    try:
        digits = sn_digits(org_unique_check)
    except ValueError:
        return False
    return luhn_sum(digits) % 32 == 0


def self_test():
    org_unique = "WH01-9AF3C1D2"          # ORG-UNIQUE（不含 CC）
    c = luhn32_check(org_unique)
    body = org_unique + "-" + c
    ok = luhn32_verify(body)
    bad = org_unique[:-1] + ("1" if org_unique[-1] == "0" else "0") + "-" + c
    bad_ok = luhn32_verify(bad)
    print("== Luhn32 示例 ==")
    print(f"  ORG-UNIQUE: {org_unique}")
    print(f"  Luhn32 校验位: {c}")
    print(f"  ORG-UNIQUE-CHECK {body} 校验: {'通过' if ok else '失败'}")
    print(f"  整串 SN: CN-{body}（CC=CN 固定，样例统一用 CN）")
    print(f"  改一位后 {bad} 校验: {'通过(异常!)' if bad_ok else '失败 ✓（单错检出）'}")
    return ok and not bad_ok and c == "E"


if __name__ == "__main__":
    raise SystemExit(0 if self_test() else 1)
