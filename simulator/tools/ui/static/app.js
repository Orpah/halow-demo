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

/* AT 命令提示库（TXW8301 / T-Halow-RJ45 兼容） */
const AT_CMDS = [
  { cmd: "AT+MODE=", hint: "[ap/sta/group/apsta] 工作模式" },
  { cmd: "AT+MODE?", hint: "查询当前模式" },
  { cmd: "AT+SSID=", hint: "[ssid] 网络名（≤32字符）" },
  { cmd: "AT+SSID?", hint: "查询 SSID" },
  { cmd: "AT+KEYMGMT=", hint: "[WPA-PSK/NONE] 加密方式" },
  { cmd: "AT+PSK=", hint: "[64位hex] 加密密码" },
  { cmd: "AT+PAIR=", hint: "[0/1] 快速配对" },
  { cmd: "AT+BSS_BW=", hint: "[1/2/4/8] 带宽 MHz" },
  { cmd: "AT+FREQ_RANGE=", hint: "[起始,结束] 频率范围 MHz" },
  { cmd: "AT+CHAN_LIST=", hint: "[freq1,freq2,...] 工作频率列表" },
  { cmd: "AT+RSSI", hint: "[?/索引/MAC] 查询信号强度" },
  { cmd: "AT+CONN_STATE", hint: "查看连接状态" },
  { cmd: "AT+WNBCFG", hint: "查看设备参数" },
  { cmd: "AT+SCAN_AP", hint: "扫描 AP（STA 模式）" },
  { cmd: "AT+BSSLIST", hint: "获取扫描到的 AP 列表" },
  { cmd: "AT+TXPOWER=", hint: "[6..20] 发射功率 dBm" },
  { cmd: "AT+ACKTMO=", hint: "[us] ACK 超时（>1km 通信时）" },
  { cmd: "AT+TX_MCS=", hint: "[0..7/255] TX MCS" },
  { cmd: "AT+HEART_INT=", hint: "[ms] 心跳间隔" },
  { cmd: "AT+UNPAIR=", hint: "[mac_addr] 解除指定 STA 配对" },
  { cmd: "AT+LOADDEF=", hint: "[1] 恢复出厂设置" },
  { cmd: "AT+SYSDBG=", hint: "[LMAC/WNB,0/1] 调试打印开关" },
  { cmd: "AT+JOINGROUP=", hint: "[组播地址,AID] 加入组播网络" },
  { cmd: "AT+R_SSID=", hint: "[ssid] 中继上级 AP 的 SSID" },
  { cmd: "AT+R_PSK=", hint: "[64hex] 中继上级 AP 的密码" },
  { cmd: "AT+ROAM=", hint: "[0/1] 漫游开关（STA 侧）" },
  { cmd: "AT+PS_MODE=", hint: "[0..4] STA 休眠模式" },
  { cmd: "AT+WAKEUP", hint: "唤醒休眠模块" },
  { cmd: "AT+VERSION", hint: "查询固件版本" },
  { cmd: "AT+MAC_ADDR", hint: "查询本机 MAC 地址" },
  { cmd: "AT+TXDATA=", hint: "[长度] 进入数据模式发送数据" },
  { cmd: "AT+RST", hint: "复位模块" },
];

/* TX-AH 泰芯真机（AH-SDK V2.x 固件 v2.4.1.x）命令提示库：真机串口(txah)用。
   与 T-Halow(tj45)/模拟器方言不同：设模式 AT+WIFIMODE=、查询带 '?'、无 AT+MODE/CONN_STATE。 */
