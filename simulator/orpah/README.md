# ORPAH-over-HaLow L1/L2 Demo（纯 PC，无硬件）

> 在 halow-demo 内、基于 PC 模拟器（`host/sim.py`）实现的 ORPAH-over-HaLow 原型。
> L1 = 数据通路最小骨架（SPEC §9 L1）；L2 = 全消息流 + 走失表 + 跟踪状态（§9 L2，
> 已含双向 Server→Client 下行）；L3 = 多 Router 漫游/去重 + SN 码号校验
> （SPEC F-04/F-07/F-01）。成熟后再抽离独立 `orpah-demo` 仓库。

## 一图流（L1 数据通路）

```
[Client host]  --注入以太网帧-->  [STA 模块]  --HaLow 虚拟空口-->  [AP 模块]  --host口-->  [Router 桥]  --UDP-->  [Server]
  client.py      ORPAH-REPORT      sim.py B       二层透明桥          sim.py A        router.py       真实 UDP        server.py
                JSON→0x88B5帧
```

L2 在其上加**下行**（Router 的 host 口连接双向）：Server UDP 应答 → Router 注入
AP 空口 → STA 模块收 → host 口推给 Client。

| 角色 | 真实形态 | 本 Demo 形态 |
|---|---|---|
| Client | 免电池可穿戴：TX-AH(STA) + CH32V203(host/SPI 数据面) | `client.py` + STA 模拟器 |
| Router | TH-RJ45：AP + RJ45 网口上行 | `router.py` + AP 模拟器（host 口 = 网口上行） |
| Server | 云端/本地 Python | `server.py`（真实 UDP socket + 权威走失库） |
| 链路 | 802.11ah 空口 | 模拟器「虚拟空口」（TCP，帧格式同固件 sim_link） |

## L1 做什么

- Client 周期生成 `ORPAH-REPORT`（JSON），封装成以太网帧（ethertype `0x88B5`
  ORPAH-L1 实验类型，见 `Protocol/docs/orpah-over-halow/SPEC.md` §5/§6 倾向 A），
  经 host 数据口注入 STA 模块。
- STA 经虚拟空口把帧转发到 AP；AP 的 host 数据口把收到的帧推给 Router 桥。
- Router 桥剥出 ORPAH JSON，用**真实 UDP** 转发到 Server 固定端口（默认 `19447`）。
- Server 收到即打印 = **L1 验收：payload(JSON) 从 STA 上行到 Python Server**。

## L2 做什么（2026-09-09 已实现）

- **报文全集**（`orpah_proto.py`，统一 JSON 公共头 `v/type/sn/ts`）：
  `ORPAH-REQ-CONNECT`(C→R) / `ORPAH-ACCESS-INFO`(R→C, 含 tracked/server_ok) /
  `ORPAH-REPORT`(C→R→S) / `ORPAH-TRACKING-STATUS`(S→R→C) / `ORPAH-ERROR` /
  `ORPAH-LOST-TABLE`(S→R)。
- **双向时序**（对齐 SPEC §4）：
  1. REQ-CONNECT (C→R) → Router 查本地走失缓存 → ACCESS-INFO (R→C, tracked?)
  2. REPORT (C→R) → Router UDP 转发 → Server 查权威走失库 → TRACKING-STATUS
     (S→R，命中=TRACKED / 未命中=NOT-TRACKED) → Router 注入空口下行 → Client 收到
  3. Server `mark_tracked/untrack` → 下发 LOST-TABLE → Router 更新缓存 →
     下一周期 REQ-CONNECT 的 ACCESS-INFO.tracked 随之变化
- **验收**：`demo_l2.py`（两分支都 PASS：未命中 NOT-TRACKED / mark 后 TRACKED）。
- UI 已加「L2 协议消息流」面板 + 走失表标记/取消按钮。

**L2 不做（留后续）**：免电池真硬件。多 Router 选路/去重与 SN 校验已在 **L3** 落地，
Router 主动拉表已在 **L3b** 落地（见下）。

## L3 做什么（2026-09-10 已实现）

- **F-07 漫游/选路**：同一 Client（同 sn）先后出现在 R1、R2 两网（`demo_l3.py` 用
  2×AP + 2×Router 模拟移动）——Server 以**上报来源**为该 sn 的**当前 Router**
  （最新位置优先），REQ/REPORT 的回执（ACCESS-INFO / TRACKING-STATUS）只回当前
  Router，旧 Router 不再收到该 sn 的下行。
