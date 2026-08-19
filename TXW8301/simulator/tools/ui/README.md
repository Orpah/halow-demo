# TXW8301 模拟器 Web UI

本地 Web 仪表盘，可视化并操控 1~2 台模拟器（CH32V203）。零第三方依赖（仅 pyserial，`--host-sim` 模式连 pyserial 都不需要）。

## 启动

### 无硬件（推荐，PC 版模拟器）

```bash
cd simulator/tools/ui
python server.py --host-sim          # 进程内跑 AP + STA 两台 PC 模拟器，自动配对
python server.py --host-sim --port 8899
```

`--host-sim` 直接在服务器进程内启动 `host/sim.py` 的两台模拟器
（A=AP、B=STA，SSID 均为 `halowlink`），通过 TCP 虚拟控制台连接。
浏览器打开后即可看到双机自动连接、下发 AT、监视数据帧——完全不需要硬件。

### 接硬件（CH32V203 开发板）

```bash
python server.py                     # 自动识别 CH340/CH341/CH343/CH9102 串口
python server.py --a COM3 --b COM4   # 指定设备 A / 设备 B
python server.py --list              # 列出串口
python server.py --port 8899         # 自定义端口
```

启动后自动打开浏览器 `http://127.0.0.1:8899/`（`--no-browser` 可关闭）。

## 界面功能

| 区域 | 功能 |
|------|------|
| **拓扑** | 设备 A / B 双机视图：模式、SSID、连接状态、RSSI 信号条、收发计数、运行时长、中间"虚拟空口"链路状态与流动动画 |
| **控制台** | 每台设备的 AT 控制台（输入 + 发送 + 快捷命令 MODE/CONN/RSSI/SSID/PAIR/WNBCFG），事件（`+CONNECTED` 等）实时显示并闪烁节点 |
| **帧监视器** | 打开"帧监视"后，解析固件 `FRAME:RX <hex>` 输出，按以太网头高亮（目的/源 MAC、类型、长度、hex） |
| **配置面板** | 表单生成 AT 命令（模式/SSID/加密/PSK/带宽/信道），一键下发到指定设备 |

## 工作原理

```
浏览器(EventSource SSE)
   │
   ├── /api/events  ← 设备线程推送：状态 / 控制台行 / 事件(+XXX) / 帧(FRAME:*) / 日志
   └── /api/command ← POST 下发 AT 命令到设备
服务器(server.py) ── 传输层(SerialTransport/TcpTransport) ──▶ 模拟器控制台
```

- 传输层抽象：`--host-sim` 用 `TcpTransport` 连 PC 模拟器的 TCP 控制台
  （设备 A `127.0.0.1:9001`，设备 B `127.0.0.1:9002`）；接硬件时用
  `SerialTransport` 连 UART 控制台（115200 8N1）。
- 状态轮询：每 2s 发 `AT+CONN_STATE` / `AT+RSSI`，每 5s 发 `AT+MODE?` / `AT+SSID?`；
  解析 `KEY:value` 更新状态。
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

- `--host-sim`：完全无硬件；退出服务器即关闭两台 PC 模拟器。
- 接硬件：每台模拟器需要一根 USB 线接它的 CH340C AT 控制台；串口 115200 8N1。
- 设备 B 未指定端口时界面显示 OFFLINE（可先连单台）。
- 帧监视开启后控制台会有较多 hex 输出；关闭"帧监视"即下发 `AT+SYSDBG=WNB,0`。
