# TXW8301 Simulator（CH32V203 纯软件模拟器）

> 给泰芯 **TXW8301**（802.11ah HaLow）做的一个**无射频纯软件模拟器**，整体形态参考
> [Xinyuan-LilyGO/T-Halow-RJ45](https://github.com/Xinyuan-LilyGO/T-Halow-RJ45)：
> 用一颗 **沁恒 CH32V203**（最低成本、无以太网）在固件层面模拟 TXW8301 的
> **AT 命令 / AP-STA 连接状态 / 配对 / RSSI / 数据通路**，对外暴露与真实模块一致的
> **SPI 宿主总线**（对应 SDK 的 `MACBUS_SPI`）+ **UART AT 控制台**。

```
 Host (SPI 主) ──SPI──▶ [CH32V203 模拟器 A = AP] ──UART 交叉链路("虚拟空口")──▶ [CH32V203 模拟器 B = STA] ──SPI──▶ Host (SPI 主)
                           ▲ USB-C / CH340 (AT 控制台)                              ▲ USB-C / CH340 (AT 控制台)
```

- 没有 802.11ah 射频、没有频谱仪、没有距离问题 —— 用 UART 交叉链路代替"空口"，
  让 **host 侧驱动 / 上层协议栈 / AT 联调** 可以脱离真实射频硬件先行开发验证。
- 两个模拟器一 AP 一 STA 对连，即可完整复现 T-Halow-RJ45 的"以太网桥"数据通路：
  HostA(SPI) → 模拟器A → 虚拟空口 → 模拟器B → HostB(SPI)。

---

## 目录结构

```
simulator/
├── README.md                  # 本文件
├── docs/
│   ├── architecture.md        # 总体架构、数据通路、模块划分
│   ├── AT_commands.md         # 模拟器 AT 命令参考（对齐 T-Halow-RJ45 文档）
│   ├── spi_protocol.md        # SPI 宿主接口帧协议（模拟 TXW8301 MACBUS_SPI）
│   ├── hardware.md            # 硬件设计（引脚分配 / 原理框图 / 接线）
│   ├── Fritzing_Build_Guide.md# Fritzing 搭建指南（元件导入 + netlist）
│   ├── toolchain.md           # 项目工具链（blender2step 工作流）
│   └── usage.md               # 快速开始：编译、烧录、接线、联调
├── hardware/
│   ├── parts/                 # Fritzing 自定义元件（CH32V203C8T6 / CH340C .fzpz）
│   ├── gen_fritzing.py        # 元件生成脚本（可复现）
│   └── BOM.md                 # 物料清单
├── firmware/
│   ├── README.md              # 固件编译 / 烧录说明
│   ├── Makefile               # riscv-none-elf-gcc 构建
│   ├── ld/link.ld             # 链接脚本（64K Flash / 20K RAM）
│   ├── startup/               # 启动文件
│   ├── Core/                  # 主程序、寄存器头、板级定义
│   ├── Periph/                # GPIO / UART / SPI 从机 驱动
│   └── Simulator/             # TXW8301 模拟核心（AT / 状态机 / 链路）
├── host/
│   ├── sim.py                 # PC 版模拟器（纯软件，无硬件，TCP 控制台+虚拟空口）
│   ├── test_sim.py / run_tests.py  # 回归测试（AT/连接/转发/配对，14 项）
└── tools/
    ├── sim_config.py          # 上位机工具（UART/SPI 访问模拟器，类 thalow_config.py）
    ├── ui/                    # Web 仪表盘（server.py + 前端，双机视图/控制台/帧监视/配置）
    └── README.md
```

> **工具链**：本项目硬件设计采用 **blender2step** 工作流
> （Fritzing 电路 → Blender 外壳 → FreeCAD 验证 → 模具/PCB 工厂），
> 这也是选用 Fritzing 的原因，详见 [docs/toolchain.md](docs/toolchain.md)。

---

## 特性

- **SPI 宿主总线**（SPI1 从机）：与 TXW8301 `MACBUS_SPI` 语义对齐的帧协议，
  支持 AT 命令 / 数据收发 / 事件通知 / 状态读取，带硬件 `IRQ`（数据就绪）脚。
- **UART AT 控制台**（USART1 + CH340C，115200）：和真实模块一样的 AT 交互体验。
- **AT 命令集**：对齐 T-Halow-RJ45 文档 —— `AT+MODE`、`AT+SSID`、`AT+KEYMGMT`、
  `AT+PSK`、`AT+PAIR`、`AT+BSS_BW`、`AT+CHAN_LIST`、`AT+FREQ_RANGE`、`AT+RSSI`、
  `AT+CONN_STATE`、`AT+WNBCFG`、`AT+SCAN_AP`、`AT+BSSLIST`、`AT+MAC_ADDR`、
  `AT+VERSION`、`AT+TXPOWER`、`AT+ACKTMO`、`AT+TX_MCS`、`AT+HEART_INT`、
  `AT+ROAM`、`AT+JOINGROUP`、`AT+PS_MODE`、`AT+R_SSID`、`AT+R_PSK`、
  `AT+LOADDEF`、`AT+SYSDBG`、`AT+TXDATA`。
- **模拟无线状态机**：AP / STA / APSTA / GROUP；扫描→关联→连接；配对（PAIR）；
  可配置的模拟 RSSI；连接 / 配对事件主动上报。
- **虚拟空口**：两片模拟器用 UART2 交叉链路互联，二层透明转发以太网帧，
  等价于真实模块的 RJ45↔HaLow 桥（数据通路在 SPI 侧）。
- **指示灯**：CONN 连接灯 + 4 颗 RSSI 信号灯（信号越好亮灯越多，同参考板）。
- **按键 / 拨码**：CONNECT(PAIR) 按键、2-bit 工作模式拨码，复刻参考板交互。

---

## 快速开始（概要，详见 docs/usage.md）

1. **硬件**：按 `docs/hardware.md` 打样/搭线；Fritzing 按 `docs/Fritzing_Build_Guide.md`
   导入元件并组装原理图；烧录用 WCH-Link（SWD）。
2. **固件**：`firmware/` 下 `make`（需 `riscv-none-elf-gcc`，MounRiver 工具链亦可），
   得到 `txw8301-sim.bin`，用 WCH-Link 烧录。
3. **两台模拟器接线**：`UART2 TX↔RX、GND` 交叉连接。
4. **配置**：PC 串口连各自 AT 控制台 ——
   - 模拟器 A：`AT+MODE=AP`、`AT+SSID=halowlink`、`AT+BSS_BW=8`
   - 模拟器 B：`AT+MODE=STA`、`AT+SSID=halowlink`、`AT+BSS_BW=8`
   - 或用 `tools/sim_config.py COM3 ap/sta --ssid halowlink --bw 8 --open`
5. **联调**：任一模拟器 `AT+CONN_STATE` 显示 `CONNECTED`；host 侧经 SPI 收发数据。
6. **图形界面**：`python tools/ui/server.py --a COM3 --b COM4` 打开 Web 仪表盘
   （双机拓扑、AT 控制台、帧监视器、配置面板，见 `tools/ui/README.md`）。

---

## 零硬件体验（PC 版模拟器，推荐先试）

开发板还没搭好？直接用 PC 版模拟器跑通全流程：

```bash
cd simulator/tools/ui
python server.py --host-sim        # 进程内启动 AP+STA 两台 PC 模拟器，自动配对
# 浏览器打开 http://127.0.0.1:8899/ 即可看到双机 CONNECTED
```

- `host/sim.py` 是固件逻辑的 Python 移植（同一套 AT 命令、帧格式、状态机），
  也用于交叉验证固件逻辑（曾发现 3 处固件 bug：beacon 长度、查询解析、配对格式）。
- 帧监视：点"帧监视: 开"后，在设备 A 控制台发 `AT+TXDATA=20` + 20 字节原始数据，
  即可在帧监视器看到 A `TX` / B `RX` 两条记录（无硬件演示数据通路）。
- 回归测试：`python host/run_tests.py`（24/24 通过）。
- 界面截图：`docs/ui_simplified_demo.png`（混合设备演示）、`docs/ui_hostsim_demo.png`、
  `docs/ui_hostsim_tj45_demo.png`。

## 支持 T-Halow-RJ45 与混合设备

A/B 两台设备可**逐台独立**指定「来源×目标」：`pc / pc:tj45 / COM3 / COM3:tj45`
（= CH32V203 虚拟机 / T-Halow-RJ45 虚拟机 / CH32V203 真机 / T-Halow-RJ45 真机）：

```bash
# Web UI：任意组合
python tools/ui/server.py --a pc --b pc:tj45      # A=CH32V203虚拟, B=T-Halow虚拟
python tools/ui/server.py --a COM3 --b COM4:tj45  # A=CH32V203真机, B=T-Halow真机

# PC 模拟器扮演 T-Halow-RJ45（状态带 + 前缀，T-Halow 的 thalow_config.py 可直接用）
python host/sim.py --name A --role AP --console 9001 --link 9011 --tj45

# 命令行配置真实板（--variant tj45 自动关调试刷屏）
python tools/sim_config.py COM3 ap --ssid halowlink --freq 9080 --bw 8 --open --variant tj45
```

关键兼容点：T-Halow-RJ45 状态/事件带 `+` 前缀（`+MODE:AP`、`+CONNECTED`）且用裸命令查询
（`AT+MODE`、`AT+VERSION`）；`--tj45` 模式与 UI 逐台规格已对齐。

### PC ↔ 真实 CH32V203 板建链（串口空口）

PC 模拟器空口可改走**串口**直连真实 CH32V203 模拟器板的 UART2（帧格式完全一致，自动
打开/重连，自动建链；手动用 `AT+PAIR=1`）：

```bash
# A=PC 模拟器（空口走 COM5，接真机 B 的 UART2），B=真机（AT 控制台 COM4）
python tools/ui/server.py --a pc --a-link COM5 --b COM4
```

接线：`板 UART2(PA2 TX/PA3 RX) → USB转串口 → PC COM`，共地 GND。
> T-Halow-RJ45 真机是射频，无空口串口可桥接，不能与 PC 模拟器建链。

> 互联域：PC↔PC 走虚拟空口；真机↔真机走物理 UART2/RF；PC 与真机（CH32V203 板）
> 可通过 `--a-link/--b-link` 串口空口建链；UI 可同时管理任意组合。

---

## 与 T-Halow-RJ45 / 真实 TXW8301 的关系

| 项目 | 射频 | 宿主总线 | MCU | 数据通路 |
|------|------|----------|-----|----------|
| T-Halow-RJ45 | 真实 802.11ah | SDIO/UART(模块内) | ESP32-S3 | RJ45↔HaLow（模块内 WNB 固件） |
| 真实 TXW8301 | 真实 802.11ah | SDIO / USB / UART / SPI | 玄铁 E803（芯片内） | host↔空口 |
| **本模拟器** | **无（虚拟空口）** | **SPI（从机）/ UART** | **CH32V203** | **HostSPI↔虚拟空口↔HostSPI** |

本模拟器把"真实 TXW8301 模块 + 空口"这一整体，替换为"CH32V203 固件 + UART 虚拟空口"，
对外（host 侧）行为尽量一致，便于在不占用射频资源、无法规限制的环境下做驱动与协议开发。