- **F-04 去重**：Server 按 **(sn,seq)** 丢弃重复上报（同一 Router 重发、或另一
  Router 迟到转发同一帧）：不重复计数、不再回 TRACKING-STATUS、且**不把“当前
  Router”切回旧 Router**（防漫游时被迟到重传拽回）。`server.py` 维护 seen 窗口
  （每 sn 最近 256 个 seq，容忍序号重启/回绕）。
- **F-01 SN 码号（对齐《Orpah ID 协议规范》v1.7）**：SN = **`CC-ORG-UNIQUE[-CHECK]`**
  （CC=ISO 3166 alpha-2；ORG 2–6 / UNIQUE 8–16 / CHECK 0–2 位，均为 **Crockford Base32**，
  去 `I L O U`）。`orpah_proto.sn_err()` 校验（empty / too-long / bad-format），Server
  收 REPORT 时校验，非法 → ERROR `FORMAT-ERR`（msg_text `bad-sn:<原因>`），不计数。
  **中文/姓名不进 SN**（放 payload 业务字段）；默认 SN = `CN-WH01-9AF3C1D2`。
- **F-03 补充：新 Router 首报追平**：Server 首次见到一台 Router 上报 → 立即把当前
  走失表全量推给它，避免它在 REQ-CONNECT 时因本地缓存为空误答 NOT-TRACKED。
- **验收**：`demo_l3.py`（7 项检查全 PASS：两阶段漫游回执归属、双 Router 缓存一致、
  tracked 分支、同/跨 Router 去重不回执、去重不切回旧 Router、非法 SN → FORMAT-ERR）。

## L3b（2026-09-10 已实现）Router 主动拉取走失表

- **背景缺口**：Server 只在「走失表变更」或「新 Router 首报」时主动推。若 Router
  重启（缓存清空）或此前从未接触 Server，且期间无变更事件 → 对已 mark 的 sn 会误答
  NOT-TRACKED。
- **解决**：新增报文 **`ORPAH-LOST-TABLE-REQ`**（R→S，Router 主动拉取）。
  `router.py` 的 `sync(timeout)`：发 REQ + 等 Server 回 LOST-TABLE（`_lost_event`），
  触发时机：**① Router.start() 启动即拉一次**（重启追平，Server 未就绪则超时忽略）；
  **② 尚未同步时（重启后 / 启动拉表失败）的首个 REQ-CONNECT 再拉一次**（此后每次变更
  Server 都会推全量表，无需每条 REQ 都拉——避免空表下重复拉取洪泛）。Server 收到 REQ：
  把该 Router 记入“见过集”（此后变更也推给它）+ 回当前全量表。
- **UI（2026-09-10）**：「走失表」卡片加**「服务器发布记录」**——走失数据是服务器主动下发
  的（mark/untrack 发 LOST-TABLE），每次发布记一条（时间/表项数/目标路由器/内容
  `sn=走失|未走失`）；逐条 TRACKING-STATUS 回执属响应，不计数不展示。
- **验收**：`demo_l4.py`（4 项检查全 PASS：mark 后启动 Router 即拉表追平、首次 REQ 答
  tracked=True、清缓存后 REQ 同步拉取首问即权威、变更推送仍生效且 REQ 不重复拉取）。

## L3c（2026-09-10 已实现）发现走失上报（ORPAH-FOUND）

- **业务**：Router 在 REQ-CONNECT **命中本地走失缓存**（tracked=True）时，即上报
  **`ORPAH-FOUND`**（R→S，**每次命中都发**）——业务告警 = “某 Router 发现走失者”。
- `router.py` `_announce_found`（found_count + on_found）；`server.py` 处理 FOUND 记录/计数。
- **UI**：「发现记录（走失命中）」feed（时间 + 发现 sn）+ Router 卡片「发现 N 次」。
- 与下链语义区分：逐条 TRACKING-STATUS 回执属响应不计数；**发现（ORPAH-FOUND）与走失表
  下发（发布/收到）是业务事件**，单独计数/展示。

## Orpah ID 层（2026-09-10 已实现，`orpah_id.py` + `demo_id.py`）

- **定位**：落实《Orpah ID 协议规范》（`Protocol/docs/OrpahIDProtocol.md` v1.12）的
  **身份与真实性层**——SN 码号 + CHECK 校验 + 数字签名 + 防重放。**独立成层**，
  不改动上面 L1–L4 的 ORPAH-REPORT 等业务报文。
