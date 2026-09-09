# ORPAH-over-HaLow L1 Demo（纯 PC，无硬件）

> 在 halow-demo 内、基于 PC 模拟器（`host/sim.py`）实现的 ORPAH **L1 数据通路最小
> 骨架**。目标（SPEC §9 L1）：证明「HaLow STA 关联 AP 后能把一个 payload 上行到
> 奥帕 Server」。成熟后再抽离独立 `orpah-demo` 仓库。

## 一图流

```
[Client host]  --注入以太网帧-->  [STA 模块]  --HaLow 虚拟空口-->  [AP 模块]  --host口-->  [Router 桥]  --UDP-->  [Server]
  client.py      ORPAH-REPORT      sim.py B       二层透明桥          sim.py A        router.py       真实 UDP        server.py
                JSON→0x88B5帧
```

| 角色 | 真实形态 | 本 Demo 形态 |
|---|---|---|
| Client | 免电池可穿戴：TX-AH(STA) + CH32V203(host/SPI 数据面) | `client.py` + STA 模拟器 |
| Router | TH-RJ45：AP + RJ45 网口上行 | `router.py` + AP 模拟器（host 口 = 网口上行） |
| Server | 云端/本地 Python | `server.py`（真实 UDP socket） |
| 链路 | 802.11ah 空口 | 模拟器「虚拟空口」（TCP，帧格式同固件 sim_link） |

## L1 做什么 / 不做什么

**做**：
- Client 周期生成 `ORPAH-REPORT`（JSON），封装成以太网帧（ethertype `0x88B5`
  ORPAH-L1 实验类型，见 `Protocol/docs/orpah-over-halow/SPEC.md` §5/§6 倾向 A），
  经 host 数据口注入 STA 模块。
- STA 经虚拟空口把帧转发到 AP；AP 的 host 数据口把收到的帧推给 Router 桥。
- Router 桥剥出 ORPAH JSON，用**真实 UDP** 转发到 Server 固定端口（默认 `19447`）。
- Server 收到即打印 = **L1 验收：payload(JSON) 从 STA 上行到 Python Server**。

**不做（L2+）**：`ORPAH-REQ-CONNECT` / `ACCESS-INFO` / `TRACKING-STATUS` 回程、
走失表、多 Router 选路/去重、IMEI 15 位校验、免电池真硬件。

## 快速开始（零硬件）

### 方式 1：Web UI（推荐，看得见的 demo）

```bash
cd simulator/orpah
python ui_server.py                  # 自动开浏览器 http://127.0.0.1:8901/
# 或：python ui_server.py --every 1.5 --sn ORPAH-0001
```
- 内嵌 AP+STA 模拟器 + Router 桥 + Server，Client **自动周期上报**。
- 页面：三层拓扑（Client→STA→空口→AP→Router→Server）+ ORPAH-REPORT 实时
  报文流（Client注入/Router上行/Server收到 三阶段 ✓）+ 三端计数 + 暂停/改 sn/改间隔。
- 页面数据链路：SSE 事件（点亮动画）+ `/api/status` 全量（计数/连接/表格真相）。

### 方式 2：命令行验收

```bash
cd simulator/orpah
python demo_l1.py --n 3        # 进程内建 AP+STA 模拟器 + Server/Router/Client，验收 3 条上行
# 期望输出结尾：Client 注入: 3 条 / Server 收到: 3 条 / 结果: PASS
```

## 分开跑（理解各进程）

终端 1 — AP 模拟器（Router 侧，开 host 口）：
```bash
python host/sim.py --name Router-AP --role AP --console 9401 --link 9411 --host 9421
```
终端 2 — STA 模拟器（Client 侧，开 host 口，连 AP 空口）：
```bash
python host/sim.py --name Client-STA --role STA --console 9402 --link 9412 --peer 127.0.0.1:9411 --host 9422
```
终端 3 — Server：
```bash
python orpah/server.py --port 19447
```
终端 4 — Router 桥（连 AP 的 host 口，转发 UDP）：
```bash
python orpah/router.py --ap-port 9421 --server-port 19447
```
终端 5 — Client（连 STA 的 host 口，周期上报）：
```bash
python orpah/client.py --sta-port 9422 --sn ORPAH-0001 --every 3
```
> 需先让 STA 关联 AP（同一 SSID，默认自动 halowlink@9080；等 `AT+CONN_STATE`=CONNECTED
> 再开 Client）。可用 `telnet 127.0.0.1 9402` 看状态。

## 代码结构与关键机制

```
simulator/
├── host/
│   └── sim.py            # PC 模拟器：新增「host 数据口」(--host <port>)
│                         #   语义 = SPI MACBUS DATA_TX/DATA_RX；帧格式同空口
│                         #   AA 55 TYPE LEN CRC payload；收帧进 rx_queue 的同时推给 host
└── orpah/
    ├── orpah_proto.py    # ORPAH 常量、REPORT JSON 编解码、以太网帧封装
    ├── host_bus.py       # host 数据口驱动（只依赖 TCP+帧格式，不 import sim）
    ├── client.py         # Client host：注入 ORPAH-REPORT
    ├── router.py         # Router 桥：AP host 口收帧 → UDP 转发 Server
    ├── server.py         # Server：UDP 收 ORPAH-REPORT
    ├── ui_server.py      # Web UI：内嵌整条链路 + HTTP/SSE（方式 1）
    ├── ui/static/        # 前端 index.html / style.css / app.js
    └── demo_l1.py        # 端到端演示 + 验收（内嵌 2 模拟器，命令行）
```

### sim.py host 数据口（本次给模拟器加的最小扩展）
- `HostPort` 类：TCP server，host 连入后：
  - host→模块：`AA 55 01 LEN CRC + 以太网帧` → `wifi.send_data()`（DATA_TX，走空口转发）
  - 模块→host：收到空口 DATA 帧（广播/本机）→ `hostport.push()`（DATA_RX）
- `Core(..., host_port=None)` / CLI `--host <port>`；不给则完全不影响原有行为
  （现有 24 项回归测试全过）。

### 帧格式（host_bus.py 独立实现，与 sim.py 一致）
```
AA 55 TYPE(0x01) LEN_H LEN_L CRC-8/ATM(poly 0x07) payload(=以太网帧 ≥14B)
```

## 报文（L1：仅上行 ORPAH-REPORT）

```json
{"v":1,"type":"ORPAH-REPORT","sn":"ORPAH-DEMO-0001","ts":1788961894,"rssi":-55,"seq":1}
```
- `sn`：被追踪设备序列号（F-01 待定：将来可换 15 位 IMEI）。
- `seq`：Client 侧递增序号（后续去重/LOST-TABLE 用）。

## 验收标准（L1）

1. 模拟器原 24 项回归不受影响（`python host/run_tests.py` 仍 24/24）。
2. `demo_l1.py --n 3`：Server 收到 3 条、sn 一致 → PASS。
   = 「HaLow STA 关联 AP 后 payload 上行到 Server」达成。

## 下一步（L2，另开任务）

- 报文子集 + 走失表 + 跟踪状态（Server→Router→Client 回程），对齐 SPEC §4 时序。
- 跨固件最终形态（TH-RJ45 V2.4-WNB Router ↔ TX-AH V2.4-FMAC Client）真机数据面
  迁移（host 数据口语义已对齐 SPI MACBUS，可平滑替换底层）。
