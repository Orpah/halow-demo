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

**处置态（2026-09-12）：`handler`（接手人，自由文本，空 = 未接手）、`handled_at`（接手时刻，秒）、
`handling`（派生布尔 = 还开着【open/found】且有接手人）。** 它不是 `status` 的一个取值 ——
「谁在办」与「走到哪一步」正交（已发现但没人管、已接手但还没找到都是合法组合），
做成状态就要改 `active_case`/`open_cases` 等所有判定。接手人只用自由文本（与审计 `actor` 同一层，
**不建 operators 表、不做登录**）。

**Event**：`{t(Unix秒), type∈{mark,found,close,assign}, sn, detail}`；
`assign` 的 `detail` = 接手人（空串 = 取消接手）。

### POST `/api/cases`

| action | 字段 | 说明 |
|---|---|---|
| `mark` | `person_id` + 走失字段（可空） | 名下非报废设备全部 `lost` + 写 `mark` 事件；已有 open/found 案件返回 `{"ok":true,"dup":true}` |
| `assign` | `case_id`, `handler`（空串 = 取消接手）, [actor] | 设/清接手人 + 写 `assign` 事件（`detail`=接手人）+ 写 IoTDB `case_assign` 审计事件（`actor` 缺省取接手人）；已结案 → `{"ok":false,"err_code":"case_closed"}`，案件不存在 → `err_code="no_case"` |
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

**Orpah ID 相关字段**（index 的「Orpah ID 签名上报」卡片用）：

| 字段 | 说明 |
|---|---|
| `id_demo` | 最近一条上报的验签结果：`sn/alg/level/trust/accepted/error/kid/gen/nonce/sig` + `degraded`（L2）/`coverage_only`（L3）（§8.3，2026-09-12 新增） |
| `id_reports` | 合成上报流（环形 20 条，最新在前），表格直接渲染 |
| `id_report_total` | 累计条数 |
| `id_level` / `id_level_modes` | 当前**降级演示模式**（§8.2）及其可选值（选项单一源，页面下拉据此生成） |
| `id_revoked` | 当前设备是否已吊销（按钮文案随之切换） |
| **`spoof_kinds`** | **防 spoof 演示的攻击清单** `[{kind, zh, en, expect}]`（来自 `spoof.UI_KINDS`，脚本/页面同一份）。页面按当前语言取 `zh`/`en` 生成下拉，`expect` 用于「期望 vs 实际」对比——**后端不返回本地化文案，只给两种语言让页面挑**，避免中英混排 |

**设备时钟字段**（index 的「上报控制」卡片用；`clock.py`，2026-09-13 新增）：

| 字段 | 说明 |
|---|---|
| `clock` | `{sn: 估计}`：从「设备自报 `ts` vs 服务器接收时刻 `rx`」反推的时钟估计。`offset`（秒，正=设备比服务器快）/ `drift_ppm`（相对服务器时基的斜率，正=设备走得快）/ `n`（整窗样本数）/ `n_off`（算偏移用的最近条数）/ `span`（整窗跨度秒）/ `spread`（最近几条的散布＝当前抖动）/ `spread_win`（**整窗**散布＝跳变指标）/ `ok`（样本够不够）/ `breach_since`（首次越界时刻，未越界为 `null`） |
| `clock_off` | 演示用：客户端把自报 `ts` 拨快/拨慢了多少秒（0 = 正常） |

⚠ 三个“不给数”的门（都是实测出来的，宁可说“还看不出来”）：

1. `ok=false`（样本 < `clock.MIN_SAMPLES=3`）→ 别看成设备时钟准。
2. `drift_ppm=null` 当：跨度 < `DRIFT_MIN_SPAN`（30s）、窗内见过**跳变**
   （`spread_win` 超过偏移告警阈值 = 拨表/重启对时，实测一次 +120s 会让斜率读成 ~2,000,000ppm）、
   或 |斜率| < `DRIFT_SIGMA_K=3` × 斜率标准差（噪声里看不出趋势——实测整数秒设备时间下，
   1s 上报/60s 窗的斜率噪声就有几十~几百 ppm）。
