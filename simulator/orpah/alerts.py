#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alerts.py — 告警规则引擎（供页面红点消费）

设计取舍：

- **无状态**：每次用当前快照重新评估，返回「活跃告警」列表，**不落库**。
  告警表达的是"当前状态"，不是"历史"——历史由 IoTDB 事件流（`root.orpah.events`）负责。
- 阈值默认值是**演示压缩时间**（真实部署要调大），但**全部可用环境变量覆盖**
  （与事件保留期限 `ORPAH_EVENT_RETENTION_DAYS` 同一套机制，改了要重启）：

      ORPAH_ALERT_NO_REPORT_SEC       长未上报（秒，默认 30）
      ORPAH_ALERT_NO_REPORT_CRIT_SEC  长未上报升级为 crit（秒，默认 300；C 方案）
      ORPAH_ALERT_CASE_OVERTIME_SEC   走失超时（秒，默认 180）
      ORPAH_ALERT_CASE_HANDLED_SEC    接手后仍未被发现（秒，默认 86400 = 24 小时）
      ORPAH_ALERT_CASE_HANDLED_CRIT_SEC 接手后又多久升 crit（秒，默认 172800 = 48 小时）
      ORPAH_ALERT_SIG_WINDOW          签名失败率窗口（条，默认 5）
      ORPAH_ALERT_SIG_FAIL_RATIO      签名失败率阈值（0~1，默认 0.5）
      ORPAH_ALERT_CLOCK_OFFSET_SEC    设备时钟偏移阈值（秒，默认 30）
      ORPAH_ALERT_CLOCK_DRIFT_PPM     设备时钟漂移阈值（ppm，默认 200）
      ORPAH_ALERT_CAP_MISMATCH_SEC    能力声明不一致的消警窗口（秒，默认 300）

  例（立案后 10 分钟才算超时，避免演示时刚立案就亮红点）：
      PowerShell:  $env:ORPAH_ALERT_CASE_OVERTIME_SEC=600; python ui_server.py --port 8901
      cmd:         set ORPAH_ALERT_CASE_OVERTIME_SEC=600 && python ui_server.py --port 8901

- 每条告警带 `key`（kind + 对象）供前端判断"是否是新告警"；`msg` 是 **i18n 键**，
  由前端本地化 —— 后端不拼中文/英文，免得又变成"后端文案不跟语言走"。
- 时间戳单位统一为**秒**（与 `registry.touch` / `cases.mark` 一致）。

已实现（第一批 3 条 + B 方案 1 条）：
    no_report               工作态（**启用 或 走失**）的设备超过 no_report_sec 无上报
    case_overtime           案件立案超过 case_overtime_sec 仍未发现**且无人接手**（只算 open；已 found 不算）
    case_handled_overtime   已接手的案件，距**接手时刻**超过 case_handled_sec 仍未发现（B 方案）
    sig_fail_rate           最近 sig_window 条签名上报里被拒比例 > sig_fail_ratio
    id_degraded             最近 id_degraded_sec 内出现过降级上报（§8.3）：L2 warn / L3 crit
    id_clock                设备时钟偏移/漂移超出阈值（估计值，§5.5 深化）
    id_cap_mismatch         设备**已签**声明「有 RTC」却送出不可用的 ts（故障/被动手脚的信号）

**能力声明不一致（`id_cap_mismatch`，2026-09-13）**：声明 `cap.rtc=true` 的设备**本应**
有时钟，但某条上报的 `ts` 不可用（ts=0/荒谬/非整数）→ 报 warn。反之「声明无 RTC + ts=0」
是**正常**（免电池终端的预期行为）→ 不报。只吃**已签**上报里的声明（`cap` 在 JCS 预像内，
篡改即验签失败 → 声明可信），业务报文未签名、其 `cap` 只能当提示，不参与告警。

