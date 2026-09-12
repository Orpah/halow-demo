# TXW8301 模拟器开发规则（simulator）

本目录是 TXW8301 的纯软件模拟器（`host/` Python 移植 + `tools/ui/` Web UI +
`firmware/` CH32V203 固件）。开发、修改、调试任何部分前，**先遵循以下规则与踩坑记录**。

## 0. ORPAH demo（2026-09-09 起，`simulator/orpah/`）

- 定位：在 halow-demo 内做 ORPAH-over-HaLow 的 L1/L2 原型（成熟后抽 orpah-demo）。
  L1 = 数据通路最小骨架（Client 上行 payload 到 Server）；L2 = 全消息流 + 走失表 +
  跟踪状态（SPEC §9，纯 PC 无硬件）。
- **⚠ 范围原则（2026-09-11 用户定，最高约束）：ORPAH 是技术搜寻手段，demo 边界取最小。**
  只做「用无线技术找到人」这一段（登记走失态/下发走失表/路由器发现上报/服务器回执落库/
  RSSI 定位/审计与告警）——**不是公安办案系统**。默认**不引入**：组织与机构建模、
  角色/权限体系、警员身份、案件分配/派单/办案流程、多租户隔离。
  新需求先过判据：**「让找人更快更准」→ 做；「让管理/流程更完整」→ 默认不做，先记
  `orpah/ROADMAP.md` §〇。** 需要「谁」时止步于审计标签（自由文本 `actor`）；需要「谁负责」
  时先确认是否存在真实运营方（demo 目前无登录者）。细节与已应用示例见 `ROADMAP.md` §〇。
- 分层（对齐 `Protocol/docs/orpah-over-halow/SPEC.md`）：链路 = 以太网帧(ethertype
  `0x88B5`) 经模拟器二层桥透传；Router→Server 段用真实 UDP。角色：Client=`client.py`+STA
  模拟器、Router=`router.py`+AP 模拟器、Server=`server.py`(UDP `19447`)。
- **L2 已实现（2026-09-09）**：`orpah_proto.py` 全套报文（REQ-CONNECT/ACCESS-INFO/
  REPORT/TRACKING-STATUS/ERROR/LOST-TABLE，统一 JSON 公共头 v/type/sn/ts）。**双向打通**
  （Server→Router UDP 应答→注入 AP 空口→STA→Client host 口）：`router.py` 双向桥
  （REQ-CONNECT 查本地缓存回 ACCESS-INFO / REPORT UDP 转发 / 收 Server LOST-TABLE 更新
  缓存 / 下行注入空口）；`server.py` **权威走失库**（mark_tracked/untrack → 下发
  LOST-TABLE；收 REPORT → 校验+查库 → 回 TRACKING-STATUS）；`client.py` 双向会话
  （REQ-CONNECT→ACCESS-INFO→REPORT→TRACKING-STATUS）。**验收：`demo_l2.py`**（两分支
  未命中 NOT-TRACKED / mark 后 TRACKED，PASS）。UI 加「L2 协议消息流」面板 + 走失表
  标记/取消按钮。
- 运行：`python orpah/demo_l1.py --n 3`（L1 验收）、`python orpah/demo_l2.py`（L2 验收）。
  单独跑见 `orpah/README.md`。
- **密钥库（2026-09-12，P1）叮：`orpah.db` 里的 `keys` 表是**已发密钥的真相**，
  改下面任一东西都会让已入库的密钥全部验不过（`signature_invalid`）：
  ① `orpah_id.Device` 的密钥生成（尤其 `derive_demo_privkey` 的派生前缀/算法 ——
  模拟器私钥就靠它「由 (SN, 代次) 确定派生」，否则服务器重启后公钥对不上）；
  ② `verify_report` 的验签入参（预像/JCS 规范化）；③ `b64url`/PEM 编解码。
  改完请跑 `python orpah/test_keys.py`（生命周期单测）+ `python orpah/demo_id.py`（端到端验收）；
  实在要换算法就删 `orpah.db` 重新播种（会一并清掉清册/案件/站位）。
- **orpah 进程不要改客户端 SN 做测试**（会真的造出新的密钥代次并写进密钥库/审计）。
- **防 spoof（空口无认证）演示（2026-09-12，P1）**：前提是 ORPAH 空口**开放/无认证** ——
  任何人都能往空口里丢一条 ORPAH-ID-REPORT。防线顺序：**格式 → SN 校验位（Damm32/mod97）
  → 时间窗/nonce 去重 → 吊销表 → 设备公钥验签**。
  - 攻击构造**只有一份**：`orpah/spoof.py`（13 种，含 1 条合法对照；含 2026-09-13 新增的
    **能力降级** `cap_downgrade` = 改已签声明的 `cap.rtc`）——
    `demo_spoof.py`（真链路端到端）、`test_spoof.py`（离线逐条）、页面（index 选类型注入）共用，
    否则“演示的”与“测的”会漂移。
  - 页面入口：index 的 Orpah ID 卡片 →「注入伪造上报」/「跑全部攻击」（走真空口链路，落 `id_reject`）。
  - **已知边界（必须如实展示，不要包装成“防住了”）**：`xport`（路由器侧观测）**不在签名预像里**，
    篡改它验签照样通过；而定位数据恰恰来自路由器侧测量 → **能冒充路由器就能伪造定位**。
    已记 ROADMAP 开放问题，动手补前先与用户对齐。
  - ⚠ `spoof.CASES` 里 `revoked` **会改密钥库状态，必须放最后**；且 `unrevoke` 会把各代转成
    retired（之后验签就 `unknown_device`）—— 页面因此把 `revoked` 排除在 `UI_KINDS` 之外。
