# -*- coding: utf-8 -*-
"""
devprofiles.py — 设备档案 / 协议族注册表（单一事实来源）
======================================================
host/sim.py（PC 模拟器引擎）与 tools/ui/server.py（Web UI）共用。

分两层：
  1. **target（设备档案 key）**：用户/命令行可见的设备类型，如 sim / tj45 / txah / hc01，
     带别名归一、中文显示名。
  2. **family（协议族）**：模拟引擎真正关心的「AT 方言」id。一个 family 可对应多个 target
     （如泰芯 AH 族 = tj45 + txah，两者命令集一致，只是显示名不同）。

以后新增 Halow 芯片/模组：在 PROFILES 加一项（key/别名/中文名/family），
若命令集全新则新增一个 family，并在 host/sim.py 的 At 方言处实现它。
"""

FAMILY_NATIVE = "native"  # 本模拟器（CH32V203 sim）原生方言：AT+MODE? 查询 + OK 追加
FAMILY_TAH = "tah"        # 泰芯 AH 族：T-Halow-RJ45(tj45) / TX-AH(txah)，状态响应带 + 前缀
FAMILY_HC01 = "hc01"      # HT-HC01（惠特自动化 ESP32+MM6108，Morse Micro）：
                          # 占位族 —— 真实 AT 命令集待其手册确认，暂复用泰芯 AH 方言，收到手册后实现独立方言


class Profile:
    """一个设备档案：key（规范名）+ aliases（别名）+ name（中文显示名）+ family（协议族）。"""

    __slots__ = ("key", "aliases", "name", "family")

    def __init__(self, key, aliases, name, family):
        self.key = key
        self.aliases = aliases
        self.name = name
        self.family = family


# 规范 key 顺序（同时是 --target 的 choices 展示顺序）
ORDER = ["sim", "tj45", "txah", "hc01"]

PROFILES = {
    "sim":  Profile("sim",  ("sim", "ch32", "ch32v203"),
                    "CH32V203", FAMILY_NATIVE),
    "tj45": Profile("tj45", ("tj45", "thalow", "t-halow", "rj45"),
                    "T-Halow-RJ45", FAMILY_TAH),
    "txah": Profile("txah", ("txah", "tx-ah", "tx_ah", "ah", "tx-ah-module"),
                    "TX-AH", FAMILY_TAH),
    # 占位：HT-HC01 真机/虚拟机已可被识别管理，AT 方言细节待手册
    "hc01": Profile("hc01", ("hc01", "ht-hc01", "ht_hc01", "hthc01", "htc01"),
                    "HT-HC01", FAMILY_HC01),
}

# 别名 → 规范 key 的查找表
_ALIAS_TO_KEY = {}
for _p in PROFILES.values():
    for _a in _p.aliases:
        _ALIAS_TO_KEY[_a] = _p.key


def is_key(k):
    return (k or "").lower() in PROFILES


def norm_target(t, default):
    """把 'sim'/'ch32'/'tj45'/'thalow'/'txah'/'hc01'/'ht-hc01' 等别名归一为规范 key。

    未知别名回退 default（default 通常来自 --target，本身已是规范 key）。
    """
    s = (t or "").strip().lower()
    return _ALIAS_TO_KEY.get(s, (default or "").lower() if is_key(default) else default)


def family(key):
    """target key → family id（协议族）。未知 key 归为 native。"""
    k = (key or "").lower()
    return PROFILES[k].family if k in PROFILES else FAMILY_NATIVE


def name(key):
    """target key → 中文显示名（如 HT-HC01）。未知 key 原样返回。"""
    k = (key or "").lower()
    return PROFILES[k].name if k in PROFILES else (key or "?")


def tah_style(fam):
    """该 family 是否用「泰芯 AH 风格」响应（+ 前缀 / 裸查询 / 状态行不追加 OK）。

    hc01 为占位族：真实 Morse-Micro AT 未知，暂按泰芯 AH 风格，待手册替换。
    """
    return fam in (FAMILY_TAH, FAMILY_HC01)