3. `offset` 只用**最近 `OFFSET_WINDOW=8` 条**算中位数（状态量，要反应快）；
   整窗中位数在拨表后**一分钟内仍读≈0**（旧样本压着），那是错的。

**只估计、不改数据**：`ts` 的归一口径仍是 `effective_ts()`（§5.5）；本估计**不**回写任何记录时间。

### `POST /api/ctl`（链路控制，body 带 `action`）

已有：`pause`/`resume`/`set_sn`/`every`/`mark`/`untrack`/`revoke`/`unrevoke`/`replay`/`stale`。

**新增 `clock_off`（设备时钟演示，2026-09-13）**：`{action:"clock_off", sec:<秒>}`

- 把客户端自报的 `ts` 拨偏 `sec` 秒（正=拨快），返回 `{ok:true, clock_off:<当前值>}`；
  页面上带「应用」按钮一起提交。用于现场演示 `id_clock` 告警与 `clock` 估计。
- 拨偏后：**偏移**约 8 条上报（8s @1s 间隔）就反映出来；**漂移**会显示 `—`（窗内有跳变，不算漂移）。

**新增 `id_level`（§8.2 降级策略演示，2026-09-12）**：`{action:"id_level", level:"<模式>"}`

- 模式取值（`ui_server.ID_LEVEL_MODES` 单一源，`/api/status.id_level_modes` 同时给页面）：
  `auto`（全正常→L0）/ `sign_fail`（Slot0 签名失败→L1）/ `se_fail`（SE 不可用→L2）/ `no_key`（无可用密钥→L3）。
- **传的是“哪个环节坏了”，不是写死的 level** —— 下一条 ID 上报由 `orpah_id.pick_level()` 按 §8.2 算出级别，
  走的才是规格里那条路径（而不是直接塞一个 level 值）。
- 返回 `{ok:true, id_level:"<实际生效值>"}`；非法值**不改**当前模式（返回实际值，页面据此回弹）。
- 效果：选 `se_fail` → 卡片显 `L2 · SE 不可用（仍更新定位）` + `id_degraded` warn 告警；
  选 `no_key` → `L3 · 仅覆盖发现` + `id_degraded` crit 告警，且**不刷新 `last_seen`**（不当人员出现）。

**新增 `spoof`（防 spoof 演示，2026-09-12）**：`{action:"spoof", kind:"<攻击类型>"}`

- 服务端用 `spoof.build_case()` 造一条攻击报文，**经既有空口链路注入**
  （client→STA→空口→AP→Router→UDP→Server），不是离线自演 —— 验签结果由 server 回
  `_on_id_report` → `id_demo`/`id_reports`/`id_reject` 事件/签名失败率告警都能看到。
- 返回 `{ok:true, kind, zh, en, expect, note}`；`kind` 非法 → `{ok:false, err:"bad_kind", kinds:[...]}`。
- `kind` 取自 `spoof.UI_KINDS`（**排除 `revoked`**：页面用的是活密钥库，跑一次会把在跑的设备搞成验不过；
  撤销场景用现有的 `revoke`/`unrevoke` 按钮演示）。
- `replay` 用**最近一条上报的 nonce**（一定已被 server 记过）→ 必被 nonce 去重拦下。
- 攻击清单与「是哪道防线拦下的」见 `ROADMAP.md` §四；端到端脚本 `demo_spoof.py`、自检 `test_spoof.py`。

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

### `/api/metrics`（指标面板）

`GET /api/metrics?minutes=N[&sn=<SN>]` → 四项指标的汇总（页面 `metrics.html`，计算在 `metrics.py`）：

