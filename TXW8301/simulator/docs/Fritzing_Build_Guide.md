# Fritzing 搭建指南

本工程交付 **可导入的 Fritzing 自定义元件**（`.fzpz`），并在本指南中给出**逐布搭建
步骤与完整 netlist**。请按下面步骤在 Fritzing 中组装原理图（约 15 分钟）。

> 为什么不直接给 `.fzz` 工程文件？
> Fritzing 的 `.fzz` 是 **GUI 内部会话格式**：每个实例的坐标、连线、连接关系通过
> 内部 `modelIndex` 互相引用，由编辑器在保存时自动生成，**无法用脚本可靠地手工产出**
> （手写极易导致文件损坏/打不开）。因此这里采用业界通用做法：交付"元件 + 接线指南"，
> 在 GUI 里组装，结果同样是一个可保存的 `.fzz`。

## 1. 导入自定义元件

1. 打开 Fritzing。
2. 菜单 **文件 → 导入 → 零件…**，选择：
   - `hardware/parts/CH32V203C8T6_LQFP48.fzpz`
   - `hardware/parts/CH340C_SOP16.fzpz`
3. 导入成功后，这两个元件会出现在右侧 **我的零件** 面板中。

## 2. 新建工程并放置元件

新建草图（Ctrl+N），切换到 **原理图** 视图。从左侧面板把以下元件拖到画布：

| 位号 | 元件（来源） |
|------|--------------|
| U1 | **CH32V203C8T6**（自定义，刚导入） |
| U2 | **CH340C**（自定义，刚导入） |
| U3 | **Voltage Regulator LM1117**（核心库：SparkFun，SOT223） |
| J1 | **USB (Micro-B)**（核心库：SparkFun） |
| D1 | **LED**（核心库，任意） |
| D2~D5 | **LED** ×4 |
| S1 | **Push Button**（核心库） |
| S2 | **Push Button**（核心库） |
| SW1 | **DIP-2 Switch**（核心库：SparkFun 2-way DIP） |
| R1~R5 | **Resistor 1kΩ**（核心库） |
| R6 | **Resistor 10kΩ** |
| C1~C6 | **Capacitor 100nF**（核心库） |
| C7, C8 | **Capacitor 10µF** ×2 |
| 排针 | **Generic Pin Header**（核心库，SPI 口 / 链路口 / SWD 口各一组） |

> 参考 BOM：`hardware/BOM.md`。若面板找不到，用右上搜索框输入名称。

## 3. 连线（netlist）

按下面连接关系在原理图视图逐条连线（**数字 = 相同网络，需连在一起**）。

### 3.1 电源

| 网络 | 连接 |
|------|------|
| 5V | USB(VBUS) → U3 IN；U2(VCC)；C7+ |
| 3V3 | U3 OUT → U1(VDDA, VDD_1, VDD_2)；U2(V3)；所有 3.3V 负载；C8+ |
| GND | USB GND、U3 GND、U1(VSSA, VSS_1, VSS_2)、U2(GND)、C7-、C8-、各 100nF- |

### 3.2 主控最小系统

| 网络 | 连接 |
|------|------|
| VCAP | U1(VCAP) → 100nF → GND（**必接**） |
| BOOT0 | U1(BOOT0) → 10kΩ → GND |
| NRST | U1(NRST) → 100nF → GND；S1 按键一端接 3V3 |
| HSE(预留) | U1(PD0-OSC_IN)/(PD1-OSC_OUT) 预留晶振，默认不贴（用 HSI） |

### 3.3 控制台（CH340C ↔ U1）

| 网络 | 连接 |
|------|------|
| UART1_TX | U2(RXD) → U1(PA9) |
| UART1_RX | U2(TXD) → U1(PA10) |
| USB_D | U2(UD+) → USB(D+)；U2(UD-) → USB(D-) |

### 3.4 SPI 宿主口（排针 J2）

| 网络 | 连接 |
|------|------|
| SCK | U1(PA5) → 排针 SCK |
| MOSI | U1(PA7) → 排针 MOSI |
| MISO | U1(PA6) → 排针 MISO |
| NSS | U1(PA4) → 排针 NSS |
| IRQ | U1(PB0) → 排针 IRQ |
| 3V3 / GND | 排针 3V3 / GND |

### 3.5 虚拟空口（排针 J3）

| 网络 | 连接 |
|------|------|
| LINK_TX | U1(PA2) → 排针 TX |
| LINK_RX | U1(PA3) → 排针 RX |
| GND | 排针 GND |

### 3.6 指示与输入

| 网络 | 连接 |
|------|------|
| CONN 灯 | U1(PC13) → 1kΩ → LED(阴极侧)，LED 阳极 → 3V3（低有效） |
| RSSI 灯 ×4 | U1(PB6/7/8/9) → 1kΩ → LED → GND（高有效） |
| CONNECT 键 | U1(PA0) → 按键 → GND |
| 模式拨码 | U1(PA1) 与 U1(PB5) 各自经 DIP 拨到 GND（内部上拉） |
| SWD | U1(PA13)=SWDIO、U1(PA14)=SWCLK → 排针 + 3V3 + GND |

## 4. 检查与保存

1. 用 Fritzing 的 **规则检查**（工具 → 设计规则检查）确认没有未连接网络。
2. **文件 → 另存为**，保存为 `TXW8301-Simulator.fzz`。
3. 需要出 PCB 时切换到 PCB 视图：核心元件已带封装，可手动摆放；
   建议使用 **Autoroute** 后手动修线。

## 5. 局限与量产建议

- Fritzing 适合**原理图/面包板原型**验证；对 LQFP48 + 0402/0603 密集布线的
  量产 PCB 支持有限（走线、覆铜、差分、阻抗控制都不完善）。
- **量产/送工厂打样建议迁移到 KiCad**：元件的引脚与网络表已在
  `docs/hardware.md` 与本文档给出，KiCad 迁移可在 1~2 小时内完成。
  需要的话可让 AI 协助生成 KiCad 工程（后续任务）。