const CMDS_TAHV2 = [
  { cmd: "AT+WIFIMODE=", hint: "[ap/sta/apsta] 工作模式" },
  { cmd: "AT+WIFIMODE=?", hint: "查询当前模式" },
  { cmd: "AT+SSID=", hint: "[ssid] 网络名（≤32字符）" },
  { cmd: "AT+SSID=?", hint: "查询 SSID" },
  { cmd: "AT+ENCRYPT=", hint: "[0/1] 加密开关" },
  { cmd: "AT+KEY=", hint: "[≥8字符] 加密密钥（ASCII）" },
  { cmd: "AT+PAIR=", hint: "[0/1/2] 快速配对（成功后 AT+PAIR=0 建链）" },
  { cmd: "AT+CHAN_LIST=", hint: "[freq1,freq2,...] 工作频率（AP/STA 须完全一致）" },
  { cmd: "AT+CHAN_LIST=?", hint: "查询信道列表" },
  { cmd: "AT+BSS_BW=", hint: "[1/2/4/8] 带宽 MHz" },
  { cmd: "AT+BSS_BW=?", hint: "查询带宽" },
  { cmd: "AT+CHANNEL=", hint: "[序号] AP 端工作信道序号" },
  { cmd: "AT+SCAN", hint: "扫描周围 AP（结果看 UMAC 打印 AT+SYSDBG=UMAC,1）" },
  { cmd: "AT+SYSCFG", hint: "查看设备参数" },
  { cmd: "AT+RSSI=?", hint: "查询信号强度（关联后非 0）" },
  { cmd: "AT+MAC_ADDR=?", hint: "查询本机 MAC" },
  { cmd: "AT+TXPOWER=", hint: "[1..20] 发射功率 dBm" },
  { cmd: "AT+ACK_TO=", hint: "[us] ACK 超时（>1km 通信时）" },
  { cmd: "AT+UNPAIR=", hint: "[mac] 解除指定 STA 配对" },
  { cmd: "AT+APHIDE=", hint: "[0/1] 隐藏 AP（1=扫描不到）" },
  { cmd: "AT+ROAM=", hint: "[0/1] 漫游开关（STA 侧）" },
  { cmd: "AT+R_SSID=", hint: "[ssid] 中继下级 SSID" },
  { cmd: "AT+R_KEY=", hint: "[key≥8] 中继下级密钥" },
  { cmd: "AT+WAKEUP=", hint: "[mac] 唤醒休眠 STA（AP 端）" },
  { cmd: "AT+DSLEEP=", hint: "[1] 进入休眠" },
  { cmd: "AT+SYSDBG=", hint: "[LMAC/UMAC/WNB,0/1] 调试打印开关" },
  { cmd: "AT+LOADDEF=", hint: "[1] 恢复出厂设置" },
  { cmd: "AT+RST", hint: "复位模块（重启固件）" },
  { cmd: "AT+VERSION", hint: "查询固件版本" },
  { cmd: "AT+PING=", hint: "[ip,次数,size] ping（需网络宏）" },
  { cmd: "AT+TEST_START=", hint: "[0/1] 进入/退出 RF 测试模式" },
];

// 每台设备当前的命令提示库与泰芯 V2.x 真机方言标记（loadBanner 按 /api/info 填充）
const devCmd = { A: AT_CMDS, B: AT_CMDS };
const devV2 = { A: false, B: false };

// 快捷按钮：默认(T-Halow/模拟器方言) vs 泰芯 V2.x 真机方言
const QUICK_BTNS = {
  def: [
    ["MODE?", "AT+MODE?", ""], ["CONN", "AT+CONN_STATE", ""],
    ["RSSI", "AT+RSSI", ""], ["SSID?", "AT+SSID?", ""],
    ["PAIR=1", "AT+PAIR=1", ""], ["PAIR=0", "AT+PAIR=0", ""],
    ["WNBCFG", "AT+WNBCFG", ""],
    ["LMAC=0", "AT+SYSDBG=LMAC,0", "关闭 LMAC 调试打印"],
    ["RST", "AT+RST", "复位模块（重启固件）"],
  ],
  v2: [
    ["MODE", "AT+WIFIMODE=?", "查询模式（设模式用 AT+WIFIMODE=ap/sta）"],
    ["RSSI", "AT+RSSI=?", "查询信号强度（关联后非 0）"],
    ["SSID?", "AT+SSID=?", "查询 SSID"],
    ["SCAN", "AT+SCAN", "扫描周围 AP（结果看 UMAC 打印）"],
    ["PAIR=1", "AT+PAIR=1", "启动快速配对"],
    ["PAIR=0", "AT+PAIR=0", "停止配对并自动建链"],
    ["SYSCFG", "AT+SYSCFG", "查看设备参数"],
    ["LMAC=0", "AT+SYSDBG=LMAC,0", "关闭 LMAC 调试打印"],
    ["RST", "AT+RST", "复位模块（重启固件）"],
  ],
};

