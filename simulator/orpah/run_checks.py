#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_checks.py — ORPAH 批量合规测试台：一键跑全部检查 + 出报告

用途（ROADMAP §二「重放/篡改自动化测试台」）：
  一键跑「离线套件 + 批量用例（+ 可选端到端 demo）」，产出可交付的 Markdown 报告
  （含 git HEAD、解释器版本、每套件耗时与结论、失败套件的输出尾部），退出码可直接给 CI 用。

运行：
  python run_checks.py                 # 离线套件 + 批量用例（不占端口，约 30 s）
  python run_checks.py --e2e           # 再跑 5 个端到端 demo（会占 94xx/97xx/98xx 端口，1-3 min）
  python run_checks.py --out r.md      # 报告写到别处（默认 ./checks_report.md）

**为什么默认不跑 e2e**：demo_l1..l4/demo_spoof 用的端口与 orpah-ui（:8901 那一套）会串扰 ——
「跑出来的失败」很可能是端口冲突而不是代码坏了。故 `--e2e` 前会检查 :8901 是否被占用，
被占用就**直接拒绝并提示先停 UI**，不制造假失败。

判定一个套件通过 = 退出码 0 **且** 输出里没有 `FAIL` / `Traceback`
（双条件：有些脚本自己 catch 了异常仍在往下跑，只看退出码会漏）。
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

# (显示名, 脚本, 附加参数) —— 离线套件：不需要硬件、不占对外端口
SUITES = [
    ("运动/定位数据源", "test_motion.py", []),
    ("密钥生命周期", "test_keys.py", []),
    ("防 spoof（离线逐条）", "test_spoof.py", []),
    ("告警规则（含处置态）", "test_alerts.py", []),
    ("指标面板纯计算", "test_metrics.py", []),
    ("时钟可信（ts=0 无 RTC）", "test_clock.py", []),
    ("IoTDB 审计/时间窗", "test_tsdb_audit.py", []),
    ("UI 服务器契约", "test_server.py", []),
    ("批量合规用例（黄金样本/SN 边界/报文）", "checks_batch.py", []),
]
# 端到端 demo：会起模拟器/占端口，默认不跑
E2E = [
    ("L1 端到端", "demo_l1.py", ["--n", "3"]),
    ("L2 消息流", "demo_l2.py", []),
    ("L3 多 Router 漫游/去重", "demo_l3.py", []),
    ("L3b 主动拉表", "demo_l4.py", []),
    ("防 spoof 空口端到端", "demo_spoof.py", []),
]
UI_PORT = 8901              # orpah-ui；被占用时跑 e2e 会端口串扰
TIMEOUT = 420               # 单套件超时（秒）


def port_busy(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def git_head():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE,
                             capture_output=True, text=True, timeout=10)
        return (out.stdout or "").strip() or "-"
    except Exception:
        return "-"


def key_lines(out, limit=6):
    """从输出里挑「有信息量」的行（小节标题 / PASS / FAIL / 结尾总计），给报告用。

    ⚠ **别把纯分隔线当"小节标题"**（2026-09-12 review 发现）：`demo_spoof.py` 的分节横幅
    恰好是四条纯 `=====`，旧逻辑只看 `startswith("==")` 就收 → 整个「关键输出」区块被分隔线
    填满，真正的结论反而看不到。现在要求该行**含实际文字**，并把 PASS/FAIL 行一并收进来。
    """
    lines = [l.rstrip() for l in out.splitlines() if l.strip()]

    def informative(line):
        s = line.strip()
        return bool(s) and not set(s) <= set("=-*•—·")     # 纯装饰行无信息

    picked = [l for l in lines
              if informative(l) and (l.strip().startswith("==")
                                     or l.strip().startswith("---")
                                     or "PASS" in l or "FAIL" in l
                                     or "Traceback" in l)]
    if not picked:
        picked = [l for l in lines if informative(l)][:limit]
    tail = lines[-2:] if len(lines) > 2 else lines
    return picked[:limit] + ([] if not picked or picked[-1] in tail else tail)