- **等待一律用 `orpah/waiting.py`（2026-09-12，review 反馈起）**：
  - **禁止** `for _ in range(N): time.sleep(0.05)` 这种「猜次数」等待 —— 机器快慢/负载一变
    就误判（等太短=假失败，等太久=白等），且循环次数与语义无关，读者无法判断够不够。
  - 统一入口：`wait_until(cond, timeout=10.0, interval=0.05)`（按**截止时间**轮询，先判一次，
    返回 bool，**不抛异常**）、`wait_new(lst, pred, timeout=5.0, interval=0.1)`（只看**新增**元素，
    避免拿到上一轮的旧记录而假 PASS）。
  - **等「网络/回调答复」不要轮询列表**：用回调 + `queue.Queue`（或 `threading.Event`）——
    见 `test_clock.py` 的 `send_id`：`OrpahServer(on_id_report=ID_EVENTS.put)` + 按 nonce 匹配、
    先抽掉陈旧条目。
  - **超时必须可见、失败要响**：`wait_until` 返回 False 时打印 `[!!] …未…` 并让用例失败
    （`return 1/2`），**绝不静默继续**（旧代码就是静默 `continue`，链路没通也报 PASS）。
  - 判据：任何等待都该能回答「等的是什么条件、超时多少、超时后怎么办」；答不上来就是猜次数。
- **拓扑计数是「按内容」分色的三个口径，别合并成一个数（2026-09-12）**：
  - **蓝 `--acc`** = L2 上行（REQ-CONNECT / REPORT）；**橙 `--id`** = Orpah ID 签名上报
    （ID-REPORT）；**浅灰白 `--found`** = 发现（ORPAH-FOUND）。同一颜色 = 同一类内容，节点行与链路拆行一致。
  - **配色按色弱友好选（2026-09-12，用户要求）**：蓝 + 橙是两个不同色觉通道，
    红盲/绿盲/蓝黄盲下都不混；发现用**中性浅灰白**（业务事件，不当内容类型上色）。
    实测（Machado CVD 模拟 + CIEDE2000）：蓝↔橙 50.5–56.1（好）、蓝↔浅灰白 21.3–24.7；
    对比度 7.49 / 8.40 / 12.26（均过 WCAG AA）。
    **别再改回紫 `#a371f7`**：它与蓝在红盲/绿盲下 ΔE00 仅 10.2 / 5.6（几乎一色）；
    **也不要用黄 `#d29922` 当发现**：它与橙 ΔE00=4.2，全类型一色。
    另：数字都带文字标签（L2/ID/REPORT/发现），颜色是辅助通道，不辨色也能读。
  - 各口径（`ui_server.status()` 提供原始计数，前端只做加和/分色）：
    `client_sent` = REQ-CONNECT + REPORT（每周期 2 条，故恒为 `router_up` 的 2 倍）；
    `id_sent` = 本机注入的 ID-REPORT（周期 + 页面重放/超窗/伪造，全部经 `_inject_id` 计数）；
    `tx_sta` = STA 空口**数据**帧 = `client_sent + id_sent`；
    `router_up`/`router_id_up` = 路由器真正发给 Server 的 REPORT / ID（REQ-CONNECT 本机应答不过 UDP）；
    UDP 帧总额 = `router_up + router_id_up + found_total`；`server_recv` 只计 REPORT，
    ID 走验签通道（`id_report_total`，**含被拒**）。
  - **新增一种上行内容时**：在 router 的转发表里加计数 + 回调（仿 `on_up_id`），
    `ui_server` 计一份、`status()` 暴露、前端给颜色与悬停说明，四步都要做；
    只在空口加而不在 UDP 侧加，页面立刻"对不上"（本次 ID 上报就是这样被发现的）。
  - 周期上报的 ID 条数会比会话数多 1：启动时立刻 `_id_tick()` 一次（见 `start()` 注释），不是漏洞。
- **IoTDB 查询：时间可进 `WHERE`，值不行（2026-09-12，回放要按窗取数）**：
  - **时间过滤写进 SQL**（`WHERE time >= <ms> AND time <= <ms>` + `ORDER BY time ASC`）——
    时间戳是 IoTDB 的原生索引，准确且快。`tsdb.query_report_range` / `query_events_range`
    就是这么取「某设备某时间窗」的（回放用，见 `orpah/API.md` §10）。
  - **值过滤（etype/sn）不要写进 WHERE**，在本地筛（`query_events*` 就是多取几倍再 filter）——
    树模型对「非投影列」做值过滤不可靠（历史坑）。两件事别混。
  - 历史回读一律**倒序**（最近优先），回放窗口一律**升序**（按时间轴消费）。
- **多路由器观测 / 「移动的人」演示数据（2026-09-12）**：
  - **一条链路分两类数据**：设备自己报的链路值 → `root.orpah.devices.<sn>`；
    **各路由器各自测到它**的强度 → `root.orpah.routers.<sid>.<sn>`（`router_id`/站位 sid 即路由器身份）。
    **绝不能把多台路由器的测量挤进同一路径的同一时间戳** —— IoTDB 同设备同时间戳是
    last-write-wins，会互相覆盖。
  - **演示数据由 `orpah/motion.py` 生成**（闭合路线 + 匀速 + 对数距离路径损耗，确定性可复现）：
    `ui_server` 扮三台路由器，每个上报周期各写一条测量；设备 REPORT 的 rssi = 当前最近那台的测量。
    关掉它用 `ui_server.py --no-walk`（回到恒定 RSSI）。
  - **定位需要同一时刻 ≥2 个观察者**：单台路由器只有距离环；「悬停点 + 窗口中位数」模型的前提是
    目标静止 —— 人一走动就必须用「路由器序列 + 取 t 之前最近一条」（`pos.js` 的 `obsOfStation`
    第三条分支，时效 `ROUTER_MAX_AGE_MS`）。观测优先级：手动绑定 > 时间窗 > 路由器序列。
  - **tsdb 写入接口的 `ts` 参数单位是 epoch 秒**（`write_report` / `write_router_obs`）。
    传毫秒会被当成天文数字时间戳 → IoTDB 报错 → 异常被 `try/except` 吞掉，
    **只表现为 `/api/status.tsdb=false` 且数据静默不落库**（排查时先看这条）。
  - **`tsdb._read_rows` 必须整段持锁**（取数据集 + 遍历游标 + 关闭）：IoTDB 的 `Session`
    **不是线程安全的**，同一 Session 上并发的查询会互相踩游标 —— 只锁 `execute_query_statement`
    时，另一线程的查询会让本线程的遍历**读出空结果**（实测：串行 4 发全对，并发 4 发里有 2 条
    返回 0 行 / `ok:false`）。HTTP 是 ThreadingHTTPServer，两个页面/两个标签页同时请求就会撞上。
    排查手法：同一窗口**串行 vs 并发**各发几次对比。
