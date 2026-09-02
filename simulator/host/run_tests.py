import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    r = subprocess.run([sys.executable, os.path.join(HERE, "test_sim.py")],
                       capture_output=True, text=True, timeout=60)
    txt = r.stdout + "\n--- stderr ---\n" + r.stderr
except subprocess.TimeoutExpired as e:
    txt = "TIMEOUT\n--- stdout ---\n" + (e.stdout or "") + "\n--- stderr ---\n" + (e.stderr or "")
with open(os.path.join(HERE, "test_results.txt"), "w", encoding="utf-8") as f:
    f.write(txt)
print("returncode", getattr(r, "returncode", "TIMEOUT"))
print("output written to host/test_results.txt")
