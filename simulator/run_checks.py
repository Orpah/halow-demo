#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_checks.py — halow-demo（空口 / 设备侧）一键自检

    python simulator/run_checks.py

三套件，全部**不需要硬件、不需要第三方依赖**：

  1. 模拟器回归 —— `host/run_tests.py`（AT / 自动连接 / 数据转发 / 配对 /
     family=tah 方言 / 串口空口 / **host 数据口**）→ 结果写 `host/test_results.txt`
  2. 界面文案字典 —— `tools/ui/chk_i18n.py`（zh/en 键集一致 + 每个键恰好两次 +
     页面引用的键都在字典里）
  3. 静态检查 —— 全部 `.py` 可编译、全部 `.js` 过 `node --check`、全部 `.json` 可解析、
     `.vscode/tasks.json` 任务自洽（label 唯一 + 本仓路径都存在）、
     `simulator/.gitignore` 覆盖 `__pycache__`

判定 = **退出码 0 且输出无 `FAIL` / `Traceback`**（有些脚本自己吞异常还继续往下跑）。
报告写到 `simulator/checks_report.md`（入库，便于"上次是不是全绿"）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # simulator/
REPO = os.path.dirname(HERE)                               # 仓库根
REPORT = os.path.join(HERE, "checks_report.md")
PY = sys.executable or "python"

SUITES = [
    ("模拟器回归（AT/连接/转发/配对/串口空口/host 数据口）",
     [os.path.join(HERE, "host", "run_tests.py")]),
    ("界面文案字典（zh/en 对齐 + 页面引用无缺失）",
     [os.path.join(HERE, "tools", "ui", "chk_i18n.py")]),
]

SKIP_DIRS = {"__pycache__", ".git", "node_modules"}


def _walk(ext):
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(ext):
                yield os.path.join(root, f)


def head_sha():
    try:
        r = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                           capture_output=True, encoding="utf-8", errors="replace")
        return (r.stdout or "").strip() or "(非 git 仓库)"
    except OSError:
        return "(取不到)"


# ---------------------------------------------------------------------------
# 套件 1/2：跑子脚本
# ---------------------------------------------------------------------------
def run_script(path):
    t0 = time.time()
    r = subprocess.run([PY, path], cwd=os.path.dirname(path),
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=180)
    out = (r.stdout or "") + (("\n--- stderr ---\n" + r.stderr) if r.stderr else "")
    ok = (r.returncode == 0) and not re.search(r"\bFAIL\b|Traceback", out)
    return ok, time.time() - t0, out, r.returncode


