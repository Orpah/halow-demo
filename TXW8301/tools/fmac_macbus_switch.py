#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fmac_macbus_switch.py — 切换 TXW8301 **FMAC 固件**的主机口（mac_bus）类型。

为什么需要它：
  模组固件 FMAC v2.4.1.5 的主机口由**编译期宏**决定（`project/project_config.h`）：
  ```c
  #define MACBUS_SDIO        // 原厂默认（SDIO/UART/USB 三选一）
  //#define MACBUS_USB
  //#define MACBUS_UART
  ```
  `project/sys_config.h` 据此定 `FMAC_MAC_BUS`（`MAC_BUS_TYPE_SDIO/USB/UART`），
  `main.c:262` 再 `wifi_mgr_init(FMAC_MAC_BUS, WIFIMGR_FRM_TYPE, ...)`。
  **SPI 不在其中**（SDK 里没有 SPI 主机口实现；手册说"SPI 与 SDIO 是同一固件"= SDIO 控制器的 SPI 模式）。
  所以想让 PC 侧能自己实现主机口，就得把固件编成 **MACBUS_UART** 版。

改完之后（本脚本只动那两行，别的不碰）：
  * 数据口 = **UART0**（`UARTBUS_DEV = HG_UART0_DEVID`）→ 模组 **IOA10(RX) / IOA11(TX)**，115200 8N1；
    `WIFIMGR_FRM_TYPE_RAW` = 线上是**裸以太网帧**（由固件封装）。
  * AT/打印口仍然是 **UART1**（`sys_config.h`：非 MACBUS_USB 时 `ATCMD_UARTDEV = HG_UART1_DEVID`）
    → 模组 **IOA12/IOA13**（开发板上 = 打印/AT 那一排）。
  * ⚠ 这两组脚**分别**和 SDIO 的 SD_D2/SD_D3 等复用；原厂 FAQ 说"角色选择 IOB2：
    RMII/USB/UART 用第 1 套方案，SDIO/SPI 用第 2 套方案" —— **硬件跳线/电阻怎么配，
    接线前要找原厂确认**（本脚本只管固件侧宏）。

用法（在 `TXW8301` 目录下）：
  python tools\fmac_macbus_switch.py status     # 看现在是哪种
  python tools\fmac_macbus_switch.py uart       # 切成 UART 主机口（关 SDIO）
  python tools\fmac_macbus_switch.py sdio       # 切回原厂默认 SDIO
  python tools\fmac_macbus_switch.py restore    # 用 .bak-sdio 整份还原
  python tools\fmac_macbus_switch.py uart --config <project_config.h 路径>

改完要**重新编译 + 烧录**（由用户执行）：
  make SHELL=sh.exe -C FMAC_SDK\project -f cdkws.mk All
  烧录：串口连 AT 口 → `at+fwupg` → SecureCRT 脚本「发送 Xmodem」选 `project/txw4002a.bin`
        （或 MounRiver/WCHISPTool 那套；见 TXW8301\README.md）

边界（如实）：
  * 只改 `project_config.h` 里的 `MACBUS_*` 两行，**不改任何其它文件**（可 `restore` 还原）。
  * `FMAC_SDK` 是**指向原厂 SDK 的 junction**（`.gitignore` 里 `*_SDK/` → 不受 git 管辖），
    所以备份文件也放那边；本脚本自身在仓库里，改动可追溯。
  * 切了宏**不等于跑得起来**：板上 UART 跳线/`IOB2` 角色选择、以及 AT 口那一侧的接线，
    都要按原厂文档配合；**未上机验证过**。
