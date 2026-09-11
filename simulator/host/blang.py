#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blang.py — 后端产生、会显示在 UI 上的文案的多语言支持（zh/en）。

后端有些文本是**运行时**拼出来的（设备卡片标签、控制台里的叙述行），
它们和前端页面文案一样会直接呈现给用户，需要跟着界面语言走。

前端在 `/api/info?lang=xx` 时调用 `set_lang()`，之后 `L(key, **kw)` 按当前语言取词。
未设置时默认 zh（与既有行为一致，不影响回归/demo 命令行输出）。

注意：只翻「叙述性」文本。设备真实输出（`OK` / `+CONNECTED` / LMAC 块）不在此列。
"""
import threading

_LOCK = threading.Lock()
_LANG = "zh"

_D = {
    "zh": {
        # 设备类型 / 顶部副标题
        "dt_pc": "虚拟机",
        "dt_serial": "真机",
        "bs_sim0": "CH32V203 · 无射频 · 虚拟空口",
        "bs_virtual": "兼容 · 无射频 · 虚拟空口",
        # 串口链路描述
        "lk_serial": "串口",
        "lk_uart2": "UART2 物理空口",
        "lk_rf": "RF 物理空口（802.11ah）",
        # server.py — 真机轮询/生命周期
        "probing": "探测固件代次…",
        "fw_gen": "固件代次={gen} 版本={ver}",
        "ver_default": "（未读到，按档案默认）",
        "no_data": "超过 {s:.0f}s 未收到设备数据，判关机（若已重新上电请稍候自动重连）",
        "alive": "设备开始应答（开机）",
        "reconnected": "串口 {port} 已重连，等待设备应答",
        "connected": "已连接 {label}",
        # sim.py — PC 版模拟器
        "sim_serial_link": "串口空口已连接 {port} @{baud}",
        "sim_wait_serial": "等待串口空口 {port} …",
        "sim_host_conn": "host 数据口 :{port} 已连接",
        "sim_start": "TXW8301 模拟器 PC 版启动 (AT 控制台 :{console}, 空口 {link})",
        "sim_start_host": "TXW8301 模拟器 PC 版启动 (AT 控制台 :{console}, 空口 {link}, host 口 :{host})",
    },
    "en": {
        "dt_pc": "virtual",
        "dt_serial": "real",
        "bs_sim0": "CH32V203 \u00b7 no RF \u00b7 virtual air",
        "bs_virtual": "compatible \u00b7 no RF \u00b7 virtual air",
        "lk_serial": "Serial",
        "lk_uart2": "UART2 physical air",
        "lk_rf": "RF air interface (802.11ah)",
        "probing": "probing firmware generation\u2026",
        "fw_gen": "firmware gen={gen} version={ver}",
        "ver_default": "(not read; profile default)",
        "no_data": "no device data for {s:.0f}s \u2014 considered off "
                   "(if just repowered it will reconnect automatically)",
        "alive": "device is responding (powered on)",
        "reconnected": "serial {port} reconnected, waiting for the device",
        "connected": "connected to {label}",
        "sim_serial_link": "serial air link connected {port} @{baud}",
        "sim_wait_serial": "waiting for serial air link {port} \u2026",
        "sim_host_conn": "host data port :{port} connected",
        "sim_start": "TXW8301 simulator (PC build) started "
                     "(AT console :{console}, air {link})",
        "sim_start_host": "TXW8301 simulator (PC build) started "
                          "(AT console :{console}, air {link}, host port :{host})",
    },
}


def set_lang(lang):
    """设置后端文案语言（'en' 开头视为英文，其余按中文）。返回生效值。"""
    global _LANG
    with _LOCK:
        _LANG = "en" if str(lang or "").lower().startswith("en") else "zh"
        return _LANG


def lang():
    with _LOCK:
        return _LANG


def L(key, **kw):
    """按当前语言取后端文案；缺键回退中文、再回退 key 自身（便于发现漏词）。"""
    with _LOCK:
        cur = _LANG
    s = _D.get(cur, {}).get(key) or _D["zh"].get(key)
    if s is None:
        return key
    return s.format(**kw) if kw else s
