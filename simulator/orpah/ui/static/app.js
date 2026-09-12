/* ORPAH L1 demo UI — 前端逻辑：SSE 报文流 + 拓扑点亮 + 计数 + 控制
 * 文案统一走 OrpahI18n（ui_i18n.js，zh/en 单一源）；URL ?lang=en 可切英文预览。
 */
"use strict";

const $ = id => document.getElementById(id);
const T = key => OrpahI18n.t(key);          // 取文案
let paused = false;
let idRevoked = false;

const STAGE_NODE = {
  client: "nodeClient", router: "nodeRouter", server: "nodeServer",
};
const STAGE_CLS = { client: "flash", router: "flash-r", server: "flash" };

/* 连接状态中文映射：机器值英文（后端 /api/status），仅展示层按字典翻译 */
const connZh = v => {
  const s = OrpahI18n.t("conn_" + v);
  return s === "conn_" + v ? (v || "?") : s;   // 字典无此键 → 回退机器值
};
/* 报文流「节点」列：后端 stage 是机器值 client/router/server → 字典 node_*（拓扑图同一套词条） */
const nodeLabel = v => {
  const s = OrpahI18n.t("node_" + v);
  return s === "node_" + v ? (v || "-") : s;   // 字典无此键 → 回退机器值
};

/* ---------- 语言应用（静态 data-i18n / title / placeholder / 文档标题） ---------- */
function applyI18n() {
  OrpahI18n.apply();
  // 按钮文案可能被状态切换，统一由 data-i18n 管理即可；这里再补 pause 态
  $("btnPause").textContent = T(paused ? "btn_resume" : "btn_pause");
}
document.addEventListener("DOMContentLoaded", applyI18n);

/* ---------- SSE 事件流 ---------- */
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => setSrv(true);
  es.onerror = () => setSrv(false);
  es.onmessage = ev => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d.type === "report") onReport(d);
  };
}
function setSrv(ok) {
  const b = $("srvstatus");
  b.textContent = ok ? T("srv_connected") : T("srv_disconnected");
  b.className = "badge " + (ok ? "on" : "off");
}

