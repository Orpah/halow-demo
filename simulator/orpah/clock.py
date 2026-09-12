#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clock.py — 设备时钟**偏移/漂移**估计（纯计算；不碰网络/存储/报文）。

**为什么需要**：协议 §5.5 允许设备用自己的时钟报 `ts`（无 RTC 的报 0 → 用服务器接收时刻）。
只要设备时钟**有偏差或漂移**，设备流里记的就是「设备认为的时刻」——回放时间轴、与外部证据
（通话记录、摄像头时间戳）对照时会**整体偏一个 offset**，而且这个 offset 还会随时间缓慢变
（晶振偏差/温漂）。本模块只用「设备 ts」与「服务器接收时刻 rx」这一对观测反推：

    offset(t) = device_ts − rx                （设备比服务器快多少秒）
    drift     = d(offset)/dt × 1e6  → ppm     （最小二乘斜率，量级与晶振偏差同级）

**只估计、不改数据**（重要）：记录里到底存设备时间还是服务器时间，是
`orpah_proto.effective_ts()` 的职责（§5.5）。本模块**绝不**替调用方改写 `ts` ——
“把设备时间校正到服务器时基”是一个需要先与用户对齐口径的动作（改的是取证时间线），
不在估计器里偷偷做。

设计取舍：
- 用**中位数**而不是均值取 offset：设备偶发一次跳变（重启后乱报）不该带动整体估计。
- **偏移与漂移用不同的尺度**（2026-09-13）：偏移是状态量、只看最近 `OFFSET_WINDOW` 条（反应快）；
  漂移是趋势量、要**长基线**（`DEFAULT_WINDOW` 条）且**只用“最近一次跳变之后”那一段**拟合。
  同一把尺子量两者，必然要么迟钝要么噪声大。
- **跳变不是漂移**（同日实测）：一次拨表/重启对时会让整窗斜率读成 ~2,000,000 ppm，而且
  只要跳变还在窗里就一直是胡说 → 按“两侧各 `JUMP_K` 条中位数之差”把序列切成段，
  **只用最新一段**拟合。用中位数比较是为了**免疫单点乱报**（重启后的垃圾 ts）：
  一条异常不动摇中位数，但真的持续变化会被认出来。
- **噪声里看不出趋势就不给数**：设备自报 `ts` 是**整数秒**（`int(time.time())`、真机 RTC 也是秒粒度）
  → 单条偏移在 1s 宽的格子里连续抖动（sd≈0.29s），而 `σ_slope ≈ σ_resid·√12/(span·√n)`。
  实测（`demo_clock.py`，1s 上报）：60s 基线 σ≈**4100ppm**、10min≈**110ppm**、1h≈**9ppm**
  —— 所以「200ppm 的晶振偏差」要 **≥1h 基线**才说得上话，短窗只能说“还看不出来”。
  门限用 `sigma_k` 倍标准差自适应，不写死一个 ppm 数。
- 拟合前把段内样本**按时间分箱取中位数**（`_bin_medians`）：让**单点乱报**（重启垃圾 ts，
  在普通最小二乘里能把整条斜率拖偏几万 ppm）进不了拟合；对 iid 量化噪声基本不损失分辨力。