- **回放页硬规则（2026-09-12）**：
  - **定位算法只有一份**：`orpah/ui/static/pos.js`（`trilaterate`/`wlsLocate`/`ellipseOf`/
    `obsOfStation`/`qualityOf`…）。`track.html` 与 `replay.html` 都用它 —— 别在页面里
    再抄一份算法（回放与实时必须逐位一致）。
  - **不看未来**：`obsOfStation` 内置 `p.t <= t`，回放某时刻只能用该时刻**之前**的样本。
    加任何「预取/缓存未来样本」的优化都会破坏这条。同理**时序平滑也是因果的**：
    `kalmanTrack` 只吃 `t<=光标` 的帧（`smRuns`/`smoothAt` 都带 `p.t <= t`；实测 20 个光标位置
    最多前视 0 ms、0 个未来点）。
  - **测量噪声（`motion.py` 的 `NOISE_DB=2.0`）是平滑/椭圆能验证的前提**：无噪声时定位结果
    恒等于真值（RMS 0.00 m），平滑、残差、置信椭圆全都失去意义。噪声用 SHA-256(sid|t_ms)
    确定性生成（不用随机数库）→ 回放/测试可复现；**逐站位不同**（`ui_server` 必须传 `sid=`），
    否则三台路由器噪声一致 = 又变回「自洽的假数据」。
  - **时序平滑用恒速卡尔曼、不用滑动平均**（`pos.js` 的 `kalmanTrack`，4 状态 x,y,vx,vy）：
    移动目标上 N 点平均滞后 ≈ (N/2)×采样周期，找人场景里滞后就是「指错位置」
    （合成实测：RMS 二者接近 3.5/3.4 m，但滞后 卡尔曼 0.4 m vs 平均 2.7 m）。
    **搜索半径取滤波后协方差 P**（Q+R），不用测量协方差 —— 否则「输出更平滑」会被误当成「更准」，
    给出过小的半径（假自信）。
  - **协方差更新必须用 Joseph 形式** `P=(I−KH)Pp(I−KH)ᵀ+KRKᵀ`：更短的 `P=(I−KH)Pp`
    在浮点下丢对称正定 → 跑几十帧后创新协方差近奇异 → 增益暴冲 → **状态发散**
    （实测真实数据第 84 帧从 −11 m 跳到 12000 m；改 Joseph 后 793 帧全有限）。
    另加「非有限/负方差 → 重置为测量值」兜底，绝不把 NaN 写进轨迹（静默垃圾最糟）。
  - 页面切换语言会带 `?lang=` **整页重载**（`ui_i18n.js` 的设计），因此 JS 动态写出的文案
    切语言后自动刷新，不用各页自己监听。
  - **轨迹导出（GPX/GeoJSON，回放页）三条硬规则**：① 导出**整窗**（不是只导已回放部分）；
    ② **缺口必须断开**（> `ROUTER_MAX_AGE_MS` 或滤波器 `reset` → GPX 多 `<trkseg>` / GeoJSON 多
    `LineString` Feature），跨缺口的直线不是真走出来的路；③ 经纬度**只走 `map.js` 的 `toLatLng`**
    （与地图落点同一个换算），GeoJSON 坐标是 `[lng, lat]`。纯前端，无新接口。
  - **告警处置态（2026-09-12，§三 A 方案）**：`case_overtime` **只在「无人接手」时**才报 ——
    `Case.handler` 是与 `status` **正交**的一维（不是新状态；「处置中」是页面派生显示），
    接手人=自由文本（复用审计 `actor`，**不建 operators 表/不做登录**）。改 `cases` 表列名/语义时记住：
    `CREATE TABLE IF NOT EXISTS` **不给老表补列** → `_init_db` 里用 `PRAGMA table_info` + `ALTER TABLE`
    兜迁移（否则老 `orpah.db` 写库报 `no such column`）。`test_alerts.py` 里的假 `Case` 必须带 `handler`
    （缺属性→测试直接崩；多给属性→掩盖真 AttributeError，两种都踩过）。
  - **一键回归 = `orpah/run_checks.py`**（2026-09-12）：跑 `test_*.py` 七个离线套件 +
    批量合规用例（`checks_batch.py`，表驱动：黄金样本/SN 边界/parse_sn/报文编解码），
    报告写到 `orpah/checks_report.md`（**入库**，同 `host/test_results.txt` 惯例）。
    **改完任何 orpah 代码先跑它**。两条硬规则：① 判定 = 退出码 0 **且** 输出无 `FAIL`/`Traceback`
    （有些脚本自己 catch 异常还往下跑，只看退出码会漏）；② `--e2e`（L1/L2/L3/L3b/防 spoof）
    **必须先在别的终端停掉 orpah-ui** —— demo 与它（:8901 那套端口）串扰会跑出假失败，
    脚本自己也检查并拒绝（退出码 2）。
  - **时钟可信（2026-09-12，无 RTC 设备）**：设备 `ts=0`/缺失 → 协议层跳过时间窗（`verify_report` 已做），
    但**存什么时间必须走唯一入口** `orpah_proto.effective_ts(ts, rx)`（返回 `(ts, src)`）——
    以前 `write_report`/路由器观测/`registry.touch` 各自 `time.time()` 兜底，会有偏差且导致
    「设备流与路由器观测时刻不一致」（定位/回放按时间对齐 → 匹配不到）。**一次算、各处用**；
    `src=server` 必须**留痕**（审计 detail 写 `ts_src=server`，页面可标）。
    **绝不改报文里的 `ts`** —— 它在签名预像里，改了验签就过不了；归一化只用于我们的记录。
    测试：`test_clock.py`（已并入 `run_checks.py`）。
  - **查审计事件别读错字段**：`GET /api/ts/events` 返回的键是 **`rows`**（不是 `events`）；
    另注意它按 `etype`/`sn` 在**本地**过滤（值过滤不进 WHERE，见 §0 IoTDB 条），
    所以“某类事件为空”先确认字段名，再确认是不是真没写进去。
  - **地图代码分两层**：`ui/static/map.js` = **底图源列表 / 条款说明 / 本地坐标↔经纬度换算 /
    底图图层 + 离线回落**的**单一源**（track.html 与 replay.html 共用，两页 `ensureMap()` 都调
    `addBaseLayer(lmap)`）—— 那是**合规相关**的东西
    （各源署名文本、离线限制、按语言两套列表都不同），拄两份迟早漂移；
    **Leaflet 图层管理各页自己写**（实时/回放画法不同：回放轨迹要跳缺口断开）。
  - **离线回落（2026-09-12，B 方案）**：OSM 官方瓦片政策禁止离线/预取 → demo **不带离线底图包**，
    改为瓦片取不到时自动换**本地自绘网格底图**（canvas 现画，不含第三方数据 → 无许可问题）+
    比例尺 + 提示（含「重试底图」）。判据 = **连续 4 张失败且成功数为 0**（个别 404 不误判）；
    自定义源空 URL 直接判离线。演示离线不用拔网线：把自定义瓦片 URL 填成不可达地址。
    PMTiles 区域包（A 方案）未做，做法/合规约束见 ROADMAP §二。
  - 回放地图开图时按「站位 + 轨迹」`fitBounds` **自动框景**：演示场景只有 ~60 m，
    默认 zoom 下几乎看不见（实测 zoom 19 才舒服）。