/* ---------- 报文事件（SSE：只做闪烁 + 触发全量刷新） ---------- */
function onReport(d) {
  const stage = d.stage;                 // client / router / server
  // 拓扑点亮对应节点
  const nid = STAGE_NODE[stage];
  const cls = STAGE_CLS[stage];
  if (nid) {
    const n = $(nid);
    n.classList.remove("flash", "flash-r");
    void n.offsetWidth;                  // 重触发动画
    n.classList.add(cls);
    setTimeout(() => n.classList.remove(cls), 900);
  }
  // 链路流动动画（方向箭头高亮：上行 client→router→server）
  const linkFlow = document.querySelectorAll(".link-flow");
  linkFlow.forEach(f => {
    f.classList.add("active");
    setTimeout(() => f.classList.remove("active"), 600);
  });
  // 表格以 /api/status 全量 reports 为准，拉一次即时刷新
  refresh();
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- 全量状态轮询（计数 / 连接 / 表格真相） ---------- */
const seenRows = {};   // seq -> row element
const MAX_ROWS = 50;
let lostSns = new Set();   // 当前丢失态设备 SN（用于报文流标红）

function renderRows(rows) {
  const tbody = $("msgList");
  // rows 已按最新在前（后端 reversed）
  const active = new Set();
  rows.forEach(r => {
    const seq = r.seq;
    active.add(seq);
    let tr = seenRows[seq];
    if (!tr) {
      tr = document.createElement("tr");
      tr.innerHTML =
        `<td class="tm"></td><td class="sq"></td><td class="sn"></td>` +
        `<td class="rs"></td>` +
        `<td class="c">·</td><td class="r">·</td><td class="s">·</td>`;
      tbody.appendChild(tr);             // 追加（顺序由顺序数组保证）
      seenRows[seq] = tr;
    }
    tr.querySelector(".tm").textContent = r.tm || "";
    tr.querySelector(".tm").title = r.ts_src === "server" ? T("reports_ts_server") : "";
    tr.querySelector(".sq").textContent = seq;
    const snCell = tr.querySelector(".sn");
    snCell.textContent = "";
    if (r.sn) {
      const a = document.createElement("a");
      a.href = "registry.html?sn=" + encodeURIComponent(r.sn);
      a.textContent = r.sn;
      a.title = T("sn_link_title");
      a.className = lostSns.has(r.sn) ? "snlink lost" : "snlink";
      snCell.appendChild(a);
    } else {
      snCell.textContent = "-";
    }
    tr.querySelector(".rs").textContent = r.rssi != null ? r.rssi : "-";
    setCell(tr, ".c", r.client);
    setCell(tr, ".r", r.router);
    setCell(tr, ".s", r.server);
  });
  // 移除已滑出窗口的行
  Object.keys(seenRows).forEach(seq => {
    if (!active.has(Number(seq))) {
      const tr = seenRows[seq];
      if (tr) tr.remove();
      delete seenRows[seq];
    }
  });
  // 最新在顶部：reports 最新在前 → DOM 里按需把新行插到最前更直观，
  // 这里统一重排一次（保持 tbody 顺序 = rows 顺序）
  [...tbody.children].sort((a, b) => {
    const sa = Number(a.querySelector(".sq").textContent);
    const sb = Number(b.querySelector(".sq").textContent);
    return sb - sa;                       // 大 seq 在前
  }).forEach(n => tbody.appendChild(n));
  while (tbody.children.length > MAX_ROWS) tbody.lastChild.remove();
}

function setCell(tr, sel, on) {
  const td = tr.querySelector(sel);
  if (!td) return;
  td.textContent = on ? "✓" : "·";
  td.className = on ? "yes" : "no";
}

/* ---------- L2：消息流面板 + 走失表 ---------- */
const MAX_FLOW = 60;
const FLOW_ZH = { "up": "↑", "down": "↓" };

function renderFlow(flow) {
  const tbody = $("flowList");
  tbody.innerHTML = "";
  flow.slice(0, MAX_FLOW).forEach(e => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(e.t)}</td><td>${FLOW_ZH[e.dir] || esc(e.dir)}</td>` +
      `<td>${esc(e.type)}</td><td>${esc(e.sn)}</td>` +
      `<td>${esc(e.status === undefined ? "-" : e.status)}</td>` +
      `<td>${esc(nodeLabel(e.stage))}</td>`;
    tbody.appendChild(tr);
  });
}

function renderLost(lost) {
  const state = $("lostState");
  const sn = $("lostSn").value || $("ctlSn").value || "CN-WH01-9AF3C1D2";
  const rec = lost[sn];
  const tracked = rec && rec.tracked;
  state.textContent = tracked ? T("lost_yes") : T("lost_no");
  state.className = "hint" + (tracked ? " lost-yes" : "");
}

/* 服务器发布走失表记录（走失数据是服务器主动“下发”的，单独列出） */
const MAX_PUB = 10;

function renderFounds(founds) {
  const ul = $("foundList");
  if (!ul) return;
  ul.innerHTML = "";
  const list = founds || [];
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "pub-empty";
    li.textContent = T("found_empty");
    ul.appendChild(li);
    return;
  }
  const parts = T("found_line").split("{sn}");   // [前, 后]
  list.slice(0, MAX_PUB).forEach(f => {
    const li = document.createElement("li");
    li.className = "pub-meta";
    li.innerHTML =
      `<span class="tm">${esc(f.t)}</span> ` +
      `<span class="pub-act">${esc(parts[0])}` +
      `<b class="lost-yes">${esc(f.sn || "-")}</b>${esc(parts[1] || "")}</span>`;
    ul.appendChild(li);
  });
}

function renderPublishes(publishes) {
  const ul = $("publishList");
  if (!ul) return;
  ul.innerHTML = "";
  const list = publishes || [];
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "pub-empty";
    li.textContent = T("pub_empty");
    ul.appendChild(li);
    return;
  }
  list.slice(0, MAX_PUB).forEach(p => {
    const li = document.createElement("li");
    const action = T("pub_action")
      .replace("{n}", p.n).replace("{k}", p.targets);
    li.innerHTML =
      `<div class="pub-meta"><span class="tm">${esc(p.t)}</span> ` +
      `<span class="pub-act">${esc(action)}</span></div>` +
      `<ul class="pub-ents">` +
      p.entries.map(en =>
        `<li>${esc(en.sn)} = ` +
        `<b class="${en.tracked ? "lost-yes" : ""}">` +
        `${esc(en.tracked ? T("lost_yes") : T("lost_no"))}</b></li>`
      ).join("") + `</ul>`;
    ul.appendChild(li);
  });
}

/* ---------- 事件历史（IoTDB 持久化，重启后仍在） ---------- */
const evtLabel = v => {
  const s = OrpahI18n.t("evt_type_" + v);
  return s === "evt_type_" + v ? (v || "?") : s;   // 字典无此键 → 回退机器值
};

function renderEvents(rows, ok, meta) {
  const ul = $("evtList");
  if (!ul) return;
  const state = $("evtState");
  const list = rows || [];
  state.textContent = ok ? T("evt_n").replace("{n}", list.length)
                         : T("evt_offline");
  state.className = ok ? "hint" : "hint lost-yes";
  const ret = $("evtRetention");
  if (ret && meta) {      // 保留期限：由后端 tsdb.EVENT_RETENTION_DAYS 决定
    const d = meta.retention_days;
    ret.textContent = d ? T("evt_retention").replace("{n}", d)
                        : T("evt_retention_all");
  }
  ul.innerHTML = "";
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "pub-empty";
    li.textContent = T("evt_empty");
    ul.appendChild(li);
    return;
  }
  list.forEach(e => {
    const li = document.createElement("li");
    li.className = "pub-meta";
    const tm = new Date(e.t || 0).toTimeString().slice(0, 8);
    // 操作者：只标人为操作（自动事件记 system，不显）
    const who = (e.actor && e.actor !== "system")
      ? ` <span class="evt-actor">${esc(e.actor)}</span>` : "";
    li.innerHTML =
      `<span class="tm">${esc(tm)}</span> ` +
      `<span class="pub-act"><b>${esc(evtLabel(e.etype))}</b>` +
      (e.sn ? ` <b class="lost-yes">${esc(e.sn)}</b>` : "") +
      (e.detail ? ` ${esc(e.detail)}` : "") + who + `</span>`;
    ul.appendChild(li);
  });
}

let evtBusy = false;

async function refreshEvents() {
  const ul = $("evtList");
  if (!ul || evtBusy) return;      // 防重入：IoTDB 慢时不堆请求
  evtBusy = true;
  const limit = Math.min(200, Math.max(5, parseInt($("evtLimit").value) || 30));
  const etype = $("evtType").value;
  try {
    const r = await fetch(`/api/ts/events?limit=${limit}` +
      (etype ? `&etype=${encodeURIComponent(etype)}` : "")).then(x => x.json());
    renderEvents(r.rows, !!r.ok, r);
  } catch (e) {
    renderEvents([], false);
  } finally {
    evtBusy = false;
  }
}

function renderId(d) {
  if (!d || !d.sn) return;
  $("idSn").textContent = d.sn;
  $("idAlg").textContent = d.alg || "-";
  $("idLevel").textContent = d.level != null ? d.level : "-";
  const t = $("idTrust");
  const ok = d.accepted;
  const trustTxt = d.trust && d.trust !== "-" ? " · " + T("trust_" + d.trust) : "";
  // 设备无时钟（ts=0）：标一句，别让人以为设备报了 1970（库里/审计用的是服务器接收时刻）
  const noClock = d.ts_src === "server" ? " · " + T("id_no_clock") : "";
  // §8.3：L2 = SE 不可用（仍更新定位）/ L3 = 只做覆盖发现（不当人员出现）—— 卡片上说清
  const deg = d.degraded ? " · " + T("id_degraded") : "";
  const cov = d.coverage_only ? " · " + T("id_coverage_only") : "";
  t.textContent = ok
    ? T("id_ok") + trustTxt + deg + cov + noClock
    : T("id_bad") + (d.error ? " · " + d.error : "") + noClock;
  t.className = ok ? "ok" : "bad";
  $("idSig").textContent = d.sig || "-";
  $("idNonce").textContent = d.nonce || "-";
}

function renderIdReports(list) {
  const tbody = $("idReportList");
  if (!tbody) return;
  tbody.innerHTML = "";
  const arr = list || [];
  if (!arr.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" class="pub-empty">${esc(T("id_stream_empty"))}</td>`;
    tbody.appendChild(tr);
    return;
  }
  arr.slice(0, 10).forEach(r => {
    const tr = document.createElement("tr");
    const trustTxt = r.trust && r.trust !== "-" ? T("trust_" + r.trust) : "-";
    tr.innerHTML =
      `<td>${esc(r.t)}</td><td>${esc(r.sn)}</td>` +
      `<td>${esc(r.alg)}</td><td>${esc(r.level)}</td>` +
      `<td>${esc(trustTxt)}</td>` +
      `<td class="${r.accepted ? "yes" : "no"}">${r.accepted ? "✓" : "✗ " + esc(r.error || "")}</td>`;
    tbody.appendChild(tr);
  });
}

