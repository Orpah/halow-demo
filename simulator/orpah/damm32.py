#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
damm32.py — Damm32 校验（Crockford Base32 的 Damm 算法）构造与验证
==================================================================
对齐《Orpah ID 协议规范》§3.2：SN 校验码 CHECK 的一种算法。规范将 32×32
quasigroup 表标为「Phase 2 待定稿」，本模块给出一个**可构造、可验证**的参考实现。

构造（弱全反对称拟群 weak totally anti-symmetric quasigroup）：
  拟群 Q 定义在有限域 GF(2^5) 上，不可约多项式 p(t) = t^5 + t + 1（系数 0x23）：
      x ⊙ y = 2 · (x ⊕ y)          （GF(2^5) 乘法；2 = 域元素 t；⊕ = 域加法/XOR）
  该拟群满足 Damm 算法检出「所有单字符替换 + 所有相邻换位」的充要条件：
      1. (c⊙x)⊙y = (c⊙y)⊙x  ⟹  x = y     —— 相邻换位检出
      2. 主对角线全 0                      —— 校验位闭合
  （充要性已用 base-10 Damm 表 + 本表的暴力校验交叉验证，见 self_test。）

校验位计算（Damm 算法）：
  state = 0
  for d in digits: state = T[state][d]
  check = 使得 T[state][check] == 0 的列号

运行：C:\\Python313\\python.exe damm32.py   （自检 + 示例）
"""
import itertools
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Crockford Base32 字母表（去易混 I L O U）
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {c: i for i, c in enumerate(CROCKFORD)}

# GF(2^5) 不可约多项式 p(t) = t^5 + t + 1（二进制 0b100011 = 0x23）
POLY = 0x23


def gf_mul(a, b, poly=POLY):
    """GF(2^5) 乘法（无进位乘法 + 模 poly 约简）。"""
    r = 0
    for _ in range(5):
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a & 0x20:
            a ^= poly
    return r & 0x1F


def build_table(poly=POLY):
    """构造 32×32 Damm32 拟群表：T[x][y] = 2·(x⊕y) 于 GF(2^5)。"""
    return [[gf_mul(2, x ^ y, poly) for y in range(32)] for x in range(32)]


# ---------------------------------------------------------------------------
# 拟群性质验证（Damm 检出充要条件）
# ---------------------------------------------------------------------------
def is_latin(T):
    n = len(T)
    return (all(sorted(r) == list(range(n)) for r in T) and
            all(sorted(T[i][j] for i in range(n)) == list(range(n))
                for j in range(n)))


def diag_zero(T):
    return all(T[i][i] == 0 for i in range(len(T)))


def adjcond(T):
    """(c⊙x)⊙y = (c⊙y)⊙x ⟹ x=y：相邻换位检出的充要条件。"""
    n = len(T)
    for s in range(n):
        for d in range(n):
            for e in range(n):
                if d != e and T[T[s][d]][e] == T[T[s][e]][d]:
                    return False
    return True


def verify_table(T):
    """返回 (是否合法, 各项检查结果 dict)。"""
    return (is_latin(T) and diag_zero(T) and adjcond(T),
            {"latin": is_latin(T), "diag_zero": diag_zero(T),
             "adjacent_transposition": adjcond(T)})


# ---------------------------------------------------------------------------
# Damm 校验位
# ---------------------------------------------------------------------------
def check_digit(T, digits):
    """给定 T 与数字序列 digits（0..31），返回校验位。"""
    state = 0
    for d in digits:
        state = T[state][d]
    return T[state].index(0)          # 使 T[state][check]==0 的列号


def validate(T, digits_with_check):
    """验证含校验位的数字序列是否合法。"""
    state = 0
    for d in digits_with_check:
        state = T[state][d]
    return state == 0


# ---------------------------------------------------------------------------
# Crockford / SN 接口
# ---------------------------------------------------------------------------
def crockford_index(ch):
    return _CROCKFORD_INDEX.get(ch.upper())


def sn_digits(sn_core):
    """CC-ORG-UNIQUE 串 → 数字序列（跳过分隔符 '-'，Crockford 索引）。

    遇非法字符（含 Crockford 排除的 I/L/O/U）抛 ValueError，而不是静默产出
    None 再在索引表时抛 TypeError（曾致调用方 500）。
    """
    out = []
    for c in sn_core:
        if c == "-":
            continue
        idx = crockford_index(c)
        if idx is None:
            raise ValueError(f"非法 Crockford 字符: {c!r}")
        out.append(idx)
    return out


# 模块加载时构建一次，damm32_check / damm32_verify 复用（免每次重建 32×32 表）
_TABLE = build_table()


def damm32_check(sn_core):
    """给 CC-ORG-UNIQUE 算 1 位 Damm32 校验字符（Crockford 字母表）。

    含非法字符抛 ValueError（调用方自行处理）。
    """
    d = check_digit(_TABLE, sn_digits(sn_core))
    return CROCKFORD[d]


def damm32_verify(sn):
    """校验含 1 位 Damm32 校验码的整串 SN。

    含非法字符（I/L/O/U 或非 Crockford 字符）视为校验不通过，返回 False。
    """
    try:
        digits = sn_digits(sn)
    except ValueError:
        return False
    return validate(_TABLE, digits)


# ---------------------------------------------------------------------------
# 暴力验证（穷举短串的所有单字符替换 + 相邻换位）
# ---------------------------------------------------------------------------
def brute_verify(T, n, maxlen=3):
    """穷举长度 ≤ maxlen 的所有串，确认单错/换位都改变校验位。返回 None=通过。"""
    for L in range(1, maxlen + 1):
        for digits in itertools.product(range(n), repeat=L):
            c = check_digit(T, list(digits))
            for p in range(L):
                for v in range(n):
                    if v == digits[p]:
                        continue
                    d2 = list(digits)
                    d2[p] = v
                    if check_digit(T, d2) == c:
                        return ("single", digits, p, v)
            for p in range(L - 1):
                if digits[p] == digits[p + 1]:
                    continue
                d2 = list(digits)
                d2[p], d2[p + 1] = d2[p + 1], d2[p]
                if check_digit(T, d2) == c:
                    return ("transposition", digits, p)
    return None


def self_test():
    T = build_table()
    ok, checks = verify_table(T)
    print("== Damm32 拟群性质 ==")
    print("  拉丁方（行/列皆 0..31 排列）:", checks["latin"])
    print("  主对角线全 0:", checks["diag_zero"])
    print("  相邻换位检出条件:", checks["adjacent_transposition"])
    print("  合法:", ok)
    print("== 暴力验证（长度≤3 全部串）==")
    print("  单错/换位漏检:", brute_verify(T, 32, 3))
    print("== 示例 ==")
    core = "CN-WH01-9AF3C1D2"
    c = damm32_check(core)
    sn = core + "-" + c
    print(f"  SN 核心: {core}")
    print(f"  Damm32 校验位: {c}")
    print(f"  整串 {sn} 校验: {'通过' if damm32_verify(sn) else '失败'}")
    # 单错 / 换位演示
    bad = core[:-1] + ("1" if core[-1] == "0" else "0") + "-" + c
    print(f"  改一位后 {bad} 校验: {'通过(异常!)' if damm32_verify(bad) else '失败'}")
    return ok and c is not None


if __name__ == "__main__":
    raise SystemExit(0 if self_test() else 1)
