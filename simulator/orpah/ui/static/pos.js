/* pos.js — ORPAH 定位内核（单一实现，供 track.html 与 replay.html 共用）

为什么单独一个文件：页面里各留一份定位算法必然会漂移（本仓库已有"算法单一源"的约定，
见 damm32.py/luhn32.py/mod97.py 与 tools/ui 的 AT 命令库）。这里只放**纯函数**：
不碰 DOM、不读输入框、不依赖页面状态（三边定位的二义选择改为显式传入 "上一个估计点"）。

包含：
- RSSI ↔ 距离换算（对数距离路径损耗模型）
- 三边定位（≥3 点为线性最小二乘；2 点取两圆交点中离上次估计更近的那个）
- 加权最小二乘（WLS，高斯-牛顿 + 步长折半线搜索）
- 95% 置信椭圆 / 搜索半径（由协方差特征值给）
- 定位质量：残差 RMS、GDOP、站位布局条件数、分级
- 观测归集：在某一时刻 t 各站位能看到什么（时间窗 + 不看未来）

全局函数（classic script，页面直接按名字调用，与重构前一致）。
*/
"use strict";

/* ---------------- RSSI ↔ 距离（对数距离模型） ---------------- */
function rssiFromDist(d, A, n) { return A - 10 * n * Math.log10(Math.max(d, 0.01)); }
function distFromRssi(rssi, A, n) { return Math.pow(10, (A - rssi) / (10 * n)); }

/* ---------------- 三边定位（线性最小二乘） ----------------
   2 个站位时两圆有两个交点（二义）：传 last（上一次估计/真值）取更近的那个，
   不传则取第一个交点（等价于以原点为参考）。 */
function trilaterate(anchors, dists, last) {
  const n = anchors.length;
  if (n === 1) return null;
  if (n === 2) {
    const [a, b] = anchors;
    const d = Math.hypot(b.x - a.x, b.y - a.y);
    if (d > dists[0] + dists[1] || d < Math.abs(dists[0] - dists[1]) || d < 1e-9) return null;
    const aa = (dists[0] * dists[0] - dists[1] * dists[1] + d * d) / (2 * d);
    const h2 = dists[0] * dists[0] - aa * aa;
    if (h2 < 0) return null;
    const h = Math.sqrt(h2);
    const x2 = a.x + aa * (b.x - a.x) / d, y2 = a.y + aa * (b.y - a.y) / d;
    // 二义：取靠近当前估计的那个交点
    const p1 = { x: x2 + h * (b.y - a.y) / d, y: y2 - h * (b.x - a.x) / d };
    const p2 = { x: x2 - h * (b.y - a.y) / d, y: y2 + h * (b.x - a.x) / d };
    const prev = last || { x: 0, y: 0 };
    return (Math.hypot(p1.x - prev.x, p1.y - prev.y)
            <= Math.hypot(p2.x - prev.x, p2.y - prev.y)) ? p1 : p2;
  }
  const [x0, y0] = [anchors[0].x, anchors[0].y];
  const d0 = dists[0];
  let a00 = 0, a01 = 0, a11 = 0, b0 = 0, b1 = 0;
  for (let j = 1; j < n; j++) {
    const [xj, yj] = [anchors[j].x, anchors[j].y];
    const dj = dists[j];
    const ax = 2 * (xj - x0), ay = 2 * (yj - y0);
    const bb = d0 * d0 - dj * dj - (x0 * x0 + y0 * y0) + (xj * xj + yj * yj);
    a00 += ax * ax; a01 += ax * ay; a11 += ay * ay;
    b0 += ax * bb; b1 += ay * bb;
  }
  const det = a00 * a11 - a01 * a01;
  if (Math.abs(det) < 1e-12) return null;
  return { x: (a11 * b0 - a01 * b1) / det, y: (a00 * b1 - a01 * b0) / det };
}

/* ---------------- 加权最小二乘（WLS）+ 误差椭圆 ----------------
   为什么必须加权：RSSI 测距误差随距离增长（路径损耗模型下 σ_d ≈ d·ln10·σ_rssi/(10n)），
   远站位的距离本就不可信；等权最小二乘会被远端噪声拽偏。
   权重 w_i = 1/σ_i²，σ_i = max(SIG_FLOOR, SIG_REL·d_i)（相对误差模型，简单且可解释）。
   协方差 C = (JᵀWJ)⁻¹ · max(1, σ̂0²)，J 行 = 估计点到站位的单位向量（与 GDOP 同一个 J），
   σ̂0² = Σw·r²/(n−2)（后验单位权方差）→ 由 C 的特征值给 95% 置信椭圆（χ²(2,0.95)=5.991）。 */