- 样本不足（< `MIN_SAMPLES`）→ 各项返回 `None`、`ok=False` —— 宁可说“还不知道”，不编数。
"""
import collections

MIN_SAMPLES = 3         # 少于此样本数不给结论
DRIFT_MIN_SPAN = 600.0  # 拟合漂移至少要跨这么多秒（真正决定分辨力的是 σ 门，见 `drift_of`）
DRIFT_SIGMA_K = 3.0     # 斜率必须大于 K 倍标准差才算“趋势”（否则只是噪声）
DRIFT_BINS = 32         # 拟合前最多分成几个时间箱（取箱内中位数）
DRIFT_BIN_MIN = 8       # 每箱至少这么多条才值得分箱
DEFAULT_WINDOW = 4096   # 每台设备保留的样本数（环形；漂移要长基线：1s 上报≈68min、5s≈5.7h）
OFFSET_WINDOW = 8       # 偏移只看**最近**这么多条（见下）
JUMP_K = 3              # 跳变检测：两侧各取这么多条的中位数比较


def median_of(xs):
    """中位数（不修改入参）。"""
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def offset_of(samples):
    """`[(rx_ts, device_ts), …]` → 偏移中位数（秒，正=设备比服务器快）。

    返回 `(offset, spread)`：`spread` = 最大−最小（散布，秒），样本为空 → `(None, None)`。
    """
    ds = [float(d) - float(r) for r, d in samples or []]
    if not ds:
        return None, None
    return median_of(ds), max(ds) - min(ds)


def _fit(pts):
    """最小二乘拟合 → `(slope, intercept, t0, sigma_slope)`（斜率的**标准差**）。

    `pts` = 已按 t 排序的 `(t, offset)`。样本不足或不退化时 `sigma` 为 `None`。
    """
    n = len(pts)
    t0 = pts[0][0]
    xs = [t - t0 for t, _ in pts]
    mx = sum(xs) / n
    my = sum(o for _, o in pts) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None, None, t0, None
    sxy = sum((x - mx) * (o - my) for x, (_, o) in zip(xs, pts))
    slope = sxy / sxx
    inter = my - slope * mx
    if n <= 2:
        return slope, inter, t0, None       # 两个点必过 → 残差恒 0，标准差没有意义
    ss = sum((o - (inter + slope * x)) ** 2 for x, (_, o) in zip(xs, pts))
    return slope, inter, t0, (ss / (n - 2) / sxx) ** 0.5


def clean_segment(rows, jump_sec, k=JUMP_K):
    """从**最新**往回找最近一次“持续跳变”，返回其后的样本 → `(segment, jumped)`。

    跳变 = 窗口两侧各 `k` 条**中位数**之差超过 `jump_sec`（秒）。为什么不用“整窗极差”：
    整窗极差会把两种完全不同的东西混在一起 —— 真拨表（一跳）和**单点乱报**（重启后的垃圾 ts）；
    而两侧中位数对单点异常免疫（一条异常不动摇中位数），对持续变化敏感。
    `jump_sec=None` / 样本太少 → 不分段（`jumped=False`）。
    """
    if jump_sec is None or len(rows) < 2 * k:
        return rows, False
    offs = [d - r for r, d in rows]
    start, jumped = 0, False
    for i in range(k, len(offs) - k + 1):
        if abs(median_of(offs[i:i + k]) - median_of(offs[i - k:i])) > float(jump_sec):
            start, jumped = i, True                # 取**最后**一个边界 → 只用最新一段
    return rows[start:], jumped


def _bin_medians(pts, bins=DRIFT_BINS, per_bin=DRIFT_BIN_MIN):
    """按时间等宽分箱、每箱取偏移**中位数** → `[(t_mid, med_offset), …]`（≤ `bins` 个点）。

    为什么分箱：设备偶发一条**乱报**（重启后的垃圾 ts）在最小二乘里能把整条斜率拖偏；
    箱内中位数把它挡在外头（箱里 ≥8 条时一条异常不动摇中位数）。对 iid 量化噪声**不损失信息**
    —— 点少了但每点更准，`σ_slope` 基本不变。点数不够分组（< 3 箱）时原样返回。
    """
    if len(pts) < per_bin * 2:
        return pts
    k = min(int(bins), max(1, len(pts) // per_bin))
    if k < 3:
        return pts
    t0, t1 = pts[0][0], pts[-1][0]
    w = ((t1 - t0) / k) or 1.0
    buckets = [[] for _ in range(k)]
    for t, o in pts:
        buckets[min(int((t - t0) / w), k - 1)].append((t, o))
    out = [(sum(t for t, _ in b) / len(b), median_of([o for _, o in b]))
           for b in buckets if b]
    return out if len(out) >= 3 else pts


def drift_of(samples, jump_sec=None, sigma_k=DRIFT_SIGMA_K, min_span=DRIFT_MIN_SPAN,
             k=JUMP_K, bins=DRIFT_BINS):
    """最小二乘斜率 → `{"ppm", "why", "n", "span", "jumped"}`（ppm 相对**服务器**时基）。

    拟合用**箱中位数**（见 `_bin_medians`）；`n`/`span` 是参与拟合的**段**（跳变之后）的样本数与跨度。
    `why` 说明“为什么没给数”（给数时为 `None`）：
    - `min_span`：最近一段（跳变之后）短于 `min_span` 秒，或样本 < `MIN_SAMPLES`；
    - `noise`：|斜率| < `sigma_k` × 斜率标准差 —— 在噪声里看不出趋势，不编一个数出去。
    换句话说：**ppm 级漂移要长基线才分得出来**，短窗/刚拨完表只能说“还看不出来”。
    """
    rows = sorted((float(r), float(d)) for r, d in samples or [])
    seg, jumped = clean_segment(rows, jump_sec, k=k)
    n = len(seg)
    span = (seg[-1][0] - seg[0][0]) if n >= 2 else 0.0
    out = {"ppm": None, "why": None, "n": n, "span": round(span, 3), "jumped": jumped}
    if n < MIN_SAMPLES or span < float(min_span):
        out["why"] = "min_span"
        return out
    pts = _bin_medians([(t, o - t) for t, o in seg], bins=bins)
    slope, _inter, _t0, sigma = _fit(pts)
    if slope is None:
        out["why"] = "min_span"
        return out
    if sigma is not None and abs(slope) < float(sigma_k) * sigma:
        out["why"] = "noise"
        return out
    out["ppm"] = slope * 1e6
    return out


def drift_ppm_of(samples, jump_sec=None, sigma_k=DRIFT_SIGMA_K, min_span=DRIFT_MIN_SPAN):
    """只要 ppm 的薄封装：`None` = 还看不出/不可信（原因见 `drift_of` 的 `why`）。"""
    return drift_of(samples, jump_sec=jump_sec, sigma_k=sigma_k, min_span=min_span)["ppm"]


def estimate(samples, offset_window=OFFSET_WINDOW, jump_sec=None,
             min_span=DRIFT_MIN_SPAN, sigma_k=DRIFT_SIGMA_K):
    """样本 → 一份估计（`offset`/`drift_ppm`/`drift_why`/`n`/`span`/`spread`/`spread_win`/`ok`）。

    **两个尺度，别混**（2026-09-13 实测后改）：
    - **偏移**是“设备时钟**现在**差多少”——状态量，要**反应快**：只看最近
      `offset_window` 条（默认 8），换钟/拨表后几条就能反映；中位数仍能免疫**单点跳变**
      （8 条里坏 1 条不动摇，坏一半才翻面 → 恢复也需要几条，天然消抖）。
      实测教训：偏移也用整窗中位数时（1s 上报、64 条），现场拨偏 +120s 后**一分钟内**读数仍≈0。
    - **漂移**是趋势量，要**长基线**：用整窗里的**最新一段**（跳变之后），见 `drift_of`。

    `spread` = 算偏移那几条的散布（当前抖动）；`spread_win` = **整窗**极差（只是**指示器**：
    人/页面看“窗里有没有过大变化”，它不再是漂移的门 —— 门改成分段 + σ 显著度）；
    `drift_n`/`drift_span` = 真正参与拟合的那段样本数/跨度。
    `ok` = 样本数够（`MIN_SAMPLES`）；`n` = 整窗样本数，`n_off` = 算偏移用的条数。
    """
    rows = [(float(r), float(d)) for r, d in samples or []]
    tail = rows[-int(offset_window):] if offset_window else rows
    off, spread = offset_of(tail)
    offs = [d - r for r, d in rows]
    dr = drift_of(rows, jump_sec=jump_sec, min_span=min_span, sigma_k=sigma_k)
    span = (rows[-1][0] - rows[0][0]) if len(rows) >= 2 else 0.0
    return {
        "offset": off, "spread": spread,
        "spread_win": (max(offs) - min(offs)) if offs else None,
        "drift_ppm": dr["ppm"], "drift_why": dr["why"],
        "drift_n": dr["n"], "drift_span": dr["span"],
        "n": len(rows), "n_off": len(tail), "span": round(span, 3),
        "ok": len(rows) >= MIN_SAMPLES,
    }


class ClockTracker:
    """按 SN 维护「设备 ts vs 服务器 rx」样本窗，给出偏移/漂移估计。

    线程安全：`add()` 会同时被上报线程调用（演示里只有一个上报线程，但 `_id_tick` 等
    也在同一循环里）→ 用一把小锁保护 `_samples`/`_breach`，与 `ui_server` 其它计数
    “单写者不加锁”的取舍不同：这里**要跨线程读**（HTTP 线程调 `snapshot()`）。
    """

    def __init__(self, window=DEFAULT_WINDOW, offset_warn=None, min_span=DRIFT_MIN_SPAN):
        self._samples = {}          # sn -> deque[(rx, device)]
        self._breach = {}           # sn -> 首次越界时刻（rx），未越界则无键
        self._lock = __import__("threading").Lock()
        self.window = int(window)
        self.offset_warn = offset_warn      # 仅用于记录“越界从何时开始”（None = 不跟踪）
        self.min_span = float(min_span)     # 拟合漂移要求的最短基线

    def add(self, sn, device_ts, rx_ts):
        """记一条观测 → 返回该 sn 的最新估计（含 `breach_since`）。"""
        sn = str(sn)
        with self._lock:
            dq = self._samples.get(sn)
            if dq is None:
                dq = self._samples[sn] = collections.deque(maxlen=self.window)
            dq.append((float(rx_ts), float(device_ts)))
            rows = list(dq)
            est = estimate(rows, jump_sec=self.offset_warn, min_span=self.min_span)
            # 越界起点：只在“从没越界 → 越界”那一刻记一次（页面“持续 X”才有意义）
            if self.offset_warn is not None and est["ok"]:
                over = abs(est["offset"] or 0.0) > float(self.offset_warn)
                if over and sn not in self._breach:
                    self._breach[sn] = float(rx_ts)
                elif not over and sn in self._breach:
                    del self._breach[sn]
            est["breach_since"] = self._breach.get(sn)
        return est

    def get(self, sn):
        with self._lock:
            dq = self._samples.get(str(sn))
            if not dq:
                return None
            est = estimate(list(dq), jump_sec=self.offset_warn, min_span=self.min_span)
            est["breach_since"] = self._breach.get(str(sn))
            return est

    def snapshot(self):
        """`{sn: est}`（供 `/api/status` 与告警使用）。"""
        with self._lock:
            out = {}
            for sn, dq in self._samples.items():
                est = estimate(list(dq), jump_sec=self.offset_warn, min_span=self.min_span)
                est["breach_since"] = self._breach.get(sn)
                out[sn] = est
            return out
