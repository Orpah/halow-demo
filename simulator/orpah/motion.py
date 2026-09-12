#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motion.py — 演示用「移动的人」运动模型 + RSSI 路径损耗换算（2026-09-12）。

**为什么需要它**：原来演示数据是恒定 RSSI（每个 report 都是 `--rssi -55`），
回放里看不见移动。而"移动的人"要能定位出**连续轨迹**，物理上必须有
**同一时刻的 ≥2 个观察者** —— 单台路由器只能给出距离环；"悬停点 + 时间窗中位数"
模型（见 `stations.py`）的前提更是**目标静止**（不同时间测的点拼不成同一时刻的位置）。

**本模块提供"多路由器同时观测"的样例数据**：让被保护对象沿一条闭合路线匀速走动，
每个上报周期对每台路由器（一台路由器 = 一个站位，坐标即站位坐标）按
    rssi = A − 10·n·log10(d)      （d = 人到该路由器的距离，米）
算出一条测量，由 `ui_server` 落库到 `root.orpah.routers.<sid>.<sn>`。

**确定性**：位置只由时刻决定（固定 epoch + 匀速 + 闭合折线），**不用随机数** ——
同一份数据的回放可复现，也便于将来在前端按同一公式画"真值轨迹"做对照。

只依赖标准库；纯函数式，便于单测（见 `test_motion.py`）。
"""
import hashlib
import math

# 演示路由（站位）坐标：与 ui_server._seed_stations 的种子一致（米，局部坐标）
#   三台路由器围成一个三角，人到各台的距离在 5~70 m 之间，RSSI 落在 -55~-88 dBm。
WALK_EPOCH_MS = 1767225600000          # 2026-01-01T00:00:00Z：位置相位基准（固定 → 可复现）
SPEED_MPS = 1.2                        # 步行速度（m/s）
RSSI_A = -40.0                         # 1 m 处参考强度（**唯一源**：页面从 /api/config 取）
RSSI_N = 2.5                           # 路径损耗指数（**唯一源**：页面从 /api/config 取）
MIN_DIST_M = 1.0                       # 距离下限（防 log10(0)）
RSSI_MIN, RSSI_MAX = -95, -30          # 实测可达范围（钳制）
# 测量噪声幅度（±dBm，矩形分布）。**为什么要有**：真实 RSSI 每次测量都抰动（多径/干扰），
# 没有噪声的演示有两个害处：① 定位解精确复原真值，看起来“好得不像话”；
# ② 误差椭圆/搜索半径、时序平滑（滑动平均/卡尔曼）全部失去意义 ——
# 无噪声时平滑只会引入滞后。用 **(sid, t) 哈希** 生成伪随机，不用随机库 → 仍然可复现。
NOISE_DB = 2.0

# 真值轨迹采样（`/api/truth` 用）：单次点数上限与步长下限。
# 网格采样只用于**画真值路线**；算误差 CDF 要用 `truth_at()`（按帧时刻精确取点）——
# 因为页面在网格点之间做线性插值，而插值误差随步长**平方**增长：
# 实测步长 250ms（v=1.2m/s、路线含直角拐角）插值误差最大 **2.9cm**；10.8s（12h 窗受上限所迫）
# 则会涨到**米级** —— 那就把真值本身搞成大误差源了。
TRUTH_MAX_POINTS = 4000
TRUTH_MIN_STEP_MS = 250
TRUTH_MAX_STEP_MS = 60_000
TRUTH_MAX_TIMES = 5000      # `truth_at` 单次请求的时刻数上限（页面会先抽稀）

# 闭合路线（局部坐标，米）：绕三台路由器走一圈，含几处折返，看起来像人在找路
WAYPOINTS = [
    (0.0, 0.0), (12.0, 6.0), (24.0, 10.0), (26.0, 20.0), (14.0, 25.0),
    (0.0, 16.0), (-12.0, 8.0), (-14.0, -6.0), (-4.0, -16.0), (10.0, -20.0),
    (22.0, -12.0), (10.0, -4.0),
]


def calibration():
    """标定参数快照（→ `GET /api/config`）—— **A/n/噪声的唯一源**。

    为什么要有这个函数（2026-09-12）：A/n/噪声原本在**四个地方各写一份**：
    本模块（模拟器发 RSSI 用）+ `track.html` / `rssi.html` / `replay.html`
    （反算距离用，输入框默认值）。靠注释“与页面默认一致”互相提醒 —— 改一处不改另一处时，
    模拟器发的 RSSI 与页面反算的距离就用不同的模型，**而且不会报错**（位置/椭圆半径静默偏离）。
    现在以本模块为唯一源，页面开页时取 `/api/config` 把默认值填进输入框（仍可手改）。

    页面的 HTML `value=` 只当**离线兜底**，`test_motion.py` 有一条“单源守卫”
    断言兜底值与这里的常量一致（否则兜底会骗人）。
    """
    return {
        "path_loss": {"A": RSSI_A, "n": RSSI_N},
        "noise_db": NOISE_DB,
        "rssi_range": {"min": RSSI_MIN, "max": RSSI_MAX},
        "walk": {"speed_mps": SPEED_MPS, "epoch_ms": WALK_EPOCH_MS},
    }


def clamp_rssi(v):
    """dBm → 钳到实测可达范围并取整（**唯一**的钳位实现：正向换算与加噪之后都走它）。

    为什么要单独一个函数（2026-09-12 审查修复）：`path_loss()` 自己钳了，但 `rssi_to()`
    与 `nearest()` 是**先钳再加噪声** → 站位恰在量程边界时（远端站已到底 -95、A 调大时近端
    已到顶 -30）噪声会把结果推出 `[RSSI_MIN, RSSI_MAX]`。实测：400 m 外的站位，
    600 秒 / 1200 条测量里有 **438 条越界**（最低 -97 dBm），而 `/api/config` 把 `rssi_range`
    当作量程对外声明 —— 声明与数据不符。噪声是**测量**误差，不会把收不到的信号变出来，
    所以钳位只能在加噪之后。
    """
    return int(round(max(RSSI_MIN, min(RSSI_MAX, float(v)))))


def path_loss(dist_m, A=RSSI_A, n=RSSI_N):
    """距离(m) → RSSI(dBm)（对数距离路径损耗模型，钳到实测可达范围；返回整数 dBm）。"""
    d = max(float(dist_m), MIN_DIST_M)
    r = float(A) - 10.0 * float(n) * math.log10(d)
    return clamp_rssi(r)


def dist(ax, ay, bx, by):
    return math.hypot(float(ax) - float(bx), float(ay) - float(by))


def truth_samples(walk, from_ms, to_ms, step=None, cap=TRUTH_MAX_POINTS):
    """真值轨迹采样 → `(points, step_ms)`：`walk.pos(t)` 在 `[from, to]` 上等间隔取点。

    `points` = `[{t, x, y}]`（升序，含区间两端附近；坐标取 3 位小数 = 毫米级，只为省载荷）。

    **口径（写给后来的自己）**：地面真值**只有演示环境有** —— `Walk` 是模拟器里的行走模型，
    真机部署根本没有真值。所以这函数只服务「演示里量定位误差（CDF）」，**不是产品指标**；
    真机的定位质量只能看**不需要真值**的那套（残差 RMS / GDOP / 95% 椭圆 / 搜索半径）。

    `step` 缺省按窗口自适应（目标 ≤ `cap` 点，不小于 `TRUTH_MIN_STEP_MS`）。
    容错：`from > to` 自动交换（调用方传反不报错）。
    """
    from_ms, to_ms = int(from_ms), int(to_ms)
    if to_ms < from_ms:
        from_ms, to_ms = to_ms, from_ms
    span = to_ms - from_ms
    if step:
        st = min(max(int(step), TRUTH_MIN_STEP_MS), TRUTH_MAX_STEP_MS)
    else:
        st = min(max(span // max(1, int(cap)), TRUTH_MIN_STEP_MS), TRUTH_MAX_STEP_MS)
    pts, t = [], from_ms
    while t <= to_ms and len(pts) <= int(cap):
        x, y = walk.pos(t)
        pts.append({"t": t, "x": round(float(x), 3), "y": round(float(y), 3)})
        t += st
    return pts, st


def truth_at(walk, times, cap=TRUTH_MAX_TIMES):
    """指定时刻的真值位置 → `[{t, x, y}]`（升序、去重、上限 `cap` 个时刻）。

    为什么要有它（与 `truth_samples` 的分工）：网格采样后页面要**插值**才能拿到任意时刻的真值，
    而插值误差随步长平方增长（实测 250ms → 2.9cm；12h 窗被点数上限逼到 10.8s/点 → 米级）。
    算「定位误差 CDF」时真值本身不能成为误差源，所以按**帧时刻**直接精确取点。
    口径同 `truth_samples`：真值只有演示环境有，不是产品指标。
    """
    uniq = sorted({int(t) for t in (times or [])})[:max(1, int(cap))]
    out = []
    for t in uniq:
        x, y = walk.pos(t)
        out.append({"t": t, "x": round(float(x), 3), "y": round(float(y), 3)})
    return out


def noise_db(sid, t_ms, amp=NOISE_DB):
    """测量噪声（±amp dBm，矩形分布，由 (sid, t) 确定 → 同一条记录永远得到同一个值）。

    真实 RSSI 抰动近似高斯，此处用**矩形分布**简化（避免引入 random/种子管理）；
    目的是让「定位质量 / 误差椭圆 / 时序平滑」有噪声可讲，不是要精确模仿信道。
    想回到无噪演示：`amp=0` 或 `Walk(noise=0)`。
    """
    amp = float(amp or 0.0)
    if amp <= 0:
        return 0.0
    h = hashlib.sha256(f"{sid}|{int(t_ms)}".encode("utf-8")).digest()
    u = int.from_bytes(h[:4], "big") / 0xFFFFFFFF      # [0, 1)
    return (u * 2.0 - 1.0) * amp


class Walk:
    """匀速走闭合折线：pos(t_ms) → (x, y)（确定性，可复现）。

    `noise` = 测量噪声幅度（±dBm，默认 NOISE_DB；0 = 无噪，见 noise_db 的说明）。
    """

    def __init__(self, points=None, speed=SPEED_MPS, epoch_ms=WALK_EPOCH_MS,
                 noise=NOISE_DB):
        pts = list(points or WAYPOINTS)
        if len(pts) < 2:
            raise ValueError("路线至少需要 2 个点")
        self.noise = float(noise or 0.0)
        self.points = [(float(x), float(y)) for x, y in pts]
        self.speed = float(speed or SPEED_MPS)
        self.epoch_ms = int(epoch_ms)
        # 预计算各段长度与累计长度（闭合：最后一段回到起点）
        segs, acc, total = [], [0.0], 0.0
        loop = self.points + [self.points[0]]
        for i in range(len(self.points)):
            (x0, y0), (x1, y1) = loop[i], loop[i + 1]
            ln = dist(x0, y0, x1, y1)
            segs.append((x0, y0, x1, y1, ln))
            total += ln
            acc.append(total)
        self.segs, self.cum, self.total = segs, acc, total

    @property
    def loop_sec(self):
        """绕一圈的时长（秒）。"""
        return self.total / self.speed if self.speed else 0.0

    def pos(self, t_ms):
        """t_ms（epoch 毫秒）→ (x, y)：沿路线走过的弧长取模。"""
        if self.total <= 0:
            return self.points[0]
        s = ((int(t_ms) - self.epoch_ms) / 1000.0 * self.speed) % self.total
        for i, (x0, y0, x1, y1, ln) in enumerate(self.segs):
            if ln <= 0:
                continue
            if s <= self.cum[i + 1] or i == len(self.segs) - 1:
                k = (s - self.cum[i]) / ln
                k = max(0.0, min(1.0, k))
                return (x0 + (x1 - x0) * k, y0 + (y1 - y0) * k)
        return self.points[0]

    def rssi_to(self, t_ms, sx, sy, A=RSSI_A, n=RSSI_N, sid=None):
        """t_ms 时刻，位于 (sx, sy) 的**路由器**测到的人 → RSSI(dBm)（含测量噪声）。

        sid = 噪声标识（每台路由器各自的噪声序列；缺省用坐标代替）。
        """
        x, y = self.pos(t_ms)
        v = path_loss(dist(x, y, sx, sy), A, n)
        return clamp_rssi(v + noise_db(sid if sid is not None else f"{sx},{sy}",
                                       t_ms, self.noise))

    def nearest(self, t_ms, stations):
        """t_ms 时刻离人最近的那台路由器 → (sid, rssi)；stations = [(sid, x, y)] 或 Station 列表。

        用于设备自己的 REPORT：报文里的 rssi 是**设备到其当前 AP** 的链路强度，
        取最近一台的测量值（人走近哪台，链路就强）。
        """
        x, y = self.pos(t_ms)
        best, best_d = None, None
        for s in stations or []:
            sid = getattr(s, "sid", None) if not isinstance(s, (tuple, list)) else s[0]
            sx = getattr(s, "x", None) if not isinstance(s, (tuple, list)) else s[1]
            sy = getattr(s, "y", None) if not isinstance(s, (tuple, list)) else s[2]
            if sx is None or sy is None:
                continue
            d = dist(x, y, sx, sy)
            if best_d is None or d < best_d:
                best, best_d = (sid, sx, sy), d
        if best is None:
            return None, None
        return best[0], clamp_rssi(path_loss(best_d)
                                   + noise_db(best[0], t_ms, self.noise))


_default = None


def default():
    """进程内共享的默认路线（ui_server 用；避免每处都 new 一个）。"""
    global _default
    if _default is None:
        _default = Walk()
    return _default