- `orpah_id.py`：Crockford Base32 编解码 / SN 生成·解析·校验（`CC-ORG-UNIQUE[-CHECK]`）/
  CHECK（Mod 97 两位 + Luhn mod 32 一位；Damm32 待 Phase 2 表定稿）/
  JCS(RFC 8785) 规范化 / 报文签名（ES256=ECDSA P-256、HS256=HMAC-SHA256、none）/
  server 验签（§9.3：alg 白名单、时间窗口含 ts=0 跳过、nonce 去重、CHECK、撤销、密钥检索）/
  router `xport` 附加观测（不参与验签）。
- 依赖 `cryptography`（ES256/HS256 需要；缺失时仅 L3 none 可用）。
- **验收**：`python demo_id.py`（22 用例：四级降级签名验签 + 篡改/重放/超窗/坏 CHECK/
  未知设备/撤销/xport 全 PASS）。
- **独立跑 `server.py` 注意**：Orpah ID 验签需要密钥库。UI（`ui_server.py`）在进程内
  自动注册设备；独立 `python server.py` 缺省**未配置密钥库** → 所有 `ORPAH-ID-REPORT`
  判 `unknown_device`（业务报文 L1/L2 不受影响）。要独立验签：先用 `KeyStore.save()`
  导出一份密钥库 JSON，再 `python server.py --keystore-file <json>` 加载：
  ```bash
  python -c "import orpah_id as o; ks=o.KeyStore(); ks.register(o.Device(sn='CN-WH01-9AF3C1D2')); ks.save('keystore.json')"
  python server.py --keystore-file keystore.json
  ```

## 快速开始（零硬件）

### 方式 1：Web UI（推荐，看得见的 demo）

```bash
cd simulator/orpah
python ui_server.py                  # 自动开浏览器 http://127.0.0.1:8901/
# 或：python ui_server.py --every 1.5 --sn CN-WH01-9AF3C1D2
```
- 内嵌 AP+STA 模拟器 + Router 桥 + Server，Client **自动周期上报**。
- 页面：精简 3 节点拓扑（客户端 →(空口)→ 路由器 →(UDP)→ 服务器）+ ORPAH-REPORT
  实时报文流（客户端注入/路由器上行/服务器收到 三阶段 ✓）+ 三端计数 + 空口收发
  （单向上行：客户端发送/路由器接收增长）+ 暂停/改 sn/改间隔。
- 文案走共享字典 `tools/ui/static/ui_i18n.js`（zh/en，`?lang=en` 可切英文预览）。
- 页面数据链路：SSE 事件（点亮动画）+ `/api/status` 全量（计数/连接/表格真相）。

### 方式 2：命令行验收

```bash
cd simulator/orpah
python demo_l1.py --n 3        # 进程内建 AP+STA 模拟器 + Server/Router/Client，验收 3 条上行
# 期望输出结尾：Client 注入: 3 条 / Server 收到: 3 条 / 结果: PASS
```

### 方式 3：一键跑全部检查 + 出报告（推荐做回归时用）

```bash
cd simulator/orpah
python run_checks.py            # 7 个离线套件（各模块自检 + 批量合规用例），约 1 秒
python run_checks.py --e2e      # 再加 5 个端到端 demo（L1/L2/L3/L3b/防 spoof），1-3 分钟
```
- 报告写到 `checks_report.md`（含 git HEAD、每套件结果/耗时/关键输出、失败详情）。
- **`--e2e` 前请先停 orpah-ui**：demo 与它（:8901 那一套）端口串扰会跑出假失败；
  脚本会自己检查并**拒绝执行**（退出码 2），不会给你一份误导的报告。