const SIG_REL = 0.25;                 // 测距相对误差（RSSI 典型 20~30%）
const SIG_FLOOR = 1.0;                // 距离下限（米）：防 d→0 时权重爆炸
const ELLIPSE_K = Math.sqrt(5.991);   // χ²(2, 0.95) → 2.4477

/* 观测的距离噪声 σ（与 wlsLocate 同一模型） */
function sigOf(o) {
  return Math.max(SIG_FLOOR, SIG_REL * Math.max(o.dist || 0, 0));
}

function wlsLocate(obs, init) {
  const n = obs.length;
  if (n < 2) return null;
  /* init 请务必传**线性解**（页面即这么用）。只有 2 个站位时若 init 给质心，
     质心正好落在两站连线上 → 两个单位向量共线 → JᵀWJ 奇异 → 直接返回 singular。
     线性解在两圆交点处（离连线有距离），故无此问题。 */
  const sig = obs.map(o => Math.max(SIG_FLOOR, SIG_REL * Math.max(o.dist, 0)));
  const w = sig.map(s => 1 / (s * s));
  const cost = (q) => {
    let s = 0;
    for (let i = 0; i < n; i++) {
      const o = obs[i];
      const r = Math.hypot(q.x - o.s.x, q.y - o.s.y) - o.dist;
      s += w[i] * r * r;
    }
    return s;
  };
  let p = init ? { x: init.x, y: init.y } : {
    x: obs.reduce((s, o) => s + o.s.x, 0) / n,
    y: obs.reduce((s, o) => s + o.s.y, 0) / n,
  };
  let c0 = cost(p);
  let iters = 0, converged = false;
  /* 高斯-牛顿 + **步长折半线搜索**：测量不自洽（距离环不相交）时裸 GN 会来回振荡、
     打满迭代还没有意义地"给出"一个点。线搜索保证代价单调下降，到不动即停。 */
  for (let it = 0; it < 40; it++) {
    let a00 = 0, a01 = 0, a11 = 0, g0 = 0, g1 = 0;
    for (let i = 0; i < n; i++) {
      const o = obs[i];
      const dx = p.x - o.s.x, dy = p.y - o.s.y;
      const r = Math.hypot(dx, dy) || 1e-6;
      const ux = dx / r, uy = dy / r;        // ∂残差/∂p（单位向量）
      const res = r - o.dist;                // 预测 − 测量
      const wi = w[i];
      a00 += wi * ux * ux; a01 += wi * ux * uy; a11 += wi * uy * uy;
      g0 += wi * ux * res; g1 += wi * uy * res;
    }
    const detN = a00 * a11 - a01 * a01;
    if (Math.abs(detN) < 1e-12) {
      return { ok: false, reason: "singular", iters, x: p.x, y: p.y,
               obsCount: n, rms: Math.sqrt(c0 / n), sig };
    }
    const d0 = -(a11 * g0 - a01 * g1) / detN;    // 解 (JᵀWJ)δ = −JᵀWr
    const d1 = -(-a01 * g0 + a00 * g1) / detN;
    let step = 1, moved = false;
    for (let k = 0; k < 8; k++) {                // 折半直到代价下降
      const q = { x: p.x + d0 * step, y: p.y + d1 * step };
      const c1 = cost(q);
      if (c1 < c0) { p = q; c0 = c1; moved = true; break; }
      step /= 2;
    }
    iters = it + 1;
    if (!moved) { converged = true; break; }     // 任何步长都不再下降 → 已到最小点
    if (Math.hypot(d0 * step, d1 * step) < 1e-3) { converged = true; break; }
  }
  /* 在最终解处再算一次：残差 / 权重 / JᵀWJ（协方差要用最终的 J） */
  let a00 = 0, a01 = 0, a11 = 0, sum2 = 0, sum2w = 0;
  const per = {};
  for (let i = 0; i < n; i++) {
    const o = obs[i];
    const dx = p.x - o.s.x, dy = p.y - o.s.y;
    const r = Math.hypot(dx, dy) || 1e-6;
    const ux = dx / r, uy = dy / r;
    const res = r - o.dist;
    per[o.s.sid] = res;
    sum2 += res * res; sum2w += w[i] * res * res;
    a00 += w[i] * ux * ux; a01 += w[i] * ux * uy; a11 += w[i] * uy * uy;
  }
  const det = a00 * a11 - a01 * a01;
  if (Math.abs(det) < 1e-12) {
    return { ok: false, reason: "singular", iters, x: p.x, y: p.y,
             obsCount: n, rms: Math.sqrt(sum2 / n), sig, per };
  }
  const dof = Math.max(1, n - 2);
  const s0 = Math.sqrt(sum2w / dof);              // 后验单位权标准差（≈1 = 残差与先验噪声相符）
  const c00 = a11 / det, c01 = -a01 / det, c11 = a00 / det;
  /* 协方差用**先验**噪声模型 (JᵀWJ)⁻¹（已在 w 里含 σ_i），只有后验明显更差时才放大：
     为什么不能只用 σ0²(JᵀWJ)⁻¹ —— 恒定 RSSI 这类「自洽但错误」的输入残差≈0，
     σ0→0 会给出「零不确定度」的假自信（正是本页一直要防的那类坑）。
     s0 > 1 说明残差比假定的测距噪声还大（有未建模误差）→ 放大椭圆。*/
  const inflate = Math.max(1, s0 * s0);
  const cov = { a: inflate * c00, b: inflate * c01, c: inflate * c11 };
  return { ok: true, x: p.x, y: p.y, iters, converged, obsCount: n, sig, w,
           per, rms: Math.sqrt(sum2 / n), sigma0: s0, inflate, cov,
           ellipse: ellipseOf(cov) };
}

