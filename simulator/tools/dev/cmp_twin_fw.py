# -*- coding: utf-8 -*-
"""比对「同一个固件的两份独立副本」：`halow-demo/simulator/firmware` ↔ `orpah-client-demo/firmware`。

为什么要有它：这两份是**故意不抽公共库、不做 submodule** 的独立副本（见
`orpah-client-demo/AGENTS.md` §1），规矩是「**在一侧发现的平台层 bug，改完要在另一侧也改掉**」。
但两侧大多文件本来就该不同（业务/状态机不同），所以需要一眼看出「哪些同、哪些不同」。

★ 标记的 7 个文件是 AGENTS 点名的**平台层**（链接脚本/启动文件/串口驱动）：
  ld/link.ld  startup/startup_ch32v203.S  Core/ch32v20x.h
  Periph/gpio.c  Periph/gpio.h  Periph/uart.c  Periph/uart.h
（2026-09-21 就是这么回灌的：链接基址 0x0、IRQn 偏移、mstatus MPP、TIM INTFR。）

⚠ 口径（2026-09-22 用户明确）：两侧**功能本来就不同**（一边模拟器固件、一边客户端固件），
所以这些文件**不一致是正常的**。★ 的含义只是「平台层的修复要在两侧都落地」，
**不是**「要逐字节相同」—— 要盯的是「别漏回灌」，不是「必须一模一样」；
下面同名一致的才意味着「两边真的没改动」。

用法（在 halow-demo 仓库里跑）：
  python simulator/tools/dev/cmp_twin_fw.py              # 汇总表（同/不同/只在一边）
  python simulator/tools/dev/cmp_twin_fw.py --diff       # 再打印不同文件的前若干行 diff
  python simulator/tools/dev/cmp_twin_fw.py --other D:\\path\\to\\firmware
"""
import argparse
import difflib
import hashlib
import os
import sys

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HERE = os.path.join(ROOT, "simulator", "firmware")          # 本仓这侧
DEFAULT_OTHER = os.path.join(os.path.dirname(ROOT), "orpah-client-demo", "firmware")
PLATFORM = {
    "ld/link.ld", "startup/startup_ch32v203.S", "Core/ch32v20x.h",
    "Periph/gpio.c", "Periph/gpio.h", "Periph/uart.c", "Periph/uart.h",
}
EXTS = (".c", ".h", ".s", ".S", ".ld", ".mk")
SKIP_DIRS = {"build", ".git", "__pycache__"}


def collect(base):
    out = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not (fn.endswith(EXTS) or fn in ("Makefile", "makefile")):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            out[rel] = p
    return out


def norm_bytes(p):
    with open(p, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def short(b):
    return hashlib.sha1(b).hexdigest()[:8]


def main():
    ap = argparse.ArgumentParser(description="比对固件两份副本")
    ap.add_argument("--here", default=HERE, help="本仓这侧（默认 simulator/firmware）")
    ap.add_argument("--other", default=DEFAULT_OTHER, help="另一侧（默认 ../orpah-client-demo/firmware）")
    ap.add_argument("--diff", action="store_true", help="打印不同文件的行级 diff（每份最多 30 行）")
    ap.add_argument("--only-platform", action="store_true", help="只看平台层 7 个文件")
    args = ap.parse_args()

    for name, base in (("本仓", args.here), ("另一侧", args.other)):
        if not os.path.isdir(base):
            print("[!!] %s 目录不存在：%s" % (name, base))
            return 2
    print("本仓  :", args.here)
    print("另一侧:", args.other)
    print()

    a, b = collect(args.here), collect(args.other)
    rels = sorted(set(a) | set(b))
    if args.only_platform:
        rels = [r for r in rels if r in PLATFORM]

    same, diff, only_a, only_b = [], [], [], []
    for rel in rels:
        if rel not in a:
            only_b.append(rel)
        elif rel not in b:
            only_a.append(rel)
        else:
            ba, bb = norm_bytes(a[rel]), norm_bytes(b[rel])
            (same if ba == bb else diff).append((rel, ba, bb))

    print("=== 平台层（★ 只意味着「平台层修复要两侧都落地」；两侧功能不同 ⇒ 不一致正常）===")
    for rel in sorted(PLATFORM):
        tag = "★"
        if rel in a and rel in b:
            ba, bb = norm_bytes(a[rel]), norm_bytes(b[rel])
            print("  %s %-30s 本仓 %s  另一侧 %s  %s"
                  % (tag, rel, short(ba), short(bb), "一致" if ba == bb else "不同"))
        elif rel in a:
            print("  %s %-30s 只在**本仓**有" % (tag, rel))
        elif rel in b:
            print("  %s %-30s 只在**另一侧**有" % (tag, rel))
        else:
            print("  %s %-30s 两侧都没有（路径变了？）" % (tag, rel))
    if args.only_platform:
        return 0

    print()
    print("=== 汇总（只比两侧同名文件）===")
    print("  同名一致 %d 个 / 同名不同 %d 个 / 只在本仓 %d 个 / 只在另一侧 %d 个"
          % (len(same), len(diff), len(only_a), len(only_b)))
    if diff:
        print("  不同的文件：")
        for rel, ba, bb in diff:
            print("   D %-34s 本仓 %s (%d 行)  另一侧 %s (%d 行)"
                  % (rel, short(ba), ba.count(b"\n") + 1, short(bb), bb.count(b"\n") + 1))
    if only_a:
        print("  只在本仓：", ", ".join(only_a))
    if only_b:
        print("  只在另一侧：", ", ".join(only_b))

    if args.diff and diff:
        for rel, ba, bb in diff:
            print()
            print("=" * 74)
            print("== %s" % rel)
            print("=" * 74)
            d = difflib.unified_diff(
                ba.decode("utf-8", "replace").split("\n"),
                bb.decode("utf-8", "replace").split("\n"),
                "本仓/" + rel, "另一侧/" + rel, n=1, lineterm="")
            n = 0
            for line in d:
                if line.startswith("@@"):
                    n += 1
                    if n > 3:
                        print("   …（还有更多，略）")
                        break
                print(line[:140])
    return 0


if __name__ == "__main__":
    sys.exit(main())
