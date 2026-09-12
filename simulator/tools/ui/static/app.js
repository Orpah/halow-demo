/* TXW8301 模拟器 UI — 前端逻辑（无框架，纯 vanilla JS） */
"use strict";

const T = (k) => OrpahI18n.t(k);

/* 按语言取时间格式（仅数字时:分:秒，两个 locale 视觉一致） */
const localeOf = () => (OrpahI18n.lang === "en" ? "en-GB" : "zh-CN");

/* 设备标签 / 顶部副标题：一律用后端给的结构化字段（source/target/pname）
 * 在前端拼——不要解析 device_type() 拼好的字符串，那串已按当前语言本地化，
 * 切语言/换语言后解析必错。 */
const locKeyOf = (source) => (source === "pc" ? "dt_pc" : "dt_serial");

function typeText(s) {
  const pname = (s && s.pname) || "";
  if (!pname) return (s && s.type) || "";      // 后端未给结构化字段时回退
  return pname + " " + T(locKeyOf(s.source));
}

function bannerText(devs) {
  const items = Object.entries(devs || {}).map(([n, d]) => ({
    n, pname: d.pname || d.target || "?", locKey: locKeyOf(d.source),
  }));
  if (!items.length) return T("bs_sim0");
  const uniq = new Set(items.map(i => i.pname + "|" + i.locKey));
  if (uniq.size === 1) {
    const i = items[0];
    if (i.locKey === "dt_pc" && i.pname === "CH32V203") return T("bs_sim0");
    if (i.locKey === "dt_pc") return i.pname + " " + T("bs_virtual");
    return i.pname + " " + T("dt_serial");
  }
  return items.map(i => `${i.n}: ${i.pname} ${T(i.locKey)}`).join(" · ");
}

/* 物理互联介质标签：后端已按语言拼好（Serial COM3 / TCP :9601 / UART2…），
 * 空值（PC↔PC 走虚拟空口）时回退到字典。 */
function linkText(raw) {
  const s = String(raw || "").trim();
  return s || T("tui_air_virtual");
}

const state = {
  A: { ok: false, conn: "OFFLINE", mode: "--", type: "--", port: "--", version: "", v2: false,
       ssid: "-", rssi: 0, tx: 0, rx: 0, uptime: 0, power: "on", chan: "", bw: 0,
       source: "", target: "",
       // 发射功率 / 距离模型 / 关联 STA（null = 该设备报不出来，界面显示 “-”）
       txpower: null, dist: 0, pathloss: null, stacnt: null, stas: [] },
  B: { ok: false, conn: "OFFLINE", mode: "--", type: "--", port: "--", version: "", v2: false,
       ssid: "-", rssi: 0, tx: 0, rx: 0, uptime: 0, power: "on", chan: "", bw: 0,
       source: "", target: "",
       txpower: null, dist: 0, pathloss: null, stacnt: null, stas: [] },
};
const consoles = { A: [], B: [] };
let frames = [];
let frameMonitor = false;

/* AT 命令提示库（TXW8301 / T-Halow-RJ45 兼容）
 * 命令本身语言中立，说明文字全部放共享字典（key = "at:def:<cmd>"），见 atHint()。 */
const AT_CMDS = [
  { cmd: "AT+MODE=" }, { cmd: "AT+MODE?" },
  { cmd: "AT+SSID=" }, { cmd: "AT+SSID?" },
  { cmd: "AT+KEYMGMT=" }, { cmd: "AT+PSK=" },
  { cmd: "AT+PAIR=" }, { cmd: "AT+BSS_BW=" },
  { cmd: "AT+FREQ_RANGE=" }, { cmd: "AT+CHAN_LIST=" },
  { cmd: "AT+RSSI" }, { cmd: "AT+CONN_STATE" }, { cmd: "AT+WNBCFG" },
  { cmd: "AT+STALIST" }, { cmd: "AT+DIST=" }, { cmd: "AT+PATHLOSS=" },
  { cmd: "AT+SCAN_AP" }, { cmd: "AT+BSSLIST" },
  { cmd: "AT+TXPOWER=" }, { cmd: "AT+ACKTMO=" }, { cmd: "AT+TX_MCS=" },
  { cmd: "AT+HEART_INT=" }, { cmd: "AT+UNPAIR=" }, { cmd: "AT+LOADDEF=" },
  { cmd: "AT+SYSDBG=" }, { cmd: "AT+JOINGROUP=" },
  { cmd: "AT+R_SSID=" }, { cmd: "AT+R_PSK=" }, { cmd: "AT+ROAM=" },
  { cmd: "AT+PS_MODE=" }, { cmd: "AT+WAKEUP" }, { cmd: "AT+VERSION" },
  { cmd: "AT+MAC_ADDR" }, { cmd: "AT+TXDATA=" }, { cmd: "AT+RST" },
];

