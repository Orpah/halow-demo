# ORPAH 模拟器后端 API 契约

> 从 `registry.html` / `case.html` 两个页面的前端调用反推固化。
> 基址 `http://127.0.0.1:8901`。所有 JSON。演示数据为内存实现（重启回种子）。

## 通用返回

写操作统一返回 `{"ok": true}` 或 `{"ok": false, "err": "..."}`。

---

## 1. `/api/registry`（设备清册）

### GET `/api/registry`

```json
{
  "persons": [ Person ],
  "devices": [ Device ]
}
```

**Person**：`pid, name, note, gender, age, height, build, features, health, mental, communicate, photo`

**Device**：`sn, person_id(null=未绑定), cc, org, status, first_seen, last_seen`（时间均为 Unix 秒）

### POST `/api/registry`（body 带 `action`）

| action | 字段 | 说明 |
|---|---|---|
| `add_person` | `name`（必填）+ 档案字段（可空） | 返回 `{"ok":true,"pid":"P00N"}` |
| `update_person` | `pid` + `name/note/...` | 编辑档案 |
| `remove_person` | `pid` | 级联解绑名下设备 `person_id=null`；**有未结案件则拒绝**（提示先结案） |
| `add_device` | `sn`、`person_id`（可空） | 服务端二次校验 SN 格式 + 校验位 |
| `set_status` | `sn`, `status` | 单台改状态 |
| `set_status_many` | `sns[]`, `status` | 批量改状态 |
| `remove_device` | `sn` | 删除设备 |

**设备状态机**：`active / disabled / lost / scrapped`。
立案 → 名下设备 `lost`；结案/撤销 → 回 `active`；`scrapped` 设备**不再参与立案**。

**SN 校验（服务端）**：格式
`^[A-Z]{2}-[0-9A-HJKMNP-TV-Z]{2,6}-[0-9A-HJKMNP-TV-Z]{8,16}(-[0-9A-HJKMNP-TV-Z]{1,2})?$`，
并按协议复核校验位（CC 不参与；0 位无校验 / 1 位 Luhn32 / 2 位 Mod97）。
`cc`/`org` 由服务端从 SN 解析，不信任前端传值。

---

## 2. `/api/cases`（走失案件）

### GET `/api/cases` → `{"cases": [ Case ]}`

**Case**：`case_id, person_id, person_name, status, devices[], events[],
missing_at, missing_place, possible_to, clothing, contact_phone, police,
police_case_no, police_station, belongings, vehicle, outcome, closed_at`

**Event**：`{t(Unix秒), type∈{mark,found,close}, sn, detail}`

### POST `/api/cases`

| action | 字段 | 说明 |
|---|---|---|
| `mark` | `person_id` + 走失字段（可空） | 名下非报废设备全部 `lost` + 写 `mark` 事件；已有 open/found 案件返回 `{"ok":true,"dup":true}` |
| `close` | `case_id`, `outcome∈{closed,revoked}` | 设备回 `active` + 写 `close` 事件 + 置 `closed_at` |

**状态机**：`open → found → closed`，`open → revoked`，`found → closed/revoked`；`closed/revoked` 只读。

**found 触发（后端，非前端轮询）**：任一设备「被看到」即触发——
- Router 命中走失表（ORPAH-FOUND，REQ-CONNECT 链路）→ `cases.on_found`
- 数据面 REPORT 上报 → `registry.touch` 同时 `cases.on_found`
首次发现（open→found）写一次 `found` 事件；同一设备重复出现只刷新时间、不重复写事件。

---

## 3. `/api/upload`（照片上传）

`POST /api/upload?filename=<原始名>`，body 为原始图片字节。

- 校验扩展名 `jpg/jpeg/png/webp/gif`；大小上限 5MB
- **uuid 重命名**（防原文件名注入/重名），存 `ui/static/uploads/`
- 返回 `{"ok":true,"url":"/uploads/<uuid>.<ext>"}`；该 URL 存入 `Person.photo`

---

## 4. `/api/status`（与 index 对齐）

