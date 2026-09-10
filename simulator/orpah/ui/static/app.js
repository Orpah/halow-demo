/* ORPAH L1 demo UI — 前端逻辑：SSE 报文流 + 拓扑点亮 + 计数 + 控制
 * 文案统一走 OrpahI18n（ui_i18n.js，zh/en 单一源）；URL ?lang=en 可切英文预览。
 */
"use strict";

const $ = id => document.getElementById(id);
const T = key => OrpahI18n.t(key);          // 取文案
let paused = false;

const STAGE_NODE = {
  client: "nodeClient", router: "nodeRouter", server: "nodeServer",
};
const STAGE_CLS = { client: "flash", router: "flash-r", server: "flash" };

/* 连接状态中文映射：机器值英文（后端 /api/status），仅展示层按字典翻译 */
const connZh = v => {
  const s = OrpahI18n.t("conn_" + v);
  return s === "conn_" + v ? (v || "?") : s;   // 字典无此键 → 回退机器值
};

/* ---------- 语言应用（静态 data-i18n） ---------- */
function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = OrpahI18n.t(el.getAttribute("data-i18n"));
  });
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
    tr.querySelector(".sq").textContent = seq;
    tr.querySelector(".sn").textContent = esc(r.sn || "-");
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
      `<td>${esc(e.stage || "-")}</td>`;
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

function renderId(d) {
  if (!d || !d.sn) return;
  $("idSn").textContent = d.sn;
  $("idAlg").textContent = d.alg || "-";
  $("idLevel").textContent = d.level != null ? d.level : "-";
  const t = $("idTrust");
  const ok = d.accepted;
  t.textContent = (ok ? T("id_ok") : T("id_bad")) + " · " + T("trust_" + d.trust);
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
    tr.innerHTML =
      `<td>${esc(r.t)}</td><td>${esc(r.sn)}</td>` +
      `<td>${esc(r.alg)}</td><td>${esc(r.level)}</td>` +
      `<td>${esc(T("trust_" + r.trust))}</td>` +
      `<td class="${r.accepted ? "yes" : "no"}">${r.accepted ? "✓" : "✗"}</td>`;
    tbody.appendChild(tr);
  });
}

async function refresh() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("snClient").textContent = s.sn;
    // 计数行（字典 fmt，数字高亮）
    $("rowClientCnt").innerHTML =
      T("lbl_sent").replace("{n}", `<b class="cnt">${s.client_sent}</b>`);
    $("rowRouterCnt").innerHTML =
      T("lbl_up").replace("{n}", `<b class="cnt">${s.router_up}</b>`);
    $("rowRouterLost").innerHTML =
      T("lbl_lost_recv").replace("{n}", `<b class="cnt">${s.router_lost_recv || 0}</b>`);
    $("rowRouterFound").innerHTML =
      T("lbl_found").replace("{n}", `<b class="cnt">${s.found_total || 0}</b>`);
    $("rowServerCnt").innerHTML =
      T("lbl_recv").replace("{n}", `<b class="cnt">${s.server_recv}</b>`);
    $("rowServerPub").innerHTML =
      T("lbl_pub").replace("{n}", `<b class="cnt">${s.publish_total || 0}</b>`);
    $("rowServerFound").innerHTML =
      T("lbl_found_recv").replace("{n}", `<b class="cnt">${s.found_recv || 0}</b>`);
    // 链路段帧数（方向箭头旁）：空口段 = 客户端发出的空口帧(tx_sta)；
    // UDP 段 = 路由器上行转发帧(router_up)。单向上行 → 数值与上报一致。
    $("airFrames").textContent = s.tx_sta;
    $("udpFrames").textContent = s.router_up;
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
    const rows = (s.reports || []).map(x => ({
      ...x, tm: new Date((x.ts || 0) * 1000).toTimeString().slice(0, 8),
    }));
    renderRows(rows);
    // L2：消息流面板 + 走失表状态 + 服务器发布记录 + 发现记录
    renderFlow(s.flow || []);
    renderLost(s.lost || {});
    renderPublishes(s.publishes || []);
    renderFounds(s.founds || []);
    renderId(s.id_demo || {});
    renderIdReports(s.id_reports || []);
    // 控制面板回显
    if (!document.activeElement || document.activeElement.id !== "ctlSn")
      $("ctlSn").value = s.sn;
    if (!document.activeElement || document.activeElement.id !== "lostSn")
      $("lostSn").value = s.sn;
  } catch (e) { /* 服务器未就绪 */ }
}

/* ---------- 控制按钮 ---------- */
function postCtl(body) {
  return fetch("/api/ctl", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
};
$("btnMark").onclick = async () => {
  const sn = $("lostSn").value || $("ctlSn").value || "CN-WH01-9AF3C1D2";
  await postCtl({ action: "mark", sn });
};
$("btnUntrack").onclick = async () => {
  const sn = $("lostSn").value || $("ctlSn").value || "CN-WH01-9AF3C1D2";
  await postCtl({ action: "untrack", sn });
};

applyI18n();               // 本文件在 </body> 前加载，DOM 已就绪，直接应用
connect();
setInterval(refresh, 1000);
refresh();
