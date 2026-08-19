# SPI 宿主接口帧协议

模拟器通过 **SPI1 从机**向 host 提供与 TXW8301 `MACBUS_SPI` 语义对齐的总线接口。
本文定义电气连接、帧格式、命令字与应答、事件通知机制。

> 设计目标：**host 侧驱动在真实 TXW8301 与模拟器之间可移植**。真实芯片的
> MACBUS 帧细节属于厂商私有协议，此处按 `mac_bus` 的 write/recv 语义
> （`mac_bus_write` / `mac_bus_recv` / `DATA_AREA_SIZE=1700`）设计了
> 一套简单、带长度和校验的帧协议，作为"模拟版"宿主协议。

## 1. 电气连接

| 信号 | 方向 | 模拟器引脚 | 说明 |
|------|------|-----------|------|
| `SCK` | host→sim | PA5 | SPI 时钟（从机，速率由 host 决定，建议 ≤ 4MHz） |
| `MOSI` | host→sim | PA7 | host 数据输出 / 模拟器数据输入 |
| `MISO` | sim→host | PA6 | 模拟器数据输出 |
| `NSS` | host→sim | PA4 | 片选，低有效（软件 NSS，EXTI 边沿检测事务边界） |
| `IRQ` | sim→host | PB0 | 数据就绪/事件通知，高有效（见 §4） |
| `GND` | - | GND | 共地 |

SPI 模式：**CPOL=0, CPHA=0**（Mode 0），MSB 优先，8bit。

## 2. 帧格式（全双工，一次 CS 事务一帧）

host 拉低 `NSS`，发送 4 字节头部 + `LEN` 字节载荷；模拟器同拍回发应答。

```
偏移   名称      长度   说明
0      CMD       1     命令字（bit7=1 表示应答）
1      LEN_H     1     载荷长度高字节
2      LEN_L     1     载荷长度低字节
3      CRC       1     CRC8 校验：CMD..LEN_L 与全部载荷
4..    PAYLOAD   LEN  载荷（host→sim 为请求体；sim→host 为应答体）
```

- **LEN 上限**：`SIM_SPI_MAX_FRAME = 1700`（对齐 `DATA_AREA_SIZE`，含以太网头）。
- **CRC8**：CRC-8/ATM，多项式 `0x07`，初值 `0x00`，MSB-first（校验值 0xF4）。见 `Simulator/sim_util.c`。
- **NSS 时序（单事务乒乓）**：host 拉低 `NSS`，先发 `4+LEN` 请求字节，然后**紧接着**
  继续发 `0xFF` 占位字节并同时读取 MISO —— 模拟器在收到请求末字节的下一拍开始回发响应，
  因此**请求与响应在同一个 `NSS=0` 事务内完成**。帧结束后拉高 `NSS`。
- **CS 检测**：模拟器用 PA4(NSS) 的 EXTI 上升/下降沿识别事务边界（软件 NSS），
  响应阶段的占位字节会被忽略，不会被误当成新请求。
- **全双工**：host 在发送同时读取 MISO；模拟器无待发数据时回 `0xFF`。
  响应长度固定按 `4+1700` 读回（不足部分为 0xFF），由响应头解析实际长度。

## 3. 命令字

| CMD | 名称 | 载荷(host→sim) | 应答(载荷) |
|-----|------|----------------|------------|
| `0x01` | `AT_CMD` | AT 命令字符串（含 `\r\n`） | AT 响应字符串（`...OK\r\n`） |
| `0x02` | `GET_STATE` | 无 | `struct sim_state`（见 §5） |
| `0x03` | `DATA_TX` | 以太网帧（≥14B 头 + 载荷） | `OK` / `ERROR` |
| `0x04` | `DATA_RX` | 无 | 一帧待收以太网帧；若无则 `ERROR` |
| `0x05` | `EVENT` | 无 | 一条待读异步事件（`+XXX` 文本）；无则 `ERROR` |
| `0x06` | `PING` | 无 | `PONG` |
| `0x07` | `RESET` | 无 | `OK`（随后软复位） |
| `0x08` | `SET_CFG` | `struct sim_cfg` 的二进制镜像 | `OK` |
| `0x09` | `GET_CFG` | 无 | `struct sim_cfg` 二进制镜像 |

应答头：`CMD|0x80`，`LEN` 为应答载荷长度，`CRC` 覆盖应答头+应答载荷。
应答失败统一返回 `ERROR`（ASCII），便于 host 驱动区分。

## 4. 事件通知（IRQ）

模拟器在有**待收数据帧**或**异步事件**时，将 `IRQ`(PB0) 置高并保持，直到 host
读取完对应队列：

- host 收到 IRQ 高 → 先 `EVENT`(0x05) 读事件（可多次，直到 `ERROR`），
  再 `DATA_RX`(0x04) 读数据帧（可多次，直到 `ERROR`）。
- 两队列均空后，模拟器自动拉低 IRQ。

这与真实模块"host 通过中断/轮询取包"的模型一致。

## 5. 状态结构 `struct sim_state`（GET_STATE 返回）

```c
struct sim_state {
    uint8  mode;        // SIM_MODE_AP/STA/APSTA/GROUP
    uint8  conn_state;  // SIM_CONN_IDLE/SCANNING/ASSOCIATING/CONNECTED/DISCONNECTED
    uint8  sta_cnt;     // 关联 STA 数（AP）
    int8   rssi;        // 信号强度 dBm
    uint8  pairing;     // 是否正在配对
    uint8  encrypt;     // 是否启用加密（WPA-PSK）
    uint8  mac[6];
    uint8  ssid_len;
    char   ssid[32];
    uint16 chan_list[16];  // 频点(0.1MHz)
    uint8  chan_cnt;
    uint8  bss_bw;         // 1/2/4/8 MHz
    uint32 up_time_ms;     // 运行时长
};
```

`struct sim_cfg`（GET/SET_CFG）见 `Simulator/sim_cfg.h`，字段与 `AT+WNBCFG` 输出一致。

## 6. Host 侧参考流程

```text
1) 初始化：拉高 NSS；配置 SPI Mode0；等待模拟器 IRQ 或直接轮询。
2) 配置：SET_CFG(0x08) 或逐条 AT_CMD(0x01) 发送 AT+...（推荐 AT，便于移植）。
3) 状态：周期 GET_STATE(0x02) 或轮询 CONN_STATE；也可订阅事件。
4) 发数据：DATA_TX(0x03) 送以太网帧 → 经虚拟空口转发到对端。
5) 收数据：IRQ 高 → EVENT/DATA_RX 读到对端帧。
```

> **事务模型**：每个命令在**单次 CS 事务**内完成 —— 拉低 NSS → 发请求帧 →
> 继续发 `4+1700` 个 `0xFF` 同时读回响应 → 拉高 NSS，按响应头解析实际长度。
> 上位机参考实现：`tools/sim_config.py`（CH341A/CH347A，实验性）。

## 7. 与真实 MACBUS 的差异（移植注意）

| 项目 | 真实 TXW8301 MACBUS_SPI | 本模拟器 |
|------|------------------------|----------|
| 帧格式 | 厂商私有（含 agg/desc） | 简化为 CMD+LEN+CRC 帧 |
| 最大载荷 | 约 1700B（DATA_AREA_SIZE） | 1700B |
| 事件 | host 中断读寄存器 | IRQ + EVENT 命令 |
| AT 路径 | UART 控制台为主 | SPI 亦可（AT_CMD） |

host 驱动把"底层收发"抽象成 `bus_write / bus_recv` 两个函数，即可在两种实现间切换。
