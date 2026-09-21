# -*- coding: utf-8 -*-
"""看 `simulator/hardware/wiring/*.svg`（接线图）里的文字与坐标；可和 HEAD 版比。

为什么要有它：那些接线图是**手改过的**（`_byHand` 流程），改完要核两件事 ——
① 文字/丝印有没有被改坏（多了少了）；② 某个标签到底放在哪个坐标。
用 Inkscape 一眼能看，但要**逐条核**（尤其从 HEAD 找回正确版本时）还是脚本快。

用法（在仓库根或任意位置）：
  python simulator/tools/dev/svg_text.py simulator/hardware/wiring/pcpeer-ch347f-nanoch32v203.svg
  python simulator/tools/dev/svg_text.py <同上> --grep P2          # 只看含 P2 的文字
  python simulator/tools/dev/svg_text.py <同上> --diff             # 与本文件 HEAD 版对比增删
  python simulator/tools/dev/svg_text.py <同上> --diff --grep RXD  # 只看相关标签的增删
"""
import argparse
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TEXT = re.compile(r"<text\b([^>]*)>(.*?)</text>", re.S)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def texts(svg):
    """返回 [(纯文字, 属性串)]，保持文档次序。"""
    out = []
    for m in TEXT.finditer(svg):
        attrs = WS.sub(" ", m.group(1)).strip()
        body = WS.sub(" ", TAG.sub("", m.group(2))).strip()
        if body:
            out.append((body, attrs))
    return out


def coord(attrs):
    x = re.search(r"\bx=\"([-0-9.]+)\"", attrs)
    y = re.search(r"\by=\"([-0-9.]+)\"", attrs)
    tr = re.search(r"transform=\"([^\"]*)\"", attrs)
    return (x.group(1) if x else "?", y.group(1) if y else "?",
            tr.group(1) if tr else "-")


def head_version(rel):
    p = subprocess.run(["git", "--no-pager", "-C", ROOT, "show", "HEAD:" + rel],
                       capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser(description="看接线图 svg 的文字与坐标")
    ap.add_argument("svg", help="svg 路径（相对仓库根）")
    ap.add_argument("--grep", default="", help="只看含该子串的文字")
    ap.add_argument("--diff", action="store_true", help="与本文件 HEAD 版对比（新增/删除/坐标变化）")
    args = ap.parse_args()

    path = os.path.join(ROOT, args.svg.replace("/", os.sep)) if not os.path.isabs(args.svg) else args.svg
    if not os.path.isfile(path):
        print("[!!] 文件不存在：", path)
        return 2
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
    now = open(path, "rb").read().decode("utf-8", "replace")
    cur = texts(now)

    def keep(items):
        return [it for it in items if not args.grep or args.grep in it[0]]

    print("文件：%s（%d B，文字 %d 条）" % (rel, len(now), len(cur)))
    print()
    print("=== 文字与坐标（x / y / transform）===")
    for body, attrs in keep(cur):
        x, y, tr = coord(attrs)
        print("  %-28s x=%-9s y=%-9s %s" % (repr(body)[:28], x, y, tr[:40]))

    if args.diff:
        old_svg = head_version(rel)
        if old_svg is None:
            print()
            print("[!] 这个文件在 HEAD 里不存在（新文件），无法对比")
            return 0
        old = keep(texts(old_svg))
        cur_k = keep(cur)
        oset = {t for t, _ in old}
        cset = {t for t, _ in cur_k}
        print()
        print("=== 相对 HEAD 的变化 ===")
        print("  HEAD %d 条 -> 现在 %d 条" % (len(old), len(cur_k)))
        added = [t for t in cset if t not in oset]
        removed = [t for t in oset if t not in cset]
        print("  新增 %d 条:" % len(added))
        for t in added:
            print("   +", repr(t))
        print("  删除 %d 条:" % len(removed))
        for t in removed:
            print("   -", repr(t))
        # 同名但坐标变了
        om = {t: coord(a) for t, a in old}
        cm = {t: coord(a) for t, a in cur_k}
        moved = [(t, om[t], cm[t]) for t in cset & oset if om[t] != cm[t]]
        print("  坐标变化 %d 条:" % len(moved))
        for t, a, b in moved:
            print("   ~ %-24s %s -> %s" % (repr(t)[:24], a[:2], b[:2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
