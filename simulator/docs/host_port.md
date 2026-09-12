# host 数据口 —— 上层程序的数据面（PC 模拟器）

> **这是一份跨仓契约**：`orpah-over-halow`（ORPAH 业务全链路）等上层程序就靠它收发数据帧。
> 实现见 `host/sim.py` 的 `HostPort` 类；固件/真机上与之对应的是 **SPI 从机**
> （见 [spi_protocol.md](spi_protocol.md)）。

## 1. 为什么需要它

AT 控制台是**控制面**：`AT+TXDATA` 是给人手敲**单帧**用的调试口 —— 它会进入粘性的数据模式、
还会改写 EtherType（见 T-Halow-RJ45 的踩坑记录），不适合上层程序长期跑数据。

上层程序（比如 ORPAH 的 Client / Router 程序）要的是**数据面**：

- 持续把以太网帧注入模块（主机 → 模块 → 空口）；
- 持续接收模块从空口收到、且目的为本机/广播/组播的帧。

所以 PC 模拟器额外开一个 **TCP「host 数据口」**（命令行 `--host <port>`），语义与真实模块的
SPI MACBUS 对齐：**将来换成真实 SPI 收发，上层程序一行不用改**。

```
 上层程序（Client / Router / 你自己的 host 驱动）
        │  host 数据口（TCP）：AA 55 TYPE LEN CRC payload
        ▼
 [PC 模拟器 A]  ──虚拟空口（TCP 或串口）──▶  [PC 模拟器 B]  ──host 数据口──▶  上层程序
```

## 2. 帧格式

与空口帧**完全同构**（同一份组帧/解帧代码）：

```
AA 55 TYPE LEN_H LEN_L CRC payload
│  │  │    └──┬──┘   │   └── 载荷：**整个以太网帧**（14B 头 + 载荷，≥14B，≤1700B）
│  │  │       │      └────── CRC-8/ATM（多项式 0x07，MSB-first，初值 0）
│  │  │       └───────────── 载荷长度（大端，2 字节）
│  │  └───────────────────── 类型：0x01 = 数据帧（LINK_TYPE_DATA）
│  └──────────────────────── 固定头 0xAA
└─────────────────────────── 固定头 0x55
```

- **CRC 覆盖范围** = `TYPE LEN_H LEN_L + payload`（不含 `AA 55` 与 CRC 自身）。
- host 口**只接受/只推送 `TYPE=0x01`**；其它类型（beacon/assoc 等服务帧）一律不转发给 host。
- 载荷长度 < 14（不是一个完整以太网头）→ 丢弃，不进空口。

## 3. 方向与语义（对应 SPI MACBUS）

| 方向 | 语义 | 实现 |
|---|---|---|
| host → 模块 | **DATA_TX**：注入一帧 → 走空口转发出去 | `HostPort._feed()` → `Wifi.send_data()` → `Link.send(DATA)` |
| 模块 → host | **DATA_RX**：空口收到、且目的为本机/广播/组播的帧 → 推给 host | `Wifi.handle_frame(DATA)` → `HostPort.push()` |

**注入在什么情况下会失败**（`send_data()` 返回 -1，帧被丢掉，无上报）：

- 帧长 < 14 或 > `MAX_FRAME`(1700)；
- 本机是 STA/APSTA 且当前 `CONN_STATE != CONNECTED`；
- 本机是 AP 且**还没有任何 STA 关联**（没人可转发）。

**推送在什么情况下会丢**：当前没有 host 连着（`push()` 直接返回）—— host 口是单连接，
后连上的会把先前那条连接顶掉（`self.sock` 被替换）。

## 4. 怎么用

命令行（模拟器侧）：

```bash
# AP 侧开 host 数据口 9021；端口写 0 = 让内核自动分配（启动行会打印实际端口）
python host/sim.py --name A --role AP --console 9001 --link 9011 --host 9021
```

Python（进程内嵌，例如给 UI / 测试用）：

```python
import sim

ap = sim.Core("A", "AP", 0, 0, None, host_port=0)   # 端口 0 = 自动分配，避免与别的实例撞车
sta = sim.Core("B", "STA", 0, 0, ("127.0.0.1", ap.link.link_port), host_port=0)

print(ap.console.port, ap.link.link_port, ap.hostport.port)   # 回读实际端口
```

上层程序侧（示例语义，不含具体实现）：连上 `127.0.0.1:9021`，按上面帧格式收发即可。
参考实现见 `orpah-over-halow/host_bus.py`（`frame_data()` / `HostBus`）。

## 5. 端口与实例

- **端口 0 = 内核自动分配**（`core.console.port` / `core.link.link_port` /
  `core.hostport.port` 回读实际值）。测试与多实例**一律用 0**。
- 固定端口在 Windows 上有个坑：`SO_REUSEADDR` 允许**两个进程同时绑定同一端口**
  （Linux 不允许），于是两个模拟器/别的仓库正在跑的 demo 会**静默共处**，客户端连上去可能
  落到另一个进程 —— 表现为莫名其妙的假数据/假失败。模拟器启动时会探一下，占用就打印告警
  （见 `sim.tcp_port_in_use`）。

## 6. 与真机的关系

| | PC 模拟器 | 真机（CH32V203 模拟器板 / 真实模块） |
|---|---|---|
| 物理层 | TCP | SPI（`MACBUS_SPI`：CS/SCK/MOSI/MISO + IRQ） |
| 帧格式 | 本文的 `AA 55 …` | 同构（`spi_protocol.md` 的 DATA 帧） |
| 语义 | DATA_TX / DATA_RX | 同 |

所以上层程序只需要换**底层收发**（把 socket 换成 SPI 驱动），协议层/业务层不变。

## 7. 谁在用它

- `orpah-over-halow`：`host_bus.py`（帧编解码 + 收发线程）、`client.py` / `router.py` / `ui_server.py`
  都通过它跑数据面（见该仓 `README.md` 的「分开跑（理解各进程）」）。
- 本仓回归测试：`host/test_sim.py` 第 7 节（3 条用例：A→B、B→A、坏帧丢弃且好帧仍按序到达）。

## 8. 改这里要注意

- 改帧格式/语义 = **破坏跨仓契约** → 必须同时改上层（至少 `host_bus.py`）并更新本文与
  `spi_protocol.md`。
- 改 `HostPort` / `send_data` 的丢弃条件要同步本文第 3 节（它现在是"哪些帧会丢"的唯一说明）。
