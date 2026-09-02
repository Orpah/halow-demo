# TXW8301 模拟器 Web UI

本地 Web 仪表盘，可视化并操控 1~2 台设备（模拟器/真实板）。零第三方依赖
（仅 pyserial，纯 PC 模拟器时连 pyserial 都不需要）。

## 每台设备可独立指定「来源 × 目标」

| 规格 | 含义 |
|------|------|
| `pc` | CH32V203 **虚拟机**（进程内 host/sim.py） |
| `pc:tj45` | T-Halow-RJ45 **虚拟机**（host/sim.py 兼容模式） |
| `pc:txah` | TX-AH **虚拟机**（泰芯 AH 兼容模式） |
| `pc:hc01` | HT-HC01 **虚拟机**（兼容模式 · 占位） |
| `COM3` | CH32V203 **真机**（串口） |
| `COM3:tj45` | T-Halow-RJ45 **真机**（串口，自动关调试刷屏） |
| `COM3:hc01` | HT-HC01 **真机**（串口，自动关调试刷屏 · 占位） |

> 目标 key / 别名 / 中文显示名 / 协议族（native / tah / hc01）的**单一事实来源**是
> [`host/devprofiles.py`](../../host/devprofiles.py)；`sim`=本模拟器、`tj45`/`txah`=泰芯 AH 族、
> `hc01`=HT-HC01（惠特自动化 ESP32+MM6108，占位，暂按泰芯 AH 方言）。

## 启动

### 无硬件（推荐，PC 版模拟器）

```bash
cd simulator/tools/ui
python server.py --host-sim          # 等价 --a pc --b pc，自动配对
python server.py --host-sim --port 8899
```

`--host-sim` 等价于 `--a pc --b pc`，在服务器进程内启动两台 PC 模拟器
（A=AP、B=STA，SSID 均为 `halowlink`），通过 TCP 虚拟控制台连接，完全不需要硬件。

### 混合设备（A/B 用不同设备）

```bash
# A=CH32V203 虚拟，B=T-Halow-RJ45 虚拟（虚拟空口仍可互联，见下方限制）
python server.py --a pc --b pc:tj45

# A=CH32V203 真机，B=T-Halow-RJ45 真机
python server.py --a COM3 --b COM4:tj45

# A=PC 模拟器，B=T-Halow-RJ45 真机（各自可管理，但无法自动建链）
python server.py --a pc --b COM4:tj45
```

`--target sim|tj45|txah|hc01` 是未在规格中指定时的默认目标（choices/别名见 devprofiles.py）。
顶部标题与设备标签会按每台实际类型显示（如 `A: CH32V203 虚拟机 · B: HT-HC01 虚拟机`）。

### PC 模拟器 ↔ 真实 CH32V203 板（串口空口建链）

PC 模拟器的空口除了 TCP 虚拟空口，还能**直接走串口**连真实 CH32V203 模拟器板：
把板子的 **UART2（PA2=TX / PA3=RX）** 经 USB 转串口（如 CH340）接到 PC，然后：

```bash
# A=PC 模拟器（空口走串口 COM5，连真机 B 的 UART2），B=真机（AT 控制台 COM4）
python server.py --a pc --a-link COM5 --b COM4

# 或 B=PC 模拟器（空口走 COM5），A=真机（AT 控制台 COM3）
python server.py --a COM3 --b pc --b-link COM5
```

- `--a-link/--b-link` = 该台 PC 模拟器空口用的串口（帧格式 `AA 55 TYPE LEN CRC` 与真机
  UART2 完全一致，透明对接，无需额外桥接进程）。
- **自动建链**：串口在后台自动打开；真机未插/端口未就绪时每 2s 重试；链路断开自动重连。
  双方 SSID/带宽/信道一致即自动连接（beacon→关联）。手动建链用 `AT+PAIR=1` 或改配置。
- 接线：`板 UART2(TX) → USB转串口(RX)`、`板 UART2(RX) → USB转串口(TX)`、共地 GND。

> ⚠️ 此桥接只对 **CH32V203 模拟器板**有效（它把空口放在 UART2 引脚）。
> 真实 **T-Halow-RJ45 是射频（802.11ah）**，没有可桥接的空口串口——PC 模拟器
> 无法与其建链（其数据通路在 RJ45 口，属真实射频域）。

### 支持 T-Halow-RJ45（真实板）

```bash
# 连两块真实 T-Halow-RJ45 板（板 A=AP 插 COM3，板 B=STA 插 COM4）
python server.py --a COM3:tj45 --b COM4:tj45
```

tj45 目标会：连接后自动下发 `AT+SYSDBG=LMAC,0` / `AT+SYSDBG=WNB,0` 关闭真实板的
调试刷屏；用裸 `AT+VERSION` 查询版本；状态解析同时兼容 `MODE:AP` 与 `+MODE:AP`。

```bash
# 两块真实 HT-HC01 板（占位：命令集待其手册，先按泰芯 AH 同款处理并关调试刷屏）
python server.py --a COM3:hc01 --b COM4:hc01
```

