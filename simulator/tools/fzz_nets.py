# -*- coding: utf-8 -*-
"""核对本仓接线图（Fritzing `.fzz`）的真实网表 —— 抄自 `orpah-client-demo/tools/fzz_nets.py`。

用法::

    python simulator\\tools\\fzz_nets.py                 # 核对 EXPECT 里登记的全部图
    python simulator\\tools\\fzz_nets.py <file.fzz> ...  # 核对指定工程

为什么需要它：`.fzz` 是个 zip，接线对不对**不该靠肉眼数线**。这里按 Fritzing 自己的
存储方式读连接——① 每个 instance 的 `<connector>/<connects>`；② **每条 wire 自身导通两端**；
③ 部件 `.fzp` 里的**内部 `<bus>`**（同网脚，例如 CH347F 的 11 个 GND）——把连接并成网
（union-find），翻译成「实例.脚名」后与**期望表**逐网比对。

期望表 `EXPECT` 就是这张图的**接线规格**（单一源）：改图时先改这里，脚本会直接告诉你差在哪一格。
退出码 0 = 全部对上；1 = 有差异（信息里带原因）。

⚠ **本文件是「两份独立副本」**（用户 2026-09-21 定：两个仓各自独立、不抽公共库）：
上游 = `orpah-client-demo/tools/fzz_nets.py`（那边带 b/c 步的图）；本份**只带本仓的图**。
逻辑保持逐字一致 ⇒ 哪天要改，**两侧一起改**（同 `AGENTS.md` §0 那条纪律）。
本仓目前登记：`pcpeer-ch347f-nanoch32v203.fzz`（PC 当空口对端，单板联调）。
"""
import os
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WIRING_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "hardware", "wiring"))

# ---- 角色（**按部件 ID 认，不按实例编号/名字**）-------------------------------
#   理由：实例 title（U2/U3/U4…）**重画就会变**，而"哪块板是什么"由部件本身决定
#   ⇒ 认 moduleIdRef 才稳。没登记的角色（例如老写法里的 `"U3"`）仍按**实例 title** 精确匹配。
MOD, MCU, BRIDGE, LED, RES = "MOD", "MCU", "BRIDGE", "LED", "RES"
ROLES = {
    MOD:    lambda mid: mid.startswith("TX-AH-R900PNR"),   # 任意一块 TX-AH 模组
    MCU:    lambda mid: mid == "CH32V203C8T6",            # nanoCH32V203 开发板
    BRIDGE: lambda mid: mid == "CH347F",                  # CH347F-EVT（USB ↔ 2×UART 桥）
    LED:    lambda mid: "ColorLED" in mid,                # Fritzing 核心 LED 部件
    RES:    lambda mid: "Resistor" in mid,                # Fritzing 核心电阻部件
}
ROLE_CN = {MOD: "模组", MCU: "MCU", BRIDGE: "桥", LED: "灯", RES: "电阻"}

# ---- 接线规格（期望的网表）--------------------------------------------------
#   每个集合 = 一个网；元素写作 `(角色, 脚名)`，脚名照部件里的 `connectorname`
#   （= 板上丝印/芯片脚名）。
#   ★ 关键点是**端口 ↔ 角色**，不是"哪一块板放在左边"。
EXPECT = {
    # ------------------------------------------------------------------
    # PC 当空口对端（单板）：nanoCH32V203（跑 simulator/firmware）↔ CH347F
    #   CH347F 的 `P2`(UART0 = COM23) 当**控制台**、`P3`(UART1 = COM24) 当**虚拟空口**；
    #   对端不是第二块板，而是 PC 上的 `python host/sim.py --link-serial COM24`。
    #   ★ 前提：**模组（TX-AH EVB）整块不接**（所以 EXPECT 里没有 MOD 的网）。
    #   ⚠ 电源不接：CH347F 的 3V3/VIO 不要接（避免两个 3.3V 源并联）；只共地。
    # ------------------------------------------------------------------
    "pcpeer-ch347f-nanoch32v203.fzz": [
        {(BRIDGE, "TXD0"), (MCU, "PA10")},       # 控制台：CH347F TXD0 → nano USART1_RX
        {(BRIDGE, "RXD0"), (MCU, "PA9")},        # 控制台：nano USART1_TX → CH347F RXD0
        {(BRIDGE, "TXD1"), (MCU, "PA3/ADC3")},   # 空口：CH347F TXD1 → nano USART2_RX
        {(BRIDGE, "RXD1"), (MCU, "PA2/ADC2")},   # 空口：nano USART2_TX → CH347F RXD1
        {(MCU, "GND"), (BRIDGE, "GND")},         # 共地
    ],
}


