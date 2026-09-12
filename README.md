# halow-demo

IEEE 802.11ah协议（也称Halow协议）完美满足了天逯系统的需求，是支撑天逯系统的基础协议。

目前淘宝上已经有了一些支持Halow协议的模块，例如泰芯的TXW8301、惠特自动化的HT-HC01。

TXW8301模块是玄铁E803处理器 + TXW8301芯片组成的，全国产。

![TXW8301模块](images/TXW8301.png)


HT-HC01模块是ESP32处理器+Morse Micro MM6108组成的。
![HT-HC01模块](images/HT-HC01.png)

目前天逯系统的开发板是基于TXW8301模块的，后续也会推出基于HT-HC01模块的开发板。

## 模拟器（simulator/）

[`simulator/`](simulator/) 是 HaLow 模组的**无射频纯软件模拟器**（参考 T-Halow-RJ45
形态：AT 命令 / AP-STA / RSSI / 数据通路一致），一个模拟器顶一台模组，用来在没有
射频硬件时先行开发验证 host 驱动 / 上层协议栈 / AT 联调。目前支持的设备目标：

| target | 设备 | 协议族 |
|--------|------|--------|
| `sim` | CH32V203 模拟器（本机） | native |
| `tj45` | T-Halow-RJ45 | 泰芯 AH（tah） |
| `txah` | 泰芯 TX-AH-MODULE | 泰芯 AH（tah） |
| `hc01` | HT-HC01（惠特自动化 ESP32+MM6108） | hc01（占位：命令集待手册） |

零硬件快速体验（两台 CH32V203 虚拟机演示）：

```bash
cd simulator
python tools/ui/server.py --host-sim    # 浏览器开 http://127.0.0.1:8899/
```

### Web UI 启动命令（tools/ui/server.py）

每台设备可独立指定「来源 × 目标」，来源 `pc`（进程内模拟器）/ `serial`（真机串口），
目标见上表（`sim`/`tj45`/`txah`/`hc01`）。常见启动方式（均 `cd simulator` 后执行）：

| 场景 | 命令 |
|---|---|
| 两台本模拟器虚拟机（零硬件推荐） | `python tools/ui/server.py --host-sim` |
| 两台 T-Halow-RJ45 虚拟机 | `python tools/ui/server.py --host-sim --target tj45` |
| 两台 TX-AH 虚拟机 | `python tools/ui/server.py --host-sim --target txah` |
| 两台 HT-HC01 虚拟机（占位） | `python tools/ui/server.py --host-sim --target hc01` |
| 混接：A=CH32V203虚拟 + B=T-Halow虚拟 | `python tools/ui/server.py --a pc --b pc:tj45` |
| TX-AH 真机 + 虚拟机（同一页面混管） | `python tools/ui/server.py --a pc:tj45 --b COM13:txah` |
| 两块真实 T-Halow-RJ45（物理 RF） | `python tools/ui/server.py --a COM3:tj45 --b COM4:tj45` |
| 自动识别 CH340 真机串口 | `python tools/ui/server.py` |
| 列出可用串口 | `python tools/ui/server.py --list` |
| 自定义 HTTP 端口 | `python tools/ui/server.py --host-sim --port 8899` |

> 互联域：仅「PC↔PC」经虚拟空口(TCP) 互联；「真机↔真机」走物理 RF/UART。
> PC 与真机无法自动建链，但 UI 可同时管理任意组合（如真机升级、对比验证）。
> 真机 tj45/txah 启动会自动探测固件代次（V1.6 T-Halow / V2.4 AH-SDK V2）选对 AT 方言。

设备档案/别名/协议族见 [`simulator/host/devprofiles.py`](simulator/host/devprofiles.py)，
完整说明见 [`simulator/README.md`](simulator/README.md)。

## ORPAH-over-HaLow demo → 已迁到独立仓库（2026-09-12）

原 `simulator/orpah/`（ORPAH 业务全链路：Router 桥 / 走失表 / 报文集 / ID 验签 / 定位 / 告警 /
IoTDB / Web UI，`ui_server.py` :8901）已**整体迁出**到独立仓库：

- `F:\git\orpah-over-halow`（GitHub: `langhua/orpah-over-halow`）
  —— `git subtree split` 迁移，160 个提交历史完整保留；那边自带空口仿真副本（`vendor/halow/`），
  零硬件、单进程即可跑全链路 demo，**不需要先启动本仓库**。

**本仓库现在只剩空口/设备侧**（`simulator/host/` 空口仿真 + `tools/ui/` TXW8301 Web UI +
`firmware/` + `hardware/`）。两边通过 **host 数据口（TCP，帧 `AA 55 TYPE LEN_H LEN_L CRC payload`）**
相接 —— 业务侧 `host_bus.py` 只依赖 TCP + 帧格式，换真实 SPI 只替换底层收发。

> 详细分工与规则：本仓库 [`simulator/AGENTS.md`](simulator/AGENTS.md) §0；
> 业务侧规则见 `orpah-over-halow/AGENTS.md`。

## 相关链接
1. [TXW8301淘宝链接](https://item.taobao.com/item.htm?id=856103881366&skuId=5660266844543)
2. [HT-HC01淘宝链接](https://item.taobao.com/item.htm?id=866899093076&skuId=6162648454293)
