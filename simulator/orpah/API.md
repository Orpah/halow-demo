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
  业务事件 `root.orpah.events`（etype/sn/detail：case_mark/case_found/case_close）。
- IoTDB 未启动时写入静默降级、每 10s 重连一次，不影响 SQLite/UI。
- `track.html` 的「真实上报」模式消费本接口：按时间升序画 RSSI 时序 + 按 A/n 换算距离。
  单测点只能得「距离环」，需多路由器（各自带 `router_id` + 已知坐标）才可三边定位到点。

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

