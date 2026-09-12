#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chk_i18n.py — 本 UI 的文案字典自检（`static/ui_i18n.js` ↔ 页面引用）

2026-09-12：字典原来是"与 orpah demo 共用的一份"，现在**本项目自持一份**
（只留本 UI 用到的 key，见提交历史里的拆分脚本与归属判据）。这个脚本防止拆完之后
"页面引用了字典里没有的 key"（页面上会直接显示成 key 名，切英文时尤其明显）。

用法：python chk_i18n.py            # 退出码 0 = 通过
"""
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DICT = os.path.join(STATIC, "ui_i18n.js")

# key 字符集要放宽：字典里还有 AT 帮助键（`qt:AT+RST` / `at:def:AT+MODE=` / `at:v2:AT+PING=`）
RE_KEY = re.compile(r'^\s*"([^"]+)"\s*:', re.M)
RE_STR = re.compile(r'''(["\'])((?:\\.|(?!\1)[^\\\n])*)\1''')

FAILS = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("   " + str(extra)) if not cond else ""))
    if not cond:
        FAILS.append(name)


txt = open(DICT, encoding="utf-8").read()
lines = txt.split("\n")
i_zh = next(i for i, l in enumerate(lines) if l.strip().startswith("zh: {"))
i_en = next(i for i, l in enumerate(lines) if l.strip().startswith("en: {"))
zh = [RE_KEY.match(l).group(1) for l in lines[i_zh + 1:i_en] if RE_KEY.match(l)]
en = [RE_KEY.match(l).group(1) for l in lines[i_en + 1:] if RE_KEY.match(l)]
keys = set(zh) | set(en)

check("字典 zh/en key 集合一致（%d / %d）" % (len(set(zh)), len(set(en))), set(zh) == set(en),
      sorted(set(zh) ^ set(en)))
check("每个 key 恰好 2 次（zh + en）", len(zh) + len(en) == 2 * len(keys),
      "zh %d + en %d vs %d" % (len(zh), len(en), 2 * len(keys)))

refs, prefs, nfiles = set(), set(), 0
for fn in sorted(os.listdir(STATIC)):
    if fn == "ui_i18n.js" or not fn.endswith((".html", ".js")):
        continue
    nfiles += 1
    blob = open(os.path.join(STATIC, fn), encoding="utf-8").read()
    refs |= set(re.findall(r'data-i18n(?:-title|-ph|-doc-title)?\s*=\s*"([^"]+)"', blob))
    refs |= set(re.findall(r'(?:\bT|\bt|\bfmt|tOr)\(\s*"([^"]+)"', blob))
    # 前缀候选：正确配对的字符串字面量（`tOr("conn_", v)` / `"at:" + lib + ":" + cmd`）
    prefs |= {m.group(2) for m in RE_STR.finditer(blob)}

fams = set()
for p in prefs:
    if p in keys:
        continue
    ok = ("_" in p and len(p) >= 4) or (":" in p and len(p) >= 3)
    # 宁洒毋漏：前缀门槛放宽只会“多留几个 key”（无害），
    # 而收窄会导致“页面引用的 key 不在字典里”（页面上直接显示成 key 名）。
    # 例：halow 主 UI 的 `tOr("pow_", s.power, null)` —— pow_ 只有 4 个字符。
    if not ok:
        continue
    fam = {k for k in keys if k.startswith(p)}
    if len(fam) >= 2:
        fams.add(p)
        refs |= fam

missing = sorted(refs - keys - fams)
check("扫描 %d 个页面/脚本，引用 %d 个 key（动态前缀家族 %d 个）"
      % (nfiles, len(refs), len(fams)), nfiles > 0)
check("页面引用的 key 全部在字典里", not missing, missing)

print()
if FAILS:
    print("文案字典：%d 项失败：%s" % (len(FAILS), "；".join(FAILS)))
    raise SystemExit(1)
print("文案字典：全部通过（%d 个 key，引用 %d 个）" % (len(keys), len(refs)))