- **`host/sim.py` 新增「host 数据口」**（`--host <port>` / `Core(host_port=)`，缺省不启用）：
  语义 = SPI MACBUS `DATA_TX`(host 注入→空口转发) / `DATA_RX`(收帧推 host)；帧格式同空口
  `AA 55 TYPE LEN CRC payload`。不加参数完全不影响原有行为（24 项回归仍过）。
- 涉及本 demo 的公共改动只有 `sim.py` 的 HostPort（可选）；orpah 各进程不 import sim
  （`orpah/host_bus.py` 独立实现同帧格式，将来换真实 SPI 只替换底层收发）。
- **UI：`python orpah/ui_server.py`（浏览器 http://127.0.0.1:8901/，VS Code 任务
  `orpah-ui`）**——内嵌整条链路自动周期会话（REQ-CONNECT→REPORT），页面三层拓扑 +
  ORPAH-REPORT 实时报文流 + L2 协议消息流（方向↑↓/报文/sn/状态/节点）+ 走失表控制。
  两 UI 启动任务（`orpah-ui` / `sim-server-host-sim|tj45|hc01`）**不带端口参数、直接用
  缺省端口**（orpah=8901、tools=8899），一键即跑不弹窗；想换端口用命令行
  `python ... --port <n>`（后端均支持 `--port`，2026-09-09）。
- **Orpah ID SN 硬规则（2026-09-10 用户定）**：
  ① CC = ISO 3166-1 alpha-2，**不套 Crockford 限制**（可含 I/L/O/U，正则 `[A-Z]{2}`）；
  ② **校验位只算 `ORG-UNIQUE`（不含 CC）**——`damm32.py` / `orpah_id.py` / `c/damm32.c`
     的 check 函数输入一律是 ORG-UNIQUE（或 ORG-UNIQUE-CHECK），不含 CC；
  ③ **所有文档与代码样例的 CC 只用 `CN`（中国）**，不使用其它国家——测试向量、黄金样本、
     UI 默认值、自检输出统一 `CN`（黄金样本 `WH01-9AF3C1D2 → B`，整串 `CN-WH01-9AF3C1D2-B`）；
  ④ 工具页（主页头部入口）：`track.html`（定位与轨迹：多路由器持续测 RSSI → 实时定位 +
     轨迹绘制，纯前端模拟）、`rssi.html`（RSSI→距离→2/3/多点定位，canvas 可视化）、
     `sig.html`（ES256/HS256/none 签名验签，后端 `/api/sig`）、
     `checksum.html`（SN 校验码，Damm32/Luhn32/Mod97 三 tab）、
     `damm32.html`（Damm32 构造/验证，计算器在最顶端）。
     checksum/damm32 的 CC 用下拉框（`<datalist>`）+ 支持直接输入 + 提示，CC 输入框回车
     跳 ORG-UNIQUE、右侧实时显示国名、ORG-UNIQUE 自动大写。

## 0b. 编码约定（2026-09-09）：仓库文本一律 UTF-8

- **文件**：git 跟踪文本文件一律 UTF-8（已扫描确认 79 个全合法 UTF-8，无 GBK 文件）。
  新写文件不加 BOM、写 `# -*- coding: utf-8 -*-` 声明。