/* 由协方差给 95% 置信椭圆：特征值 → 半轴长，特征向量方位 → 倾角。
   degenerate = 半短轴 ≈0（几何退化，如站位近共线）→ 椭圆退化成一条线段，
   此时「半径」仍可报（沿最长轴），但面积/形状不可信。 */
function ellipseOf(cov) {
  if (!cov) return null;
  const tr = cov.a + cov.c, det = cov.a * cov.c - cov.b * cov.b;
  const disc = Math.max(tr * tr / 4 - det, 0);
  const l1 = tr / 2 + Math.sqrt(disc);
  const l2 = tr / 2 - Math.sqrt(disc);
  if (!(l1 > 0) || !isFinite(l1)) return null;
  const theta = 0.5 * Math.atan2(2 * cov.b, cov.a - cov.c);   // 数学坐标系（y 向上）
  const semiMajor = ELLIPSE_K * Math.sqrt(l1);
  const semiMinor = l2 > 0 ? ELLIPSE_K * Math.sqrt(l2) : 0;
  const deg = d => (d * 180 / Math.PI + 360) % 360;
  return {
    l1, l2, theta, thetaDeg: deg(theta),
    semiMajor, semiMinor,
    radius: semiMajor,                       // 保守覆盖半径（沿最长轴，95%）
    area: Math.PI * semiMajor * semiMinor,
    degenerate: semiMinor < 0.05 * semiMajor, // 半短轴相对半长轴太小
  };
}

/* 椭圆 → 局部坐标点列（画布/地图都能用；n 段足够平滑） */
function ellipsePoints(ell, cx0, cy0, n = 48) {
  if (!ell) return [];
  const ct = Math.cos(ell.theta), st = Math.sin(ell.theta);
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = 2 * Math.PI * i / n;
    const u = ell.semiMajor * Math.cos(t), v = ell.semiMinor * Math.sin(t);
    out.push({ x: cx0 + u * ct - v * st, y: cy0 + u * st + v * ct });
  }
  return out;
}