**设备时钟（2026-09-12）**：`clock.ClockTracker` 从「设备自报 ts vs 服务器接收时刻」估计
每台设备的**偏移**（中位数）与**漂移**（最小二乘斜率，ppm）。本规则在超阈时报 warn：
- 偏移超 `ORPAH_ALERT_CLOCK_OFFSET_SEC`（默认 30s）→ 设备时钟不对，回放时间轴会整体偏；
- 漂移超 `ORPAH_ALERT_CLOCK_DRIFT_PPM`（默认 200ppm ≈ 每天 17s）→ 晶振/温漂异常。
- 只在估计**可信**（样本数 ≥ `clock.MIN_SAMPLES`）时才报，宁可不报也不编；
  `since` = 首次越界时刻（`ClockTracker` 记的），页面「持续 X」才有意义。

**降级告警（§8.3，2026-09-12）**：L2（SE 不可用、改用 CH32 对称密钥）→ 记录告警（SE 异常）；
L3（无可用密钥、裸上报）→ 触发“设备异常”通知运维。
- 按“**窗口内出现过**”而不是按条数：设备降级是**状态**（SE 坏了不会自己好），报一次就该有人看；
  窗口只用来自动消警（窗口内没再报 = 最近没降级）。
- 同一台设备只出一条（取最高级）：否则一台 SE 坏掉的设备每次上报都刷一条，红点满了看不出别的。
- 阈值 `ORPAH_ALERT_ID_DEGRADED_SEC`（默认 300s，与 no_report 同一个演示时间尺度）。

**按持续时长分级（2026-09-12 用户定 C 方案）**：从“有时间阈值”的两条规则开始，时长越长等级越高：

    规则                      起步         升级
    no_report                > 30s  warn   > 300s  crit
    case_handled_overtime    > 24h  warn   > 48h   crit

- 为什么只给这两条升级：它们是**“设备/案子沉默得越来越久”**型问题，严重度随时间单调增长；
  而 `case_overtime`（没人接手）与 `sig_fail_rate`（验签被拒）是**定性**问题，
  一发生就该是 crit —— 给它们加 warn 反而会把 A 方案刚解决的问题又拿回来（刚超时先 warn 不报红）。
- 阈值全部可配（含升级阈值）；两个 crit 阈值默认值是**演示压缩 / 真实**混着的：
  `NO_REPORT_CRIT_SEC=300`（5 min，与 30s 同一个演示时间尺度）、
  `CASE_HANDLED_CRIT_SEC=172800`（48h，真实尺度）。
- 若把 crit 阈值设得比起步阈值还小/相等，则只要超起步阈值就直接 crit（当“关闭分级”用）。

**处置态（2026-09-12 用户定 A 方案）**：`case_overtime` 额外要求「无人接手」（`case.handler` 空）——
案件一旦有人接手就转入“处置中”跟踪、不再占红点；否则只要案件还开着就永远 crit，
红点恒亮被淹没（看不出新旧，也分不出“刚超时没人管”与“已在找人”）。

**时长上限（2026-09-12 用户定 B 方案）**：A 方案有个反过来滞点 —— “已接手”一旦成立就
永不再报，案子被认领后搁置（人没找着、也没人再管）就完全静默。故加
`case_handled_overtime`：**从接手时刻**起再超 `case_handled_sec`（默认 24h）仍未被发现 → 再提醒一次。
- 级别用 **warn 而非 crit**：它是“有人在办、只是拖太久”的提醒，不应盖过“没人接”的 crit。
- `since` = **接手时刻**（不是立案时刻）—— 页面「持续 X」要读成“接手后多久还没找到”。
- 默认 24h 是**真实时长**，演示（2s 一包）里不会自然发生；要看效果请把
  `ORPAH_ALERT_CASE_HANDLED_SEC` 设小（例：`60`）。