def read_fzz(path):
    """返回 (fz 文本, {moduleId: {connectorId: 脚名}}, {modelIndex: (moduleId, title, body)},
    {moduleId: [同网脚集合, ...]})。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        fz = z.read([n for n in names if n.endswith(".fz")][0]).decode("utf-8", "replace")
        fzps = {n: z.read(n).decode("utf-8", "replace") for n in names if n.endswith(".fzp")}

    pins, buses = {}, {}
    for txt in fzps.values():
        mid = re.search(r'<module[^>]*moduleId="([^"]+)"', txt)
        if not mid:
            continue
        mid = mid.group(1)
        pins[mid] = dict(re.findall(r'<connector id="([^"]+)" name="([^"]*)"', txt))
        buses[mid] = [set(re.findall(r'connectorId="([^"]+)"', body))
                      for _bid, body in re.findall(r'<bus id="([^"]*)"\s*>(.*?)</bus>', txt, re.S)]

    insts = {}
    for m in re.finditer(r'<instance moduleIdRef="([^"]+)"([^>]*)>(.*?)</instance>', fz, re.S):
        midref, attrs, body = m.groups()
        mi = re.search(r'modelIndex="([^"]+)"', attrs)
        title = re.search(r"<title>([^<]*)</title>", body)
        if mi:
            insts[mi.group(1)] = (midref, title.group(1) if title else "?", body)
    return fz, pins, insts, buses


def nets(path):
    fz, pins, insts, buses = read_fzz(path)
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for mi, (midref, _t, body) in insts.items():
        if midref == "WireModuleID":
            union((mi, "connector0"), (mi, "connector1"))     # wire 自己导通两端
        for cm in re.finditer(r'<connector connectorId="([^"]+)"[^>]*>(.*?)</connector>',
                              body, re.S):
            cid, blk = cm.groups()
            find((mi, cid))
            for cc in re.finditer(r'<connect connectorId="([^"]+)"[^>]*modelIndex="([^"]+)"', blk):
                union((mi, cid), (cc.group(2), cc.group(1)))
    for mi, (midref, _t, _b) in insts.items():                # 部件内部 bus（同网脚）
        if midref == "WireModuleID":
            continue
        for grp in buses.get(midref, []):
            grp = sorted(grp)
            for cid in grp[1:]:
                union((mi, grp[0]), (mi, cid))

    groups = {}
    for k in list(parent):
        groups.setdefault(find(k), []).append(k)
    out = []
    for members in groups.values():
        lbl = set()
        for mi, cid in members:
            midref, title, _ = insts.get(mi, ("?", "?", ""))
            if midref == "WireModuleID":
                continue
            lbl.add((title, midref, pins.get(midref, {}).get(cid, cid)))
        if lbl:
            out.append(lbl)
    return out, insts


def _match(want, got):
    """want: {(角色, 脚名)}；got: {(title, moduleIdRef, 脚名)}。每个 want 都要能对上。

    角色优先按 `ROLES`（部件 ID）认；没登记的角色按实例 title 认（老写法兼容）。
    """
    used = []
    for role, pin in want:
        pred = ROLES.get(role)
        for t, mid, nm in got:
            if nm != pin:
                continue
            if pred(mid) if pred else (role == t):
                used.append((t, nm))
                break
        else:
            return None
    return used


def check(path):
    name = os.path.basename(path)
    got, insts = nets(path)
    exp = EXPECT.get(name)
    print("=" * 88)
    print(name, "->", path)
    print("  实例：", ", ".join("%s=%s" % (t, m) for m, (mr, t, _b) in insts.items()
                               if mr != "WireModuleID"))
    print("  实际网表（%d 个网）：" % len(got))
    for g in sorted(got, key=lambda s: sorted(s)[0]):
        print("    " + "  <->  ".join("%s.%s" % (t, n) for t, _m, n in sorted(g)))
    if exp is None:
        print("  （EXPECT 里没有这张图的规格，仅列出网表）")
        return True
    ok = True
    print("  --- 逐网核对（板子不限实例编号）---")
    matched = []
    for want in exp:
        hit = None
        for g in got:
            used = _match(want, g)
            if used:
                hit = (g, used)
                break
        desc = "  <->  ".join("%s.%s" % (ROLE_CN.get(r, r), p) for r, p in sorted(want))
        if hit:
            matched.append(hit[0])
            real = "  ".join("%s.%s" % (t, n) for t, n in sorted(hit[1]))
            print("    ✓ %-42s  （图上 = %s）" % (desc, real))
        else:
            ok = False
            print("    ✗ %s ：图上找不到这个网" % desc)
    for g in got:
        if g in matched:
            continue
        owners = {t for t, _m, _n in g}
        if len(owners) > 1:                     # 跨实例却没写进规格 = 多出来的连线
            ok = False
            print("    ✗ 多出来的跨实例网：%s"
                  % "  <->  ".join("%s.%s" % (t, n) for t, _m, n in sorted(g)))
        elif len(g) > 1:                        # 同一实例内部同网 = 部件自己的 <bus>，不是连线
            print("    · 部件内部同网（非图上连线）：%s"
                  % "  <->  ".join("%s.%s" % (t, n) for t, _m, n in sorted(g)))
    print("  结论：" + ("全部对上 ✓" if ok else "有差异 ✗"))
    return ok


def main(argv):
    files = argv[1:] or [os.path.join(WIRING_DIR, n) for n in sorted(EXPECT)]
    bad = 0
    for f in files:
        if not os.path.exists(f):
            print("!! 找不到", f)
            bad += 1
            continue
        if not check(f):
            bad += 1
    print("=" * 88)
    print("一共 %d 张图，%d 张有问题" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
