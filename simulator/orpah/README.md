# ORPAH-over-HaLow 演示（纯 PC，无硬件）

> 在 halow-demo 内、基于 PC 模拟器（`host/sim.py`）实现的 ORPAH-over-HaLow 原型。
> **链路/协议**：L1 数据通路最小骨架（SPEC §9 L1）、L2 全消息流 + 走失表 + 跟踪状态
> （已含双向 Server→Client 下行）、L3 多 Router 漫游/去重 + SN 码号校验（F-04/F-07/F-01）、
> L3b Router 主动拉表、L3c 发现走失上报（ORPAH-FOUND）。
> **其上**：Orpah ID 身份/签名层、设备清册与走失案件、告警、指标面板、RSSI 定位与回放、
> SQLite + IoTDB 双存储。
> 只想先看懂系统：直接跳到《能力总览》《页面一览》《走一遍完整剧本》。
> 成熟后再抽离独立 `orpah-demo` 仓库。

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

---

## 能力总览（2026-09-12）

> 「能力」按协议/功能分层（不是代码目录），每项给出一句话实现位置 + 一个验收入口 ——
> 出问题时先跑那一项。

| 能力 | 实现 | 验收 / 自检 |
|---|---|---|
| L1 数据通路（以太网帧 `0x88B5` → UDP 19447） | `client.py` / `router.py` / `server.py` / `host_bus.py` | `demo_l1.py` |
| L2 全消息流 + 走失表 + 跟踪状态（双向） | `orpah_proto.py` | `demo_l2.py` |
| L3 多 Router 漫游/去重 + SN 码号 | `server.py`（`seen` 窗口） | `demo_l3.py` |
| L3b Router 主动拉表 `ORPAH-LOST-TABLE-REQ` | `router.sync()` | `demo_l4.py` |
| L3c 发现走失上报 `ORPAH-FOUND` | `router._announce_found` | `demo_l3.py` + 首页「发现记录」 |
| Orpah ID：码号/CHECK/签名/防重放/密钥多代轮换吊销 | `orpah_id.py` / `keystore.py` | `demo_id.py`、`test_keys.py` |
| 降级策略（§8）：按环节坏在哪自动选级 L0→L3；L2 告警、L3 只做覆盖发现（不当人员出现） | `orpah_id.pick_level()` / `counts_as_presence()` + `alerts.id_degraded` | `test_levels.py` + 首页「降级演示」下拉 |
| 无认证空口防 spoof（13 种攻击端到端） | `spoof.py` | `demo_spoof.py`、`test_spoof.py` |
| 设备清册 / 走失案件（立案→发现→找回·撤销→结案，含接手人） | `registry.py` / `cases.py` | 页面 + `test_server.py` |
| 告警（长未上报 / 案件超时 / 处置超时 / 验签失败率 / 降级上报 / 设备时钟 / **能力声明不一致**） | `alerts.py` | `test_alerts.py`、`test_levels.py` |
| 指标面板（验签失败率·算法分布 / 平均 RSSI / 处置时长） | `metrics.py` | `test_metrics.py` |
| 定位：多路由器观测 → 三边/WLS + 95% 椭圆 + 卡尔曼平滑 + 回放 + **误差 CDF（仅模拟环境有真值）** + **补站位建议（几何不行时给可执行坐标）** | `motion.py` / `stations.py` / `ui/static/pos.js` | `test_motion.py`、`test_posjs.py`（51 条 + 1 条页面守卫，套件自己报数） |
| 时钟可信：①无 RTC 设备 `ts=0` → 服务器接收时刻（唯一入口）②设备时钟**偏移/漂移估计**（只估计不改数据；长基线才给漂移，原因可见：基线不足/噪声）③**设备自报能力位 `cap.rtc`**（三态；已签声明防篡改；无 RTC ⇒ 一律服务器时刻且不喂估计器；声明有 RTC 却给不出可用时间 → `id_cap_mismatch` 告警） | `orpah_proto`（`effective_ts`/`cap_of`/`rtc_of`） / `clock.py`（`ClockTracker`） | `test_clock.py`（88 条）+ `test_server.py`（28 条）+ `test_alerts.py` + `demo_clock.py` + 首页「上报控制」能力下拉/ts 置 0 |
| 抓包解析 / 双源对照（pcap → ORPAH 报文；与 UDP 侧计数对差） | `capture.py`（解析复用 `orpah_proto` 单一源） | `test_capture.py` |
| **能量轴（免电池客户端）**：三参数储能模型（采集 / 储能 / 上报代价）→ 由能量决定**间隔与降级**；降级**下限 L1**（永不 L3，§8.3 里 L3 不能确认人在场）；电量写进**已签**上报的 `battery_mv`，服务端从（级别+电量）**推导成因**；“没电了”从沉默里**分流**出来（`no_report_energy` warn vs `no_report` crit） | `energy.py` + `alerts.py` + `server.py`/`ui_server.py` | `test_energy.py`（51 条）+ `test_alerts.py` + 首页「能量轴」卡片（含扫描表） |
| 存储：SQLite（元数据）+ IoTDB（时序/事件） | `registry`/`cases`/`keystore`/`stations` + `tsdb.py` | `test_tsdb_audit.py` |