`status` 返回新增 `lost_sns: [sn...]`（当前 `lost` 状态设备），
index 报文流据此把丢失设备 SN 标红；SN 已链接 `registry.html?sn=`。
另含 `tsdb: bool`（IoTDB 是否在线）。
registry/cases/index 均 1s 轮询同一数据源（SQLite 持久化）。

---

## 5. `/api/ts/query`（IoTDB 时序查询）

`GET /api/ts/query?sn=<SN>&limit=N` → 该设备最近上报点 + 各路由器对该设备的测量：

```json
{"ok": true, "sn": "CN-WH01-9AF3C1D2",
 "rows": [{"t": 1789100000000, "rssi": -55.0, "seq": 1, "router_id": ""}],
 "obs": {"S1": [{"t": 1789100000000, "rssi": -76.0, "seq": 1}],
         "S2": [{"t": 1789100000000, "rssi": -73.0, "seq": 1}]}}
```

- `t` 为毫秒时间戳；`ok=false` 表示 IoTDB 未就绪或查询失败。
- `rows` = **设备自己**报的链路值（时间倒序，消费前自行翻正）；`obs` = **各路由器各自**测到该设备的
  强度 `{sid: [{t,rssi,seq}]}`（时间升序，每台一条序列，含空表）。**定位用 `obs`**（见 §7）。
- 数据模型：设备上报 `root.orpah.devices.<sn>`（测点 rssi/seq/router_id）；
  路由器测量 `root.orpah.routers.<sid>.<sn>`（测点 rssi/seq）；业务事件 `root.orpah.events`（etype/sn/detail/actor）。
- 路由器测量**必须单独一条路径**：同一设备的同一时间戳在 IoTDB 是 last-write-wins，
  三台路由器的测量挤进 `devices.<sn>` 会互相覆盖（每台一条序列也便于各取各的窗口）。
- IoTDB 未启动时写入静默降级、每 10s 重连一次，不影响 SQLite/UI。
- 写入接口的 `ts` 参数是 **epoch 秒**（`write_report` / `write_router_obs` 一致）；传毫秒会被当成
  天文数字的时间戳而写失败（异常被吞 → 只表现为 `/api/status.tsdb=false`）。
- `track.html` 的「真实上报」模式消费本接口：按时间升序画 RSSI 时序 + 按 A/n 换算距离。
  单测点只能得「距离环」；配上「定位站位表」（已知坐标，见 §7）即可多点三边定位到点。
- **`query_report` 按时间倒序返回**，前端消费前需自行翻正；`query_router_recent` 内部已翻成升序。

### `/api/ts/events`（业务事件历史）

`GET /api/ts/events?limit=N[&etype=<类型>][&sn=<SN>]` → 事件倒序：

```json
{"ok": true, "etype": "", "sn": "", "retention_days": 30, "purged_upto": 1786548902866,
 "rows": [{"t": 1789100000000, "etype": "publish", "sn": "", "detail": "n=2 targets=1 CN-...=1", "actor": "system"}]}
```

| etype | 何时写 | detail 形态 | actor |
|---|---|---|---|
| `publish` | Server 发布/更新 LOST-TABLE | `n=<项数> targets=<台数> <sn>=<1\|0>,…` | `system` |
| `found` | Server 收到 ORPAH-FOUND（走失命中） | `router <ip>:<port>` | `system` |
| `id_report` | Server 验完一条 Orpah ID 上报 | `alg=… level=… trust=… accepted=…` | `system` |
| `id_reject` | 同上但 `accepted=false`（验签被拒） | 同上 + `err=<原因>` | `system` |
| `case_mark` | 立案（去重后只写一次） | `case_id` | 操作者（POST 传的 `actor`） |
| `case_found` | 案件进入已发现（`newly` 时才写） | 触发来源 | `system` |
| `case_close` | 结案 | `<case_id>:closed\|revoked` | 操作者（POST 传的 `actor`） |
| `key_issue` | 签发新一代密钥 | `kid` | 操作者 |
| `key_rotate` | 轮换（旧代→宽限） | `<旧 kid> -> <新 kid> grace=<秒>s` | 操作者 |
| `key_retire` | 退役某代（提前失效） | `kid[,kid…]` | 操作者 |
| `key_revoke` | 整机作废 | `<原因>`（未填记 `-`） | 操作者 |
| `key_unrevoke` | 撤销恢复（仅演示） | `unrevoke (demo only)` | 操作者 |

