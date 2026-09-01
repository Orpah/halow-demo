/* TXW8301 模拟器 UI — 前端逻辑（无框架，纯 vanilla JS） */
"use strict";

const state = {
  A: { ok: false, conn: "OFFLINE", mode: "--", type: "--", port: "--",
       ssid: "-", rssi: 0, tx: 0, rx: 0, uptime: 0 },
  B: { ok: false, conn: "OFFLINE", mode: "--", type: "--", port: "--",
       ssid: "-", rssi: 0, tx: 0, rx: 0, uptime: 0 },
};
const consoles = { A: [], B: [] };
let frames = [];
let frameMonitor = false;

/* ---------------- 基础工具 ---------------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = () => new Date().toLocaleTimeString("zh-CN", { hour12: false });

function fetchCmd(dev, line, hex) {
  return fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device: dev, line: line, hex: !!hex }),
  }).catch(() => {});
}

async function sendCmd(dev, line, hex) {
  if (hex) {
    // HEX 模式：自动先进入数据模式（AT+TXDATA=<字节数>），再发原始字节，避免漏步
    const hexOnly = line.replace(/\s+/g, "");
    const n = hexOnly.length / 2;
    if (hexOnly.length % 2 !== 0) { alert("HEX 字节数必须是偶数"); return; }
    if (n < 14) { alert("以太网帧最短 14 字节（6 目的MAC + 6 源MAC + 2 类型）"); return; }
    await fetchCmd(dev, "AT+TXDATA=" + n, false);
    await new Promise((r) => setTimeout(r, 600));   // 等 sim 建立数据模式（防轮询/时序竞争）
  }
  await fetchCmd(dev, line, !!hex);
}

/* ---------------- 顶部标题副文字（按目标动态） ---------------- */
function loadBanner() {
  fetch("/api/info")
    .then((r) => r.json())
    .then((info) => {
      if (info && info.sub) $("bannerSub").textContent = info.sub;
      if (info && info.devices) {
        const links = Object.values(info.devices).map((d) => d.link || "");
        const serial = links.find((l) => l.startsWith("串口"));
        if (serial) $("linkLabel").textContent = serial;                 // 如 "串口 COM5"
        else if (links.some((l) => l.startsWith("UART2")))
          $("linkLabel").textContent = "UART2 物理空口";
        else $("linkLabel").textContent = "虚拟空口 (TCP)";
      }
    })
    .catch(() => {});
}

/* ---------------- SSE ---------------- */
function connectSSE() {
  const es = new EventSource("/api/events");
  es.onopen = () => { $("srvstatus").textContent = "已连接"; $("srvstatus").className = "badge ok"; };
  es.onerror = () => { $("srvstatus").textContent = "重连中…"; $("srvstatus").className = "badge"; };
  es.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    onEvent(m);
  };
}

function onEvent(m) {
  const d = m.device;
  switch (m.type) {
    case "status":
      if (d) { Object.assign(state[d], m.state); updateStatus(d); updateTopology(); }
      break;
    case "console":
      if (d) appendConsole(d, m.text);
      break;
    case "event":
      if (d) { appendConsole(d, m.text); flashNode(d); }
      break;
    case "frame":
      addFrame(d, m.dir, m.hex);
      break;
    case "log":
      appendConsole(d, m.text);
      break;
  }
}

/* ---------------- 状态 ---------------- */
function updateStatus(d) {
  const s = state[d];
  const connCls = { CONNECTED: "ok", SCANNING: "scan", ASSOCIATING: "scan",
                    PAIRING: "pair" }[s.conn] || "";
  $(`conn${d}`).textContent = s.conn || "OFFLINE";
  $(`conn${d}`).className = "conn " + connCls;
  $(`mode${d}`).textContent = s.mode || "--";
  $(`type${d}`).textContent = s.type || "--";
  $(`port${d}`).textContent = s.port || "--";
  $(`ssid${d}`).textContent = s.ssid || "-";
  $(`tx${d}`).textContent = s.tx ?? 0;
  $(`rx${d}`).textContent = s.rx ?? 0;
  $(`up${d}`).textContent = (s.uptime ?? 0) + "s";
  // RSSI 条（4 格）
  const v = Math.max(0, Math.min(4, s.rssi ? rssiBars(s.rssi) : 0));
  [...$(`rssi${d}`).children].forEach((el, i) =>
    el.classList.toggle("on", i < v));
}

function rssiBars(rssi) {
  const a = Math.abs(rssi);
  if (a <= 40) return 4;
  if (a <= 55) return 3;
  if (a <= 70) return 2;
  if (a <= 80) return 1;
  return 0;
}

function flashNode(d) {
  const n = $(`node${d}`);
  n.classList.add("flash");
  setTimeout(() => n.classList.remove("flash"), 600);
}

function updateTopology() {
  const a = state.A, b = state.B;
  const linked = (a.conn === "CONNECTED" || b.conn === "CONNECTED");
  $("linkState").textContent = linked ? "链路已建立 ✓" : "链路断开";
  $("linkState").className = "link-state " + (linked ? "ok" : "");
  // 数据流动画：有连接才流动
  $("linkState").parentElement.querySelector(".flow").classList.toggle("active", linked);
  $(`nodeA`).classList.toggle("linked", a.conn === "CONNECTED");
  $(`nodeB`).classList.toggle("linked", b.conn === "CONNECTED");
}