/* TX-AH 泰芯真机（AH-SDK V2.x 固件 v2.4.1.x）命令提示库：真机串口(txah)用。
   与 T-Halow(tj45)/模拟器方言不同：设模式 AT+WIFIMODE=、查询带 '?'、无 AT+MODE/CONN_STATE。 */
const CMDS_TAHV2 = [
  { cmd: "AT+WIFIMODE=" }, { cmd: "AT+WIFIMODE=?" },
  { cmd: "AT+SSID=" }, { cmd: "AT+SSID=?" },
  { cmd: "AT+ENCRYPT=" }, { cmd: "AT+KEY=" }, { cmd: "AT+PAIR=" },
  { cmd: "AT+CHAN_LIST=" }, { cmd: "AT+CHAN_LIST=?" },
  { cmd: "AT+BSS_BW=" }, { cmd: "AT+BSS_BW=?" }, { cmd: "AT+CHANNEL=" },
  { cmd: "AT+SCAN" }, { cmd: "AT+SYSCFG" }, { cmd: "AT+RSSI=?" },
  { cmd: "AT+MAC_ADDR=?" }, { cmd: "AT+TXPOWER=" }, { cmd: "AT+ACK_TO=" },
  { cmd: "AT+UNPAIR=" }, { cmd: "AT+APHIDE=" }, { cmd: "AT+ROAM=" },
  { cmd: "AT+R_SSID=" }, { cmd: "AT+R_KEY=" }, { cmd: "AT+WAKEUP=" },
  { cmd: "AT+DSLEEP=" }, { cmd: "AT+SYSDBG=" }, { cmd: "AT+LOADDEF=" },
  { cmd: "AT+RST" }, { cmd: "AT+VERSION" }, { cmd: "AT+PING=" },
  { cmd: "AT+TEST_START=" },
];

/* 命令库取值："def"=默认方言 / "v2"=泰芯 V2.x；字典 key = "at:<库>:<命令>"。
 * 注：AT+SYSDBG= 在两个库里说明不同，故 key 必须带库名。 */
function atHint(lib, cmd) {
  const k = "at:" + lib + ":" + cmd;
  const s = OrpahI18n.t(k);
  return s === k ? "" : s;      // 字典缺键 → 空串
}
const cmdLib = (d) => (devV2[d] ? "v2" : "def");

/* 快捷按钮悬停说明：字典 key = "qt:<命令>"。 */
function qtHint(cmd) {
  const k = "qt:" + cmd;
  const s = OrpahI18n.t(k);
  return s === k ? "" : s;
}

// 每台设备当前的命令提示库与泰芯 V2.x 真机方言标记（loadBanner 按 /api/info 填充）
const devCmd = { A: AT_CMDS, B: AT_CMDS };
const devV2 = { A: false, B: false };

// 快捷按钮：默认(T-Halow/模拟器方言) vs 泰芯 V2.x 真机方言
const QUICK_BTNS = {
  def: [
    ["MODE?", "AT+MODE?"], ["CONN", "AT+CONN_STATE"],
    ["RSSI", "AT+RSSI"], ["SSID?", "AT+SSID?"],
    ["PAIR=1", "AT+PAIR=1"], ["PAIR=0", "AT+PAIR=0"],
    ["WNBCFG", "AT+WNBCFG"],
    ["LMAC=0", "AT+SYSDBG=LMAC,0"],
    ["RST", "AT+RST"],
  ],
  v2: [
    ["MODE", "AT+WIFIMODE=?"],
    ["RSSI", "AT+RSSI=?"],
    ["SSID?", "AT+SSID=?"],
    ["SCAN", "AT+SCAN"],
    ["PAIR=1", "AT+PAIR=1"],
    ["PAIR=0", "AT+PAIR=0"],
    ["SYSCFG", "AT+SYSCFG"],
    ["LMAC=0", "AT+SYSDBG=LMAC,0"],
    ["RST", "AT+RST"],
  ],
};