- `limit` 上限 500（默认 50）。`etype` / `sn` 在**服务端本地过滤**（多取 10 倍再筛，上限 5000），
  因为 IoTDB 树模型对「非投影列」做值过滤不可靠。
- **持久化**：这些事件重启后仍在（内存环形缓冲只留 20 条，历史以本接口为准）；
  `index.html` 的「事件历史（IoTDB 落库）」区消费本接口。
- **写事件的时间戳单调化**：所有事件共用 `root.orpah.events` 这一个设备路径，
  IoTDB 同设备同时间戳是 last-write-wins → 同一毫秒的多条事件会互相覆盖。
  故未显式传 `ts` 时把时间戳钳成严格递增（最多偏移几毫秒）；显式传 `ts`（业务时间）则原样保留。
- 逐条报文流不重复写事件：已作为设备测点存在 `root.orpah.devices.<sn>`（见上）。

#### 审计：`actor`（谁）

`root.orpah.events` 的第四个字段 `actor`：

- 人为操作（立案/结案）由页面随 POST 带上 → 落库为该操作者；
  页面用共享组件 `ui_i18n.js` 的 `bootActorBox()`（只要放 `<span id="actorBox"></span>`），
  值存 `localStorage["orpah_ui_actor"]`，取用接口 `OrpahI18n.actor()`。
- 自动事件（publish/found/id_report/id_reject）不传 → 记 `system`；操作者留空 → 记 `system`。
- **`actor` 列是后加的**：更早写入的行回读为 `null`，本接口统一归一成 `""`（页面显示为无标签）。
- `index.html` 事件历史只给**人为操作**渲染操作者标签（`system` 不显），避免逐条噪声。
- **尚未纳入审计的写操作**（改动这些端点的状态不会产生事件）：`/api/registry` 增删改、
  `/api/stations` 增删改/打点/绑定。

#### 审计：保留期限

- 保留天数由环境变量 `ORPAH_EVENT_RETENTION_DAYS` 决定（默认 **30**，`0` = 不清理）。
- 进程启动首次连上 IoTDB 后按期限清理一次（`delete_data`，只删早于 `now - N天` 的），
  只跑一次；IoTDB 比本进程晚起时，在第一次成功重连后补跑。
- 返回值：`retention_days` = 当前策略天数；`purged_upto` = 最近一次清理的截止时间(ms)，
  未清理过为 `null`。页面在旁边显示「保留 30 天 / 保留全部」。

---

## 6. `/api/checksum`（SN 校验位 / 拟群表）

`GET /api/checksum?action=<a>&...`，算法单一源 = `damm32.py` / `luhn32.py` / `mod97.py`
（前端不再各留一份实现，避免两套算法漂移）。

| action | 参数 | 返回 |
| --- | --- | --- |
| `compute` | `algo=damm32\|luhn32\|mod97`，`org_unique=<SN 去 CC 段>` | `{ok, algo, org_unique, check, valid}` |
| `verify` | `algo`，`body=<SN 去 CC 段 + "-" + 校验位>` | `{ok, algo, valid}` |
| `table` | `algo=damm32` | `{ok, algo, crockford, quasigroup[32][32], valid, checks:{latin,diag_zero,adjacent_transposition}}` |
| `brute` | `n=32`，`maxlen=N` | `{ok, miss, ms}`，`miss=null` 表示无漏检 |

- `check` 为校验位字符串（mod97 两位十进制）；`full` 由前端拼成 `CC-ORG-UNIQUE-CHECK`。
- `valid` = 用该算法回验 `ORG-UNIQUE-CHECK` 是否通过（`compute` 恒为 `true`，可作自检）。
- `algo` / `action` 未知 → `{ok:false, err:"..."}`；参数非法一律 `ok:false`，不抛 500。
- `brute` 在服务端穷举（`maxlen=3` 约 1.05s），前端只负责展示。

---

## 7. `/api/stations`（定位站位 / 悬停计划）

