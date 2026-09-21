# -*- coding: utf-8 -*-
"""文档检查：每个 README 是否「图文并茂」+ 相对链接/图片是否真的存在。

为什么要有它：README 里写坏的相对路径**不会报错**，只是图不显示/链接点不动，
人眼很容易漏掉（本仓库真的踩过：`simulator/tools/ui/README.md` 引 `simulator/docs/*.png`
却写成 `docs/…`，少两层）。所以把这条做成可跑的检查。

用法（在仓库任意位置、任意解释器下都可跑）：
  python simulator/tools/dev/check_docs.py            # 判定：README 有图 + 所有 md 的相对链接都在
  python simulator/tools/dev/check_docs.py --stats    # 只看统计：各 md（含子目录）的图片数
  python simulator/tools/dev/check_docs.py --inline   # 额外提示「反引号里写的仓内路径」是否存在
  python simulator/tools/dev/check_docs.py --all-md   # 非 README 的 md 没图也列出来（不判失败）

判定：退出码 0 = 全过；1 = 有 README 没图，或有坏链接（可直接当检查器用）。
"""
from __future__ import print_function

import argparse
import io
import os
import re
import sys

# Windows 控制台默认 GBK，中文/emoji 会乱码甚至抛 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

# dev/ -> tools/ -> simulator/ -> 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 第三方 / 生成物 / 虚拟环境：不是我们的文档，不参与检查
SKIP_DIRS = {".git", "node_modules", "__pycache__", "build", "out", ".venv", "venv",
             "TXW8301", "nanoCH32V203", "CH32V20xEVT", ".vscode", "images"}

IMG = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b", re.I)
MERMAID = re.compile(r"```mermaid", re.I)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
INLINE = re.compile(r"`([^`\n]*(?:\.md|\.png|\.svg|\.py|\.json|\.cmd|\.txt))`")

# 扫描链接前要剥掉的东西 —— 文档里**教怎么写作**的示例（`[![caption](x.svg)](x.svg)`）
# 不是真链接，不剥就会误报坏链接（本仓库真的被误报过一次）。
FENCE = re.compile(r"^\s*```.*?^\s*```", re.S | re.M)
CODESPAN = re.compile(r"`[^`\n]*`")
HTMLCOMMENT = re.compile(r"<!--.*?-->", re.S)


def strip_examples(text):
    """去掉代码块 / 行内代码 / HTML 注释，剩下的才是真文档正文。"""
    return CODESPAN.sub(" ", HTMLCOMMENT.sub(" ", FENCE.sub(" ", text)))


def md_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def is_readme(p):
    return os.path.basename(p).lower().startswith("readme")


def check_links(p, text):
    """返回 (检查条数, 坏链接列表)。"""
    bad = []
    n = 0
    base = os.path.dirname(p)
    for m in LINK.finditer(text):
        t = m.group(1).split("#")[0].strip()
        if not t or t.startswith(("http://", "https://", "mailto:", "data:")):
            continue
        n += 1
        if not os.path.exists(os.path.join(base, t.replace("/", os.sep))):
            bad.append(t)
    return n, bad


def inline_paths(p, text):
    """反引号里写的路径 —— 只作提示，不判失败（有些是示意写法）。"""
    hints = []
    base = os.path.dirname(p)
    for m in INLINE.finditer(text):
        t = m.group(1).strip()
        if "/" not in t or t.startswith(("http", "python ", "pip ")):
            continue
        if not os.path.exists(os.path.join(base, t.replace("/", os.sep))):
            alt = os.path.exists(os.path.join(ROOT, t.replace("/", os.sep)))
            hints.append((t, "仓根下存在，但相对本文件不存在" if alt else "找不到"))
    return hints


def main():
    ap = argparse.ArgumentParser(description="README 图文并茂 + md 相对链接检查")
    ap.add_argument("--stats", action="store_true", help="只看图片数统计，不做判定")
    ap.add_argument("--inline", action="store_true", help="额外检查反引号里的仓内路径（提示性质）")
    ap.add_argument("--all-md", action="store_true", help="非 README 的 md 没图也列出")
    args = ap.parse_args()

    mds = md_files()
    readmes = [p for p in mds if is_readme(p)]
    nofig = [p for p in mds if is_readme(p)
             and not IMG.search(io.open(p, encoding="utf-8", errors="replace").read())
             and not MERMAID.search(io.open(p, encoding="utf-8", errors="replace").read())]

    if args.stats:
        print("=== 各 md 的图片引用数（仓库根：%s）===" % ROOT)
        for p in mds:
            t = io.open(p, encoding="utf-8", errors="replace").read()
            print("  %-52s 图 %-3d mermaid %-3d %5d 行"
                  % (rel(p), len(IMG.findall(t)), len(MERMAID.findall(t)), t.count("\n") + 1))
        print()
        print("md 文件 %d 个（其中 README %d 个）" % (len(mds), len(readmes)))
        return 0

    print("=== README 是否有图（markdown 图片 / <img> / mermaid）===")
    print("  README 共 %d 个，其中一张图都没有的 %d 个" % (len(readmes), len(nofig)))
    for p in nofig:
        print("   X %s" % rel(p))

    if args.all_md:
        rest = [p for p in mds if not is_readme(p)]
        n = 0
        for p in rest:
            t = io.open(p, encoding="utf-8", errors="replace").read()
            if not IMG.search(t) and not MERMAID.search(t):
                n += 1
                print("   · (非 README，不作要求) %s" % rel(p))
        print("  非 README md %d 个，其中无图 %d 个" % (len(rest), n))

    print()
    print("=== 相对链接 / 图片是否真的存在 ===")
    total_links = 0
    all_bad = []
    for p in mds:
        t = io.open(p, encoding="utf-8", errors="replace").read()
        n, bad = check_links(p, strip_examples(t))
        total_links += n
        for b in bad:
            all_bad.append((rel(p), b))
    print("  md %d 个，相对链接 %d 条，坏 %d 条" % (len(mds), total_links, len(all_bad)))
    for f, b in all_bad:
        print("   X %-46s <- %s" % (b, f))

    if args.inline:
        print()
        print("=== 反引号里的仓内路径（提示，不计入判定）===")
        for p in mds:
            t = io.open(p, encoding="utf-8", errors="replace").read()
            for h, why in inline_paths(p, t):
                print("   · %-46s %-22s <- %s" % (h, why, rel(p)))

    print()
    ok = not nofig and not all_bad
    print("判定：", "通过" if ok else "不通过（见上面 X 行）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