# ---------------------------------------------------------------------------
# 套件 3：静态检查（内联；全部细节都收进报告）
# ---------------------------------------------------------------------------
def static_checks():
    problems = []
    notes = []

    # (a) Python 可编译（语法错会在真机/演示时才炸，代价很高）
    r = subprocess.run([PY, "-m", "compileall", "-q", HERE],
                       capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        problems.append("compileall 失败：\n" + (r.stdout or "") + (r.stderr or ""))
    notes.append("py_compile: %d 个文件" % sum(1 for _ in _walk(".py")))

    # (b) JS 过 node --check（LuCI/页面脚本语法错在浏览器里才暴露）
    node = shutil.which("node") or shutil.which("node.exe")
    js = sorted(_walk(".js"))
    if not node:
        notes.append("node --check: **跳过**（本机没装 node），共 %d 个 .js 未检查" % len(js))
    else:
        for p in js:
            r = subprocess.run([node, "--check", p],
                               capture_output=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                problems.append("node --check 失败：%s\n%s" % (p, (r.stderr or "").strip()))
        notes.append("node --check: %d 个 .js" % len(js))

    # (c) JSON 可解析
    jsons = sorted(list(_walk(".json")) + [os.path.join(REPO, ".vscode", "tasks.json")])
    bad = []
    for p in jsons:
        try:
            json.loads(open(p, encoding="utf-8").read())
        except (OSError, ValueError) as e:
            bad.append("%s: %s" % (p, e))
    if bad:
        problems.append("JSON 解析失败：\n" + "\n".join(bad))
    notes.append("JSON: %d 个" % len(jsons))

    # (d) tasks.json 自洽：label 唯一、引用的**本仓**路径都存在
    #     （本仓曾积累 239 个任务、其中 231 个指向已迁出的 simulator/orpah —— 靠这条守住）
    tp = os.path.join(REPO, ".vscode", "tasks.json")
    if os.path.isfile(tp):
        try:
            tasks = json.load(open(tp, encoding="utf-8"))["tasks"]
        except (OSError, ValueError, KeyError) as e:
            tasks = []
            problems.append("tasks.json 读不出 tasks：%s" % e)
        labels = [t.get("label") for t in tasks]
        dup = sorted({x for x in labels if labels.count(x) > 1})
        if dup:
            problems.append("tasks.json 有重复 label：%s" % dup)
        for t in tasks:
            if not t.get("label") or not t.get("type"):
                problems.append("tasks.json 任务缺 label/type：%r" % (t.get("label"),))
            blob = json.dumps(t, ensure_ascii=False).replace("\\\\", "\\")
            for m in re.findall(r"[A-Za-z]:\\[^\"']*?(?=[\"'\s,;|]|$)", blob):
                p = m.rstrip("\\")
                if p.lower().startswith(REPO.lower()) and not os.path.exists(p):
                    problems.append("tasks.json 的 %s 引用了不存在的本仓路径：%s"
                                    % (t.get("label"), p))
        notes.append("tasks.json: %d 个任务" % len(tasks))

    # (e) .gitignore 覆盖字节码（迁出子集时规则不跟着走会把 .pyc 吃进库 —— 上游踩过）
    gi = os.path.join(HERE, ".gitignore")
    txt = open(gi, encoding="utf-8", errors="replace").read() if os.path.isfile(gi) else ""
    for pat in ("__pycache__/", "*.pyc"):
        if pat not in txt:
            problems.append("simulator/.gitignore 缺少 %s" % pat)

    ok = not problems
    out = ("说明：\n  " + "\n  ".join(notes)
           + ("\n\n问题：\n  " + "\n  ".join(problems) if problems else "\n\n无问题。"))
    return ok, out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                  # noqa: BLE001
            pass

    print("=" * 72)
    print("halow-demo 自检（空口/设备侧）  HEAD=%s  python=%s"
          % (head_sha(), sys.version.split()[0]))
    print("=" * 72)

    results = []
    for title, cmds in SUITES:
        print("\n### %s" % title)
        ok, secs = True, 0.0
        outs = []
        for cmd in cmds:
            if not os.path.isfile(cmd):
                ok, out, code = False, "套件文件不存在：%s" % cmd, 127
            else:
                ok_i, dt, out, code = run_script(cmd)
                ok = ok and ok_i
                secs += dt
            outs.append(out)
            for line in out.splitlines():
                if re.search(r"\[FAIL\]|结果:|^FAIL|OK$|Traceback", line):
                    print("  " + line.strip())
        print("  → %s（%.2fs）" % ("通过" if ok else "**失败**", secs))
        results.append((title, ok, secs, "\n".join(outs)))

    t0 = time.time()
    ok, out = static_checks()
    secs = time.time() - t0
    print("\n### 静态检查（py/js/json/tasks/gitignore）")
    for line in out.splitlines():
        if line.startswith(("问题", "  py_", "  node", "  JSON", "  tasks")):
            print("  " + line.strip())
    print("  → %s（%.2fs）" % ("通过" if ok else "**失败**", secs))
    results.append(("静态检查（py/js/json/tasks/gitignore）", ok, secs, out))

    passed = sum(1 for r in results if r[1])
    total = len(results)

    lines = ["# halow-demo 自检报告（空口/设备侧）", "",
             "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "- HEAD：`%s`" % head_sha(),
             "- Python：%s" % sys.version.split()[0],
             "- 结果：**%d/%d 通过**" % (passed, total), "",
             "> 全部套件都不需要硬件与第三方依赖；模拟器回归的结果同时写进",
             "> `host/test_results.txt`（历史一直如此，便于对照）。", "",
             "| 套件 | 结果 | 用时 |", "|---|---|---|"]
    for title, ok_i, secs_i, _ in results:
        lines.append("| %s | %s | %.2fs |" % (title, "通过" if ok_i else "失败", secs_i))
    for title, _ok, _secs, out in results:
        lines += ["", "## %s" % title, "", "```", out.strip() or "(无输出)", "```"]
    lines.append("")
    with open(REPORT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print("\n" + "=" * 72)
    print("结果：%d/%d 通过；报告 → %s" % (passed, total, os.path.relpath(REPORT, REPO)))
    print("=" * 72)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