- 判定 = 退出码 0 **且** 输出无 `FAIL`/`Traceback`（有些脚本自己吞异常还会往下跑）。

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
python orpah/client.py --sta-port 9422 --sn CN-WH01-9AF3C1D2 --every 3
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
    ├── orpah_proto.py    # ORPAH 常量、L1/L2 报文编解码（REQ-CONNECT/ACCESS-INFO/
    │                     #   REPORT/TRACKING-STATUS/ERROR/LOST-TABLE）、以太网帧封装
    ├── host_bus.py       # host 数据口驱动（只依赖 TCP+帧格式，不 import sim）
    ├── client.py         # Client host：双向（REQ-CONNECT→REPORT + 收下行回执）
    ├── router.py         # Router 桥：双向（上行转发 + 下行注入；走失缓存）
    ├── server.py         # Server：权威走失库 + UDP 应答/TRACKING-STATUS/LOST-TABLE
    ├── waiting.py        # 共享等待工具：wait_until / wait_new（按截止时间，不猜循环次数）
    ├── ui_server.py      # Web UI：内嵌整条链路 + HTTP/SSE（方式 1）
    ├── ui/static/        # 前端 index.html / style.css / app.js
    ├── demo_l1.py        # L1 端到端验收（内嵌 2 模拟器，命令行）
    ├── demo_l2.py        # L2 全消息流验收（双向 + 走失两分支，命令行）
    ├── demo_l3.py        # L3 多 Router 漫游/去重 + SN 校验验收（2×Router）
    ├── demo_l4.py        # L3b Router 主动拉表验收（启动/缓存未命中拉取）
    ├── demo_spoof.py     # 防 spoof 真·端到端（攻击注入空口，Server 侧断言）
    ├── demo_hw1.py       # 【未真机验证】阶段二真机自检：板卡代次/族、关联、跨空口 UDP、raw 0x88B5 透传
    ├── run_checks.py     # 批量合规测试台：一键跑全部套件 + 出报告（checks_report.md）
    ├── checks_batch.py   # 表驱动批量用例（黄金样本 / SN 边界 / parse_sn / 报文编解码）
    ├── checks_report.md  # 最近一次测试台报告（入库，同 host/test_results.txt 惯例）
    └── docs/
        └── real-hw-stage2.md   # 上机手册 + 五组验证清单（不预设通路；烧录由用户执行）
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

## 报文（L1/L2，统一 JSON 公共头 v/type/sn?/ts）

L1 上行示例：
```json
{"v":1,"type":"ORPAH-REPORT","sn":"CN-WH01-9AF3C1D2","ts":1788961894,"rssi":-55,"seq":1}
```
L2 报文类型：`ORPAH-REQ-CONNECT`{sn,mac?,hw?}、`ORPAH-ACCESS-INFO`{sn,tracked,server_ok,status?}、
`ORPAH-TRACKING-STATUS`{sn,status:TRACKED|NOT-TRACKED|...}、`ORPAH-ERROR`{code}、
`ORPAH-LOST-TABLE`{entries:[{sn,tracked,note}]}、`ORPAH-LOST-TABLE-REQ`（R→S，Router
主动拉表，Server 回当前全量 LOST-TABLE）、`ORPAH-FOUND`（R→S，Router 发现走失，每次命中都发）。
- `sn`：被追踪设备标识（Orpah ID 码号 `CC-ORG-UNIQUE[-CHECK]`，Crockford Base32；
  中文/姓名放 payload；Server 校验非法 → ERROR `FORMAT-ERR`，见 `orpah_proto.sn_err`）。
- `seq`：Client 侧递增序号（去重用：Server 按 (sn,seq) 丢弃重复上报）。

## 验收标准

1. 模拟器原 24 项回归不受影响（`python host/run_tests.py` 仍 24/24）。
2. L1：`demo_l1.py --n 3` → Server 收到 3 条、sn 一致 → PASS。
3. L2：`demo_l2.py` → 双向打通（Client 收到 ACCESS-INFO + TRACKING-STATUS）且两分支
   正确（未 mark → NOT-TRACKED；mark 后 → ACCESS-INFO.tracked=True + TRACKED）→ PASS。
4. L3：`demo_l3.py` → 漫游（同 sn 先后经 R1/R2，回执只经当前 Router）、(sn,seq) 去重
   （同/跨 Router 重发不计数不回执、不切回旧 Router）、SN 校验（非法 → FORMAT-ERR）→ PASS。
5. L3b：`demo_l4.py` → mark 后启动 Router 主动拉表追平、清缓存后 REQ 同步拉取首问即
   权威、变更推送仍生效且不重复拉取 → PASS。
6. 真机（阶段二，**需硬件**）：按 `docs/real-hw-stage2.md` 的五组清单上机；`demo_hw1.py`
   负责能自动判的部分（固件代次/族、关联状态、跨空口 UDP、raw `0x88B5` 透传）。
   **两者均未经真机验证**，烧录/上机由用户执行。
7. **一键回归**：`python run_checks.py`（7 个离线套件，~1s）→ `checks_report.md`；
   加 `--e2e` 跑 5 个端到端 demo（**需先停 orpah-ui**，否则端口串扰；脚本会自己拒绝）。

## 下一步（L2.5/L4+）

- **L2.5 真机最终形态**（TH-RJ45 V2.4-WNB Router ↔ TX-AH V2.4-FMAC Client）数据面
  迁移（host 数据口语义已对齐 SPI MACBUS，可平滑替换底层；烧录由用户执行）。
- F-03 走失表子集下发/过期、F-05 防伪造/限频、F-06 隐私、F-08 RSSI 粗定位。
- 免电池客户端（TX-AH + CH32V203）低功耗策略。