## 页面一览（`ui/static/`，11 页）

全部页面共用 `tools/ui/static/ui_i18n.js`（zh/en 单一源，右上角按钮切换，`?lang=en` 可直开）。

| 页面 | 作用 | 主要接口 | 存储 |
|---|---|---|---|
| `index.html` | 三节点拓扑 + ORPAH-REPORT 报文流 + L2 消息流 + Orpah ID 卡片 + 发现记录 + 走失表 + 事件历史 + 上报控制/防 spoof 注入；顶部 ⚠ 告警计数 | `/api/status`、`/api/events`(SSE)、`/api/ctl`、`/api/alerts`、`/api/ts/events` | 计数只在内存（**重启归零**，是设计）；事件历史在 IoTDB |
| `registry.html` 设备清册 | 人员↔设备台账、状态、照片、`?sn=` 高亮定位 | `/api/registry`、`/api/upload` | SQLite `persons`/`devices` + `uploads/` |
| `case.html` 走失案件 | 立案（寻人启事要素）/ 接手 / 找回结案 / 撤销 | `/api/cases`、`/api/registry` | SQLite `cases`/`case_events` |
| `track.html` 定位与轨迹 | 模拟·真实双模式；站位表（打点/绑定）；WLS 定位 + 95% 椭圆；画布⇄地图 | `/api/ts/query`、`/api/stations`、`/api/config` | IoTDB（设备流 + 各路由器观测）+ SQLite `stations` |
| `rssi.html` | 路径损耗教学计算器（2/3/多点定位） | `/api/config` | 无状态 |
| `replay.html` 回放 | 时间窗回放、逐帧定位、平滑、有效时段分色、事件时间线、GPX/GeoJSON 导出 | `/api/replay`、`/api/stations`、`/api/registry`、`/api/config` | **只读** IoTDB |
| `metrics.html` 指标面板 | 四项指标 + 各案件处置时长 | `/api/metrics`、`/api/status` | 只读（IoTDB + SQLite） |
| `keys.html` 密钥管理 | 生成→分发→轮换→吊销→退役（多代并存） | `/api/keys` | SQLite `keys`/`key_revocations` + IoTDB 审计 |
| `sig.html` 签名工具 | ES256/HS256 签名与验签演示 | `/api/sig` | 无状态（临时密钥对） |
| `checksum.html` / `damm32.html` | SN 校验位算法（Mod97/Luhn32/Damm32、拟群表、穷举） | `/api/checksum` | 无状态（算法只调 `damm32.py`/`luhn32.py`/`mod97.py`） |

