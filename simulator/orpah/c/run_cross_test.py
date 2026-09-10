#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_cross_test.py — 校验码跨语言一致性测试（Python vs C，三算法）

用 Python 参考实现（../damm32.py + ../orpah_id.py）生成测试向量（黄金值），
分别编译 C 参考实现（damm32.c / luhn32.c / mod97.c），然后对每个算法：

  1. C `selftest`   —— 读向量文件，内部重算校验字符并验证，比对黄金值；
  2. C `batch`      —— 一次性把全部 ORG-UNIQUE 喂给 C，逐行比对 C 校验位 vs Python 校验位；
  3. C `verify`     —— 对黄金样本 ORG-UNIQUE-CHECK 抽查 verify=1、篡改一位 verify=0。

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
import damm32 as m      # noqa: E402  Damm32 参考实现
import orpah_id as o    # noqa: E402  Luhn32 / Mod97 参考实现

# 三个算法：C 源文件 / 向量文件 / 校验位计算 / 校验
ALGOS = [
    dict(name="damm32", src="damm32.c", vec="test_vectors.txt",
         check=lambda c: m.damm32_check(c),
         verify=lambda b: m.damm32_verify(b)),
    dict(name="luhn32", src="luhn32.c", vec="test_vectors_luhn32.txt",
         check=lambda c: o.compute_check(c, "luhn32"),
         verify=lambda b: o.verify_check_luhn32(b)),
    dict(name="mod97", src="mod97.c", vec="test_vectors_mod97.txt",
         check=lambda c: o.compute_check(c, "mod97"),
         verify=lambda b: o.verify_check_mod97(b)),
]

# 非法输入样例（ORG-UNIQUE 部分含 Crockford 排除的 I/L/O/U 或其它符号）。
# 仅 Damm32 做该一致性检查：Luhn32/Mod97 对 I/L/O/U 的语义不同（Mod97 按全字母表）。
INVALID = [
    "WH0I-9AF3C1D2",    # 含 I
    "WH0L-9AF3C1D2",    # 含 L
    "WH0O-9AF3C1D2",    # 含 O
    "WH01-9AF3C1D2+",   # 含非字母数字
]


def gen_vectors():
    """确定性向量集：黄金样本 + 手工边界 + 固定种子随机（均为 ORG-UNIQUE，不含 CC）。"""
    cores = [
        "WH01-9AF3C1D2",   # 黄金样本（ORG=WH01, UNIQUE=9AF3C1D2）
        "0", "Z", "2", "7", "T", "V",
        "000000000000", "ZZZZZZZZ",
        "wh01-9af3c1d2",   # 小写 → 与黄金样本同值
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


def compile_c(exe, src):
    cc = os.environ.get("CC")
    if cc:
        subprocess.run(cc.split() + ["-std=c99", "-O2", "-o", exe, src], check=True)
        return
    for cand in ("gcc", "clang", "cc"):
        if shutil.which(cand):
            subprocess.run([cand, "-std=c99", "-O2", "-o", exe, src], check=True)
            return
    vc = _vs_env()
    if vc and shutil.which("cl"):
        cmd = f'"{vc}" >nul 2>&1 && cl /nologo /utf-8 "{src}" /Fe:"{exe}"'
        # 在临时目录里编译：cl 默认把 .obj 写到 cwd，别污染仓库
        subprocess.run(cmd, shell=True, check=True, cwd=os.path.dirname(exe))
        return
    raise RuntimeError("未找到可用 C 编译器；可设 CC 环境变量指定")


def run(exe, args, stdin=None):
    return subprocess.run([exe] + args, input=stdin,
                          capture_output=True, text=True)


def test_algo(algo, cores, tmp):
    """对单个算法：写向量 → 编译 C → selftest + batch + verify 抽查。返回是否全过。"""
    vec_file = os.path.join(HERE, algo["vec"])
    with open(vec_file, "w", encoding="utf-8", newline="\n") as f:
        for c in cores:
            f.write(f"{c}\t{algo['check'](c)}\n")
    print(f"[{algo['name']}] 生成 {len(cores)} 条向量 -> {algo['vec']}")

    src = os.path.join(HERE, algo["src"])
    exe = os.path.join(tmp, algo["name"] + (".exe" if os.name == "nt" else ""))
    compile_c(exe, src)
    print(f"[{algo['name']}] C 编译完成: {os.path.basename(exe)}")

    # 1) selftest：读向量文件，重算 + 验证，比对黄金值
    r = run(exe, ["selftest", vec_file])
    print(r.stdout, end="")
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return False

    # 2) batch：同批 ORG-UNIQUE，逐行比对 C 校验位 vs Python 校验位
    r = run(exe, ["batch"], stdin="\n".join(cores) + "\n")
    mismatch = 0
    for core, line in zip(cores, r.stdout.strip().split("\n")):
        got = line.rsplit("\t", 1)[-1]
        exp = algo["check"](core)
        if got != exp:
            mismatch += 1
            print(f"MISMATCH {core}: py={exp} c={got}")
    if mismatch:
        print(f"FAIL: [{algo['name']}] batch 比对 {mismatch} 处不一致")
        return False

    # 3) verify 抽查：黄金样本 ORG-UNIQUE-CHECK 应得 1，篡改一位应得 0
    golden = "WH01-9AF3C1D2"
    check = algo["check"](golden)
    good = golden + "-" + check
    bad = golden[:-1] + ("1" if golden[-1] == "0" else "0") + "-" + check
    v_ok = run(exe, ["verify", good]).stdout.strip()
    v_bad = run(exe, ["verify", bad]).stdout.strip()
    if v_ok != "1" or v_bad != "0":
        print(f"FAIL: [{algo['name']}] verify 抽查 {good}->{v_ok}(期望1) {bad}->{v_bad}(期望0)")
        return False

    print(f"PASS: [{algo['name']}] {len(cores)} 条向量，Python 与 C 零偏差")
    return True


def main():
    cores = gen_vectors()
    tmp = tempfile.mkdtemp(prefix="cross_")
    try:
        all_ok = True
        for algo in ALGOS:
            if not test_algo(algo, cores, tmp):
                all_ok = False

        # Damm32 特有：非法输入一致性（Python verify=False ⟺ C verify=0；
        # Python check 抛 ValueError ⟺ C compute 返回 INVALID）
        damm32_exe = os.path.join(tmp, "damm32" + (".exe" if os.name == "nt" else ""))
        for bad in INVALID:
            pyv = 1 if m.damm32_verify(bad + "-H") else 0
            cv = run(damm32_exe, ["verify", bad + "-H"]).stdout.strip()
            if cv != str(pyv):
                print(f"FAIL: verify 拒绝不一致 {bad}: py={pyv} c={cv}")
                all_ok = False
                continue
            try:
                m.damm32_check(bad)
                print(f"FAIL: Python damm32_check({bad}) 未抛 ValueError")
                all_ok = False
                continue
            except ValueError:
                pass
            r = run(damm32_exe, ["compute", bad])
            if r.returncode != 1 or r.stdout.strip() != "INVALID":
                print(f"FAIL: C compute({bad}) 未返回 INVALID")
                all_ok = False

        return 0 if all_ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
