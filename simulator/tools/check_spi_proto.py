# -*- coding: utf-8 -*-
"""check_spi_proto.py — SPI 宿主接口的**协议层离线对拍**（不需要任何硬件、不需要开发板）。

为什么要它：SPI 从机的寄存器/EXTI 那部分只能上机验，但**帧格式/CRC/应答布局**是纯逻辑。
原来这套逻辑在固件 `Periph/spi_slave.c` 与主机 `tools/sim_config.py` 里**各写一份**，
两份漂移了不会报错 —— 真机上只表现为「发出去没反应」。现在：

    设备侧：`firmware/Simulator/spi_proto.c`（纯逻辑，无寄存器）
    主机侧：`tools/spi_frame.py`（Python 模型 + 向量生成器）
    中间：  `tools/spi_proto_cli.c`（**主机** CLI，把设备侧源码拿到 PC 上跑；不编进固件）

本脚本把两者跑同一批向量（`tools/spi_test_vectors.txt`）**逐字节**比对：
CRC、请求帧、应答帧、**就地**应答（DATA_RX 那条重叠搬路径）、以及接收状态机（frame /
bad_crc / too_long / 同事务内第二帧被忽略 / CS 分段）。

用法：
    python tools/check_spi_proto.py              # 对拍（退出码 0 = 一致）
    python tools/check_spi_proto.py --refresh    # 用 Python 模型重生成向量文件（勿手改）
    python tools/check_spi_proto.py --cc clang   # 指定主机编译器

退出码：0 = 全过；1 = 有不一致；2 = **跳过**（本机没有可用的主机 C 编译器）—— 跳过是**可见**的，
绝不静默当通过（`run_checks.py` 会把它标成 SKIP）。
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)                       # simulator/
FW = os.path.join(SIM, "firmware")
VEC = os.path.join(HERE, "spi_test_vectors.txt")

sys.path.insert(0, HERE)
import spi_frame as sf                            # noqa: E402  （同目录，向量单一源）

VEC_HEADER = "\n".join([
    "# spi_test_vectors.txt — SPI 宿主协议层对拍向量（**勿手改**）",
    "#   生成： python tools/check_spi_proto.py --refresh    （参照 = tools/spi_frame.py）",
    "#   判定： python tools/check_spi_proto.py              （被测 = firmware/Simulator/spi_proto.c）",
    "#   每行： <子命令> <参数…> => <期望输出>；`-` = 空载荷，`<子命令>` 见 tools/spi_proto_cli.c",
    "",
])


def _hex(b):
    return b.hex()


def _rx_expect(segments):
    """Python 模型跑一遍 `rx` 用例，产出与 CLI 相同格式的期望行（按 `|` 分段 = 各一次 CS 事务）。

    行格式：`<ev> <cmd> <len>[ <payload-hex>]`；too_long 时第 3 个数是**声明的 LEN**
    （那时载荷根本不存在，拿它当长度会越界 —— C 侧一开始就这么错了，被这里抓出来）。
    """
    d = sf.RxDecoder()
    lines = []
    for seg in segments:
        d.cs_start()
        for b in bytes.fromhex(seg):
            ev = d.feed(b)
            if ev in (sf.RX_FRAME, sf.RX_BAD_CRC, sf.RX_TOO_LONG):
                if ev == sf.RX_TOO_LONG:
                    ln, pl = d.length, b""
                else:
                    pl = bytes(d.payload)
                    ln = len(pl)
                line = "%s %d %d" % (ev, d.cmd, ln)
                if pl:
                    line += " " + pl.hex()
                lines.append(line)
        d.cs_end()
    return "\n".join(lines)


def build_cases():
    """(argv, 期望输出) 列表。期望**全部**由 Python 模型算出（独立实现，才是对拍）。"""
    cases = []
    payloads = [b"", b"\x00", b"\x01\x02\x03", bytes(range(16)),
                b"AT+SSID?\r\n", bytes(((i * 7 + 3) & 0xFF) for i in range(200))]
    for cmd in sf.CMDS:
        for pl in payloads:
            a = "-" if not pl else _hex(pl)
            cases.append((["crc", "%02x" % cmd, a], "%02x" % sf.frame_crc(cmd, pl)))
            cases.append((["req", "%02x" % cmd, a], _hex(sf.encode_request(cmd, pl))))
            cases.append((["resp", "%02x" % cmd, a], _hex(sf.encode_response(cmd, pl))))
            cases.append((["respip", "%02x" % cmd, a], _hex(sf.encode_response(cmd, pl))))

    ping = sf.encode_request(sf.CMD_PING)
    at = sf.encode_request(sf.CMD_AT, b"AT+SSID?\r\n")
    dt = sf.encode_request(sf.CMD_DATA_TX, bytes(range(64)))
    bad = bytearray(sf.encode_request(sf.CMD_DATA_TX, b"\x01\x02\x03"))
    bad[-1] ^= 0xFF
    streams = [
        [_hex(ping)],                                     # 最简请求
        [_hex(at)],                                       # 带载荷
        [_hex(bytes(bad))],                               # CRC 错
        ["0606a5"],                                       # LEN=1701 > 1700 → too_long
        [_hex(ping) + _hex(ping)],                        # 同事务内第二帧被忽略
        [_hex(ping), _hex(sf.encode_request(sf.CMD_GET_STATE))],   # 两次 CS 事务 → 两帧
        [_hex(dt) + "ff" * 8],                            # 响应阶段填充字节被忽略
        [_hex(ping)[:6]],                                 # 截断（不足 4 字节）→ 无事件
        ["aabbccdd"],                                     # 畸形：LEN=0xbbcc → too_long
    ]
    for segs in streams:
        cases.append((["rx"] + ["|".join(segs)], _rx_expect(segs)))
    return cases


GCC_NAMES = ("gcc", "clang", "cc")
GCC_HINTS = [
    r"C:\Program Files\LLVM\bin\clang.exe",
    r"C:\TDM-GCC-64\bin\gcc.exe",
    r"C:\msys64\mingw64\bin\gcc.exe",
    r"C:\MinGW\bin\gcc.exe",
    r"C:\Program Files\mingw-w64\mingw64\bin\gcc.exe",
]
VSWHERE = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
VS_HINTS = [
    r"F:\Program Files\Microsoft Visual Studio\2022\Community",
    r"C:\Program Files\Microsoft Visual Studio\2022\Community",
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional",
    r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise",
    r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools",
]


def find_cc(explicit=None):
    """找主机 C 编译器：gcc/clang/cc（PATH → 常见安装路径），最后才是 MSVC 的 cl。"""
    if explicit:
        return explicit                                # 用户指定就听他的（找不到会在 build 里报错）
    for c in (os.environ.get("CC"),) + GCC_NAMES:
        if c and shutil.which(c):
            return c
    for p in GCC_HINTS:
        if os.path.exists(p):
            return p
    cl = shutil.which("cl")
    if cl:
        return cl
    return None


def msvc_vcvars():
    """MSVC 裸调 `cl` **不够** —— 它找不到 UCRT 头（实测：`stdio.h: No such file`）。
    必须先把 VS 环境（INCLUDE/LIB）套上，也就是先 call `vcvars64.bat`。"""
    roots = []
    if os.path.exists(VSWHERE):
        p = subprocess.run([VSWHERE, "-latest", "-products", "*",
                            "-property", "installationPath"],
                           capture_output=True, encoding="utf-8", errors="replace")
        if p.stdout.strip():
            roots.append(p.stdout.strip().splitlines()[0].strip())
    roots += VS_HINTS
    for r in roots:
        bat = os.path.join(r, "VC", "Auxiliary", "Build", "vcvars64.bat")
        if os.path.exists(bat):
            return bat
    return None


def build(cc, outdir):
    """编译 `spi_proto_cli.c` + 设备侧协议层（spi_proto.c + sim_util.c）→ 可执行文件。

    ★ 一律 `cwd=outdir`：中间产物（.obj/.dSYM…）落在临时目录，**不许脏仓库**。
    """
    exe = os.path.join(outdir, "spi_proto_cli.exe" if os.name == "nt" else "spi_proto_cli")
    srcs = [os.path.join(HERE, "spi_proto_cli.c"),
            os.path.join(FW, "Simulator", "spi_proto.c"),
            os.path.join(FW, "Simulator", "sim_util.c")]
    incs = [os.path.join(FW, "Simulator"), os.path.join(FW, "Core")]

    if os.path.basename(cc).lower().startswith("cl"):
        bat = msvc_vcvars()
        if bat is None:
            print("[FAIL] 找到 cl.exe，但没找到 vcvars64.bat（VS 环境套不上，cl 找不到头文件）。"
                  "装 gcc/clang 或用 --cc <gcc 路径>。")
            return None
        # 两条实测过的必要项（沿用 orpah-client-demo/proto/run_cross_test.py 的配方）：
        #   · `/utf-8`：本仓源码是 **UTF-8 无 BOM + 中文注释**，cl 默认按 GBK(936) 读
        #     → 中文字节会把换行/`#` 吃掉，报一个**假的** `#if/#endif 不匹配`（实测踩到）；
        #   · `/std:c11`：C99 起才允许的一些写法（块内声明之后再有语句）在 C89 模式编不过。
        #   · MSVC 的 `/Fo`/`/Fe` 参数**不带前导路径**时会落到 cwd ⇒ 一律 cwd=临时目录，别脏仓库。
        srclist = " ".join('"%s"' % s for s in srcs)
        cmd = 'call "%s" >nul 2>&1 && cl /nologo /TC /std:c11 /utf-8 /W4 /O2 %s %s /Fo:"%s\\\\" /Fe:"%s"' % (
            bat, " ".join('"/I%s"' % i for i in incs), srclist, outdir, exe)
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                           shell=True, cwd=outdir)
    else:
        args = [cc, "-std=c99", "-O1", "-Wall", "-Wextra"] + ["-I" + i for i in incs] \
             + ["-o", exe] + srcs
        p = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace",
                           cwd=outdir)

    if p.stdout.strip():
        print(p.stdout.strip())
    if p.returncode != 0:
        print("[FAIL] 编译协议层失败：\n" + (p.stderr or ""))
        return None
    if (p.stderr or "").strip():
        print("[warn] 编译告警：\n" + p.stderr.strip())
    if not os.path.exists(exe):
        print("[FAIL] 编译似乎成功但没产出可执行文件：%s" % exe)
        return None
    return exe


def static_guards():
    """两条**结构性**检查（不只比字节）：设备侧协议层必须与硬件无关；CLI 不许编进固件。"""
    fails = []
    src = open(os.path.join(FW, "Simulator", "spi_proto.c"), encoding="utf-8").read()
    for sym in ("HOST_SPI", "IRQHandler", "GPIO", "NVIC", "EXTI", "RCC"):
        if sym in src:
            fails.append("spi_proto.c 出现硬件符号 %s —— 这层必须无寄存器（否则没法在 PC 上对拍）" % sym)
    mk = open(os.path.join(FW, "Makefile"), encoding="utf-8").read()
    if "spi_proto.c" not in mk:
        fails.append("firmware/Makefile 没把 Simulator/spi_proto.c 编进固件")
    if "spi_proto_cli" in mk:
        fails.append("firmware/Makefile 把主机 CLI 也编进固件了（它是 tools/ 侧的东西）")
    return fails


def run_case(exe, argv):
    p = subprocess.run([exe] + argv, capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None, "exit %d: %s" % (p.returncode, (p.stderr or "").strip())
    return p.stdout.replace("\r\n", "\n").strip(), None


def main():
    ap = argparse.ArgumentParser(description="SPI 协议层离线对拍（设备侧 C ↔ 主机侧 Python）")
    ap.add_argument("--refresh", action="store_true", help="用 Python 模型重生成向量文件")
    ap.add_argument("--cc", default=None, help="主机 C 编译器（默认自动探测 gcc/clang/cc）")
    ap.add_argument("--workdir", default=None, help="编译输出目录（默认系统临时目录）")
    args = ap.parse_args()

    for _s in (sys.stdout, sys.stderr):
        _s.reconfigure(encoding="utf-8", errors="replace")

    cases = build_cases()

    if args.refresh:
        with open(VEC, "w", encoding="utf-8", newline="\n") as f:
            f.write(VEC_HEADER)
            for argv, exp in cases:
                f.write("%s => %s\n" % (" ".join(argv), exp.replace("\n", " || ") if exp else ""))
        print("已刷新 %s（%d 条用例）" % (os.path.relpath(VEC, os.path.dirname(SIM)), len(cases)))

    # 从文件读回（refresh 之后也读文件 —— 这样「文件被手改坏」会当场暴露）
    if not os.path.exists(VEC):
        print("[FAIL] 缺向量文件 %s（先跑 --refresh）" % VEC)
        return 1
    file_cases = []
    for i, line in enumerate(open(VEC, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if " => " not in line:
            print("[FAIL] %s:%d 向量行格式不对：%s" % (os.path.basename(VEC), i, line))
            return 1
        lhs, rhs = line.split(" => ", 1)
        file_cases.append((lhs.split(" "), "" if not rhs else rhs.replace(" || ", "\n")))

    fails = static_guards()
    npass = 0

    # 向量文件与 Python 模型必须是同一批（防止有人手改文件「让它变绿」）
    if len(file_cases) != len(cases):
        fails.append("向量文件有 %d 条，模型给 %d 条 —— 文件与模型不同源，跑 --refresh 重生成"
                     % (len(file_cases), len(cases)))
    else:
        for (fa, fe), (ma, me) in zip(file_cases, cases):
            if fa != ma or fe != me:
                fails.append("向量文件与模型不一致：文件 %r => %r / 模型 %r => %r"
                             % (" ".join(fa), fe, " ".join(ma), me))
                break

    cc = find_cc(args.cc)
    if cc is None:
        for x in fails:
            print("[FAIL] " + x)
        print("[SKIP] 本机没找到主机 C 编译器（gcc/clang/cc）→ 协议层对拍**未跑**"
              "（不是通过；装了 gcc 或 --cc 指定即可）")
        return 1 if fails else 2

    import tempfile
    tmp = args.workdir or tempfile.mkdtemp(prefix="spi_proto_")
    os.makedirs(tmp, exist_ok=True)
    print("[info] 编译器 %s → %s" % (cc, tmp))
    exe = build(cc, tmp)
    if exe is None:
        return 1

    total = len(cases)
    for argv, exp in cases:
        got, err = run_case(exe, argv)
        if err is not None:
            fails.append("%s → %s" % (" ".join(argv), err))
            continue
        if got.strip() != exp.strip():          # 两侧都去掉行尾空白再比（避免装饰性差异掩盖真错）
            fails.append("%s → 实际 %r / 期望 %r" % (" ".join(argv), got, exp))
            continue
        npass += 1
    for x in fails:
        print("[FAIL] " + x)
    print("spi_proto cross-check %d/%d" % (npass, total))
    return 0 if (not fails and npass == total) else 1


if __name__ == "__main__":
    sys.exit(main())