**HTTP 接口清单**（字段与规则一律见 `API.md`，这里只回答“有哪几个”）——
GET：`/api/status`、`/api/registry`、`/api/cases`、`/api/stations`、`/api/keys`、`/api/config`、
`/api/alerts`、`/api/metrics`、`/api/replay`、`/api/checksum`、`/api/ts/query`、`/api/ts/events`、`/api/events`(SSE)；
POST：`/api/ctl`（暂停/改 SN·间隔/走失表 mark·untrack/密钥吊销/重放与伪造 ID 上报/防 spoof）、
`/api/upload`、`/api/registry`、`/api/cases`、`/api/stations`、`/api/keys`、`/api/sig`。

## 前端共享件（单一源，改一处多页生效）

| 文件 | 作用 | 谁用 |
|---|---|---|
| `ui/static/pos.js` | 定位纯函数：RSSI↔距离、三边、WLS、椭圆、质量（GDOP/残差）、观测归集、卡尔曼 | `track.html`、`replay.html` |
| `ui/static/map.js` | 底图源列表与条款、本地坐标→经纬度、离线回落 | `track.html`、`replay.html` |
| `tools/ui/static/ui_i18n.js` | **共享 i18n 字典**（zh/en 单一源） | orpah 11 页 + halow-demo 主 UI |
| `orpah/ui/static/style.css` | 样式与配色变量（告警红 / 上行蓝 / ID 橙 / 发现灰，色弱校验过） | orpah 各页 |

> ⚠ **模型参数（路径损耗 A/n、噪声）以服务端为准**：`motion.py` 是**唯一源** → `GET /api/config` →
> `track`/`rssi`/`replay` 开页取默认值（输入框仍可手改）。页面 HTML 里的 `value=` 只是**离线兜底**；
> `test_motion.py` §8 有「单源守卫」断言兜底值 == 常量、且页面确实去取接口。

## 走一遍完整剧本（入网 → 移动 → 走失 → 发现 → 定位 → 找回 → 结案）

前提：`python ui_server.py`（:8901）。下表的按钮/文案均为**页面实测**（2026-09-12）。

| # | 页面 | 操作 | 应看到 |
|---|---|---|---|
| 1 | 首页 | 打开即自动周期上报；「上报控制」卡可改 `ctlSn`（SN）/ `ctlEvery`（间隔秒）后按「应用」；`暂停上报` 可停 | 报文流三列 ✓（客户端注入·路由器上行·服务器收到）、三端计数同步增长 |
| 2 | 设备清册 | 登记人员与设备（SN 走 `CC-ORG-UNIQUE[-CHECK]`） | 台账出现该人/设备；可上传照片 |
| 3 | 定位与轨迹 | 数据源切「真实上报」→「定位站位」表出现 3 台路由器观测 | `参与定位 3/3 个站位有观测`、三个距离环 + 红叉估计 + 黄椭圆；**点在移动**（演示数据由 `motion.py` 按闭合路线生成） |
| 4 | 走失案件 | 填寻人要素 → `标记走失 / 立案`（以**人**为单位） | 该人名下设备全部→丢失、并进走失表；案件列表出现该案 |
| 5 | 首页 | 「走失表（服务器权威）」卡填 `lostSn` → `标记为走失`（只按 **SN** 加进走失表，**不立案** —— 与第 4 步的区别就在这） | `服务器发布记录` +1、路由器卡「收到走失表」+1 |
| 6 | 首页 | 等下一个上报周期（人走近路由器时） | 「发现记录（走失命中）」出现「发现 SN」、路由器/服务器卡「发现 N 次」+1；若已有案件 → 案件转「已发现」 |
| 7 | 走失案件 | `标记已接手` → 找回后 `找回（结案）`（误报则 `撤销（误报）`） | 状态→已找回/已撤销；设备回「启用」；审计事件落 IoTDB（首页「事件历史」卡可见） |
| 8 | 回放 | 选 SN + 时间窗（快捷 `30` 分钟）→ `▶ 播放` | 轨迹/距离环/椭圆逐帧推进；进度条 **绿(≥2 台可定位)/橙(仅 1 台)/灰(无观测)**、`跳过无效段`；`导出轨迹` GPX/GeoJSON（缺口断开成段） |
| 9 | 指标面板 | 打开（窗口 15 分钟–24 小时 + SN） | 验签失败率与算法分布、平均 RSSI、各案件处置时长（时长不可用会标 `invalid`，不给负数） |
| 10 | 首页 | `暂停上报` 后等一会儿 | 「告警」卡出现「设备 X 无上报 · 持续 …」+ 顶部 ⚠ 计数（阈值见 `alerts.py` 的 `ORPAH_ALERT_*` 环境变量） |
| 11 | 首页 | `注入伪造上报` / `跑全部攻击`（Orpah ID 卡） | 「期望 X · 实际 Y」对照（`signature_invalid` / `replay_detected` / `unknown_device`…），验签失败率随之上升并触发告警 |

