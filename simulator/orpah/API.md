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

`GET /api/ts/query?sn=<SN>&limit=N` → 该设备最近上报点：

```json
{"ok": true, "sn": "CN-WH01-9AF3C1D2", "rows": [{"t": 1789100000000, "rssi": -55.0, "seq": 1, "router_id": ""}]}
```

- `t` 为毫秒时间戳；`ok=false` 表示 IoTDB 未就绪或查询失败。
- 数据模型：设备上报 `root.orpah.devices.<sn>`（测点 rssi/seq/router_id），
  业务事件 `root.orpah.events`（etype/sn/detail）。
- IoTDB 未启动时写入静默降级、每 10s 重连一次，不影响 SQLite/UI。
- `track.html` 的「真实上报」模式消费本接口：按时间升序画 RSSI 时序 + 按 A/n 换算距离。
  单测点只能得「距离环」；配上「定位站位表」（已知坐标，见 §7）即可多点三边定位到点。
- **`query_report` 按时间倒序返回**，前端消费前需自行翻正。

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

每个站位取**一条**观测，优先级：

1. 手动绑定 `rssi`（`bind`）→ 直接用；
2. 时间窗 `t0` 存在 → 取 `t0 <= t < t1`（`t1` 缺省=至今）内所有 report 的 RSSI **中位数**；
3. 都没有 → 该站位无观测，不参与定位。

≥2 个站位有观测时调用 `track.html` 现成的三边定位（`trilaterate`，≥3 点为最小二乘）。
**定位计算放在前端**，与模拟模式共用同一个内核，避免两套实现。

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

规则（阈值可在 `alerts.py` 常量或 `evaluate(..., **th)` 覆盖）：

| kind | level | 条件 | 阈值 |
|---|---|---|---|
| `no_report` | `warn` | 启用中且**曾上报过**的设备，距上次上报超过 N 秒 | `no_report_sec=30` |
| `case_overtime` | `crit` | `open` 状态的案件立案超过 N 秒仍未发现 | `case_overtime_sec=180` |
| `sig_fail_rate` | `crit` | 最近 N 条签名上报中，被拒比例 > 50% | `sig_window=5` |

字段说明：

- `key` = `<kind>:<对象>`，用于前端判断「是不是新告警」（新 key → 徽标闪烁一次）。
- `msg` = **i18n 键**（不是成品文案）；页面用 `T(msg)` 取模板，再用告警对象里
  同名字段替换 `{占位符}`（`gap` 会先格式化成 `1h2m`/`3m20s`/`45s`）。
- `since` = 告警起算时间（设备用 `last_seen`、案件用 `created`、签名用首条样本时间），
  页面显示为「持续 X」。
- 排序：`crit` 先于 `warn`，同级按 `since` 升序。
- 阈值未满样本时不告警（如签名样本不足 `sig_window` 条）；设备从未上报过、
  或状态非「启用」的，不参与 `no_report`。
- 页面：`index.html` 页头徽标（`#alertBadge`，`crit` 红 / `warn` 橙）+ 告警卡片，
  3 秒轮询；无告警时徽标与卡片整体隐藏。