function renderQuick(d) {
  const box = document.querySelector(`.quick[data-dev="${d}"]`);
  if (!box) return;
  box.innerHTML = "";
  (devV2[d] ? QUICK_BTNS.v2 : QUICK_BTNS.def).forEach(([label, cmd]) => {
    const b = document.createElement("button");
    b.dataset.cmd = cmd;
    const t = qtHint(cmd);          // 悬停说明来自字典，缺键则不设 title
    if (t) b.title = t;
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
const fmtTime = () => new Date().toLocaleTimeString(localeOf(), { hour12: false });

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
    if (hexOnly.length % 2 !== 0) { alert(T("tui_hex_even")); return; }
    if (n < 14) { alert(T("tui_eth_min")); return; }
    await fetchCmd(dev, "AT+TXDATA=" + n, false);
    await new Promise((r) => setTimeout(r, 600));   // 等 sim 建立数据模式（防轮询/时序竞争）
  }
  await fetchCmd(dev, line, !!hex);
}

/* ---------------- 顶部标题副文字（按目标动态） ---------------- */
function loadBanner() {
  // 带 ?lang= → 后端把「设备标签/控制台叙述行」也切到同一语言
  fetch("/api/info?lang=" + encodeURIComponent(OrpahI18n.lang))
    .then((r) => r.json())
    .then((info) => {
      if (info && info.devices) {
        $("bannerSub").textContent = bannerText(info.devices);
        // 物理互联介质标签：优先显示第一条“真实介质”（串口直连 / UART2 交叉 / RF 空口）
        const links = Object.values(info.devices).map((d) => d.link || "");
        const real = links.find((l) => l && !l.startsWith("TCP"));
        $("linkLabel").textContent = linkText(real);
        // 每台设备按方言选命令库 + 渲染快捷按钮（泰芯 V2.x 真机 vs 默认）
        ["A", "B"].forEach((k) => {
          const d = info.devices[k];
          devV2[k] = !!(d && d.v2);
          devCmd[k] = devV2[k] ? CMDS_TAHV2 : AT_CMDS;
          renderQuick(k);
        });
      } else if (info && info.sub) {
        $("bannerSub").textContent = info.sub;   // 后端未给结构化字段时回退原文
      }
    })
    .catch(() => {});
}

/* ---------------- SSE ---------------- */
function connectSSE() {
  const es = new EventSource("/api/events");
  es.onopen = () => { $("srvstatus").textContent = T("tui_srv_ok"); $("srvstatus").className = "badge ok"; };
  es.onerror = () => { $("srvstatus").textContent = T("tui_srv_retry"); $("srvstatus").className = "badge"; };
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
  // 方言（v2）可能在连接后由后端探测才确定 → 若与当前命令库不一致，切换该台命令库/快捷按钮
  if (s.v2 !== devV2[d]) {
    devV2[d] = !!s.v2;
    devCmd[d] = devV2[d] ? CMDS_TAHV2 : AT_CMDS;
    renderQuick(d);
  }
  // 显示用中文映射：仅前端展示文案；机器值仍是英文（CONNECTED/AP…），
  // 后端逻辑、/api/status、测试等都不受影响（拓扑判定读的是 s.conn 机器值）。
  // 文案统一来自共享字典 ui_i18n.js（OrpahI18n，zh/en 单一源），改一处全 UI 生效。
  const tOr = (prefix, val, fb) => {      // 字典取词；无该键（返回 key 自身）→ 回退
    const k = prefix + val, s = OrpahI18n.t(k);
    return (s === k) ? fb : s;
  };
  const connCls = { CONNECTED: "ok", SCANNING: "scan", ASSOCIATING: "scan",
                    PAIRING: "pair" }[s.conn] || "";
  $(`conn${d}`).textContent = tOr("conn_", s.conn, s.conn || T("conn_OFFLINE"));
  $(`conn${d}`).className = "conn " + connCls;
  const powTxt = tOr("pow_", s.power, null);
  $(`pow${d}`).textContent = powTxt || "--";
  $(`pow${d}`).className = "chip pow " + (s.power === "on" ? "ok" : "off");
  $(`mode${d}`).textContent = tOr("mode_", s.mode, s.mode || "--");
  $(`type${d}`).textContent = typeText(s) || "--";
  // 端口行：串口号 + 固件版本合并成一行（如 “COM6 v2.4.1.3-39777, app:0”）
  $(`port${d}`).textContent = (s.port || "--") + (s.version ? " " + s.version : "");
  $(`ssid${d}`).textContent = s.ssid || "-";
  // 频点/带宽：后端 chan 为 ×10 频点列表（如 9160），÷10 显示为 MHz
  const cf = String(s.chan || "").split(",").map((x) => x.trim()).filter(Boolean)
    .map((x) => Math.round(Number(x)) / 10).join("/");
  $(`chan${d}`).textContent = cf ? cf + " MHz" : "-";
  $(`bw${d}`).textContent = s.bw ? s.bw + " MHz" : "-";
  $(`tx${d}`).textContent = s.tx ?? 0;
  $(`rx${d}`).textContent = s.rx ?? 0;
  $(`up${d}`).textContent = (s.uptime ?? 0) + "s";
  // 发射功率（+ 距离模型的米数）/ 关联 STA 数：真机报不出来的字段显示 “-”（不编值）
  $(`txpow${d}`).textContent = (s.txpower === null || s.txpower === undefined)
    ? "-" : (s.txpower + " dBm" + (s.dist ? " @ " + s.dist + "m" : ""));
  $(`sta${d}`).textContent = (s.stacnt === null || s.stacnt === undefined) ? "-" : s.stacnt;
  const sl = $(`staList${d}`);
  if (sl) {
    const rows = (s.stas || []).map((x) => `${x.mac} ${x.rssi}dBm`);
    sl.textContent = rows.join("  ·  ");
    sl.title = rows.join("\n");
  }
  // RSSI 条（4 格）+ dBm 数值（v2=TX-AH 是 dBm；其它只显数字，不硬加单位防误导）
  let v = Math.max(0, Math.min(4, s.rssi ? rssiBars(s.rssi) : 0));
  if (s.rssi && v < 1) v = 1;   // 有信号(已关联)至少 1 格：弱链路(-80 以下)也别显示成“无信号”
  [...$(`rssi${d}`).querySelectorAll("i")].forEach((el, i) =>
    el.classList.toggle("on", i < v));
  const rt = $(`rssiTxt${d}`);
  if (rt) rt.textContent = s.rssi ? (s.rssi + (devV2[d] ? " dBm" : "")) : "";
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
  $("linkState").textContent = linked ? T("tui_link_up") : T("tui_link_down");
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
  const box = pre.parentElement;          // .console = 真正滚动容器（overflow:auto）
  // 之前是否在底部附近：是则内容更新后跟随到底；用户向上翻历史时不强拉回
  const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  pre.innerHTML = consoles[d].map((l) => {
    if (l.kind === "spam") {
      const body = l.open
        ? `<div class="ac-spam-body">${l.lines.map((x) => esc(x)).join("\n")}</div>` : "";
      return `<div class="ac-spam" data-id="${l.id}"><span class="ac-spam-mark">${l.open ? "▼" : "▶"}</span> ${esc(T("tui_spam"))}</div>${body}`;
    }
    const tx = l.dir === "tx";
    const mark = tx ? "→ " : "← ";
    return `<span class="c-${tx ? "tx" : "rx"}">${esc(mark + l.text)}</span>`;
  }).join("\n");
  if (stick) box.scrollTop = box.scrollHeight;   // 之前 pre.scrollTop 无效：滚动容器是父 .console
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
    const hexline = b.length ? hexStr(b) : T("tui_empty");
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
      if (psk.length < 8) { alert(T("tui_key_min")); return; }
      cmds.push("AT+ENCRYPT=1", `AT+KEY=${psk}`);
    } else {
      cmds.push("AT+ENCRYPT=0");
    }
  } else {
    cmds = [`AT+MODE=${mode}`, `AT+SSID=${ssid}`];
    if (key === "WPA-PSK") {
      if (!/^[0-9a-fA-F]{64}$/.test(psk)) { alert(T("tui_psk_hex")); return; }
      cmds.push("AT+KEYMGMT=WPA-PSK", `AT+PSK=${psk}`);
    } else {
      cmds.push("AT+KEYMGMT=NONE");
    }
  }
  cmds.push(`AT+CHAN_LIST=${chan}`, `AT+BSS_BW=${bw}`);
  const tx = $("cfgTx") ? $("cfgTx").value : "";
  if (tx) cmds.push(`AT+TXPOWER=${tx}`);     // 真机也支持（TX-AH V2 同样有 TXPOWER）
  cmds.forEach((c) => sendCmd(d, c));
  // 距离模型是本模拟器扩展，而且是**链路属性**（每个方向各自算：RSSI = 对端发射功率 − 本机设的距离损耗）
  // → 同时下发给两台 PC 模拟器；真机没有这两条命令（会回 ERROR），所以只对模拟器发。
  const dist = $("cfgDist") ? $("cfgDist").value.trim() : "";
  if (dist !== "") {
    const sims = ["A", "B"].filter((x) => state[x].source === "pc");
    if (!sims.length) {
      alert(T("tui_cfg_pl_hint"));
      return;
    }
    const pl = $("cfgPl") ? $("cfgPl").value : "";
    sims.forEach((x) => {
      sendCmd(x, `AT+DIST=${dist}`);
      if (pl) sendCmd(x, `AT+PATHLOSS=${pl}`);
    });
  }
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
    div.innerHTML = `<span class="ac-cmd">${esc(c.cmd)}</span><span class="ac-hint">${esc(atHint(cmdLib(d), c.cmd))}</span>`;
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
    $("btnFrameMonitor").textContent = T("tui_fm")
      .replace("{s}", frameMonitor ? T("tui_fm_on") : T("tui_fm_off"));
    $("btnFrameMonitor").classList.toggle("on", frameMonitor);
    ["A", "B"].forEach((d) => sendCmd(d, frameMonitor ? "AT+SYSDBG=WNB,1" : "AT+SYSDBG=WNB,0"));
  });
}

/* ---------------- 启动 ---------------- */
window.addEventListener("load", () => {
  OrpahI18n.apply();
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