```json
{"ok": true, "tsdb": true,
 "window": {"minutes": 60, "sn": "CN-WH01-9AF3C1D2", "t0": 1789193000000, "t1": 1789196600000},
 "verify": {"total": 30, "reports": 29, "rejected": 1, "fail_ratio": 0.0333,
            "by_alg": {"ES256": 29, "none": 1},
            "by_level": {"0": 27, "1": 1, "2": 1},
            "degraded": {"l2": 1, "l3": 0, "total": 1},
            "degraded_ratio": 0.0345, "level_unknown": 0},
 "rssi": {"n": 30, "avg": -67.4, "min": -80, "max": -55},
 "cases": {"total": 3, "open": 1, "ended": 2,
           "to_found": {"n": 1, "avg": 400.0, "min": 400, "max": 400},
           "to_close": {"n": 1, "avg": 900.0, "min": 900, "max": 900},
           "rows": [{"case_id": "C001", "person_id": "P002", "status": "closed",
                     "created": 1789104728, "to_found_sec": 400,
                     "to_close_sec": 900, "elapsed_sec": null}]}}
```

- **窗口** `minutes`（默认 60，1~1440）只作用于**事件流**（`root.orpah.events` 时间窗）与
  **上报流**（`root.orpah.devices.<sn>`）；`sn` 缺省 = 当前演示终端。
- **案件不走窗口**：一个案子跨小时，按窗口切会把「立案→发现/结案」算错 —— 处置时长是全量口径。
- **无样本 → `null`，不是 0**：`fail_ratio` / `rssi.avg` 在没有样本时为 `null`
  （0% 失败率与 0 dBm 都是真实值，拿来冒充"没有样本"会误导）。
  ⚠ **消费约定**：判断"有没有数据"请用 `verify.total === 0` / `rssi.n === 0`，
  **不要**用 `fail_ratio` 的真值 —— `null` 与 `0` 在 JS 里都是 falsy，用真值判断会把
  "还没数据"与"0% 失败（好事）"当成同一件事（`metrics.html` 用的是 `null` 判断，显示「—」）。
- **未结案的案件不进 `to_found` / `to_close` 的均值**（否则均值随等待时间漂移）；
  未结案在 `cases.open` 里单列，逐案 `elapsed_sec` 只在未结案时给（读者自己判断"已经等了多久"）。
- `cases.invalid` = **时长不可用的案件条数**：① 缺 `created`（整行跳过）；
  ② 时间回拨（发现/结案时刻早于立案）—— 此时该字段置 `null` 而不是负数
  （负的“处置时长”没意义，报出来会被当成真实值），页面在有值时红字提示。
- **时间单位**：案件相关的 `created` / `closed_at` / `events.t` / 各项时长都是**秒**
  （与 `cases.py` / `registry` / `alerts.py` 同一约定）；`window.t0/t1` 与 `reports.t` 是**毫秒**。
- `verify.by_alg` 是从审计 `detail` 里的 `alg=` **解析**出来的（审计没有结构化列），
  **只收令牌字符** `[A-Za-z0-9_.-]`（长度 ≤24），其余归 `unknown`，不猜。
  ⚠ 这个 `alg` 值**来自空口报文的头**（`server.py:_on_id_report` 直接取 `hdr.alg` 落审计，
  连被拒报文也落）→ 属外部输入：服务端**故意**原样保留（取证要留“攻击者当时发了什么”），
  但**派生层（本模块）与展示层（页面 `esc()`）都必须收口**，不要把原值直接拼进 HTML。