function renderQuick(d) {
  const box = document.querySelector(`.quick[data-dev="${d}"]`);
  if (!box) return;
  box.innerHTML = "";
  (devV2[d] ? QUICK_BTNS.v2 : QUICK_BTNS.def).forEach(([label, cmd, title]) => {
    const b = document.createElement("button");
    b.dataset.cmd = cmd;
    if (title) b.title = title;
    b.textContent = label;
    b.addEventListener("click", () => sendCmd(d, cmd));
    box.appendChild(b);
  });
}
const acState = { A: { list: [], idx: 0 }, B: { list: [], idx: 0 } };

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
        // 物理互联介质标签：优先显示第一条“真实介质”（串口直连 / UART2 交叉 / RF 空口）
        const links = Object.values(info.devices).map((d) => d.link || "");
        const real = links.find((l) => l && !l.startsWith("TCP"));
        $("linkLabel").textContent = real || "虚拟空口 (TCP)";
        // 每台设备按方言选命令库 + 渲染快捷按钮（泰芯 V2.x 真机 vs 默认）
        ["A", "B"].forEach((k) => {
          const d = info.devices[k];
          devV2[k] = !!(d && d.v2);
          devCmd[k] = devV2[k] ? CMDS_TAHV2 : AT_CMDS;
          renderQuick(k);
        });
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
      if (d) appendConsole(d, m.text, m.dir);
      break;
    case "event":
      if (d) { appendConsole(d, m.text, m.dir || "rx"); flashNode(d); }
      break;
    case "frame":
      addFrame(d, m.dir, m.hex);
      break;
    case "log":
      appendConsole(d, m.text, m.dir || "rx");
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
let spamSeq = 0;   // 折叠块唯一 id

// 真机固件周期打印（LMAC 状态/SSID 等）→ 折叠成可展开块，避免刷屏
function isSpam(t) {
  return /^(-{3,}|\[\d+\](LMAC STATUS|SSID:)|freq= \d|bgr:|chn:|buf:|irq:|cca:|sta_list|chip-temperat|\btx :|\brx :)/.test(t);
}

function renderConsole(d) {
  const pre = $(`console${d}`);
  pre.innerHTML = consoles[d].map((l) => {
    if (l.kind === "spam") {
      const body = l.open
        ? `<div class="ac-spam-body">${l.lines.map((x) => esc(x)).join("\n")}</div>` : "";
      return `<div class="ac-spam" data-id="${l.id}"><span class="ac-spam-mark">${l.open ? "▼" : "▶"}</span> 设备自动调试信息</div>${body}`;
    }
    const tx = l.dir === "tx";
    const mark = tx ? "→ " : "← ";
    return `<span class="c-${tx ? "tx" : "rx"}">${esc(mark + l.text)}</span>`;
  }).join("\n");
  pre.scrollTop = pre.scrollHeight;
  pre.querySelectorAll(".ac-spam").forEach((el) => {
    el.addEventListener("click", () => {
      const item = consoles[d].find((x) => x.kind === "spam" && x.id === Number(el.dataset.id));
      if (item) { item.open = !item.open; renderConsole(d); }
    });
  });
}

function appendConsole(d, text, dir) {
  const c = consoles[d];
  if (isSpam(text)) {
    const last = c[c.length - 1];
    if (last && last.kind === "spam") {
      last.lines.push(text);
      if (last.lines.length > 50) last.lines.shift();   // 单块最多留 50 行
    } else {
      c.push({ kind: "spam", id: ++spamSeq, lines: [text], open: false });
    }
  } else {
    c.push({ kind: "line", text, dir });
  }
  if (c.length > 500) c.shift();
  renderConsole(d);
}

function clearConsole(d) {
  consoles[d] = [];
  $(`console${d}`).textContent = "";
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
  const isV2 = devV2[d];
  const mode = $("cfgMode").value;
  const ssid = $("cfgSsid").value.trim();
  const key = $("cfgKey").value;
  const psk = $("cfgPsk").value.trim();
  const bw = $("cfgBw").value;
  const chan = $("cfgChan").value.trim();
  let cmds;
  if (isV2) {
    // 泰芯 V2.x：AT+WIFIMODE（小写）/ AT+ENCRYPT / AT+KEY
    cmds = [`AT+WIFIMODE=${mode.toLowerCase()}`, `AT+SSID=${ssid}`];
    if (key === "WPA-PSK") {
      if (psk.length < 8) { alert("KEY 需 ≥8 个 ASCII 字符"); return; }
      cmds.push("AT+ENCRYPT=1", `AT+KEY=${psk}`);
    } else {
      cmds.push("AT+ENCRYPT=0");
    }
  } else {
    cmds = [`AT+MODE=${mode}`, `AT+SSID=${ssid}`];
    if (key === "WPA-PSK") {
      if (!/^[0-9a-fA-F]{64}$/.test(psk)) { alert("PSK 必须是 64 位 hex"); return; }
      cmds.push("AT+KEYMGMT=WPA-PSK", `AT+PSK=${psk}`);
    } else {
      cmds.push("AT+KEYMGMT=NONE");
    }
  }
  cmds.push(`AT+CHAN_LIST=${chan}`, `AT+BSS_BW=${bw}`);
  cmds.forEach((c) => sendCmd(d, c));
}