async function refresh() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("snClient").textContent = s.sn;
    // 计数行（字典 fmt，数字高亮）。**按内容分色**：同一颜色 = 同一类内容，
    // 蓝 = L2（REQ-CONNECT/REPORT）、紫 = Orpah ID 签名上报、黄 = 发现（ORPAH-FOUND）。
    // 口径（为什么会看到不同数字，全部在此说明，避免"看起来不一致"）：
    //   · 客户端「上行注入」= client_sent = REQ-CONNECT + REPORT（每周期 2 条）
    //   · 客户端「ID 上报」= id_sent = 本机注入的 ID-REPORT（含页面注入的重放/超窗/伪造报文）
    //   · 空口帧 = tx_sta = 上面两者之和（STA 发出的**数据**帧；不含信标/关联帧）
    //   · 转发 REPORT / 转发 ID = 路由器真正发给 Server 的两种内容（REQ-CONNECT 本机应答不过 UDP）
    //   · 服务器「收到」只计 REPORT；ID 走验签通道单独计（含被拒，供防 spoof 演示）
    $("rowClientCnt").innerHTML =
      T("lbl_sent").replace("{n}", `<b class="cnt">${s.client_sent}</b>`);
    $("rowClientCnt").title = T("lbl_sent_tip");
    $("rowClientId").innerHTML =
      T("lbl_id_up").replace("{n}", `<b class="cnt-id">${s.id_sent || 0}</b>`);
    $("rowRouterCnt").innerHTML =
      T("lbl_up").replace("{n}", `<b class="cnt">${s.router_up}</b>`);
    $("rowRouterId").innerHTML =
      T("lbl_id_fwd").replace("{n}", `<b class="cnt-id">${s.router_id_up || 0}</b>`);
    $("rowRouterLost").innerHTML =
      T("lbl_lost_recv").replace("{n}", `<b class="cnt">${s.router_lost_recv || 0}</b>`);
    $("rowRouterFound").innerHTML =
      T("lbl_found").replace("{n}", `<b class="cnt-found">${s.found_total || 0}</b>`);
    $("rowServerCnt").innerHTML =
      T("lbl_recv").replace("{n}", `<b class="cnt">${s.server_recv}</b>`);
    $("rowServerId").innerHTML =
      T("lbl_id_recv").replace("{n}", `<b class="cnt-id">${s.id_report_total || 0}</b>`);
    $("rowServerPub").innerHTML =
      T("lbl_pub").replace("{n}", `<b class="cnt">${s.publish_total || 0}</b>`);
    $("rowServerFound").innerHTML =
      T("lbl_found_recv").replace("{n}", `<b class="cnt-found">${s.found_recv || 0}</b>`);
    // 两段链路：总数的口径见下 + 「按内容」拆行（颜色与节点行一致）
    //   空口帧 = L2 注入 + ID 注入（= STA 发出的数据帧总数，所以两项相加等于总数）
    //   UDP 帧 = 转发 REPORT + 转发 ID + 发现（= 路由器真正发给 Server 的帧总数；
    //            不含控制面：REQ-CONNECT 本机应答、LOST-TABLE 拉表/推送）
    const found = s.found_total || 0;
    $("airFrames").textContent = s.tx_sta;
    $("airSplit").innerHTML =
      `<span class="s-l2">L2 <b>${s.client_sent}</b></span> · ` +
      `<span class="s-id">ID <b>${s.id_sent || 0}</b></span>`;
    $("udpFrames").textContent = s.router_up + (s.router_id_up || 0) + found;
    $("udpSplit").innerHTML =
      `<span class="s-l2">REPORT <b>${s.router_up}</b></span> · ` +
      `<span class="s-id">ID <b>${s.router_id_up || 0}</b></span> · ` +
      `<span class="s-found">${T("sp_found")} <b>${found}</b></span>`;
    // 连接 / 徽标（展示层按字典中文化）
    const setConn = (elId, val) => {
      const el = $(elId);
      el.textContent = connZh(val);
      el.className = el.className.split(" ")[0] + " " +
        (val === "CONNECTED" ? "ok" : "");
    };
    setConn("chipClient", s.conn_b);
    setConn("chipRouter", s.conn_a);
    $("chipServer").textContent = s.server_recv > 0 ? T("chip_run") : T("chip_listen");
    $("chipServer").className = "chip" + (s.server_recv > 0 ? " ok" : "");
    // 报文流表格（全量真相）
    lostSns = new Set(s.lost_sns || []);
    // 时间列：设备无时钟（ts=0/缺失，见 orpah_proto.effective_ts）→ 显示**服务器接收时刻**并加 *，
    // 与库里真正用的时间一致（否则界面显示 1970、库里却是现在，对不上）
    const hhmmss = v => new Date((v || 0) * 1000).toTimeString().slice(0, 8);
    const rows = (s.reports || []).map(x => ({
      ...x,
      tm: x.ts ? hhmmss(x.ts) : (x.ts_eff ? hhmmss(x.ts_eff) + "*" : "--"),
    }));
    renderRows(rows);
    // L2：消息流面板 + 走失表状态 + 服务器发布记录 + 发现记录
    renderFlow(s.flow || []);
    renderLost(s.lost || {});
    renderPublishes(s.publishes || []);
    renderFounds(s.founds || []);
    renderId(s.id_demo || {});
    renderIdReports(s.id_reports || []);
    fillSpoofKinds(s.spoof_kinds || []);
    spoofKinds = s.spoof_kinds || spoofKinds;
    // §8.2 降级演示下拉：选项来自 /api/status（单一源），选中值回显当前模式
    fillIdLevelModes(s.id_level_modes || []);
    const selLv = $("idLevelMode");
    if (selLv && document.activeElement !== selLv && s.id_level) selLv.value = s.id_level;
    lastIdNonce = (s.id_demo && s.id_demo.nonce) || lastIdNonce;
    spoofCompare(s.id_demo || {});
    idRevoked = !!s.id_revoked;
    const btnRev = $("btnIdRevoke");
    if (btnRev) btnRev.textContent = T(idRevoked ? "btn_unrevoke" : "btn_revoke");
    // 控制面板回显
    if (!document.activeElement || document.activeElement.id !== "ctlSn")
      $("ctlSn").value = s.sn;
    if (!document.activeElement || document.activeElement.id !== "lostSn")
      $("lostSn").value = s.sn;
    // 设备时钟偏移/漂移估计（clock.py）：只**估计**，不改记录时间语义（§5.5）
    if (!document.activeElement || document.activeElement.id !== "ctlClock")
      $("ctlClock").value = s.clock_off || 0;
    // 设备能力声明（2026-09-13）：null=未声明 / true=有 RTC / false=无 RTC
    const selCap = $("ctlCap");
    if (selCap && document.activeElement !== selCap)
      selCap.value = s.id_cap_rtc === true ? "yes" : (s.id_cap_rtc === false ? "no" : "none");
    const cbTs = $("ctlTsBroken");
    if (cbTs && document.activeElement !== cbTs) cbTs.checked = !!s.id_ts_broken;
    const ci = $("clockInfo");
    if (ci) {
      const est = (s.clock || {})[s.sn];
      const off = s.clock_off || 0;
      const why = (est && est.drift_ppm == null && est.drift_why)
        ? T("clock_why_" + est.drift_why) : "";
      const idr = (s.id_demo || {});
      // 上报卡上先说清“时间是谁给的”：无 RTC / ts 置 0 时设备没有可用时钟（§5.5）
      const capTxt = s.id_cap_rtc === false ? T("cap_rtc_no")
        : (s.id_cap_rtc === true ? T("cap_rtc_yes") : T("cap_none"));
      const tsTxt = (s.id_ts_broken || idr.ts_src === "server")
        ? " · " + T("cap_ts_server").replace("{cap}", capTxt) : " · " + capTxt;
      ci.textContent = (est && est.ok)
        ? T("clock_info")
            .replace("{off}", (est.offset >= 0 ? "+" : "") + est.offset.toFixed(1))
            .replace("{drift}", est.drift_ppm == null ? "—" : (est.drift_ppm >= 0 ? "+" : "") + est.drift_ppm.toFixed(0))
            .replace("{why}", why)
            .replace("{n}", est.n)
          + (off ? "  ·  " + T("clock_demo_on").replace("{v}", off) : "")
          + tsTxt
        : T("clock_none") + tsTxt;
    }
    renderEnergy(s.energy, s.energy_axis);
  } catch (e) { /* 服务器未就绪 */ }
}