- `tsdb=false` 表示 IoTDB 未连：事件流/上报流为空，只有案件指标有意义（`metrics.html` 会提示）。
- **降级指标（`by_level` / `degraded` / `degraded_ratio` / `level_unknown`，2026-09-12 加）**：
  粒度对齐 §8.1/§8.3（L0 正常 / L1 Slot0 签名失败 / L2 SE 不可用 / L3 无可用密钥）。
  - `by_level` **只统计“通过”的上报**（键是 0..3 的字符串化数字，JSON 对象）。被拒的报文里也有
    `level=`，但那是**攻击者宣称的级别**（伪造一条 `level=0` 不代表设备工作在 L0）→ 混进来会把
    降级占比算错，故不计入；被拒的量由 `rejected` / `fail_ratio` 表达。
  - `degraded` = 通过里 `level≥2` 的条数（`l2`/`l3`/`total`）；`degraded_ratio` = `degraded.total / reports`。
  - **分母是 `reports`（通过总数）**，含“取不到级别”的老审计行 → 所以 `degraded_ratio` 是**下界**；
    `level_unknown` 把那些行数摆出来，不让读者自己猜（页面在有值时补一句提示）。
  - `level` 与 `alg` 同源（都是报文头字段经 `detail` 解析）→ 同样**只认单个数字 0..3**，
    其余（`level=<b>` / `level=9` / 缺字段）→ `None`、不进 `by_level`。
    ⚠ **`None` ≠ `0`**：把缺级别当成 L0 会抬高分母、压低降级占比（假乐观），所以单独计数。
  - ⚠ **`by_alg` 与 `by_level` 口径**不一样**（有意为之）**：`by_alg` 统计**两类事件**（通过+被拒）——
    攻击者用了什么算法是有价值的情报（页面 `none 10` 里含被拒的免签冒充）；`by_level` **只数通过**，
    因为被拒报文里的 `level` 是攻击者**宣称**的级别，不代表设备真实工作级别。所以页面上
    `none` 与 `L3` 的条数**本来就可以不等**（差的就是被拒的那几条），不是 bug。
  - 无样本 → `degraded_ratio` 为 `null`（与 `fail_ratio` 同一口径）。

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
- ⚠ **`etype` / `sn` 是精确匹配（大小写敏感）**：`tsdb.query_events` 里是 `r["etype"] != etype`
  直接比较，没有 `lower()` —— 传 `case_mark` 能筛到，传 `Case_Mark` 会得到空集（且 `ok:true`，
  因为那只是一次合法但无匹配的查询）。页面上的筛选是**下拉框**（value 就是机器值）
  所以不会踩到；直接调 API 时请用小写机器值。
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

### 时钟可信：设备无时钟时的 `ts`（2026-09-12）

免电池客户端**没有 RTC**，协议 §5.5 规定 `ts=0`（或缺失）→ **跳过时间窗判断**，仅靠 nonce 防重放。
“收不收”之外还有“**存什么时间**”，本 demo 的规则（单一入口 `orpah_proto.effective_ts()`）：

| 设备给的 ts | 入库/审计用的时刻 | 标记 |
|---|---|---|
| 正常（整数、非 0、≥2000-01-01、不超前服务器 >1 天） | 用设备时间 | `ts_src=device` |
| `0` / 缺失 / 非整数 / 早于 2000 / 超前 >1 天 | **服务器接收时刻** | `ts_src=server` |

- **一次算、各处用**：设备测点流（`devices.<sn>`）、路由器观测序列（`routers.<sid>.<sn>`）、
  `registry.last_seen`、审计事件、页面展示都用同一个时刻 —— 否则定位/回放按时间对齐时两边对不上。
- **留痕**：审计事件 detail 写 `ts_src=server`；`/api/status.reports[]` 带 `ts_src`/`ts_eff`
  （页面时间列显示服务器时刻 + `*`）；`/api/status.id_demo` 带 `ts_src`（卡片显「设备无时钟」）。
- **不改报文**：`ts` 在签名预像里 → 改了验签不过；归一化只用于记录，原始 `ts` 原样保留在报文里。

**处置态（2026-09-12 用户定 A 方案）**：`case_overtime` 额外要求案件**无人接手**
（`Case.handler` 为空）才报 —— 原来只要案件还 `open` 就永远 crit，红点**恒亮被淹没**
（看不出新旧，也分不出「刚超时没人管」与「已在找人」）。
点「标记已接手」（`POST /api/cases {action:"assign"}`）→ 本条告警消失，案件转入「处置中」继续跟
（时长照常累计、案件页可见）；「取消接手」→ 告警回来。
**告警文案也跟着改了**（`alert_case_overtime` 加了“且无人接手”），否则会让人以为已接手还在报警。