补上「这个 RSSI 是在哪个**已知坐标**测到的」这一维，单台路由器/无人机多点悬停即可定位。
站位表是**全局一张**（定位属环境配置，与具体设备无关），存 SQLite `stations` 表，重启不丢。

### GET `/api/stations` → `{"ok":true, "stations":[Station]}`

```json
{"sid":"S1","name":"悬停点A","x":30.0,"y":0.0,
 "t0":1789100000000,"t1":1789100020000,"rssi":null,"rssi_t":null}
```

### POST `/api/stations`（body 带 `action`）

每个 action 都回**全量站位表**（`{ok, ..., stations:[…]}`），前端直接重渲染，避免两边状态漂移。

| action | 字段 | 说明 |
|---|---|---|
| `add` | `x`, `y`, `name?` | 新增站位，`sid` 自动编号（返回 `sid`） |
| `update` | `sid` + `x?`/`y?`/`name?`/`t0?`/`t1?` | 未给的字段不动 |
| `remove` | `sid` | 删除站位 |
| `clear` | — | 清空（返回 `removed` 条数） |
| `import` | `stations:[{sid?,name?,x,y,t0?,t1?}]` | **覆盖式**导入悬停计划；也接受裸数组；无 `x`/`y` 的项跳过（返回 `imported` 条数） |
| `punch` | `sid`, `t?` | **打点**：此刻在该站位（返回 `t0`） |
| `bind` | `sid`, `rssi`, `t?` | 手动绑定一条观测（优先于时间窗） |
| `unbind` | `sid` | 取消手动绑定 → 回落到时间窗 |

### 观测归集（前端 `track.html` 真实模式）

每个站位取**一条**观测，优先级从高到低（实现 = `ui/static/pos.js` 的 `obsOfStation`）：

1. 手动绑定 `rssi`（`bind`）→ 直接用；
2. 时间窗 `t0` 存在且 `t0 <= t` → 取 `t0 <= t < t1`（`t1` 缺省=至今）内所有 report 的 RSSI **中位数**
   —— 「无人机悬停在某点」的模型，**前提是目标静止**；
3. **路由器序列**：给了该站位自己的测量序列 → 取 `t` 之前**最近一条**，时效 `ROUTER_MAX_AGE_MS = 30 s`
   —— 多路由器**同时**观测，跟得住移动目标（数据在 `root.orpah.routers.<sid>.<sn>`，见 §5 与 §10）；
4. 都没有 → 该站位无观测，不参与定位。

**为什么 3 不能省**：单台路由器只能给出距离环，且悬停窗口把不同时刻的测量混在一起；
人一走动，只有「同一时刻多台各自的最近测量」才能解出连续轨迹（阶段二的核心）。

≥2 个站位有观测时调用 `track.html` 现成的三边定位（`trilaterate`，≥3 点为最小二乘）。
**定位计算放在前端**，与模拟模式共用同一个内核，避免两套实现。

**真实模式的求解器（2026-09-12）**：先用线性 `trilaterate` 得初值，再用**加权最小二乘**
（`wlsLocate`：高斯-牛顿 + 步长折半线搜索，`σ = max(1 m, 0.25×距离)` → `w = 1/σ²`）出最终解；
并由协方差 `(JᵀWJ)⁻¹ × max(1, σ̂0²)` 给 **95% 置信椭圆**与**搜索半径**（沿最长轴的覆盖半径，χ²(2,0.95)=5.991）。
加权法方程奇异（站位共线等）→ 回退线性解并提示；迭代不收敛 → 明确报「未收敛」而不给假结果。
**接口不变**（A/n、站位表与时间窗/绑定语义均同前）——加权与椭圆都是前端计算，只在页面上多出
「加权解 / 95% 置信 / 搜索半径」三行与画布/地图上的黄虚线椭圆。

**打点语义**：`punch(S2)` → `S2.t0=now, t1=null`，同时把其它「已打点但未收尾」的站位
（`t0` 更早、`t1` 为空）视为已离开 → `t1=now`。于是各站位的时间窗 = 两次打点之间的区间。
对同一站位重复打点 = 该窗口重来。

