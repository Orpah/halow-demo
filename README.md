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

零硬件快速体验（两台 HT-HC01 虚拟机演示）：

```bash
cd simulator
python tools/ui/server.py --host-sim --target hc01   # 浏览器开 http://127.0.0.1:8899/
```

设备档案/别名/协议族见 [`simulator/host/devprofiles.py`](simulator/host/devprofiles.py)，
完整说明见 [`simulator/README.md`](simulator/README.md)。

## 相关链接
1. [TXW8301淘宝链接](https://item.taobao.com/item.htm?id=856103881366&skuId=5660266844543)
2. [HT-HC01淘宝链接](https://item.taobao.com/item.htm?id=866899093076&skuId=6162648454293)