**时长上限（2026-09-12 用户定 B 方案）**：A 方案有个反向滞点 —— 「已接手」一旦成立就**永不再报**，
案子被认领后搁置（人没找着、也没人再管）就完全静默。故加 `case_handled_overtime`：
从**接手时刻**（`Case.handled_at`）起再超 N 秒仍未被发现 → 再提醒一次。
- 级别 **`warn`**（“有人在办、只是拖太久”的提醒），不盖过“没人接手”的 `crit`。
- `since` = **接手时刻**（不是立案时刻）→ 页面「持续 X」读作“接手后多久还没找到”。
- 默认 `86400`（真实 24h）；演示（2s 一包）里不会自然发生，要看效果把 env 设小（如 `5`）。
- 已 `found` / 已结案的案件不报；`handled_at` 缺失（老库/手工对象）回落到 `created`。

**按持续时长分级/升级（2026-09-12 用户定 C 方案）**：让“拖得越久越严重”能表达出来 ——
原来是写死的等级（`no_report` 恒 warn、`case_overtime` 恒 crit）。只给**“沉默得越来越久”型**的两条
加升级，因为它们的严重度真的随时间单调增长：

| 规则 | 起步 | 升级为 `crit` |
|---|---|---|
| `no_report` | `> 30s` → `warn` | `> 300s`（`ORPAH_ALERT_NO_REPORT_CRIT_SEC`） |
| `case_handled_overtime` | `> 24h` → `warn` | `> 48h`（`ORPAH_ALERT_CASE_HANDLED_CRIT_SEC`） |

- **为何不给另外两条分级**：`case_overtime`（无人接手）与 `sig_fail_rate`（验签被拒）是**定性**问题，
  一发生就是 `crit`；给它们加一段 warn 会把 A 方案刚解决的问题拿回来（刚超时先不报红）。
- 两个升级阈值均可配；把升级阈值设得**比起步阈值还小/相等** → 一超起步就 `crit`
  （等于把分级关掉，保留旧行为）。

未做：Webhook/邮件通知、SSE 弹窗、RSSI 突变/校验位连续失败规则、页面展示当前阈值 —— 见 `ROADMAP.md` §三。

规则（阈值可用**环境变量**覆盖，改了要重启；默认值有演示压缩也有真实时长，见下）：

| kind | level | 条件 | 阈值 | 环境变量 |
|---|---|---|---|---|
| `no_report` | `warn` → `crit` | **工作态**（启用 **或 走失中**）且**曾上报过**的设备，距上次上报超过 N 秒 | `30` / 升级 `300` | `ORPAH_ALERT_NO_REPORT_SEC` / `ORPAH_ALERT_NO_REPORT_CRIT_SEC` |
| `case_overtime` | `crit`（不分级） | `open` 状态的案件，立案超过 N 秒仍未发现 **且无人接手** | `180` | `ORPAH_ALERT_CASE_OVERTIME_SEC` |
| `case_handled_overtime` | `warn` → `crit` | `open` 且**已有接手人**，距**接手时刻**超过 N 秒仍未发现（B 方案） | `86400` / 升级 `172800` | `ORPAH_ALERT_CASE_HANDLED_SEC` / `ORPAH_ALERT_CASE_HANDLED_CRIT_SEC` |
| `sig_fail_rate` | `crit`（不分级） | 最近 N 条签名上报中，被拒比例 > 比例阈值 | `5` 条 / `0.5` | `ORPAH_ALERT_SIG_WINDOW` / `ORPAH_ALERT_SIG_FAIL_RATIO` |
| `id_degraded` | L2 `warn` / L3 `crit` | 最近 N 秒内出现过**降级上报**（§8.3）：L2 = SE 不可用（仍更新定位）、L3 = 无可用密钥（裸上报） | `300` | `ORPAH_ALERT_ID_DEGRADED_SEC` |