**悬停计划 JSON**（`stations.example.json` 为示例）：

```json
{"stations":[{"sid":"S1","name":"悬停点A","x":30,"y":0},
              {"sid":"S2","name":"悬停点B","x":-15,"y":26}]}
```

省略 `t0`/`t1` 则由页面「打点」实时生成；脚本预演时可直接把悬停时刻写进 `t0`/`t1`（epoch 毫秒）。

---

## 8. `/api/alerts`（告警红点）

`GET /api/alerts` → 当前**活跃告警**（无参数）：

```json
{"ok": true, "counts": {"crit": 1, "warn": 0, "total": 1},
 "alerts": [{"kind": "case_overtime", "level": "crit", "key": "case_overtime:C001",
             "msg": "alert_case_overtime", "since": 1789104728,
             "case_id": "C001", "person_id": "P002", "gap": 35856}]}
```

**无状态**：每次请求都用当前快照（设备清册 + 走失案件 + 最近签名上报）重算，
不存告警表、没有确认/关闭流程 → 条件消失则告警自动消失，无需状态机。

规则（阈值可用**环境变量**覆盖，改了要重启；默认值是演示压缩时间，真实部署要调大）：

| kind | level | 条件 | 阈值 | 环境变量 |
|---|---|---|---|---|
| `no_report` | `warn` | 启用中且**曾上报过**的设备，距上次上报超过 N 秒 | `30` | `ORPAH_ALERT_NO_REPORT_SEC` |
| `case_overtime` | `crit` | `open` 状态的案件立案超过 N 秒仍未发现 | `180` | `ORPAH_ALERT_CASE_OVERTIME_SEC` |
| `sig_fail_rate` | `crit` | 最近 N 条签名上报中，被拒比例 > 比例阈值 | `5` 条 / `0.5` | `ORPAH_ALERT_SIG_WINDOW` / `ORPAH_ALERT_SIG_FAIL_RATIO` |

- 环境变量与事件保留期限（`ORPAH_EVENT_RETENTION_DAYS`，见 §5）同一套机制：
  未设 / 空串 / 非法值 → 回退上表默认值。
- 也可以在进程内覆盖：`alerts.evaluate(..., no_report_sec=…, case_overtime_sec=…,
  sig_window=…, sig_fail_ratio=…)`（单测用的就是这个入口）。
- 例（想避免「刚立案 3 分钟就亮红点」的观感）：
  PowerShell `$env:ORPAH_ALERT_CASE_OVERTIME_SEC=600; python ui_server.py --port 8901`；
  cmd `set ORPAH_ALERT_CASE_OVERTIME_SEC=600 && python ui_server.py --port 8901`。

字段说明：

- `key` = `<kind>:<对象>`，用于前端判断「是不是新告警」（新 key → 徽标闪烁一次）。
- `msg` = **i18n 键**（不是成品文案）；页面用 `T(msg)` 取模板，再用告警对象里
  同名字段替换 `{占位符}`（`gap` 会先按界面语言格式化成时长，最多两段：
  中文 `10天2小时`/`10小时13分钟`/`3分20秒`/`45秒`，英文 `10d2h`/`10h13m`/`3m20s`/`45s`）。
- `since` = 告警起算时间（设备用 `last_seen`、案件用 `created`、签名用首条样本时间），
  页面显示为「持续 X」。
- 排序：`crit` 先于 `warn`，同级按 `since` 升序。
- 阈值未满样本时不告警（如签名样本不足 `sig_window` 条）；设备从未上报过、
  或状态非「启用」的，不参与 `no_report`。
- 页面：`index.html` 页头徽标（`#alertBadge`，`crit` 红 / `warn` 橙）+ 告警卡片，
  3 秒轮询；无告警时徽标与卡片整体隐藏。

---

## 9. `/api/keys`（密钥库：生成→分发→轮换→吊销→退役）

密钥生命周期逻辑在**协议层** `orpah_id.KeyStore`（纯内存、不依赖数据库，`server.py --keystore-file`
也用它）；**持久化**在 `keystore.KeyStoreDB`（SQLite，与清册同库 `orpah.db`，写穿透）；
页面 `keys.html`；审计事件见 §5。