/* ---------- 控制按钮 ---------- */
function postCtl(body) {
  return fetch("/api/ctl", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(e => console.error("postCtl 请求失败:", e));
}

$("btnPause").onclick = async () => {
  paused = !paused;
  await postCtl({ action: paused ? "pause" : "resume" });
  $("btnPause").textContent = T(paused ? "btn_resume" : "btn_pause");
};
$("btnReset").onclick = () => {
  Object.keys(seenRows).forEach(k => delete seenRows[k]);
  $("msgList").innerHTML = "";
};
$("btnApply").onclick = async () => {
  await postCtl({
    action: "every", every: parseFloat($("ctlEvery").value) || 2,
  });
  await postCtl({ action: "set_sn", sn: $("ctlSn").value || "CN-WH01-9AF3C1D2" });
  await postCtl({ action: "clock_off", sec: parseFloat($("ctlClock").value) || 0 });
  // 能力声明：none → 不声明（null），yes/no → true/false
  const cap = $("ctlCap").value;
  await postCtl({ action: "cap", rtc: cap === "yes" ? true : (cap === "no" ? false : null) });
  await postCtl({ action: "ts_broken", on: !!$("ctlTsBroken").checked });
};
$("btnMark").onclick = async () => {
  const sn = $("lostSn").value || $("ctlSn").value || "CN-WH01-9AF3C1D2";
  await postCtl({ action: "mark", sn });
};
$("btnUntrack").onclick = async () => {
  const sn = $("lostSn").value || $("ctlSn").value || "CN-WH01-9AF3C1D2";
  await postCtl({ action: "untrack", sn });
};
$("btnIdRevoke").onclick = async () => {
  await postCtl({ action: idRevoked ? "unrevoke" : "revoke" });
};
$("btnIdReplay").onclick = async () => {
  await postCtl({ action: "replay" });
};
$("btnIdStale").onclick = async () => {
  await postCtl({ action: "stale" });
};

/* ---------- 能量轴（免电池客户端）----------

   模型在 energy.py（三参数：采集 P / 储能 C / 每次上报代价 cost），这里只做呈现：
   · 状态格：电量 mV、级别、间隔、还能撑多久、净余、原因（`why` 是机器值，字典翻译）；
   · 扫描表：横轴 = 采集功率 → 纵轴 = 可持续的上报间隔（这就是「能量轴」的名字由来）；
   · 头条：`min_harvest_mw` = 少于此功率就跟不住人（要≥0.1mW 才每 300s 报一次）。

   页面操作**不改模型**：参数只是喂给 `energy.plan()` 的输入，判定恒由后端算（单一源）。 */

let enBusy = false;

const EN_WHY = w => {
  const s = T("en_why_" + w);
  return s === "en_why_" + w ? (w || "-") : s;
};

function enNum(v, digits) {
  return (v == null || !isFinite(v)) ? "—" : Number(v).toFixed(digits == null ? 2 : digits);
}

function fmtInterval(v) {
  return v == null ? T("en_silent") : enNum(v, 1) + " s";
}

function fmtSilence(v) {
  if (v == null) return "—";
  if (v >= 86400) return enNum(v / 86400, 1) + " " + T("en_day");
  if (v >= 3600) return enNum(v / 3600, 1) + " " + T("en_hour");
  return enNum(v, 0) + " s";
}

function renderEnergy(e, ax) {
  const box = $("enState");
  if (!box) return;
  const on = !!(e && e.on);
  const st = (e && e.state) || {};
  const mv = st.mv;
  const cell = (k, v, cls) =>
    `<div class="id-row"><span>${esc(T(k))}</span><b class="${cls || ""}">${v}</b></div>`;
  if (!on) {
    box.innerHTML = cell("en_st_state", esc(T("en_state_off"))) +
      cell("en_st_mv", "—") + cell("en_st_level", "—") +
      cell("en_st_interval", "—") + cell("en_st_silence", "—");
  } else {
    // 电站「还有多少」= 储能 × 电压映射；沉默倒计时是**演示加速后**的直观秒数
    const lv = mv == null ? "—" : mv + " mV";
    const lvCls = (st.mv != null && st.why === "empty") ? "lost-yes" : "";
    let sTxt = "—";
    if (st.silent) sTxt = T("en_silent_now");
    else if (st.hard) sTxt = T("en_hard_now") + " (" + fmtSilence(st.silence_eta_s) + ")";
    else if (st.silence_in_s != null) sTxt = fmtSilence(st.silence_eta_s);
    box.innerHTML =
      cell("en_st_state", esc(T("en_state_on"))) +
      cell("en_st_mv", lv, lvCls) +
      cell("en_st_level", esc(st.level || "—") +
           (st.degraded ? ` <span class="hint">${esc(T("en_degraded"))}</span>` : "")) +
      cell("en_st_interval", esc(fmtInterval(st.interval_s))) +
      cell("en_st_silence", esc(sTxt)) +
      cell("en_st_net", enNum(st.net_mw, 3) + " mW") +
      cell("en_st_why", esc(EN_WHY(st.why)));
  }
  // 输入框回显（不动正在编辑的那个）
  const ae = document.activeElement && document.activeElement.id;
  const p = (e && e.params) || {};
  if (ae !== "enHarvest" && p.harvest_mw != null) $("enHarvest").value = p.harvest_mw;
  if (ae !== "enCharge" && p.charge_mj != null) $("enCharge").value = p.charge_mj;
  if (ae !== "enStore" && p.store_mj != null) $("enStore").value = p.store_mj;
  if (ae !== "enSpeedup" && p.speedup != null) $("enSpeedup").value = p.speedup;
  const cbOn = $("enOn");
  if (cbOn && document.activeElement !== cbOn) cbOn.checked = on;
  const cbPush = $("enPush");
  if (cbPush && document.activeElement !== cbPush) cbPush.checked = !!p.push;

  // 扫描表 + 头条
  const msg = $("enAxisMsg");
  const tb = $("enAxisList");
  if (!tb) return;
  const rows = (ax && ax.rows) || [];
  tb.innerHTML = "";
  rows.forEach(r => {
    const tr = document.createElement("tr");
    const cur = (e && e.params && Math.abs(r.harvest_mw - e.params.harvest_mw) < 1e-9);
    if (cur) tr.className = "en-cur";
    const usable = !!r.usable;
    tr.innerHTML =
      `<td>${enNum(r.harvest_mw, 3)}${cur ? " ◀" : ""}</td>` +
      `<td>${enNum(r.net_mw, 3)}</td>` +
      `<td class="${usable ? "yes" : "no"}">${esc(r.level || "—")}` +
      `${r.degraded ? ` <span class="hint">${esc(T("en_degraded"))}</span>` : ""}</td>` +
      `<td>${esc(fmtInterval(r.interval_s))}` +
      `${r.every_s != null ? ` <span class="hint">(${enNum(r.every_s, 1)}s)</span>` : ""}</td>` +
      `<td>${esc(fmtSilence(r.silence_in_s))}</td>` +
      `<td>${esc(EN_WHY(r.why))}</td>`;
    tb.appendChild(tr);
  });
  if (msg) {
    msg.textContent = (ax && ax.min_harvest_mw != null)
      ? T("en_axis_head").replace("{n}", enNum(ax.min_harvest_mw, 2))
          .replace("{n2}", enNum(ax.n, 0))
      : T("en_axis_none");
  }
}

async function postEnergy(body) {
  if (enBusy) return;                     // 防重入：连点不堆请求
  enBusy = true;
  try {
    const r = await fetch("/api/energy", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(x => x.json());
    if (r && r.axis) renderEnergy(r, r.axis);   // 立刻回显，不等下一次轮询
  } catch (err) {
    console.error("postEnergy 失败:", err);
  } finally {
    enBusy = false;
  }
}

if ($("btnEnApply")) {
  $("btnEnApply").onclick = () => postEnergy({
    action: "set",
    on: !!$("enOn").checked,
    harvest_mw: parseFloat($("enHarvest").value) || 0,
    charge_mj: parseFloat($("enCharge").value) || 0,
    store_mj: parseFloat($("enStore").value) || 0,
    push: !!$("enPush").checked,
    speedup: parseFloat($("enSpeedup").value) || 1,
  });
  $("btnEnReset").onclick = () => postEnergy({ action: "reset" });
  $("enOn").onchange = () => postEnergy({ action: $("enOn").checked ? "on" : "off" });
}

/* ---------- §8.2 降级演示：切换「哪个环节坏了」---------- */
function fillIdLevelModes(list) {
  const sel = $("idLevelMode");
  if (!sel || !list || !list.length) return;
  const sig = list.join("|");
  if (sel.dataset.sig === sig && OrpahI18n.lang === sel.dataset.lang) return;
  const keep = sel.value;
  sel.innerHTML = list.map(k =>
    `<option value="${esc(k)}">${esc(T("id_lv_" + k))}</option>`).join("");
  sel.dataset.sig = sig;
  sel.dataset.lang = OrpahI18n.lang;
  if (keep && list.includes(keep)) sel.value = keep;
}
if ($("idLevelMode")) {
  $("idLevelMode").onchange = async () => {
    await postCtl({ action: "id_level", level: $("idLevelMode").value });
  };
}

/* ---------- 防 spoof：把攻击报文真的注入空口，看服务器怎么拦 ---------- */
let spoofKinds = [];        // /api/status.spoof_kinds（脚本/UI 同一份，见 spoof.py）
let spoofRunning = false;
let lastIdNonce = "";       // 最近一条验签结果的 nonce（用来等"这条攻击的结果到了"）

function spoofOptText(o) {
  const name = OrpahI18n.lang === "en" ? (o.en || o.kind) : (o.zh || o.kind);
  return name + "  →  " + (o.expect || T("spoof_accept"));
}

function fillSpoofKinds(list) {
  const sel = $("idSpoofKind");
  if (!sel || !list || !list.length) return;
  const sig = list.map(o => o.kind).join("|");
  if (sel.dataset.sig === sig && OrpahI18n.lang === sel.dataset.lang) return;
  const keep = sel.value;
  sel.innerHTML = list.map(o =>
    `<option value="${esc(o.kind)}">${esc(spoofOptText(o))}</option>`).join("");
  sel.dataset.sig = sig;
  sel.dataset.lang = OrpahI18n.lang;
  if (keep && list.some(o => o.kind === keep)) sel.value = keep;
}

function spoofMsg(html, cls) {
  const el = $("spoofMsg");
  if (!el) return;
  el.innerHTML = html;
  el.className = "hint" + (cls ? " " + cls : "");
}

async function spoofOne(kind) {
  const r = await postCtl({ action: "spoof", kind });
  let info = {};
  try { info = await r.json(); } catch (e) { /* ignore */ }
  if (!info.ok) { spoofMsg(T("spoof_fail") + (info.err || ""), "err"); return null; }
  const o = spoofKinds.find(x => x.kind === kind) || info;
  const name = OrpahI18n.lang === "en" ? (o.en || kind) : (o.zh || kind);
  spoofMsg(T("spoof_sent").replace("{k}", esc(name))
    .replace("{e}", esc(info.expect || T("spoof_accept"))) + " …");
  // 验签结果由 server 异步回（经真链路），等下一轮 id_demo 更新后再比对
  return { kind, name, expect: info.expect, note: info.note };
}

/* 把"期望 vs 实际"写进结果行；由 refresh() 在 id_demo 更新时调 */
let spoofPending = null;
function spoofCompare(d) {
  if (!spoofPending || !d || d.sn === undefined) return;
  const got = d.accepted ? null : (d.error || "?");
  const ok = got === spoofPending.expect;
  const mark = ok ? "✓" : "✗";
  const tn = t => (t == null ? T("spoof_accept") : t);
  spoofMsg(T("spoof_res").replace("{k}", esc(spoofPending.name))
    .replace("{e}", esc(tn(spoofPending.expect)))
    .replace("{g}", esc(tn(got)))
    .replace("{m}", mark), ok ? "" : "err");
  spoofPending = null;
}

$("btnIdSpoof").onclick = async () => {
  const kind = $("idSpoofKind").value;
  if (!kind) return;
  const p = await spoofOne(kind);
  if (p) spoofPending = p;
};

$("btnIdSpoofAll").onclick = async () => {
  if (spoofRunning) return;
  spoofRunning = true;
  $("btnIdSpoofAll").disabled = true;
  $("btnIdSpoofStop").style.display = "";
  const list = spoofKinds.slice();
  const hits = [];
  for (let i = 0; i < list.length && spoofRunning; i++) {
    const p = await spoofOne(list[i].kind);
    if (!p) continue;
    hits.push(p);
    // 等该条的验签结果（id_demo 的 nonce 变化 = 新结果到了）
    const t0 = Date.now();
    let last = lastIdNonce;
    while (Date.now() - t0 < 3000 && lastIdNonce === last) {
      await new Promise(res => setTimeout(res, 120));
    }
    spoofPending = null;
    await new Promise(res => setTimeout(res, 150));
  }
  spoofRunning = false;
  $("btnIdSpoofAll").disabled = false;
  $("btnIdSpoofStop").style.display = "none";
  const n = hits.length;
  spoofMsg(T("spoof_all_done").replace("{n}", n)
    + " " + T("spoof_all_hint"), "");
};
$("btnIdSpoofStop").onclick = () => { spoofRunning = false; };

applyI18n();               // 本文件在 </body> 前加载，DOM 已就绪，直接应用
connect();
setInterval(refresh, 1000);
refresh();

/* 事件历史：初始化拉一次 + 每 5s 刷新（IoTDB 查询很轻，不跟 1s 轮询） */
if ($("btnEvtRefresh")) {
  $("btnEvtRefresh").onclick = refreshEvents;
  $("evtType").onchange = refreshEvents;
  $("evtLimit").onchange = refreshEvents;
  setInterval(refreshEvents, 5000);
  refreshEvents();
}

/* ---------- 告警（规则引擎在 alerts.py；本页只轮询 + 渲染） ----------
   后端只回 {kind, level, key, msg(i18n 键), since, ...数据} —— 文案由本页本地化，
   免得又变成"后端文案不跟语言走"。
   红点用轮询（3s）而不是 SSE：比 1s 的 /api/status 慢一档，规则评估很轻。 */
let alertKeys = new Set();     // 上一轮的告警 key：用来判断"新告警"

/* 持续时长：中文用 天/小时/分钟/秒，英文用 d/h/m/s（单位走字典，不写死文案）。
   最多两段（有更大单位就截到下一级），与常见「只在需要时才细分」习惯一致。 */
function fmtGap(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600),
        m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const vals = { d: d, h: h, m: m, s: s };
  let out = T(d ? "dur_dh" : (h ? "dur_hm" : (m ? "dur_ms" : "dur_s")));
  Object.keys(vals).forEach(k => { out = out.split("{" + k + "}").join(String(vals[k])); });
  return out;
}

/* 用告警自带字段填 msg 模板 */
function alertText(a) {
  const data = Object.assign({}, a);
  delete data.msg;
  if (data.gap !== undefined) data.gap = fmtGap(data.gap);
  let s = T(a.msg);
  Object.keys(data).forEach(k => { s = s.split("{" + k + "}").join(String(data[k])); });
  return s;
}

function renderAlerts(r) {
  const badge = $("alertBadge"), card = $("alertCard"), ul = $("alertList");
  if (!badge || !card || !ul) return;
  const list = r.alerts || [], counts = r.counts || {}, n = counts.total || 0;
  badge.hidden = !n;
  badge.textContent = n ? "⚠ " + n : "";
  badge.className = "badge" + (counts.crit ? " crit" : (n ? " warn" : ""));
  card.hidden = !n;
  ul.innerHTML = "";
  list.forEach(a => {
    const li = document.createElement("li");
    li.className = a.level;
    const age = fmtGap(Date.now() / 1000 - a.since);
    li.innerHTML = esc(alertText(a)) +
      ' <span class="since">· ' + esc(T("alert_age").replace("{v}", age)) + "</span>";
    ul.appendChild(li);
  });
  // 出现"上一轮没有的告警"→ 徽标闪一下（比弹窗轻，不打断演示）
  const keys = new Set(list.map(a => a.key));
  const isNew = n > 0 && [...keys].some(k => !alertKeys.has(k));
  alertKeys = keys;
  if (isNew) {
    badge.style.boxShadow = "0 0 10px 2px currentColor";
    setTimeout(() => { badge.style.boxShadow = ""; }, 1500);
  }
}

async function refreshAlerts() {
  try {
    const r = await fetch("/api/alerts").then(x => x.json());
    if (r && r.ok) renderAlerts(r);
  } catch (e) { /* 服务器未就绪 */ }
}
if ($("alertBadge")) {
  setInterval(refreshAlerts, 3000);
  refreshAlerts();
}

/* ---------- 顶部「工具」下拉菜单 ---------- */
const toolsBtn = $("toolsBtn");
if (toolsBtn) {
  toolsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    $("toolsMenu").classList.toggle("open");
  });
  document.addEventListener("click", () => $("toolsMenu").classList.remove("open"));
  $("toolsMenu").querySelectorAll(".menu-list a").forEach(a => {
    a.addEventListener("click", () => $("toolsMenu").classList.remove("open"));
  });
}