/* ---------------- AT 命令输入提示 ---------------- */
function acFilter(d) {
  const v = $(`cmd${d}`).value.trim().toUpperCase();
  const list = devCmd[d] || AT_CMDS;
  if (!v || $(`hex${d}`).checked) return [];   // HEX 模式不提示 AT 命令
  if (v === "AT" || v === "AT+") return list;
  return list.filter((c) => c.cmd.toUpperCase().startsWith(v));
}

function renderAC(d, list) {
  const s = acState[d];
  const menu = $(`acMenu${d}`);
  menu.innerHTML = "";
  list.forEach((c, i) => {
    const div = document.createElement("div");
    div.className = "ac-item" + (i === s.idx ? " active" : "");
    div.innerHTML = `<span class="ac-cmd">${esc(c.cmd)}</span><span class="ac-hint">${esc(c.hint)}</span>`;
    div.addEventListener("mousedown", (e) => { e.preventDefault(); acPick(d, c.cmd); });
    div.addEventListener("mouseenter", () => { s.idx = i; renderAC(d, list); });
    menu.appendChild(div);
  });
  menu.hidden = list.length === 0;
}

function acPick(d, cmd) {
  $(`cmd${d}`).value = cmd;
  $(`acMenu${d}`).hidden = true;
  $(`cmd${d}`).focus();
}

function handleACKey(d, e) {
  const s = acState[d];
  const menu = $(`acMenu${d}`);
  if (menu.hidden) return false;
  if (e.key === "ArrowDown") { e.preventDefault(); s.idx = (s.idx + 1) % s.list.length; renderAC(d, s.list); return true; }
  if (e.key === "ArrowUp") { e.preventDefault(); s.idx = (s.idx - 1 + s.list.length) % s.list.length; renderAC(d, s.list); return true; }
  if (e.key === "Escape") { e.preventDefault(); menu.hidden = true; return true; }
  if (e.key === "Enter" || e.key === "Tab") {
    const c = s.list[s.idx];
    if (c) { e.preventDefault(); acPick(d, c.cmd); return true; }
  }
  return false;
}

function setupAutocomplete(d) {
  const inp = $(`cmd${d}`);
  inp.addEventListener("input", () => {
    acState[d].list = acFilter(d);
    acState[d].idx = 0;
    renderAC(d, acState[d].list);
  });
  inp.addEventListener("blur", () => setTimeout(() => { $(`acMenu${d}`).hidden = true; }, 150));
  $(`hex${d}`).addEventListener("change", () => { $(`acMenu${d}`).hidden = true; });
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
  ["A", "B"].forEach((d) => {
    setupAutocomplete(d);
    $(`cmd${d}`).addEventListener("keydown", (e) => {
      if (handleACKey(d, e)) return;            // 补全优先（↑/↓ 导航、Enter/Tab 选中、Esc 关闭）
      if (e.key === "Enter") { e.preventDefault(); document.querySelector(`.send[data-dev="${d}"]`).click(); }
    });
  });
  document.querySelectorAll(".quick button").forEach((b) =>
    b.addEventListener("click", () => sendCmd(b.closest(".quick").dataset.dev, b.dataset.cmd)));

  $("btnApply").addEventListener("click", applyConfig);
  $("clearA").addEventListener("click", () => clearConsole("A"));
  $("clearB").addEventListener("click", () => clearConsole("B"));
  // Ctrl+L 清屏：聚焦哪台清哪台，未聚焦输入框则两台都清
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "l") {
      e.preventDefault();
      const ae = document.activeElement;
      if (ae === $("cmdA")) clearConsole("A");
      else if (ae === $("cmdB")) clearConsole("B");
      else { clearConsole("A"); clearConsole("B"); }
    }
  });
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