/* ---------------- 控制台 ---------------- */
function appendConsole(d, text) {
  const c = consoles[d];
  c.push(text);
  if (c.length > 500) c.shift();
  const pre = $(`console${d}`);
  pre.textContent = c.join("\n");
  pre.scrollTop = pre.scrollHeight;
}

function appendLog(text) {
  // 服务器级日志（无特定设备）——同时显示在两台控制台
  appendConsole("A", text);
  appendConsole("B", text);
}

/* ---------------- 帧监视器 ---------------- */
const ETH = { "0800": "IPv4", "0806": "ARP", "86dd": "IPv6", "88a1": "HaLow/PPPoE?" };

function addFrame(dev, dir, hexstr) {
  let bytes = [];
  for (let i = 0; i + 1 < hexstr.length; i += 2) {
    const b = parseInt(hexstr.substr(i, 2), 16);
    if (!isNaN(b)) bytes.push(b);
  }
  const row = { t: fmtTime(), dev, dir, bytes };
  frames.push(row);
  if (frames.length > 200) frames.shift();
  renderFrames();
  // 触发拓扑流动
  if (dir === "RX") flashNode(dev);
}

function renderFrames() {
  const tb = $("frameList");
  tb.innerHTML = "";
  for (const f of frames) {
    const tr = document.createElement("tr");
    const b = f.bytes;
    const dst = b.length >= 6 ? mac(b.slice(0, 6)) : "-";
    const src = b.length >= 12 ? mac(b.slice(6, 12)) : "-";
    const et = b.length >= 14 ? hex(b[12]) + hex(b[13]) : "";
    const hexline = b.length ? hexStr(b) : "(空)";
    const hint = b.length >= 14 ? ETH[et.toLowerCase()] || "0x" + et : "";
    tr.innerHTML =
      `<td>${f.t}</td>` +
      `<td class="dir ${f.dir === 'RX' ? 'rx' : 'tx'}">${f.dev} ⇠ ${f.dir}</td>` +
      `<td class="mono">${dst}</td>` +
      `<td class="mono">${src}</td>` +
      `<td>${esc(hint)}</td>` +
      `<td>${b.length} B</td>` +
      `<td class="mono hex" title="${esc(hexline)}">${esc(hexline.length > 96 ? hexline.slice(0, 96) + "…" : hexline)}</td>`;
    tb.appendChild(tr);
  }
}

const mac = (b) => b.map(hex).join(":");
const hex = (n) => n.toString(16).padStart(2, "0");
const hexStr = (b) => b.map(hex).join(" ");

/* ---------------- 配置面板 ---------------- */
function applyConfig() {
  const d = $("cfgDevice").value;
  const mode = $("cfgMode").value;
  const ssid = $("cfgSsid").value.trim();
  const key = $("cfgKey").value;
  const psk = $("cfgPsk").value.trim();
  const bw = $("cfgBw").value;
  const chan = $("cfgChan").value.trim();
  const cmds = [`AT+MODE=${mode}`, `AT+SSID=${ssid}`];
  if (key === "WPA-PSK") {
    if (!/^[0-9a-fA-F]{64}$/.test(psk)) { alert("PSK 必须是 64 位 hex"); return; }
    cmds.push("AT+KEYMGMT=WPA-PSK", `AT+PSK=${psk}`);
  } else {
    cmds.push("AT+KEYMGMT=NONE");
  }
  cmds.push(`AT+CHAN_LIST=${chan}`, `AT+BSS_BW=${bw}`);
  cmds.forEach((c) => sendCmd(d, c));
}

/* ---------------- 事件绑定 ---------------- */
function bindUI() {
  document.querySelectorAll(".send").forEach((b) =>
    b.addEventListener("click", () => {
      const d = b.dataset.dev;
      const inp = $(`cmd${d}`);
      const hex = $(`hex${d}`).checked;
      if (inp.value.trim()) { sendCmd(d, inp.value.trim(), hex); inp.value = ""; }
    }));
  ["A", "B"].forEach((d) =>
    $(`cmd${d}`).addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); document.querySelector(`.send[data-dev="${d}"]`).click(); }
    }));
  document.querySelectorAll(".quick button").forEach((b) =>
    b.addEventListener("click", () => sendCmd(b.closest(".quick").dataset.dev, b.dataset.cmd)));

  $("btnApply").addEventListener("click", applyConfig);
  $("btnClearConsole").addEventListener("click", () => { consoles.A = []; consoles.B = []; $(`consoleA`).textContent = ""; $(`consoleB`).textContent = ""; });
  $("btnClearFrames").addEventListener("click", () => { frames = []; renderFrames(); });

  $("btnFrameMonitor").addEventListener("click", () => {
    frameMonitor = !frameMonitor;
    $("btnFrameMonitor").textContent = "帧监视: " + (frameMonitor ? "开" : "关");
    $("btnFrameMonitor").classList.toggle("on", frameMonitor);
    ["A", "B"].forEach((d) => sendCmd(d, frameMonitor ? "AT+SYSDBG=WNB,1" : "AT+SYSDBG=WNB,0"));
  });
}

/* ---------------- 启动 ---------------- */
window.addEventListener("load", () => {
  // 初始拉一次状态
  fetch("/api/status").then((r) => r.json()).then((st) => {
    Object.keys(st).forEach((d) => { if (st[d]) Object.assign(state[d], st[d]); });
    ["A", "B"].forEach((d) => { updateStatus(d); });
    updateTopology();
  }).catch(() => {});
  loadBanner();
  bindUI();
  connectSSE();
});