- **运行时输出**：Windows 控制台默认代码页 GBK/cp936 会把 UTF-8 输出显示成乱码，
  对 emoji（如 ✅）还抛 `UnicodeEncodeError: 'gbk' codec...`。因此**可执行脚本**（打印
  中文/emoji 的）在 import 后必须强制：`for _s in (sys.stdout, sys.stderr):
  _s.reconfigure(encoding="utf-8", errors="replace")`（orpah 各脚本已加；仿照即可）。
- VS Code task（`orpah-ui`/`orpah-demo-cli`）已设 `PYTHONIOENCODING=utf-8` 双保险。
- 检测某文件是否 GBK：python `open(p,'rb').read().decode('utf-8')` 抛错而 `.decode('gbk')`
  成功 → GBK。注意**不要**只读文件前 N 字节判断（会因截断多字节字符误报，2026-09-09 教训）。
- **⚠ 用 PowerShell 5.1 往 HTTP API 发中文会被静默换成 `?`（2026-09-12 实测复现）**：
  `Invoke-RestMethod -ContentType "application/json" -Body '<含中文的 JSON 字符串>'` →
  每个非 ASCII 字符在服务端落库都变成 `?`（实测 `"name":"悬停点Z"` → 库里 `???Z`；
  先前 `"actor":"张警官"` → 事件里 `???`）。**加 `charset=utf-8` 也无效**。
  注意**命令回显里中文是好的**（说明命令文本到了 shell），坏在 PS 组装 body 那一步 ——
  所以别以为是"终端显示乱码"，是**数据真的坏了**。
  - **正路**：① 传 UTF-8 字节（实测有效）：
    `$by=[System.Text.Encoding]::UTF8.GetBytes($json); Invoke-RestMethod ... -Body $by`
    ② 更省事：改用 `C:\Python313\python.exe` 写小脚本（`json.dumps(...).encode("utf-8")`）；
    ③ 或直接在页面上操作（浏览器发的就是 UTF-8）。
  - 破坏是**不可逆**的（服务端收到时就是 `?`，无从还原），只能重新写入正确值。
  - **入库前的自检**：写完中文用 API 读回一眼（`repr()`），别只看 POST 的返回。
  - **同一个坑的第二种用法（2026-09-12 踩到）**：**不要用 PowerShell 改写含中文的源码文件** ——
    `(Get-Content f.py -Raw) -replace ... | Set-Content f.py -Encoding UTF8` 会把所有中文变成乱码
    （`Get-Content` 默认按 ANSI 代码页读 UTF-8 文件），而且**破坏后编译直接语法错**。
    改源码一律用编辑器工具；已在终端里改坏的就 `Remove-Item` 重写。

## 1. 定位与启动

- 给泰芯 TXW8301（802.11ah HaLow）做的**无射频**模拟器，形态参考 T-Halow-RJ45
  （AT 命令 / AP-STA / RSSI / 数据通路一致）。项目位于仓库根 `simulator/`（2026-09 从
  `TXW8301/simulator` 移到 halow-demo 仓库根，以承载多模组）。
- **设备档案 / 协议族注册表（唯一事实来源）= `host/devprofiles.py`**：
  - target（设备档案 key）：sim / tj45 / txah / hc01，各带别名 + 中文显示名；
  - family（AT 方言）：`native`（本模拟器 CH32V203，`?` 查询 + OK）/ `tah`（泰芯 AH：
    tj45+txah）/ `hc01`（HT-HC01 占位：真实 AT 待其手册，暂复用 tah 方言）。
- Web UI 启动（不依赖 cwd，`server.py` 用 `os.path.dirname(__file__)` 定位 static/host）：
  - 两台本模拟器虚拟机：`python tools/ui/server.py --host-sim`
  - 两台 T-Halow 虚拟机：`python tools/ui/server.py --host-sim --target tj45`
  - 一台 TX-AH 真机 + 虚拟机：`python tools/ui/server.py --a pc:tj45 --b COM13:txah`
  - 两台 HT-HC01 虚拟机（占位）：`python tools/ui/server.py --host-sim --target hc01`
  - 两台真机（真实 RF）：`python tools/ui/server.py --a COM3:tj45 --b COM4:tj45`
  - 列出串口：`python tools/ui/server.py --list`
- 设备规格：`pc | pc:sim | pc:tj45 | pc:txah | pc:hc01 | COM3 | COM3:sim | COM3:tj45 | COM3:txah | COM3:hc01`
  （来源×目标；source=pc/serial；target 归一/标签一律看 devprofiles.py；
  tj45=T-Halow-RJ45、txah=泰芯 TX-AH-MODULE，两者同属泰芯 AH 固件（family=tah，
  协议一致只差显示名）；hc01=惠特自动化 HT-HC01（family=hc01，占位））。

## 2. 互联域（硬规则）

- 虚拟空口(TCP) **只在 PC↔PC 之间**建立；真机↔真机走物理 RF（802.11ah）。
- **PC↔真机不互通**：真机走真实射频、PC 模拟器无射频，二者不能自动建链，
  UI 只能同时管理。别指望"模拟器 A 发帧 → 真机 B 收帧"。
- 帧过滤：目的 MAC 必须 `FF*6`（广播）或匹配，否则对端按单播过滤丢弃（忠实模拟，**非 bug**）。

## 3. 命令 / 响应约定

- 泰芯 AH 族（family=tah：tj45/txah；hc01 占位暂同）状态响应带 `+` 前缀（`+MODE:AP`），
  且**不追加 OK**（避免轮询刷屏）；设置命令仍走 `ok()` 回 OK。