⚠ **默认值分两类，别看混**：
- **演示压缩时间**（客户端 2s 一包，为了现场能看到效果）：`no_report` 30s（升级 300s）、
  `case_overtime` 180s、`sig_window` 5 条、`sig_fail_ratio` 0.5。
- **真实时长**：`case_handled_overtime` 的 `86400`（= 24h，升级 48h）—— 真实世界里“接手后一天没找到”
  才算拖太久，演示里不会自然发生；想现场看效果把它压小（如 `ORPAH_ALERT_CASE_HANDLED_SEC=5`）。

⚠ `no_report` 为什么把**走失中**也算工作态（2026-09-12 修正）：走失者的追踪器正是最该盯的一台，
它掉线（没电/出范围）往往就是“找不到人”的原因；原来只算“启用”，一旦立案（设备转 `lost`）
反而不再盯它，方向反了。停用/报废仍不盯（已不是现行设备）。

- 环境变量与事件保留期限（`ORPAH_EVENT_RETENTION_DAYS`，见 §5）同一套机制：
  未设 / 空串 / 非法值 → 回退上表默认值。
- 也可以在进程内覆盖：`alerts.evaluate(..., no_report_sec=…, no_report_crit_sec=…,
  case_overtime_sec=…, case_handled_sec=…, case_handled_crit_sec=…,
  sig_window=…, sig_fail_ratio=…, id_degraded_sec=…)`（单测用的就是这个入口）。

**降级告警 `id_degraded`（§8.3，2026-09-12）**：
- 数据源 = `/api/status.id_reports` 的环形快照（最新 20 条）；判定用 `accepted && level∈{2,3}`。
- 按「**窗口内出现过**」而不是按条数：设备降级是**状态**（SE 坏了不会自己好），报一次就该有人看；
  窗口只用来把“很久没再降级”自动消掉。
- **同一台设备只出一条**（取最高级：3 > 2）—— 否则一台 SE 坏掉的设备每次上报都刷一条，红点满了看不出别的。
- 文案：L2 → `alert_id_degraded`（数据字段 `sn` / `lv`）；L3 → `alert_id_no_key`。
- **被拒的上报不算降级**（那是 `sig_fail_rate` 的事）；L0/L1 也不告警（§8.3：L0/L1 正常处理）。

**§8.3 存在性语义（同日修）**：`registry.last_seen` 只由 `orpah_id.counts_as_presence(rec)`
（= `accepted` 且非 `coverage_only`）的结果刷新 —— 即 **L0/L1/L2 算人员出现，被拒的（含伪造）与 L3 不算**。
修前 `ui_server._on_id_report` 无条件 `registry.touch()`，后果实测：一条**验签失败**的伪造上报把
`last_seen` 从 `1789199499` 推到 `1789199504` → **伪造报文能“报平安”，把「长未上报」告警永远抑住**。
注：业务报文 `ORPAH-REPORT`（L2）走另一条路，它照样刷新 `last_seen`（那是设备自己的上报，与 ID 层无关）。
- 例（想避免「刚立案 3 分钟就亮红点」的观感）：
  PowerShell `$env:ORPAH_ALERT_CASE_OVERTIME_SEC=600; python ui_server.py --port 8901`；
  cmd `set ORPAH_ALERT_CASE_OVERTIME_SEC=600 && python ui_server.py --port 8901`。

字段说明：

- `key` = `<kind>:<对象>`，用于前端判断「是不是新告警」（新 key → 徽标闪烁一次）。
- `msg` = **i18n 键**（不是成品文案）；页面用 `T(msg)` 取模板，再用告警对象里
  同名字段替换 `{占位符}`（`gap` 会先按界面语言格式化成时长，最多两段：
  中文 `10天2小时`/`10小时13分钟`/`3分20秒`/`45秒`，英文 `10d2h`/`10h13m`/`3m20s`/`45s`）。
