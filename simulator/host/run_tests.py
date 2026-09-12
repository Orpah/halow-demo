"""run_tests.py — 跑模拟器回归并把结果写入 host/test_results.txt

用法：python run_tests.py     （退出码 = 子进程退出码；同时把「结果: n/m」那行打出来）

注：子进程输出按 **UTF-8** 解读（test_sim.py 已强制 UTF-8 输出）—— Windows 上默认按
GBK 解会在读线程里抛 UnicodeDecodeError，且 stderr 会变成 None（连带断言消息自己炸）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(HERE, "test_results.txt")

try:
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_sim.py")],
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=120)
    txt = (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or "")
    code = r.returncode
except subprocess.TimeoutExpired as e:
    txt = "TIMEOUT\n--- stdout ---\n" + (e.stdout or "") + "\n--- stderr ---\n" + (e.stderr or "")
    code = 2

with open(RESULT, "w", encoding="utf-8", newline="\n") as f:
    f.write(txt)

# 把关键结论回显到终端（以前只 print returncode，得去翻文件才知道过没过）
for line in txt.splitlines():
    if line.startswith("结果:") or "[FAIL]" in line or line.startswith("TIMEOUT"):
        print(line)
print(f"returncode={code}  报告: {os.path.relpath(RESULT, os.path.dirname(HERE))}")
sys.exit(code)
