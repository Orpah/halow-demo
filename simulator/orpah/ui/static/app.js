/* ORPAH L1 demo UI — 前端逻辑：SSE 报文流 + 拓扑点亮 + 计数 + 控制 */
"use strict";

const $ = id => document.getElementById(id);
let paused = false;

const STAGE_NODE = {
  client: "nodeClient", router: "nodeRouter", server: "nodeServer",
  sta: "nodeSTA", ap: "nodeAP",
};
const STAGE_CLS = { client: "flash", router: "flash-r", server: "flash", sta: "flash", ap: "flash-r" };

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
  b.textContent = ok ? "已连接" : "连接断开";
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
  // 链路流动动画
  const linkFlow = document.querySelectorAll(".flow");
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

async function refresh() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("cntClient").textContent = s.client_sent;
    $("cntRouter").textContent = s.router_up;
    $("cntServer").textContent = s.server_recv;
    $("snClient").textContent = s.sn;
    $("connSTA").textContent = s.conn_b;
    $("connSTA").className = "conn" + (s.conn_b === "CONNECTED" ? " ok" : "");
    $("connAP").textContent = s.conn_a;
    $("connAP").className = "conn" + (s.conn_a === "CONNECTED" ? " ok" : "");
    $("chipSTA").textContent = s.conn_b;
    $("chipSTA").className = "chip" + (s.conn_b === "CONNECTED" ? " ok" : "");
    $("chipAP").textContent = s.conn_a;
    $("chipAP").className = "chip" + (s.conn_a === "CONNECTED" ? " ok" : "");
    // 芯片状态
    $("chipClient").textContent = s.conn_b;
    $("chipClient").className = "chip" + (s.conn_b === "CONNECTED" ? " ok" : "");
    $("chipRouter").textContent = s.conn_a;
    $("chipRouter").className = "chip" + (s.conn_a === "CONNECTED" ? " ok" : "");
    $("chipServer").textContent = s.server_recv > 0 ? "运行" : "监听";
    $("chipServer").className = "chip" + (s.server_recv > 0 ? " ok" : "");
    // 报文流表格（全量真相）
    const rows = (s.reports || []).map(x => ({
      ...x, tm: new Date((x.ts || 0) * 1000).toTimeString().slice(0, 8),
    }));
    renderRows(rows);
    // 控制面板回显
    if (!document.activeElement || document.activeElement.id !== "ctlSn")
      $("ctlSn").value = s.sn;
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
  $("btnPause").textContent = paused ? "继续上报" : "暂停上报";
};
$("btnReset").onclick = () => {
  Object.keys(seenRows).forEach(k => delete seenRows[k]);
  $("msgList").innerHTML = "";
};
$("btnApply").onclick = async () => {
  await postCtl({
    action: "every", every: parseFloat($("ctlEvery").value) || 2,
  });
  await postCtl({ action: "set_sn", sn: $("ctlSn").value || "ORPAH-0001" });
};

connect();
setInterval(refresh, 1000);
refresh();