**自检（黄金样本一键）**：`python run_checks.py` 会把上面的算法/协议断言全跑一遍 ——
含黄金样本 SN（`damm32=B` / `luhn32=E` / `mod97=21`）、SN 边界 28 条、报文/以太网帧边界、
密钥生命周期、防 spoof 清单、告警规则、指标计算、时钟归一化、IoTDB 时间窗、UI 契约
（用例表见 `checks_batch.py`，各模块自检见 `test_*.py`）。

---

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
python run_checks.py            # 14 个离线套件（各模块自检 + 批量合规 + 抓包解析 + 时钟漂移 + 能量轴 + pos.js 内核），约 2 秒
python run_checks.py --e2e      # 再加 5 个端到端 demo（L1/L2/L3/L3b/防 spoof），1-3 分钟
```
- 报告写到 `checks_report.md`（含 git HEAD、每套件结果/耗时/关键输出、失败详情）。
- ⚠ **报告是全量口径的**：不带 `--e2e` 跑会把 `checks_report.md` **整个覆盖**成只含离线套件的结果
  （14/14 → 9/9，e2e 那几行直接消失）。要提交这份报告就先跑 `--e2e`；若已跑过 `--e2e`
  又随手跑了离线版，**重跑一次 `--e2e` 恢复**（否则入库的报告会骗人）。
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
│   └── sim.py            # PC 模拟器（AP/STA）：host 数据口 --host <port>，语义 = SPI MACBUS
│                         #   DATA_TX/DATA_RX；帧 AA 55 TYPE LEN CRC payload；另有 24 项回归 run_tests.py
└── orpah/
    ├── orpah_proto.py    # 【协议】报文全集编解码 + 以太网帧(0x88B5) + SN 校验 + effective_ts（时钟归一化）
    ├── host_bus.py       # 【链路】host 数据口驱动（只依赖 TCP+帧格式，不 import sim）
    ├── client.py         # 【链路】Client host：REQ-CONNECT→REPORT + 收下行回执
    ├── router.py         # 【链路】Router 桥：上行转发/下行注入、走失缓存、主动拉表 sync()、FOUND 上报
    ├── server.py         # 【链路】Server：权威走失库、(sn,seq) 去重、TRACKING-STATUS/LOST-TABLE/FOUND
    ├── waiting.py        # 【工具】共享等待：wait_until / wait_new（按截止时间，不猜循环次数）
    ├── orpah_id.py       # 【身份】Crockford32 / SN+CHECK / JCS / ES256·HS256 / 验签 / 多代密钥状态机
    ├── keystore.py       # 【身份】密钥库写穿透（SQLite keys/key_revocations；私钥不入库）
    ├── damm32.py         # 【身份】SN 校验位算法**单一源**（与 luhn32.py / mod97.py 同；前后端都调它）
    ├── luhn32.py         # 【身份】同上（Luhn mod 32）
    ├── mod97.py          # 【身份】同上（Mod 97 两位）
    ├── spoof.py          # 【安全】攻击构造**单一源**（13 种 + 合法对照），脚本与页面共用
    ├── registry.py       # 【业务】人员↔设备台账（SQLite persons/devices，写穿透 + 首启播种）
    ├── cases.py          # 【业务】案件状态机（立案→发现→找回/撤销→结案；handler 与 status 正交）
    ├── alerts.py         # 【业务】告警规则（无存储、按快照重算；阈值走 ORPAH_ALERT_* 环境变量）
    ├── metrics.py        # 【业务】指标纯计算（验签失败率/算法分布/平均 RSSI/处置时长）
    ├── clock.py          # 【业务】设备时钟偏移/漂移估计（纯计算；只估计不改数据，短窗/跳变/噪声里给 None）
    ├── energy.py         # 【业务】能量轴三参数模型（采集/储能/上报代价 → 间隔与降级；参数是**演示标定值**）
    ├── stations.py       # 【定位】站位 = 已知坐标观测点（绑定 > 时间窗中位数 > 路由器序列）
    ├── motion.py         # 【定位】演示用「移动的人」+ 路径损耗/噪声（A/n **唯一源** → /api/config）
    ├── tsdb.py           # 【存储】IoTDB 接入（设备流/各路由器观测/事件；未就绪优雅降级）
    ├── ui_server.py      # 【UI】Web 服务：内嵌整条链路 + HTTP/SSE（方式 1）
    ├── ui/static/        # 【UI】11 个页面 + pos.js / map.js / app.js / style.css / vendor/leaflet
    ├── demo_l1.py        # 【验收】L1 数据通路（内嵌 2 模拟器，命令行）
    ├── demo_l2.py        # 【验收】L2 全消息流（双向 + 走失两分支）
    ├── demo_l3.py        # 【验收】L3 多 Router 漫游/去重 + SN 校验（2×Router）
    ├── demo_l4.py        # 【验收】L3b Router 主动拉表（启动 / 缓存未命中拉取）
    ├── demo_clock.py     # 【验收】设备时钟估计（合成几小时数据：准/偏快/短基线/拨表/乱报 + 分辨率）
    ├── demo_spoof.py     # 【验收】防 spoof 真·端到端（攻击注入空口，Server 侧断言）
    ├── demo_id.py        # 【验收】Orpah ID 22 用例（四级降级签名 + 篡改/重放/超窗/坏 CHECK/撤销）
    ├── demo_hw1.py       # 【验收·未真机验证】阶段二真机自检：代次/族、关联、跨空口 UDP、raw 0x88B5
    ├── run_checks.py     # 【测试台】14 个离线套件一键跑 + 出报告（--e2e 再加 5 个 demo）
    ├── test_*.py         # 【测试台】各模块自检：motion / keys / spoof / alerts / metrics / clock /
    │                     #   energy / tsdb_audit / server / levels / capture / posjs（pos.js 原文用 node 跑）
    ├── test_posjs.py     # 【测试台】定位内核 pos.js 的离线自检（node 执行同一份源码，不复制算法）
    ├── capture.py        # 【工具】pcap → ORPAH 报文解析 + 双源对照（真机抓包在网口侧；见文件头）
    ├── checks_batch.py   # 【测试台】表驱动批量用例（黄金样本 / SN 边界 / parse_sn / 报文编解码）
    ├── checks_report.md  # 【测试台】最近一次报告（入库，同 host/test_results.txt 惯例）
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
7. **一键回归**：`python run_checks.py`（14 个离线套件，~2s）→ `checks_report.md`；
   加 `--e2e` 跑 5 个端到端 demo（**需先停 orpah-ui**，否则端口串扰；脚本会自己拒绝）。
   ⚠ 报告口径是全量的：离线单跑会把它覆盖成 9/9（e2e 行消失），详见「方式 3」。

## 下一步（L2.5/L4+）

- **L2.5 真机最终形态**（TH-RJ45 V2.4-WNB Router ↔ TX-AH V2.4-FMAC Client）数据面
  迁移（host 数据口语义已对齐 SPI MACBUS，可平滑替换底层；烧录由用户执行）。
- F-03 走失表子集下发/过期、F-05 防伪造/限频、F-06 隐私、F-08 RSSI 粗定位。
- 免电池客户端（TX-AH + CH32V203）低功耗策略。

> 完整的待办与优先级见 `ROADMAP.md`（本文档只管“有什么、怎么跑”）。