### GET `/api/keys` → 密钥库全量视图

```json
{"ok": true, "now": 1789143000, "grace_sec": 604800,
 "demo": {"sn": "CN-WH01-9AF3C1D2", "gen": 6},
 "counts": {"sn": 3, "active": 2, "grace": 1, "retired": 5, "revoked_sn": 0},
 "items": [{"sn": "CN-WH01-9AF3C1D2",
            "device": {"status": "active", "person_id": "P001", "org": "WH01", "cc": "CN", "last_seen": 1789143286},
            "revoked": null,
            "keys": [{"kid": "CN-WH01-9AF3C1D2#6", "gen": 6, "state": "active",
                       "created_at": 1789142900, "grace_until": null, "grace_left": null,
                       "retired_at": null, "se_sn": "ATECC608B-DEMO", "model": "…",
                       "firmware": "1.0.3", "has_pubkey": true, "has_hmac": true,
                       "pubkey_pem": "-----BEGIN PUBLIC KEY-----…"}]}]
}
```

- `items` 包含**所有**已入密钥库的 SN **加上**设备清册里的 SN（后者 `keys: []`）→ 页面上直接给它
  签发第一代（产线先发钥、设备后入网也合理）。
- `demo` = 当前演示终端（Orpah ID 设备）的 SN 与**正在使用的代次** → 页面标出「← 当前用这把」。
- 每次 GET 顺手 `sweep` 一次（宽限已过的 `grace` → `retired`）；只在真有转移时写库。
- 私钥不在返回值里（也不入库）：库里只有 **server 侧该持有的** ES256 公钥 + 降级 HS256 对称密钥。

### POST `/api/keys`（body 带 `action`，成功回全量 `view`）

| action | 字段 | 说明 |
|---|---|---|
| `issue` | `sn`, `model?`, `firmware?` | 签发新一代（`gen = 最大代次+1`）；**已有 active 时幂等** → `note_code=already_active` 并回既有 `kid` |
| `rotate` | `sn` | 旧 active → `grace`（`now+grace_sec`），新钥 → `active`；回 `kid`/`prev_kid`/`grace_until` |
| `adopt` | `sn` | 让**演示终端**改用当前 `active` 代（演示「设备侧完成更新」）；非终端 SN → `note_code=not_demo_sn` |
| `retire` | `sn`, `kid?` | 退役某代（**当「让宽限期立即到期」的按钮**）；不带 `kid` 则退所有非 active 代 |
| `revoke` | `sn`, `reason?` | **整机作废**：所有代立即不可验签（不可逆*） |
| `unrevoke` | `sn` | 撤销的逆操作（*仅演示；代次一律转 `retired`，要恢复需重新 `issue`） |

**返回机器码，文案由页面本地化**（后端不拼中文，免得「后端文案不跟语言走」）：

- 失败：`{"ok":false, "code":"<码>", "err":"<兜底文本>"}`；页面取 `keys_err_<码>` 显示。
- 成功：`{"ok":true, "code":"<action>", "note_code?":"…", "view":{…}}`。
- 错误码：`no_sn` / `unknown_sn` / `unknown_action` / `revoked_sn` / `no_active` /
  `nothing_retire` / `bad_json` / `exception`。
- 只允许对「已在密钥库或已在设备清册」的 SN 操作（防手滑打错 SN 造出野钥）。
- **`revoked_sn` 挡在签发前**：已作废的设备不能 `issue`/`rotate` 复活（撤销不可逆），
  必须 `unrevoke` → 再 `issue`。协议层 `_issue` 也有同名护栏（双保险）。

### 生命周期与「轮换不断链」

```
register/issue ──> active ──rotate──> grace ──宽限到期(sweep)──> retired
                     │                  └── retire(提前退役)
                     └── revoke（整机：所有代 → revoked，立即不可验签，不可逆*）
```

- **不改报文格式**：报文头**不加 `kid`**，验签时按代次倒序**逐代试签**（活跃 + 宽限代通常只有
  1~2 个，代价可忽略）→ 老报文/老设备无需任何改动。命中哪代会在结果里回 `kid`/`gen`，
  并写进 `id_report` 事件的 `detail`（`gen=<n>`）。