"""
import argparse
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_REL = os.path.join("FMAC_SDK", "project", "project_config.h")
BACKUP_SUFFIX = ".bak-sdio"

# 宏名字面量（照 project_config.h 原文写，别"顺手改写"）
LINE_SDIO_ON = "#define MACBUS_SDIO"
LINE_SDIO_OFF = "//#define MACBUS_SDIO"
LINE_UART_ON = "#define MACBUS_UART"
LINE_UART_OFF = "//#define MACBUS_UART"

ROLES = {
    "sdio": (LINE_SDIO_ON, LINE_UART_OFF),
    "uart": (LINE_SDIO_OFF, LINE_UART_ON),
}


def find_config(rel):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)                      # TXW8301/
    cand = rel if os.path.isabs(rel) else os.path.join(root, rel)
    if not os.path.exists(cand):
        raise SystemExit("找不到 %s（FMAC_SDK 是不是没建 junction？）" % cand)
    return cand


def read_lines(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return raw.decode("utf-8").splitlines(keepends=True), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("gbk").splitlines(keepends=True), "gbk"


def detect(lines):
    """只认**整行**等于 `#define MACBUS_xxx` 的（`//#define ...` 里含同样子串，不能用 in 判）。"""
    on = []
    for ln in lines:
        s = ln.strip()
        for name, macro in (("SDIO", "MACBUS_SDIO"), ("USB", "MACBUS_USB"),
                            ("UART", "MACBUS_UART")):
            if s == "#define %s" % macro:
                on.append(name)
    return on


def cmd_status(path):
    lines, enc = read_lines(path)
    on = detect(lines)
    print("配置文件：%s" % path)
    print("编码：%s" % enc)
    print("当前打开的主机口：%s" % ("、".join(on) if on else "(没有！sys_config.h 会 #error)"))
    if on == ["SDIO"]:
        print("⇒ 原厂默认（SDIO）。要让 PC 侧能自己实现主机口，就 `uart` 一次。")
    elif on == ["UART"]:
        print("⇒ UART 主机口。数据口 = UART0(IOA10/A11) 115200，AT 口 = UART1(IOA12/A13)。")
    else:
        print("⚠ 同时开了多个/组合不常见，自己确认一下 project_config.h")
    return on


def apply_role(path, role):
    lines, enc = read_lines(path)
    want_sdio, want_uart = ROLES[role]
    out, hits = [], {"sdio": 0, "uart": 0}
    for ln in lines:
        s = ln.rstrip("\r\n")
        crlf = ln[len(s):]
        if s.strip() in (LINE_SDIO_ON, LINE_SDIO_OFF):
            out.append(want_sdio + crlf)
            hits["sdio"] += 1
        elif s.strip() in (LINE_UART_ON, LINE_UART_OFF):
            out.append(want_uart + crlf)
            hits["uart"] += 1
        else:
            out.append(ln)
    if hits["sdio"] != 1 or hits["uart"] != 1:
        raise SystemExit("预期各命中 1 行 MACBUS_SDIO / MACBUS_UART，实际 %s —— 不动它，先人工看一眼"
                         % hits)
    bak = path + BACKUP_SUFFIX
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print("已备份原文件 → %s" % os.path.basename(bak))
    with open(path, "wb") as fh:
        fh.write("".join(out).encode(enc))
    print("已写入：SDIO=%s，UART=%s" % (want_sdio, want_uart))
    return cmd_status(path)


def cmd_restore(path):
    bak = path + BACKUP_SUFFIX
    if not os.path.exists(bak):
        raise SystemExit("没有 %s，无法还原（没改过就不需要还原）" % os.path.basename(bak))
    shutil.copy2(bak, path)
    print("已用 %s 还原 %s" % (os.path.basename(bak), os.path.basename(path)))
    return cmd_status(path)


def main():
    ap = argparse.ArgumentParser(description="切换 FMAC 固件的 mac_bus 主机口（SDIO ⇄ UART）")
    ap.add_argument("action", choices=("status", "uart", "sdio", "restore"))
    ap.add_argument("--config", default=DEFAULT_REL, help="project_config.h 的路径（默认走仓库内 junction）")
    args = ap.parse_args()
    path = find_config(args.config)
    if args.action == "status":
        cmd_status(path)
    elif args.action == "restore":
        cmd_restore(path)
    else:
        apply_role(path, args.action)
        print("\n下一步（**由你执行**）：")
        print("  1) 重编：make SHELL=sh.exe -C FMAC_SDK\\project -f cdkws.mk All")
        print("  2) 烧录：AT 口 `at+fwupg` + XMODEM 发 project\\txw4002a.bin")
        print("  3) 回退：python tools\\fmac_macbus_switch.py restore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