- 泰芯 AH 族查询用**裸命令**（`AT+MODE` / `AT+VERSION` / `AT+CONN_STATE` / `AT+RSSI`）。
- **真机 TX-AH(txah) 不是上面的 T-Halow 方言**（2026-09-06 实测，TX-AH-Rx00P 固件 v2.4.1.5）：
  档案 at='v2'（见 `host/devprofiles.py`）走泰芯 AH-SDK V2.x —— 设模式 `AT+WIFIMODE=ap/sta`、
  查询带 `?`（`AT+WIFIMODE=?` / `AT+RSSI=?` / `AT+SSID=?`）、加密 `AT+ENCRYPT=0/1`+`AT+KEY`(≥8 ASCII)，
  **无 `AT+MODE`/`AT+CONN_STATE`**，连接状态用 `AT+RSSI=?`（关联后非 0）推断；时序坑见 §6。
- `AT+TXDATA` 用**等号**：`AT+TXDATA=<len≥14>`；随后数据模式收 len 字节原始数据。

## 4. 前端控制台 / UI 约定

- console 事件带 `dir`：`tx`=自己发送（命令/HEX 回显、FRAME:TX），`rx`=接收
  （OK/状态行/FRAME:RX/TX DATA OK）。
- 显示**双通道**：方向前缀 `→`/`←`（主）+ 颜色 绿`#7ee787`/蓝`#79c0ff`（辅）——
  色弱友好，**禁止只靠颜色传递收发信息**。
- 轮询响应（CONN_STATE/RSSI/MODE/SSID/VERSION）默认静默（`_poll_until` 窗口抑制），
  用户命令回显 + 状态响应才显示，避免控制台刷屏。
- 真机固件周期打印（`LMAC STATUS`/`freq=`/`bgr:`/`chn:`/`buf:`/`irq:`/`tx :`/`rx :`/
  `cca:`/`chip-temperature`/`sta_list`/分隔线/`[时间戳]SSID:`）识别为 spam，折叠成
  「▶ 设备自动调试信息」可展开块；AT 响应（无时间戳的 `SSID:` 等）不误折叠。
- 改样式/脚本后刷新即生效：静态文件已加版本号查询串（`style.css?v=xxx`）+
  `Cache-Control: no-store`。

## 5. 防爆 / 健壮性

- EVENTS 事件队列**有界**（`maxsize=2000`），push 满时丢最旧（SSE 断连不再无限堆积）。
- `reader_loop` 行缓冲超 64KB 只留尾部 4KB（防无换行二进制 flood）。
- 数据模式期间暂停该设备轮询（`poll_paused_until`，`AT+TXDATA=` 后 30s），
  防轮询字节污染/提前结束数据帧。

## 6. 踩坑记录（2026-09 补，务必记住）

- **顶部 TX/RX 计数曾始终 0**：后端只初始化 `state["tx"]/["rx"]=0` 从不递增，
  须在 FRAME 分支 TX→`tx+=1`、RX→`rx+=1` 并 push status。
- **版本号防缓存的连环坑**：给 `style.css?v=xxx` 加版本号后，`server.py` 的 `do_GET`
  必须**剥离查询串**（`rel.split("?",1)[0]`），否则带 `?` 的路径被当文件名 → **404** →
  CSS/JS 全挂 → 页面无样式无 JS（表现为"未连接"、设备占位、布局乱）。曾误以为是缓存。
- **布局**：`.node` 用 `width:280px` 会在窄视口被 flex 压缩 → 设备名断行
  （"T- Halow- RJ45"）。须 `flex:1 1 280px; min-width:280px` 防压缩。
- `sim.py` Link `connect/accept` 后必须 `c.settimeout(None)`（否则 1s 空闲被 `_reader` 断开）。
- **真机 TX-AH(txah) 轮询硬坑（2026-09-06）**：真机**一次只应答一条 AT 查询**，背靠背发
  `AT+RSSI=?`+`AT+WIFIMODE=?` 会吞掉后面那条 → server.py 对 txah 真机（`tahv2`）把
  RSSI?/WIFIMODE?/SSID? **逐条错开 ≥1s** 发（见 `poll_loop` 的 seq）。另：真机每条应答自带 OK
  （轮询窗口内已抑制）、回显带 `[ts]` 序号前缀需剥离。
- **真机 TX/RX 真实计数 + 真实连接判定（2026-09-07 加）**：真机 TX-AH 固件周期性打印
  `LMAC STATUS`（SYSDBG=LMAC,1，~1-6s，含每窗口 `tx : cnt=N`/`rx : cnt=N`，AP/STA 都有）
  和 `IEEE80211 Status`（SYSDBG=UMAC,1，~6s，每接口一行含 `WPA_状态`）。server.py 对 tahv2
  启动即开 **LMAC,1 + UMAC,1**（逐条间隔 ≥1s 发，且每 ~20s 周期重断言一次，防板子 RST 后
  SYSDBG 被重置丢流）：
  - `_consume_tahv2_lmac()`：整块抑制进控制台，把 tx:/rx: cnt 累加进卡片 TX/RX；同时抓 AP 侧
    `STA1..`/`stamap` 判 AP 有无已认证 STA。
  - `_consume_tahv2_umac()`：整块抑制（AT+SCAN 的 BSS 表行放行），抓 running VIF 的 WPA 状态；
    **conn 只在 STA 到 `WPA_COMPLETED`（或 AP 有已认证 STA）才算 CONNECTED**——不用 RSSI 推断
    （KEY 错时 RSSI 非 0 但 4-way 反复失败 → STA 显示 SCANNING、AP 显示 OFFLINE）。
  - 每块 UMAC 开头清空 VIF 快照，避免重启后陈旧状态误报。
