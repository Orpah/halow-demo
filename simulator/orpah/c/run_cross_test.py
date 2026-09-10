#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_cross_test.py — Damm32 跨语言一致性测试（Python vs C）

用 Python 参考实现（../damm32.py）生成测试向量（黄金值）写入 test_vectors.txt，
编译 C 参考实现（damm32.c），然后：

  1. C `selftest`   —— 读向量文件，内部重算校验字符并验证，比对黄金值；
  2. C `batch`      —— 一次性把全部 ORG-UNIQUE 喂给 C，逐行比对 C 校验位 vs Python 校验位；
  3. C `verify`     —— 对黄金样本 ORG-UNIQUE-CHECK 抽查 verify=1。

任一步不一致即非零退出；全部一致输出 PASS（Phase 2 真机验证前零偏差）。

运行：C:\\Python313\\python.exe run_cross_test.py
编译器探测顺序：$CC 环境变量 → gcc/clang/cc → MSVC cl（经 vswhere/vcvars64.bat）。
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ORPAH = os.path.dirname(HERE)
sys.path.insert(0, ORPAH)
import damm32 as m  # noqa: E402  Python 参考实现

C_SRC = os.path.join(HERE, "damm32.c")
VEC_FILE = os.path.join(HERE, "test_vectors.txt")

# 非法输入样例（ORG-UNIQUE 部分含 Crockford 排除的 I/L/O/U 或其它符号）：Python/C 应一致拒绝。
INVALID = [
    "WH0I-9AF3C1D2",    # 含 I
    "WH0L-9AF3C1D2",    # 含 L
    "WH0O-9AF3C1D2",    # 含 O
    "WH01-9AF3C1D2+",   # 含非字母数字
]


def gen_vectors():
    """确定性向量集：黄金样本 + 手工边界 + 固定种子随机（均为 ORG-UNIQUE，不含 CC）。"""
    cores = [
        "WH01-9AF3C1D2",   # 黄金样本 → B（ORG=WH01, UNIQUE=9AF3C1D2）
        "0", "Z", "2", "7", "T", "V",
        "000000000000", "ZZZZZZZZ",
        "wh01-9af3c1d2",   # 小写 → 与黄金样本同 B
        "WH01", "CA-0001", "AA-000-0000",
    ]
    rnd = random.Random(20260910)
    alpha = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    for _ in range(50):
        cores.append("".join(rnd.choice(alpha) for _ in range(rnd.randint(1, 20))))
    seen, uniq = set(), []
    for c in cores:
        u = c.upper()
        if u not in seen:
            seen.add(u)
            uniq.append(c)
    return uniq


def _vs_env():
    """定位 VS 的 vcvars64.bat（找不到返回 None）。"""
    for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("ProgramFiles", r"C:\Program Files")):
        vsw = os.path.join(base, "Microsoft Visual Studio", "Installer", "vswhere.exe")
        if os.path.isfile(vsw):
            try:
                out = subprocess.run(
                    [vsw, "-latest", "-property", "installationPath"],
                    capture_output=True, text=True, timeout=10).stdout.strip()
                vc = os.path.join(out, "VC", "Auxiliary", "Build", "vcvars64.bat")
                if out and os.path.isfile(vc):
                    return vc
            except Exception:
                pass
    for base in (r"C:\Program Files\Microsoft Visual Studio\2022",
                 r"C:\Program Files (x86)\Microsoft Visual Studio\2022"):
        for edition in ("Community", "Professional", "Enterprise", "BuildTools"):
            vc = os.path.join(base, edition, "VC", "Auxiliary", "Build", "vcvars64.bat")
            if os.path.isfile(vc):
                return vc
    return None


def compile_c(exe):
    cc = os.environ.get("CC")
    if cc:
        subprocess.run(cc.split() + ["-std=c99", "-O2", "-o", exe, C_SRC], check=True)
        return
    for cand in ("gcc", "clang", "cc"):
        if shutil.which(cand):
            subprocess.run([cand, "-std=c99", "-O2", "-o", exe, C_SRC], check=True)
            return
    vc = _vs_env()
    if vc and shutil.which("cl"):
        cmd = f'"{vc}" >nul 2>&1 && cl /nologo /utf-8 "{C_SRC}" /Fe:"{exe}"'
        # 在临时目录里编译：cl 默认把 .obj 写到 cwd，别污染仓库
        subprocess.run(cmd, shell=True, check=True, cwd=os.path.dirname(exe))
        return
    raise RuntimeError("未找到可用 C 编译器；可设 CC 环境变量指定")


def run(exe, args, stdin=None):
    return subprocess.run([exe] + args, input=stdin,
                          capture_output=True, text=True)


def main():
    cores = gen_vectors()
    with open(VEC_FILE, "w", encoding="utf-8", newline="\n") as f:
        for c in cores:
            f.write(f"{c}\t{m.damm32_check(c)}\n")
    print(f"生成 {len(cores)} 条测试向量 -> {os.path.relpath(VEC_FILE, ORPAH)}")

    tmp = tempfile.mkdtemp(prefix="damm32_cross_")
    exe = os.path.join(tmp, "damm32.exe" if os.name == "nt" else "damm32")
    try:
        compile_c(exe)
        print(f"C 编译完成: {os.path.basename(exe)}")

        # 1) C selftest：读向量文件，重算 + 验证，比对黄金值
        r = run(exe, ["selftest", VEC_FILE])
        print(r.stdout, end="")
        if r.returncode != 0:
            sys.stderr.write(r.stderr)
            return 1

        # 2) C batch：同批 SN 核心，逐行比对 C 校验位 vs Python 校验位
        r = run(exe, ["batch"], stdin="\n".join(cores) + "\n")
        mismatch = 0
        for core, line in zip(cores, r.stdout.strip().split("\n")):
            got = line.rsplit("\t", 1)[-1]
            exp = m.damm32_check(core)
            if got != exp:
                mismatch += 1
                print(f"MISMATCH {core}: py={exp} c={got}")
        if mismatch:
            print(f"FAIL: batch 比对 {mismatch} 处不一致")
            return 1

        # 3) C verify 抽查：黄金样本 ORG-UNIQUE-CHECK 应得 1，篡改一位应得 0
        golden = "WH01-9AF3C1D2"
        good = golden + "-" + m.damm32_check(golden)
        bad = good[:-2] + ("1" if good[-1] == "0" else "0")
        v_ok = run(exe, ["verify", good]).stdout.strip()
        v_bad = run(exe, ["verify", bad]).stdout.strip()
        if v_ok != "1" or v_bad != "0":
            print(f"FAIL: verify 抽查 {good}->{v_ok}(期望1) {bad}->{v_bad}(期望0)")
            return 1

        # 4) 非法输入一致性：Python verify=False ⟺ C verify=0；
        #    Python check 抛 ValueError ⟺ C compute 返回 INVALID
        for bad in INVALID:
            pyv = 1 if m.damm32_verify(bad + "-H") else 0
            cv = run(exe, ["verify", bad + "-H"]).stdout.strip()
            if cv != str(pyv):
                print(f"FAIL: verify 拒绝不一致 {bad}: py={pyv} c={cv}")
                return 1
            try:
                m.damm32_check(bad)
                print(f"FAIL: Python damm32_check({bad}) 未抛 ValueError")
                return 1
            except ValueError:
                pass
            r = run(exe, ["compute", bad])
            if r.returncode != 1 or r.stdout.strip() != "INVALID":
                print(f"FAIL: C compute({bad}) 未返回 INVALID")
                return 1

        print(f"PASS: {len(cores)} 条向量，Python 与 C 零偏差")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