/* ---------------- 定位质量 ---------------- */
function median(vals) {
  const v = vals.slice().sort((x, y) => x - y);
  if (!v.length) return 0;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/* 残差 + 几何强度
   残差 = 测量距离 − 估计点到该站位的距离；RMS 越小越可信。
   GDOP = sqrt(trace((HᵀH)^-1))，H 为估计点到各站位的单位向量：
   站位数不足、近共线、或都在同一侧时 HᵀH 降秩 → GDOP 极大/无解（估计点不可信）。
   没有残差/几何指标时，恒定 RSSI 这类退化输入会给出一个看着很正常、实际无意义的坐标。 */
function qualityOf(obs, est) {
  if (!est || obs.length < 2) return null;
  let sum2 = 0;
  const per = {};
  obs.forEach(o => {
    const d = Math.hypot(est.x - o.s.x, est.y - o.s.y);
    const r = o.dist - d;                       // 测量 − 估计
    per[o.s.sid] = r;
    sum2 += r * r;
  });
  const rms = Math.sqrt(sum2 / obs.length);
  let a = 0, b = 0, c = 0;
  obs.forEach(o => {
    const dx = o.s.x - est.x, dy = o.s.y - est.y;
    const L = Math.hypot(dx, dy) || 1e-6;
    const ux = dx / L, uy = dy / L;
    a += ux * ux; b += ux * uy; c += uy * uy;
  });
  const det = a * c - b * b;
  const gdop = Math.abs(det) > 1e-9 ? Math.sqrt((a + c) / det) : null;
  return { rms, per, gdop, medDist: median(obs.map(o => o.dist)) };
}

/* 站位布局条件数（与估计点无关）：经典最小二乘矩阵 A（行 = 2(xj-x0), 2(yj-y0)）
   的 λmax/λmin；∞ = 完全共线。**解不出来时**用它区分「站位几何不行」还是「距离环不相交」。 */
function layoutCond(obs) {
  if (obs.length < 2) return null;
  const x0 = obs[0].s.x, y0 = obs[0].s.y;
  let a00 = 0, a01 = 0, a11 = 0;
  for (let j = 1; j < obs.length; j++) {
    const ax = 2 * (obs[j].s.x - x0), ay = 2 * (obs[j].s.y - y0);
    a00 += ax * ax; a01 += ax * ay; a11 += ay * ay;
  }
  const tr = a00 + a11, det = a00 * a11 - a01 * a01;
  const disc = Math.max(tr * tr / 4 - det, 0);
  const l1 = tr / 2 + Math.sqrt(disc), l2 = tr / 2 - Math.sqrt(disc);
  if (l2 <= 1e-12) return Infinity;          // 完全共线
  return Math.sqrt(l1 / l2);
}

/* 等级：good / fair / bad（null = 无法判定） */
function gdopGrade(g) {
  if (g === null || g === undefined || !isFinite(g)) return "bad";
  if (g <= 1.5) return "good";
  if (g <= 4) return "fair";
  return "bad";
}
function resGrade(rms, medDist) {
  const base = Math.max(medDist || 0, 1);
  if (rms <= 0.2 * base) return "good";
  if (rms <= 0.6 * base) return "fair";
  return "bad";
}

/* ---------------- 观测归集（单一实现：实时与回放共用） ----------------
   站位 s 在**时刻 t** 的观测：
     1) 手动绑定 rssi → 直接用（不受时间窗限制）；
     2) 时间窗 [t0, t1) 存在且 t0 <= t → 取窗内样本的 RSSI **中位数**；
     3) 其它 → 无观测。
   **样本一律限于 ts <= t**：回放时不能看未来（否则会提前知道后面的测量）。
   实时模式传 t = now，行为与重构前完全一致。 */
function obsOfStation(s, samples, t) {
  if (s.rssi !== null && s.rssi !== undefined) {
    return { rssi: s.rssi, n: 1, src: "bind" };
  }
  if (s.t0 === null || s.t0 === undefined || s.t0 > t) return null;
  const t1 = (s.t1 === null || s.t1 === undefined) ? Infinity : s.t1;
  const vals = samples
    .filter(p => p.t >= s.t0 && p.t < t1 && p.t <= t
                 && typeof p.rssi === "number")
    .map(p => p.rssi).sort((a, b) => a - b);
  if (!vals.length) return null;
  const m = vals.length >> 1;
  const med = vals.length % 2 ? vals[m] : (vals[m - 1] + vals[m]) / 2;
  return { rssi: med, n: vals.length, src: "window" };
}

/* 时刻 t 的全部观测（含距离换算） */
function obsAt(stations, samples, t, A, n) {
  const out = [];
  for (const s of stations) {
    const o = obsOfStation(s, samples, t);
    if (o) out.push({ s, rssi: o.rssi, n: o.n, src: o.src,
                      dist: distFromRssi(o.rssi, A, n) });
  }
  return out;
}