- **真机功能实测事实（2026-09-07，详细实测记录见 docs/usage.md §0.1.0.1）**：
  - **重配加密链路次序坑（LOADDEF 后尤其）**：`AT+KEY=` 用**当时 SSID** 派生 PSK。改 SSID 后必须重设
    KEY，且次序固定 = **先 `AT+SSID=` → `AT+ENCRYPT=1` → `AT+KEY=`**；次序颠倒/只改 SSID 不重设
    KEY → STA **能扫到该 AP（BSSID/RSSI/WPA2-PSK-CCMP 都在 BSS 表里）却一直卡 SCANNING 不去关联**、
    AP 侧无 STA、RSSI 两边都 0。按序重配 + 双 `AT+RST` 即恢复。
  - **恢复出厂 `AT+LOADDEF=1`**：自动复位回默认 = `WIFIMODE=sta` + SSID `HALOW_<MAC尾3字节>`（如
    HALOW_647090），配置**自动保存**。LOADDEF/多次 RST 后若 RF 互听不到：先按上面次序重配双端再 RST，
    仍不行需**物理断电重插 USB** 清 RF 前端。
  - **中文 SSID 能连**（UTF-8，两侧字节一致+同 KEY；SSID ≤32 字节≈10 个汉字）。
    **PAIR 快速配对**：双端 `AT+PAIR=1`（A 侧打 pairing success）→`AT+PAIR=0` → STA 用**从 AP 学到**
    的 SSID/KEY 自动连（免手填，中文 SSID 也字节一致传递）。常规连接 AP/STA 必须同 SSID，PAIR 是唯一例外。
  - 隐藏/信道/带宽/功率/自愈/休眠：`AT+APHIDE=1` 只挡通配发现，已知 SSID 定向扫描/已关联仍能连
    （802.11 标准）；AP `AT+CHANNEL=n`（chan_list 内序号）切主信道，STA 在共享 chan_list 内自动跟随重连
    （9080↔9240 均跟）；`AT+BSS_BW` 两侧一致同改（8↔4MHz）按新带宽重连；`AT+TXPOWER=1..20` 生效但近距离
    RSSI 看不出功率差（桌面饱和，需拉远几米）；AP 复位→STA 正确 SCANNING→~15s 自动重连；连接态
    `AT+DSLEEP=1` 保活休眠（链路保持、AT 可用、AP 端 `AT+WAKEUP=<mac>` 接受）。KEY 明文可被
    `AT+KEY=?`/`AT+SYSCFG` 读回（防"别人连入"，不防"改配置"）。
- **串口断电/休眠 → UI 冻结旧 CONNECTED（2026-09-07 加，server.py 修复）**：真机状态只在"收到一行
  应答"才更新，板子断电/休眠后无应答 → conn/rssi/uptime 全冻结在旧 CONNECTED（无超时）。修复 =
  Device 加看门狗 + 断开自愈（仅真实串口 `SerialTransport`，TCP/PC 模拟器不启用）：
  - `_check_liveness()`：`poll_loop` 每轮调用，`time.monotonic()-self._last_rx > LIVENESS_TIMEOUT(15s)`
    且非数据模式、非已 OFFLINE → conn=OFFLINE、rssi=0、清 `_vif`/`_ap_sta`，跳变才 push。
    `_last_rx` 在 `reader_loop` 收到任何字节时更新（LMAC~1-6s/UMAC~6s 正常一直在打，15s 不会误判）。
  - `reader_loop` 包 try/except：读异常/断开（休眠唤醒 COM 句柄失效）→ `_close_transport()` →
    每 `RECONNECT_INTERVAL(2s)` `_reconnect_serial()` 重开串口（换句柄、清 buf/块状态、`_last_rx` 归零、
    `_assert_at=now+1` 提前重断言 SYSDBG）→ 继续读；重上电后 ~几秒自动 CONNECTED，不用重启服务器。
  - 实测：关 B → B 转 OFFLINE；重上电 → OFFLINE→SCANNING→CONNECTED。
- **开机/关机(power)徽标 + RSSI 归零 + 状态中文显示（2026-09-07 加）**：power 与 conn **解耦**——真机
  收到任何字节=power=on；超 `LIVENESS_TIMEOUT` 无字节或自(重)连后从未收到=off（`_ever_rx` 标志）；AP 开着
  无客户端 = on + OFFLINE（不误当关机）。UI 标题栏加「开机/关机」徽标（绿/灰）。RSSI：tahv2 判 OFFLINE 时
  归零，且 `AT+RSSI=?` 应答在 conn=OFFLINE 时强制置 0（固件掉线后回陈旧缓存如 -70，会把信号条点亮——
  实测抓到）。前端 conn/mode 显示中文映射（仅展示层；机器值保持英文，逻辑/测试/API 不受影响）：
  CONNECTED=已连接/SCANNING=扫描中/ASSOCIATING=关联中/PAIRING=配对中/OFFLINE=离线；
  AP=接入点/STA=客户端/APSTA=双模/GROUP=组网。改显示只动 app.js 的 CONN_ZH/MODE_ZH，勿改后端 state 字符串。
- **数据面 / 负向测试（2026-09-07 实测）**：① TX-AH-Rx00P = **fmac 固件**（版本第 4 位 5）：AT 只有控制面，  **无 AT 级用户数据命令**（手册全集无“发数据”；`AT+PING`/`AT+IPERF2` 需网络宏/LWIP，本固件无）。实测
  PING 只回 OK 无结果；WNB,1 帧打印不进帧监视表（表只认模拟器 `FRAME:` 行）。payload 需走主机
  SDIO/SPI(MACBUS) 或换网络版固件。② 负向：AP/STA 信道列表不含对端主信道 → STA 扫不到、SCANNING 连不上；
  AP bw8 vs STA bw4 → STA 解不出 8MHz AP、连不上；恢复一致自动重连。`AT+BSS_BW` 生效且跨 RST 保存
  （设完立刻 RST 偶发不存，等 2-3s 再 RST）。不匹配时 AP 侧关联表滞后会短暂“已连接”，STA 恒 SCANNING。
