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
import math

# 演示路由（站位）坐标：与 ui_server._seed_stations 的种子一致（米，局部坐标）
#   三台路由器围成一个三角，人到各台的距离在 5~70 m 之间，RSSI 落在 -55~-88 dBm。
WALK_EPOCH_MS = 1767225600000          # 2026-01-01T00:00:00Z：位置相位基准（固定 → 可复现）
SPEED_MPS = 1.2                        # 步行速度（m/s）
RSSI_A = -40.0                         # 1 m 处参考强度（与页面默认 A 一致）
RSSI_N = 2.5                           # 路径损耗指数（与页面默认 n 一致）
MIN_DIST_M = 1.0                       # 距离下限（防 log10(0)）
RSSI_MIN, RSSI_MAX = -95, -30          # 实测可达范围（钳制）

# 闭合路线（局部坐标，米）：绕三台路由器走一圈，含几处折返，看起来像人在找路
WAYPOINTS = [
    (0.0, 0.0), (12.0, 6.0), (24.0, 10.0), (26.0, 20.0), (14.0, 25.0),
    (0.0, 16.0), (-12.0, 8.0), (-14.0, -6.0), (-4.0, -16.0), (10.0, -20.0),
    (22.0, -12.0), (10.0, -4.0),
]


def path_loss(dist_m, A=RSSI_A, n=RSSI_N):
    """距离(m) → RSSI(dBm)（对数距离路径损耗模型，钳到实测可达范围；返回整数 dBm）。"""
    d = max(float(dist_m), MIN_DIST_M)
    r = float(A) - 10.0 * float(n) * math.log10(d)
    r = max(RSSI_MIN, min(RSSI_MAX, r))
    return int(round(r))


def dist(ax, ay, bx, by):
    return math.hypot(float(ax) - float(bx), float(ay) - float(by))


class Walk:
    """匀速走闭合折线：pos(t_ms) → (x, y)（确定性，可复现）。"""

    def __init__(self, points=None, speed=SPEED_MPS, epoch_ms=WALK_EPOCH_MS):
        pts = list(points or WAYPOINTS)
        if len(pts) < 2:
            raise ValueError("路线至少需要 2 个点")
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

    def rssi_to(self, t_ms, sx, sy, A=RSSI_A, n=RSSI_N):
        """t_ms 时刻，位于 (sx, sy) 的**路由器**测到的人 → RSSI(dBm)。"""
        x, y = self.pos(t_ms)
        return path_loss(dist(x, y, sx, sy), A, n)

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
        return best[0], path_loss(best_d)


_default = None


def default():
    """进程内共享的默认路线（ui_server 用；避免每处都 new 一个）。"""
    global _default
    if _default is None:
        _default = Walk()
    return _default