- 宽限期 = `ORPAH_KEY_GRACE_SEC`（默认 **7 天**；`0` = 旧钥立即失效）。
- **模拟器的私钥不入库**：由 `orpah_id.derive_demo_privkey(sn, gen)` 由 (SN, 代次) 确定派生，
  所以服务器重启后公钥仍对得上（否则持久化的密钥库每次重启都验不过）。
  真实设备 `demo_key=False`（安全元件内生成、私钥不可导出）。
- **审计**：每个变更都写 `key_*` 事件（带 `actor`），见 §5。
- **本页只管密钥**：不做组织/角色/权限（见 `ROADMAP.md` §〇 范围原则）。

---

## 10. `/api/replay`（按时间段回放）

回放页 `replay.html` 的**唯一**数据入口：把「某设备在某时间窗内的上报点」+「该窗内的业务事件」
一次性取回，前端按时间轴播放。**定位不在服务端算** —— 页面拿 `points` + `/api/stations` 用
`pos.js`（与实时页**同一个**内核）逐帧求解，所以回放出来的数与实时页逐位一致，不存在两套定位。

### GET `/api/replay?sn=<SN>&from=<epoch ms>&to=<epoch ms>`

| 参数 | 必填 | 说明 |
|---|---|---|
| `sn` | ✅ | 设备 SN；缺 → `{"ok":false,"code":"no_sn"}` |
| `from` / `to` | 建议 | epoch 毫秒；缺 `from` 时用 `to - minutes×60000`；非数字 → 按缺省处理 |
| `minutes` | 可选 | 省略 `from` 时的窗宽（默认 **30**，钳到 1…720） |
| `evlimit` | 可选 | 事件条数上限（默认 2000） |

窗口上限 **12 小时**（超了把 `from` 抬到 `to-12h`）；`from > to` 自动交换。
数据全部来自 **IoTDB 时间窗**（`WHERE time >= x AND time <= y`，时间过滤是原生索引，
与 §5 里「值过滤不能进 WHERE」是两件事）→ 重启不丢、天然的按时间切片。

**回放定位用的是 `obs`（各路由器对该设备的测量），不是 `points`**：`points` 是设备自己报的链路值，
只用于展示时间轴/报文流；`points` 与 `obs` 都按时间升序。

```json
{"ok":true,"sn":"CN-WH01-9AF3C1D2","from":1789143060000,"to":1789144860000,
 "points":[{"t":1789143061000,"rssi":-55.0,"seq":22,"router_id":""}],
 "obs":{"S1":[{"t":1789143061000,"rssi":-76.0,"seq":22}],
        "S2":[{"t":1789143061000,"rssi":-73.0,"seq":22}],
        "S3":[{"t":1789143061000,"rssi":-84.0,"seq":22}]},
 "events":[{"t":1789143060000,"etype":"publish","sn":"CN-WH01-9AF3C1D2","detail":"n=1","actor":"system"}],
 "counts":{"points":795,"events":828,"obs":2400},
 "truncated":false,"events_ok":true}
```

- `points`/`events` 均**按时间升序**（回放顺序消费；与 §5 的倒序历史查询相反）。
- `ok=false` = 上报点拿不到（IoTDB 未就绪）→ 页面提示「IoTDB 不可达」。
- `events_ok=false` 但 `ok=true` = 上报点可用、事件查询失败（页面照常回放，只是时间线空）。
- `truncated=true` = 命中点数 ≥ `REPLAY_MAX_POINTS`（20000）被截断，页面提示缩小时间段。
- 事件是**全局表**（`root.orpah.events` 不分设备，见 §5），故未知 SN 也能拿到事件、
  只是 `points:[]`。
- 回放**不看未来**：前端只用 `ts <= 当前光标` 的样本（`pos.js` 的 `obsOfStation` 已内置）。

> 回放页本身不再有后端契约：播放/暂停/倍速/拖动进度条、轨迹与 95% 椭圆绘制、
> 事件时间线「已发生/未发生」全在 `replay.html` 内完成。