- **角色互换（2026-09-07 实测）**：两块板仅 `AT+WIFIMODE=ap/sta` 对调（SSID/KEY/信道一致不变）+ 双 RST 即可
  互换 AP/STA → 双机 CONNECTED 稳定（B 当接入点、A 当客户端都正常）→ **两块板都能当 AP（角色对称）**；
  换回基线（A=AP/B=STA）亦正常。
- **TH-RJ45 真机（tj45，2026-09-07 实测；显示名改 TH-RJ45 + `_spaced_real` 逐条轮询）**：
  - UI 显示名 = TH-RJ45（devprofiles tj45 档案 name；key 仍 tj45，别名 rj45/thalow）。
  - 方言：设 `AT+MODE=`；查询裸命令（AT+MODE/SSID/RSSI/VERSION，带 ? 也认）；`AT+KEYMGMT`+`AT+PSK=64hex`；
    `AT+CONN_STATE`→`+CONNECTED/+DISCONNECT`（事件式）；RSSI 连上=小整数(8/7)、断开=0。
  - **AT+MODE 角色不跨 RST 保存**（重启回 sta，即时生效）→ 改角色别 RST；AP 起时会 ACS 自动选信道，
    `AT+CHAN_LIST=9080` 可压回 9080（无害 `lmac error!!!chan idx=2`）。
  - **一次只应答一条（与 TX-AH 同坑）**：server.py tj45 真机走 `_spaced_real` 逐条 ≥1.3s 轮询——只轮
    RSSI（判连接）+ MODE/SSID 慢轮；不轮 CONN_STATE（+CONNECTED 是事件会刷屏）。实测重启后状态自动刷新。
  - 板上每条命令后常打 `valid cmds:`（固件噪音）。数据通路=RJ45 网口（USB-C 只供电+AT 配置）。
- **跨固件互连 TH-RJ45 ↔ TX-AH（2026-09-07 实测，双向不互通）**：同族内都正常；跨族 TH-RJ45(T-Halow
  v1.6.4.3) ↔ TX-AH(AH-SDK V2 v2.4.1.5) open/9080/bw8 **双向可发现不可关联**（TX-AH STA `assoc_timeout`
  循环；TH-RJ45 STA `find suitable ap` 后不连）→ 两套固件关联握手不兼容（已排除信道/方向）。
  混接 UI：A=TH-RJ45 + B=TX-AH 同页，命令提示/快捷按钮按每台设备方言切换（/api/info v2 标记），验证 OK。
- **控制台自动滚动坑（2026-09-07 修）**：真正可滚动的是外层 `.console` div（`overflow:auto;height:220px`），
  `renderConsole` 原来设 `pre.scrollTop=scrollHeight` 无效（`pre` 不滚，父 div 才滚）→ 贴底时新行来了视野
  "向上跑"。修：`const box=pre.parentElement`；渲染前测 `box.scrollHeight-box.scrollTop-box.clientHeight<24`
  （是否在底部附近），渲染后仅在"在底部"时 `box.scrollTop=box.scrollHeight`；用户向上翻历史时不强拉回。
- **RSSI 信号条显示（2026-09-07）**：4 格**直角满高矩形**（`.rssi-bar i{flex:1;align-self:stretch}` 无圆角）+
  旁显数值（`rssiTxtA/B`）；**有信号(已关联)至少 1 格**（`s.rssi&&v<1 → v=1`，弱链路 -80 以下不再显"无信号"）；
  单位按方言：v2=TX-AH 加 `dBm`，tj45 真机 RSSI 是小整数非 dBm 只显数字（防误导）。**坑**：flex 容器加
  `align-items:center` 会让空 `<i>` 塌成 0 高（格消失）——须给子项显式高度或 `align-self:stretch`。
- 终端 flaky：长驻服务器用 async 终端，命令被加 `^U` 前缀报错时重新 `send_to_terminal`；
  一次性命令若卡住改用 `create_and_run_task`（tasks.json）。

## 7. 新增设备类型检查清单（如 tj45→txah→hc01，勿漏）

新增 target（设备档案 key）后，以下位置**必须同步**，否则 UI/文档不一致：

- `host/devprofiles.py`（**单一事实来源**）：`PROFILES` 加一项（key/别名/中文名/family）。
  同一协议族只加档案（如 txah 加在 `FAMILY_TAH` 族）；**全新命令集则新增一个 family**，
  并在 `host/sim.py` 的 `At` 方言处实现（`tah_style`/响应格式按 family 分支）。
- `server.py`：`norm_target()` / `device_type()` / `HostSims.add()` / argparse `--target`
  已改为走 devprofiles（新增 target 通常无需再改 server.py，除非要加别名/标签以外逻辑）。
- **`index.html`「启动模拟器」常用启动命令列表（`#startsec`，最易漏）**：加一条新设备的启动示例。
- `app.js`：`AT_CMDS` 命令库若新设备有特有命令/参数需补。
- `tools/sim_config.py`：`--variant` choices（真机 variant 自动关调试刷屏）。
- `AGENTS.md`：本文件 §1 设备规格 / 启动命令同步。
- 验证：`--a pc:xxx --b pc:xxx` 看 banner / `device_type` 显示；有真机则实测 AT 响应。

（真实教训 2026-09-02：加 txah 时后端/AGENTS 都改了，唯独漏了 UI 常用命令列表，后被用户指出补上。
2026-09-02 加 hc01：HT-HC01 属**新协议族**（惠特自动化 ESP32+MM6108，非泰芯），先登记占位、
暂复用 tah 方言，收到其 AT 手册后需补真实方言并更新本清单。）

（fritzing 元件规则见 `fritzing-parts-langhua/AGENTS.md`；详细历史踩坑在仓库 docs/ 各文件。）