- `since` = 告警起算时间（设备用 `last_seen`、案件 `case_overtime` 用 `created`、
  `case_handled_overtime` 用 `handled_at`、签名用首条样本时间），页面显示为「持续 X」。
- 排序：`crit` 先于 `warn`，同级按 `since` 升序。
- 阈值未满样本时不告警（如签名样本不足 `sig_window` 条）；设备从未上报过、
  或状态非**工作态**（启用 / 走失中）的，不参与 `no_report`。
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
| `adopt` | `sn` | 让**演示终端**改用当前 `active` 代（演示「设备侧完成更新」）：把 `id_dev` 置空后按 active 代重建，**下一次上报周期起**用新代签名（不是即时改签名）；非终端 SN → `note_code=not_demo_sn` |
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

### 时序平滑（回放页的前端行为，2026-09-12）

面板新增「平滑估计 / 平滑搜索半径 / 轨迹抖动」三行，画布与地图上多一条**绿线**（平滑轨迹）
与原始**红线**并列（原始结果不受影响）。算法在 `pos.js` 的 `kalmanTrack()`（4 状态恒速卡尔曼
x,y,vx,vy，松耦合位置量测，长缺口 reset），**不是滑动平均**：

- 移动目标上 N 点平均滞后 ≈ (N/2)×采样周期 —— 找人场景里滞后 = 指错位置（合成实测：
  降噪量二者接近，原始 RMS 4.5 m → 卡尔曼 3.5 m / 5 点平均 3.4 m，但滞后 卡尔曼 0.4 m
  vs 平均 2.7 m）。
- **平滑搜索半径取滤波后协方差 P**（含过程噪声 Q + 测量噪声 R），不用测量协方差 ——
  否则「输出更平滑」会被误当成「更准」，给出过小的半径（假自信）。实测半径 27.3 → 21.9 m，
  95% 椭圆对真值覆盖率 100%（合成场景）。
- **因果、无前视**：只吃 `t <= 光标` 的帧（实测 20 个光标位置最多前视 0 ms、0 个未来点）。
- 真实演示数据噪声小（±2 dBm）而 WLS 的 `σ=max(1, 0.25×距离)` 偏保守 → 真实数据上平滑幅度
  有限（抖动 3.5 → 3.1 m，−12%）；真机 RSSI 标定后该模型可收紧。
- 关掉复选框 → 绿线与平滑两行同时消失，原始轨迹/半径照旧。

### 轨迹导出（回放页的前端行为，2026-09-12）

「导出轨迹」= **原始 / 平滑** × **GPX / GeoJSON**，纯前端生成（`Blob` + `<a download>`），**无新后端接口**：

- **导出整窗**轨迹，不是只导已回放的部分（导出是拿去用的成果，缺的时间段被截掉会误导）。
- **缺口断开成多段**：相邻帧间隔 > `ROUTER_MAX_AGE_MS`（30 s 观测时效）算缺口；平滑侧再按滤波器
  `reset` 断开。跨缺口的直线不是真走出来的路 → GPX 用多个 `<trkseg>`、GeoJSON 一段一个
  `LineString` Feature（带 `from`/`to`/`points` 属性）。
- **经纬度走 `map.js` 的 `toLatLng`**（基点 + 米/度换算）—— 与地图视图落点**同一个**换算，
  不另写一份；GeoJSON 坐标顺序是 `[经度, 纬度]`（标准）。
- GPX = 1.1，带 `<time>`（QGIS / Google Earth 可直接读）；GeoJSON 额外带 `from_ms`/`to_ms` 原始时间戳。
- 文件名 `orpah-<SN>-<raw|smoothed>-<起>-<止>.<gpx|geojson>`；SN 允许中文，故非 `[A-Za-z0-9._-]` 字符
  在文件名里替换为 `_`。
- 本窗无可定位帧 → 提示「本窗没有可导出的定位轨迹」，**不产出空文件**。

### 有效时段（回放页的前端行为，2026-09-12 用户定）