def run_suite(label, script, args, e2e=False, verbose=False):
    path = os.path.join(HERE, script)
    if not os.path.isfile(path):
        return {"label": label, "script": script, "ok": False, "secs": 0.0,
                "rc": None, "why": "脚本不存在", "out": "", "keys": []}
    cmd = [sys.executable, script] + args
    print(f"\n=== {label}  ({script} {' '.join(args)})")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
        out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        out, rc = f"(超时 {TIMEOUT}s)", None
    secs = time.time() - t0
    bad_words = [w for w in ("FAIL", "Traceback") if re.search(w, out)]
    ok = rc == 0 and not bad_words
    why = "通过" if ok else (
        f"退出码 {rc}" if rc not in (0, None) else
        ("超时" if rc is None else f"输出含 {','.join(bad_words)}"))
    if verbose or not ok:
        print(out if out.strip() else "(无输出)")
    print(f"--- {label}: {'PASS' if ok else 'FAIL'}  {secs:.1f}s  ({why})")
    return {"label": label, "script": script, "ok": ok, "secs": secs,
            "rc": rc, "why": why, "out": out, "keys": key_lines(out)}


def write_report(path, results, e2e_results, meta):
    ok_n = sum(1 for r in results + e2e_results if r["ok"])
    tot = len(results) + len(e2e_results)
    fails = [r for r in results + e2e_results if not r["ok"]]
    lines = [
        "# ORPAH 批量合规测试报告",
        "",
        f"- 时间：{meta['when']}",
        f"- git HEAD：`{meta['head']}`",
        f"- 解释器：{meta['py']}",
        f"- 结论：**{'全部通过' if not fails else str(len(fails)) + ' 项失败'}**"
        f"（{ok_n}/{tot} 套件通过）",
        "",
        "## 套件结果",
        "",
        "| 套件 | 脚本 | 结果 | 耗时 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for r in results + e2e_results:
        lines.append(f"| {r['label']} | `{r['script']}` | "
                     f"{'✅ PASS' if r['ok'] else '❌ FAIL'} | {r['secs']:.1f}s | {r['why']} |")
    lines += ["", "## 关键输出", ""]
    for r in results + e2e_results:
        lines.append(f"### {r['label']} — {'PASS' if r['ok'] else 'FAIL'}（{r['secs']:.1f}s）")
        lines.append("")
        for k in r["keys"]:
            lines.append(f"    {k}")
        lines.append("")
    if fails:
        lines += ["## 失败详情（输出尾部 40 行）", ""]
        for r in fails:
            lines.append(f"### {r['label']} — {r['why']}")
            lines.append("")
            lines.append("```text")
            lines += r["out"].strip().splitlines()[-40:]
            lines.append("```")
            lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description="ORPAH 批量合规测试台（一键跑 + 出报告）")
    ap.add_argument("--e2e", action="store_true", help="额外跑 5 个端到端 demo（占端口）")
    ap.add_argument("--out", default=os.path.join(HERE, "checks_report.md"),
                    help="报告路径（默认 ./checks_report.md）")
    ap.add_argument("--verbose", action="store_true", help="把每个套件的完整输出都打印出来")
    a = ap.parse_args()

    if a.e2e and port_busy(UI_PORT):
        print(f"[!!] :{UI_PORT} 被占用（orpah-ui 在跑）—— e2e demo 与它端口串扰，"
              f"会跑出假失败。\n     请先停掉 UI（或改用别的端口跑 UI），再执行 --e2e。")
        return 2

    meta = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "head": git_head(),
            "py": f"{sys.version.split()[0]} @ {sys.executable}"}
    print(f"ORPAH 批量合规测试台 · git {meta['head']} · {meta['py']}")
    print(f"离线套件 {len(SUITES)} 个" + (f" + 端到端 {len(E2E)} 个" if a.e2e else "（未含端到端，加 --e2e）"))
    t0 = time.time()
    results = [run_suite(lbl, scr, args, verbose=a.verbose) for lbl, scr, args in SUITES]
    e2e_results = [run_suite(lbl, scr, args, e2e=True, verbose=a.verbose)
                   for lbl, scr, args in E2E] if a.e2e else []
    write_report(a.out, results, e2e_results, meta)

    fails = [r for r in results + e2e_results if not r["ok"]]
    print(f"\n{'=' * 62}")
    for r in results + e2e_results:
        print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['label']:34s} {r['secs']:6.1f}s  {r['why']}")
    print(f"{'=' * 62}")
    print(f"总计 {len(results) + len(e2e_results) - len(fails)}/"
          f"{len(results) + len(e2e_results)} 通过，用时 {time.time() - t0:.1f}s")
    print(f"报告：{a.out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