第二批可加：RSSI 突变、校验位连续失败（需要历史序列，本模块暂不做）。
"""
import os
import time

import cases as cs
import registry as reg

LEVEL_CRIT = "crit"
LEVEL_WARN = "warn"


def _env_int(name, default):
    """取整数环境变量；未设/空串/非法值 → 回退默认（与 tsdb._env_int 同语义）。"""
    try:
        return int(str(os.environ.get(name, "") or default).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    """取浮点环境变量；未设/空串/非法值 → 回退默认。"""
    try:
        return float(str(os.environ.get(name, "") or default).strip())
    except (TypeError, ValueError):
        return default


NO_REPORT_SEC = _env_int("ORPAH_ALERT_NO_REPORT_SEC", 30)        # 超过这么久没上报 → 告警
NO_REPORT_CRIT_SEC = _env_int("ORPAH_ALERT_NO_REPORT_CRIT_SEC", 300)   # 再久 → 升 crit（C）
CASE_OVERTIME_SEC = _env_int("ORPAH_ALERT_CASE_OVERTIME_SEC", 180)  # 立案后这么久还没发现
CASE_HANDLED_SEC = _env_int("ORPAH_ALERT_CASE_HANDLED_SEC", 86400)  # 接手后这么久还没发现（B）
CASE_HANDLED_CRIT_SEC = _env_int("ORPAH_ALERT_CASE_HANDLED_CRIT_SEC", 172800)  # 再久 → crit（C）
SIG_WINDOW = _env_int("ORPAH_ALERT_SIG_WINDOW", 5)              # 签名失败率统计窗口（条）
SIG_FAIL_RATIO = _env_float("ORPAH_ALERT_SIG_FAIL_RATIO", 0.5)  # 窗口内被拒比例超过它 → 告警
ID_DEGRADED_SEC = _env_int("ORPAH_ALERT_ID_DEGRADED_SEC", 300)  # 降级上报（L2/L3）消警窗口（秒）
CLOCK_OFFSET_SEC = _env_int("ORPAH_ALERT_CLOCK_OFFSET_SEC", 30)  # 设备时钟偏移超此值 → 告警（秒）
CLOCK_DRIFT_PPM = _env_int("ORPAH_ALERT_CLOCK_DRIFT_PPM", 200)   # 设备时钟漂移超此值 → 告警（ppm）
CAP_MISMATCH_SEC = _env_int("ORPAH_ALERT_CAP_MISMATCH_SEC", 300)  # 能力声明不一致的消警窗口（秒）


def _alert(kind, level, key_obj, msg, since, **data):
    a = {"kind": kind, "level": level, "key": f"{kind}:{key_obj}",
         "msg": msg, "since": int(since or 0)}
    a.update(data)
    return a


def level_by_gap(gap, warn_after, crit_after):
    """按持续时长分级（C 方案）：超过 crit_after → crit，否则 warn。

    调用方已经判定过“超过起步阈值”（gap > warn_after），所以这里只管升级那一步。
    crit_after <= warn_after → 一超起步就 crit（相当于把分级关掉）。
    """
    return LEVEL_CRIT if crit_after <= warn_after or gap > crit_after else LEVEL_WARN


def evaluate(registry, cases, id_reports, now=None, clock=None, **th):
    """返回活跃告警列表（crit 在前，同级按触发时间）。

    参数与阈值都可注入，便于单测（见 test_alerts.py）。
    `clock` = `{sn: {"offset":…, "drift_ppm":…, "n":…, "ok":…, "breach_since":…}}`
    （来自 `clock.ClockTracker.snapshot()`；不传则不评估时钟规则）。
    """
    now = int(now if now is not None else time.time())
    no_rep = th.get("no_report_sec", NO_REPORT_SEC)
    no_rep_crit = th.get("no_report_crit_sec", NO_REPORT_CRIT_SEC)
    case_ov = th.get("case_overtime_sec", CASE_OVERTIME_SEC)
    case_handled = th.get("case_handled_sec", CASE_HANDLED_SEC)
    case_handled_crit = th.get("case_handled_crit_sec", CASE_HANDLED_CRIT_SEC)
    win = th.get("sig_window", SIG_WINDOW)
    fail_ratio = th.get("sig_fail_ratio", SIG_FAIL_RATIO)
    deg_sec = th.get("id_degraded_sec", ID_DEGRADED_SEC)
    cap_sec = th.get("cap_mismatch_sec", CAP_MISMATCH_SEC)
    off_max = th.get("clock_offset_sec", CLOCK_OFFSET_SEC)
    drift_max = th.get("clock_drift_ppm", CLOCK_DRIFT_PPM)
    out = []

    # 1) 长未上报：只看「**工作态**且曾经上报过」的设备 ——
    #    · 工作态 = 启用 **或 走失**（2026-09-12 复核修正）：走失者的追踪器正是最该盯的一台，
    #      它掉线（没电/出范围）往往就是「找不到人」的原因；原来只算 STATUS_ACTIVE，
    #      一旦立案（设备转 lost）反而不再盯它，方向反了。
    #    · 停用/报废不报（已不是现行设备）。
    #    · 从未上报的新设备不报，否则一开机就一片红，反而盖住真问题。
    for rec in registry.devices.values():
        if rec.status not in (reg.STATUS_ACTIVE, reg.STATUS_LOST) or not rec.last_seen:
            continue
        gap = now - int(rec.last_seen)
        if gap > no_rep:
            # C 方案：沉默越久越严重（>30s warn → >300s crit）
            out.append(_alert("no_report", level_by_gap(gap, no_rep, no_rep_crit),
                              rec.sn, "alert_no_report", rec.last_seen,
                              sn=rec.sn, gap=gap))

    # 2) 走失案件：只看 open（已 found 的不算），分两支 ——
    #    ① 无人接手（A 方案）：「刚超时没人管」最严重 → 恒 crit（**不参与 C 分级**：定性的“没人管”）
    #    ② 已接手但太久没找到（B 方案）：「有人在办、拖太久」→ warn，再久升 crit（C 分级）
    #    为什么要分：只做 ① 会让「已接手」变成永不再报（案子被认领后搁置就完全静默）；
    #    只做 ② 又会让「没人管」淹没在“已接手”里。两条一起才既不恒亮、又不会静默。
    for c in cases.open_cases():
        if c.status != cs.CASE_OPEN:      # 常量在 cases 模块上，不在 CaseManager 实例上
            continue
        if c.handler:
            # B 方案（2026-09-12）：已接手 ≠ 永不再报 —— 从**接手时刻**起再超
            # case_handled_sec 仍未被发现，则再提醒一次（否则案子被认领后搁置就完全静默）。
            # 起点用 handled_at（缺则回落到 created，兼容老库/手工对象），
            # 级别 warn：有人在办、只是拖太久，不该盖过“没人接手”的 crit。
            since_h = int(c.handled_at or c.created)
            gap_h = now - since_h
            if gap_h > case_handled:
                # C 方案：接手后拖得越久越严重（>24h warn → >48h crit）
                out.append(_alert("case_handled_overtime",
                                  level_by_gap(gap_h, case_handled, case_handled_crit),
                                  c.case_id, "alert_case_handled_overtime", since_h,
                                  case_id=c.case_id, person_id=c.person_id,
                                  handler=c.handler, gap=gap_h))
            continue
        gap = now - int(c.created)
        if gap > case_ov:
            out.append(_alert("case_overtime", LEVEL_CRIT, c.case_id,
                              "alert_case_overtime", c.created,
                              case_id=c.case_id, person_id=c.person_id, gap=gap))

    # 3) 签名失败率：样本不足不告警（避免误报）
    recent = list(id_reports)[:win]          # deque 最新在前
    if len(recent) >= win:
        bad = [r for r in recent if not r.get("accepted")]
        if len(bad) / len(recent) > fail_ratio:
            # since 必须是 **epoch 秒**：前端算“持续多久”（`Date.now()/1000 - since`），
            # 且本函数末尾按 since 排序（与其它规则的 int 混排）。
            # 2026-09-12 修 bug：这里原来传 `rec["t"]`（"15:46:21" 这种展示用字符串）
            # → `_alert` 里 `int(since)` 抛 ValueError → 只要签名失败率告警一触发，
            # `/api/alerts` 整个 500（红点也拿不到其它告警）；且就算不抛也会算出 NaN。
            # 取 `ts_eff`（effective_ts 填的实际记录时刻），缺则回退 now。
            out.append(_alert("sig_fail_rate", LEVEL_CRIT, "recent",
                              "alert_sig_fail",
                              int(recent[0].get("ts_eff") or now),
                              n=len(bad), total=len(recent)))

    # 4) 降级上报（§8.3）：L2 = SE 不可用（仍更新定位）→ warn；L3 = 无可用密钥 → crit。
    #    deque 上限 20 条，本身就是“最近”的证据；窗口只用于把“很久没再降级”自动消掉。
    worst = {}
    for r in list(id_reports):
        if not r.get("accepted"):
            continue
        lv = r.get("level")
        if lv not in (2, 3):
            continue
        ts = int(r.get("ts_eff") or 0)
        if ts and now - ts > deg_sec:            # 超出窗口 → 不再视为当前问题
            continue
        sn = r.get("sn") or "-"
        if sn not in worst or lv > worst[sn][0]:  # 同一台设备取最高级（3 > 2）
            worst[sn] = (lv, ts or now)
    for sn, (lv, ts) in worst.items():
        out.append(_alert("id_degraded",
                          LEVEL_CRIT if lv == 3 else LEVEL_WARN, sn,
                          "alert_id_no_key" if lv == 3 else "alert_id_degraded",
                          ts, sn=sn, lv=lv))   # 数据字段叫 lv：第二个形参已是 level

    # 5) 设备时钟（§5.5 深化）：偏移/漂移超阈 → warn。
    #    只吃**估计可信**的样本（`ok`，即样本数够）；`since` 用越界起点（没有则用 now，
    #    至少别报一个 1970）。数据字段带 offset/drift/n，页面/审计能看到“偏了多少”。
    for sn, est in (clock or {}).items():
        if not est or not est.get("ok"):
            continue
        off = est.get("offset")
        drift = est.get("drift_ppm")
        bad_off = off is not None and abs(off) > off_max
        bad_drift = drift is not None and abs(drift) > drift_max
        if bad_off or bad_drift:
            out.append(_alert("id_clock", LEVEL_WARN, sn, "alert_id_clock",
                              est.get("breach_since") or now,
                              sn=sn, offset_sec=(round(off, 3) if off is not None else None),
                              drift_ppm=(round(drift, 1) if drift is not None else None),
                              n=est.get("n")))

    # 6) 能力声明不一致（2026-09-13）：设备**已签**声明「有 RTC」，但送来的 ts 不可用
    #    （ts=0/荒谬/非整数）—— 它本来该有时钟，这属于设备故障或被动了手脚，值得看一眼。
    #    反之（声明无 RTC + ts=0）是**正常**，不告警：那正是免电池终端的预期行为。
    #    以规则 4 同样的口径处理：**状态型问题**（固件不回 RTC/被降级），
    #    同一台只出一条（取最近一次），窗口只用于「最近没再犯 = 自动消警」。
    bad_cap = {}
    for rec in list(id_reports):                 # deque 最新在前，上限 20 条
        if not rec.get("accepted") or rec.get("cap_rtc") is not True:
            continue                             # 只吃**已签**的权威声明；未声明/无 RTC 不管
        if rec.get("ts_ok"):
            continue                             # 声明有 RTC 且 ts 可用 → 正常
        ts = int(rec.get("ts_eff") or 0)
        if ts and now - ts > cap_sec:            # 超出窗口 → 不再视为当前问题
            continue
        sn = rec.get("sn")
        if sn and sn not in bad_cap:             # 最新一条优先（deque 最新在前）
            bad_cap[sn] = (ts or now, rec.get("ts_src"), rec.get("ts"))
    for sn, (ts, src, ts_raw) in bad_cap.items():
        out.append(_alert("id_cap_mismatch", LEVEL_WARN, sn, "alert_id_cap_mismatch",
                          ts, sn=sn, ts_src=src, ts_raw=ts_raw))

    out.sort(key=lambda a: (0 if a["level"] == LEVEL_CRIT else 1, a["since"]))
    return out


def summary(alert_list):
    """计数，供前端徽标直接使用。"""
    return {"crit": sum(1 for a in alert_list if a["level"] == LEVEL_CRIT),
            "warn": sum(1 for a in alert_list if a["level"] == LEVEL_WARN),
            "total": len(alert_list)}
