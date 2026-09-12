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
- **偏移与漂移用不同的窗**（2026-09-13）：偏移是状态量、只看最近 `OFFSET_WINDOW` 条（反应快），
  漂移是趋势量、用整窗 `DEFAULT_WINDOW` 条（基线够长才有意义）。
  同一把尺子量两者，必然要么迟钝要么噪声大。
- **漂移只在能信的时候给**（同日实测后加）：窗内见过跳变（`spread_win > 告警偏移阈值`）→ 不是
  漂移（实测一次 +120s 拨表会读成 ~2,000,000 ppm）；斜率幅度不到 `DRIFT_SIGMA_K` 倍标准差
  → 是噪声不是趋势（实测整数秒设备时间下，1s 上报/60s 窗的斜率噪声就有 ~900 ppm）。
  换句话说：**ppm 级漂移要长基线才分得出来**，短窗只能说“还看不出来”。
- 样本不足（< `MIN_SAMPLES`）→ 各项返回 `None`、`ok=False` —— 宁可说“还不知道”，不编数。
"""
import collections

MIN_SAMPLES = 3         # 少于此样本数不给结论
DRIFT_MIN_SPAN = 30.0   # 估漂移至少要跨这么多秒（否则斜率是噪声）
DRIFT_SIGMA_K = 3.0     # 斜率必须大于 K 倍标准差才算“趋势”（否则只是噪声）
DEFAULT_WINDOW = 64     # 每台设备保留的样本数（环形；漂移用长基线）
OFFSET_WINDOW = 8       # 偏移只看**最近**这么多条（见下）


def offset_of(samples):
    """`[(rx_ts, device_ts), …]` → 偏移中位数（秒，正=设备比服务器快）。

    返回 `(offset, spread)`：`spread` = 最大−最小（散布，秒），样本为空 → `(None, None)`。
    """
    ds = [float(d) - float(r) for r, d in samples or []]
    if not ds:
        return None, None
    ds.sort()
    m = len(ds) // 2
    med = ds[m] if len(ds) % 2 else (ds[m - 1] + ds[m]) / 2.0
    return med, ds[-1] - ds[0]


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


def drift_ppm_of(samples, step_spread=None, sigma_k=DRIFT_SIGMA_K):
    """最小二乘斜率（秒/秒）× 1e6 → ppm（相对**服务器**时基，正=设备走得快）。

    只在**能信**的时候给数，否则 `None`（宁可说“还看不出来”，不编一个数出去）：
    - 样本 < 3 条或跨度 < `DRIFT_MIN_SPAN` → 基线不够；
    - `step_spread` 非空且整窗偏移**极差** > 它 → 窗内见过**跳变**（拨表/重启对时），
      那不是漂移（实测：一次 +120s 的跳变会让斜率读成 ~2,000,000 ppm）。参数名带 spread 是因为
      它比的是**极差**而不是“跳变幅度”，调用方传的是自己认为“还在正常抖动范围”的秒数
      （`ClockTracker` 传的就是偏移告警阈值）；
    - |斜率| < `sigma_k` × 斜率标准差 → 在噪声里看不出趋势（实测：整数秒设备时间
      的量化噪声，1s 上报、60s 窗下斜率噪声就有 ~900 ppm，比晶振 ppm 大得多）。
    """
    pts = sorted((float(r), float(d) - float(r)) for r, d in samples or [])
    if len(pts) < MIN_SAMPLES:
        return None
    span = pts[-1][0] - pts[0][0]
    if span < DRIFT_MIN_SPAN:
        return None
    offs = [o for _, o in pts]
    if step_spread is not None and (max(offs) - min(offs)) > float(step_spread):
        return None
    slope, _inter, _t0, sigma = _fit(pts)
    if slope is None:
        return None
    if sigma is not None and abs(slope) < float(sigma_k) * sigma:
        return None
    return slope * 1e6


def estimate(samples, offset_window=OFFSET_WINDOW, step_spread=None):
    """样本 → 一份估计（`offset`/`drift_ppm`/`n`/`span`/`spread`/`spread_win`/`ok`）。

    **两个时间尺度，别混**（2026-09-13 实测后改）：
    - **偏移**是“设备时钟**现在**差多少”——是个状态量，要**反应快**：只看最近
      `offset_window` 条（默认 8），换钟/拨表后几条就能反映；中位数仍能免疫**单点跳变**
      （8 条里坏 1 条不动摇，坏一半才翻面 → 恢复也需要几条，天然消抖）。
    - **漂移**是趋势量，要**长基线**：用整窗（`DEFAULT_WINDOW=64`），且要求跨 `DRIFT_MIN_SPAN`、
      窗内无跳变、斜率显著（见 `drift_ppm_of`）。
    实测教训：一开始偏移也用整窗中位数（1s 上报、64 条）→ 现场拨偏 +120s 后**一分钟内**
    读数仍≈0（旧样本把中位数压着），演示看着像坏的、告警也不亮。

    `spread` = 算偏移那几条的散布（当前抖动）；`spread_win` = **整窗**散布（跳变指标）。
    `ok` = 样本数够（`MIN_SAMPLES`）；`n`/`span` = 整窗样本数与跨度，`n_off` = 算偏移用的条数。
    """
    rows = [(float(r), float(d)) for r, d in samples or []]
    tail = rows[-int(offset_window):] if offset_window else rows
    off, spread = offset_of(tail)
    offs = [d - r for r, d in rows]
    span = (rows[-1][0] - rows[0][0]) if len(rows) >= 2 else 0.0
    return {
        "offset": off, "spread": spread,
        "spread_win": (max(offs) - min(offs)) if offs else None,
        "drift_ppm": drift_ppm_of(rows, step_spread=step_spread),
        "n": len(rows), "n_off": len(tail), "span": round(span, 3),
        "ok": len(rows) >= MIN_SAMPLES,
    }


class ClockTracker:
    """按 SN 维护「设备 ts vs 服务器 rx」样本窗，给出偏移/漂移估计。

    线程安全：`add()` 会同时被上报线程调用（演示里只有一个上报线程，但 `_id_tick` 等
    也在同一循环里）→ 用一把小锁保护 `_samples`/`_breach`，与 `ui_server` 其它计数
    “单写者不加锁”的取舍不同：这里**要跨线程读**（HTTP 线程调 `snapshot()`）。
    """

    def __init__(self, window=DEFAULT_WINDOW, offset_warn=None):
        self._samples = {}          # sn -> deque[(rx, device)]
        self._breach = {}           # sn -> 首次越界时刻（rx），未越界则无键
        self._lock = __import__("threading").Lock()
        self.window = int(window)
        self.offset_warn = offset_warn      # 仅用于记录“越界从何时开始”（None = 不跟踪）

    def add(self, sn, device_ts, rx_ts):
        """记一条观测 → 返回该 sn 的最新估计（含 `breach_since`）。"""
        sn = str(sn)
        with self._lock:
            dq = self._samples.get(sn)
            if dq is None:
                dq = self._samples[sn] = collections.deque(maxlen=self.window)
            dq.append((float(rx_ts), float(device_ts)))
            rows = list(dq)
            est = estimate(rows, step_spread=self.offset_warn)
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
            est = estimate(list(dq), step_spread=self.offset_warn)
            est["breach_since"] = self._breach.get(str(sn))
            return est

    def snapshot(self):
        """`{sn: est}`（供 `/api/status` 与告警使用）。"""
        with self._lock:
            out = {}
            for sn, dq in self._samples.items():
                est = estimate(list(dq), step_spread=self.offset_warn)
                est["breach_since"] = self._breach.get(sn)
                out[sn] = est
            return out