窗口里常有**大段解不出位置的时段**（无观测 / 只有 1 台观测 / 几何退化）。处理原则：

- **不静默截取**：`from`/`to` 永不自动改窄 ——「某段时间完全没被任何路由器听到」本身就是线索。
- **标注**：前端用共享内核 `pos.js` 的 `obsSegments()`（逐段调用 `obsOfStation`，判定语义单一源）
  把窗口切成 ≤1200 段，逐段给出有几台站位有观测；进度条按 **绿(≥2)/橙(=1)/灰(0)** 分色，
  并给「有效 a%（Xm）· 无效 b%（Ym）」统计。
- **光标先落在首个能定位的时刻**（`nextValidAt`），不是窗首 —— 否则第一眼全是「无解」。
- **可选「跳过无效段」**（默认开）：播放时直接跳到下一个能定位的时刻；跳过的缺口会在
  轨迹里**断开**（`S.trail` 插 `null`），不会把跨缺口的直线画成「走出来的路」。

---

## 11. `/api/config`（标定参数：A/n/噪声的唯一源）

```json
{"ok":true,
 "path_loss":{"A":-40.0,"n":2.5},
 "noise_db":2.0,
 "rssi_range":{"min":-95,"max":-30},
 "walk":{"speed_mps":1.2,"epoch_ms":1767225600000}}
```

`GET /api/config` → 上面这份**标定参数快照**（内容由 `motion.calibration()` 生成）。

### 为什么要有这个接口（2026-09-12）

`A`（1 m 处参考 RSSI）与 `n`（路径损耗指数）原本在**四处各写一份**：

| 位置 | 用途 |
|---|---|
| `motion.py`（`RSSI_A`/`RSSI_N`） | 模拟器**正向**算 RSSI（发给页面的上报值） |
| `track.html`（`#plA`/`#plN`） | 把 RSSI **反算**成距离 → 定位、置信椭圆 |
| `rssi.html`（`#plA`/`#plN`） | 教学计算器：正向仿真 + 反向反算 |
| `replay.html`（`#rpA`/`#rpN`） | 把**历史落库的 RSSI** 反算成距离 → 回放定位 |

靠注释「与页面默认一致」互相提醒 —— 改一处不改另一处时**两边用不同的模型**，
定位与椭圆半径会**静默偏离**（不报错、无日志），而且回放页与实时页会给出不同结果。

现在以 `motion.py` 为**唯一源**：三个页面开页时 `GET /api/config` 把默认值填进输入框。

### 契约

- **只是默认值，不是硬绑定**：输入框仍可手改（试别的 `n` 看定位怎么变 = 演示的一部分）。
- 页面 HTML 里的 `value="-40"` / `value="2.5"` 降级为**离线兜底**（服务端不可达时用）。
  `test_motion.py` §8 有一条**单源守卫**：断言三页兜底值 == `motion` 常量、且页面确实去取
  `/api/config` → 兜底不会骗人，也不会有人偷偷把页面改回写死。
- `noise_db` 是**服务端注入的测量噪声**（`motion.NOISE_DB`）。`track.html`/`rssi.html` 自己也有
  「噪声 ±」输入框 —— 那是**页面自己仿真**用的旋钮（在浏览器里造合成数据），语义与「服务端给
  真实数据加了多少噪声」不同，故**刻意不绑**：改一个不该动另一个。
- `rssi_range` 是**量程**，可放心当刻度/告警阈值用：`path_loss()` 与**加噪之后**的结果都被钳到
  这里（2026-09-12 修复：原先只在正向换算里钳，远端站位 -95 再减噪声会给出 -97 —— 实测 600 秒
  1200 条测量中 438 条越界，声明与数据不符）。噪声是**测量**误差，不会把收不到的信号变出来，
  所以钳位只能在加噪之后（`motion.clamp_rssi()` 是唯一的钳位实现）。
- 站位（路由器）坐标不在本接口：见 §7 `/api/stations`（可增删改/导入，页面表格里直接编辑）。