> **互联域限制**：只有「PC↔PC」能通过**虚拟空口(TCP)**互联；「真机↔真机」靠物理
> UART2（CH32V203 模拟器板）或 RF（T-Halow-RJ45）互联；**PC 与真机之间无法自动建链**，
> 但 UI 可同时管理任意组合（各自 AT/配置/状态照常可用）。
>
> **PC ↔ 真实 CH32V203 板例外**：PC 模拟器空口可改走**串口**（`--a-link/--b-link`）
> 直连板子 UART2，实现 PC↔真机建链（见上一节）。T-Halow-RJ45 真机除外（射频）。

### 接硬件（CH32V203 开发板）

```bash
python server.py                     # 自动识别 CH340/CH341/CH343/CH9102 串口
python server.py --a COM3 --b COM4   # 指定设备 A / 设备 B
python server.py --list              # 列出串口
python server.py --port 8899         # 自定义端口
```

启动后自动打开浏览器 `http://127.0.0.1:8899/`（`--no-browser` 可关闭）。

> 界面截图：`docs/ui_simplified_demo.png`（混合设备演示）。

## 界面功能

| 区域 | 功能 |
|------|------|
| **拓扑（设备信息唯一来源）** | 设备 A / B 卡片：设备名 + **类型**（CH32V203 虚拟机/真机、T-Halow-RJ45 虚拟机/真机）+ **模式**（AP/STA）+ **端口**（TCP :9001 / 串口 COM5 / COM3）+ SSID + 连接状态 + RSSI 信号条 + TX/RX/运行时长；中间为链路状态与流动动画（TCP 虚拟空口 / 串口空口 / UART2 物理空口） |
| **控制台** | 每台设备的 AT 控制台（标题简洁，仅"设备 A/B 控制台"；输入 + 发送 + 快捷命令 MODE/CONN/RSSI/SSID/PAIR/WNBCFG），事件（`+CONNECTED` 等）实时显示并闪烁对应卡片 |
| **帧监视器** | 打开"帧监视"后，解析 `FRAME:RX/TX <hex>` 输出，按以太网头高亮（目的/源 MAC、类型、长度、hex） |
| **配置面板** | 表单生成 AT 命令（模式/SSID/加密/PSK/带宽/信道），一键下发到指定设备 |

## 工作原理

```
浏览器(EventSource SSE)
   │
   ├── /api/events  ← 设备线程推送：状态 / 控制台行 / 事件(+XXX) / 帧(FRAME:*) / 日志
   ├── /api/info   ← 每台设备类型/空口描述（标题与链路标签用）
   └── /api/command ← POST 下发 AT 命令到设备
服务器(server.py) ── 传输层(SerialTransport/TcpTransport) ──▶ 设备控制台
```

- **逐台设备**：`--a/--b` 各自指定 `pc | pc:sim | pc:tj45 | pc:txah | pc:hc01 | COM3 | ...`
  （规范 key 与别名见 `host/devprofiles.py`）；
  PC 设备用 `TcpTransport` 连其 TCP 控制台（A `127.0.0.1:9001`，B `127.0.0.1:9002`），
  真机用 `SerialTransport` 连 UART 控制台（115200 8N1）。
- **空口**：PC 设备默认 TCP 虚拟空口；`--a-link/--b-link COMx` 改走串口空口连真机 UART2。
- 状态轮询：每 2s 发 `AT+CONN_STATE` / `AT+RSSI`，每 5s 发 `AT+MODE?` / `AT+SSID?`；
  解析 `KEY:value` 或 `+KEY:value`（T-Halow-RJ45）更新状态。
- **帧监视**：点击"帧监视: 开"会下发 `AT+SYSDBG=WNB,1`，模拟器即把空口数据帧
  以 `FRAME:RX/TX <hex>` 打印到控制台（PC 模拟器 / 固件 `sim_link.c` 均支持）。

## 用帧监视器看数据帧（无硬件演示）

1. `python server.py --host-sim` 启动后，浏览器显示 A(AP) 与 B(STA) 均 CONNECTED；
2. 点"帧监视: 开"（向 A、B 下发 `AT+SYSDBG=WNB,1`）；
3. 在设备 A 控制台输入 `AT+TXDATA=20`（等号分隔，长度含 14 字节以太网头），
   随后直接发送 20 字节原始数据（示例：`00 01 02 ... 13`）；
4. 帧监视器即显示 A `TX` 与 B `RX` 两条记录（目的/源 MAC、类型、长度、hex）。

> 注意：`AT+TXDATA=<len>` 用**等号**，随后进入数据模式、按字节数收原始数据
> （与 T-Halow-RJ45 参考板行为一致）。

## 注意事项

- `--host-sim` / `pc` 规格：完全无硬件；退出服务器即关闭进程内 PC 模拟器。
- 接硬件（serial 规格）：每台设备一根 USB 线接它的 CH340C AT 控制台；串口 115200 8N1。
- 设备 B 未指定时界面显示 OFFLINE（可先连单台）。
- 帧监视开启后控制台会有较多 hex 输出；关闭"帧监视"即下发 `AT+SYSDBG=WNB,0`。
- **帧监视对真实 T-Halow-RJ45 可能为空**：帧监视依赖 `AT+SYSDBG=WNB,1` 后输出的
  `FRAME:RX/TX <hex>` 行，真实板固件格式可能不同（其数据通路在 RJ45 口而非 SPI）。
- **互联域**：PC↔PC 走虚拟空口；真机↔真机走物理 UART2/RF；PC 与真机不能自动建链。
