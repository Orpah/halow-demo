/* ui_i18n.js — UI 文案字典（zh/en 双语，本项目自持一份）
 * ==================================================
 * 用法：<script src="ui_i18n.js"></script> → OrpahI18n.t("key") / setLang("en") / fmt("key", v)。
 * 语言解析顺序：URL ?lang= → localStorage("orpah_ui_lang") → 默认 zh。
 *
 * ⚠ 2026-09-12 从"两个 UI 共用的一份"拆成各持一份（另一份在另一个项目里）。
 *   两边都用的 10 个 key 这里也留着，改文案时**两份一起改**：
 *     actor_ph actor_title conn_ASSOCIATING conn_CONNECTED conn_DISCONNECTED conn_IDLE conn_OFFLINE conn_PAIRING conn_SCANNING hint
 *   其余 key 只属于本项目。
 *
 * 文件必须 UTF-8；新增文案：zh/en 两边都要补（少一边会在英文界面漏成 key 名）。
 * 自检：`python test_i18n.py`（zh/en 一一对应 + 每个 key 恰好 2 次 + 页面引用的 key 都在）。
 */
(function (global) {
  "use strict";

  var D = {
    zh: {
      "actor_ph": "操作者",
      "actor_title": "操作者（记入审计日志）",
      "at:def:AT+ACKTMO=": "[us] ACK 超时（>1km 通信时）",
      "at:def:AT+BSSLIST": "获取扫描到的 AP 列表",
      "at:def:AT+BSS_BW=": "[1/2/4/8] 带宽 MHz",
      "at:def:AT+CHAN_LIST=": "[freq1,freq2,...] 工作频率列表",
      "at:def:AT+CONN_STATE": "查看连接状态",
      "at:def:AT+FREQ_RANGE=": "[起始,结束] 频率范围 MHz",
      "at:def:AT+HEART_INT=": "[ms] 心跳间隔",
      "at:def:AT+JOINGROUP=": "[组播地址,AID] 加入组播网络",
      "at:def:AT+KEYMGMT=": "[WPA-PSK/NONE] 加密方式",
      "at:def:AT+LOADDEF=": "[1] 恢复出厂设置",
      "at:def:AT+MAC_ADDR": "查询本机 MAC 地址",
      "at:def:AT+MODE=": "[ap/sta/group/apsta] 工作模式",
      "at:def:AT+MODE?": "查询当前模式",
      "at:def:AT+PAIR=": "[0/1] 快速配对",
      "at:def:AT+PSK=": "[64位hex] 加密密码",
      "at:def:AT+PS_MODE=": "[0..4] STA 休眠模式",
      "at:def:AT+ROAM=": "[0/1] 漫游开关（STA 侧）",
      "at:def:AT+RSSI": "[?/索引/MAC] 查询信号强度",
      "at:def:AT+RST": "复位模块",
      "at:def:AT+R_PSK=": "[64hex] 中继上级 AP 的密码",
      "at:def:AT+R_SSID=": "[ssid] 中继上级 AP 的 SSID",
      "at:def:AT+SCAN_AP": "扫描 AP（STA 模式）",
      "at:def:AT+SSID=": "[ssid] 网络名（≤32字符）",
      "at:def:AT+SSID?": "查询 SSID",
      "at:def:AT+SYSDBG=": "[LMAC/WNB,0/1] 调试打印开关",
      "at:def:AT+TXDATA=": "[长度] 进入数据模式发送数据",
      "at:def:AT+TXPOWER=": "[6..20] 发射功率 dBm",
      "at:def:AT+TX_MCS=": "[0..7/255] TX MCS",
      "at:def:AT+UNPAIR=": "[mac_addr] 解除指定 STA 配对",
      "at:def:AT+VERSION": "查询固件版本",
      "at:def:AT+WAKEUP": "唤醒休眠模块",
      "at:def:AT+WNBCFG": "查看设备参数",
      "at:v2:AT+ACK_TO=": "[us] ACK 超时（>1km 通信时）",
      "at:v2:AT+APHIDE=": "[0/1] 隐藏 AP（1=扫描不到）",
      "at:v2:AT+BSS_BW=": "[1/2/4/8] 带宽 MHz",
      "at:v2:AT+BSS_BW=?": "查询带宽",
      "at:v2:AT+CHANNEL=": "[序号] AP 端工作信道序号",
      "at:v2:AT+CHAN_LIST=": "[freq1,freq2,...] 工作频率（AP/STA 须完全一致）",
      "at:v2:AT+CHAN_LIST=?": "查询信道列表",
      "at:v2:AT+DSLEEP=": "[1] 进入休眠",
      "at:v2:AT+ENCRYPT=": "[0/1] 加密开关",
      "at:v2:AT+KEY=": "[≥8字符] 加密密钥（ASCII）",
      "at:v2:AT+LOADDEF=": "[1] 恢复出厂设置",
      "at:v2:AT+MAC_ADDR=?": "查询本机 MAC",
      "at:v2:AT+PAIR=": "[0/1/2] 快速配对（成功后 AT+PAIR=0 建链）",
      "at:v2:AT+PING=": "[ip,次数,size] ping（需网络宏）",
      "at:v2:AT+ROAM=": "[0/1] 漫游开关（STA 侧）",
      "at:v2:AT+RSSI=?": "查询信号强度（关联后非 0）",
      "at:v2:AT+RST": "复位模块（重启固件）",
      "at:v2:AT+R_KEY=": "[key≥8] 中继下级密钥",
      "at:v2:AT+R_SSID=": "[ssid] 中继下级 SSID",
      "at:v2:AT+SCAN": "扫描周围 AP（结果看 UMAC 打印 AT+SYSDBG=UMAC,1）",
      "at:v2:AT+SSID=": "[ssid] 网络名（≤32字符）",
      "at:v2:AT+SSID=?": "查询 SSID",
      "at:v2:AT+SYSCFG": "查看设备参数",
      "at:v2:AT+SYSDBG=": "[LMAC/UMAC/WNB,0/1] 调试打印开关",
      "at:v2:AT+TEST_START=": "[0/1] 进入/退出 RF 测试模式",
      "at:v2:AT+TXPOWER=": "[1..20] 发射功率 dBm",
      "at:v2:AT+UNPAIR=": "[mac] 解除指定 STA 配对",
      "at:v2:AT+VERSION": "查询固件版本",
      "at:v2:AT+WAKEUP=": "[mac] 唤醒休眠 STA（AP 端）",
      "at:v2:AT+WIFIMODE=": "[ap/sta/apsta] 工作模式",
      "at:v2:AT+WIFIMODE=?": "查询当前模式",
      "bs_sim0": "CH32V203 · 无射频 · 虚拟空口",
      "bs_virtual": "兼容 · 无射频 · 虚拟空口",
      "conn_ASSOCIATING": "关联中",
      "conn_CONNECTED": "已连接",
      "conn_DISCONNECTED": "已断开",
      "conn_IDLE": "空闲",
      "conn_OFFLINE": "离线",
      "conn_PAIRING": "配对中",
      "conn_SCANNING": "扫描中",
      "dir_down": "下行",
      "dir_up": "上行",
      "doc_tools": "TXW8301 模拟器 UI",
      "dt_pc": "虚拟机",
      "dt_serial": "真机",
      "hint": "客户端自动周期上报；服务器每收到一条即点亮对应行。",
      "lbl_air": "空口",
      "lbl_rx": "接收",
      "lbl_tx": "发送",
      "mode_AP": "接入点",
      "mode_APSTA": "双模",
      "mode_GROUP": "组网",
      "mode_STA": "客户端",
      "pow_off": "关机",
      "pow_on": "开机",
      "qt:AT+PAIR=0": "停止配对并自动建链",
      "qt:AT+PAIR=1": "启动快速配对",
      "qt:AT+RSSI=?": "查询信号强度（关联后非 0）",
      "qt:AT+RST": "复位模块（重启固件）",
      "qt:AT+SCAN": "扫描周围 AP（结果看 UMAC 打印）",
      "qt:AT+SSID=?": "查询 SSID",
      "qt:AT+SYSCFG": "查看设备参数",
      "qt:AT+SYSDBG=LMAC,0": "关闭 LMAC 调试打印",
      "qt:AT+WIFIMODE=?": "查询模式（设模式用 AT+WIFIMODE=ap/sta）",
      "tui_air_virtual": "虚拟空口 (TCP)",
      "tui_brand": "TXW8301 模拟器",
      "tui_bw": "带宽",
      "tui_cfg_apply": "应用配置",
      "tui_cfg_bw": "带宽",
      "tui_cfg_chan": "信道",
      "tui_cfg_dev": "设备",
      "tui_cfg_enc": "加密",
      "tui_cfg_hint": "(生成 AT 命令下发)",
      "tui_cfg_mode": "模式",
      "tui_cfg_psk": "PSK(64hex)",
      "tui_cfg_psk_ph": "WPA-PSK 时填写",
      "tui_cfg_title": "配置面板",
      "tui_clear_btn": "清屏",
      "tui_clear_console": "清空控制台",
      "tui_clear_frames": "清空帧",
      "tui_clear_title": "清空本台控制台 (Ctrl+L)",
      "tui_cmd_ph": "AT 命令 / HEX 数据",
      "tui_conn": "连接",
      "tui_console": "控制台",
      "tui_dev_a": "设备 A",
      "tui_dev_b": "设备 B",
      "tui_empty": "(空)",
      "tui_eth_min": "以太网帧最短 14 字节（6 目的MAC + 6 源MAC + 2 类型）",
      "tui_fm": "帧监视: {s}",
      "tui_fm_off": "关",
      "tui_fm_off_btn": "帧监视: 关",
      "tui_fm_on": "开",
      "tui_frames_hint": "(需开启“帧监视”，走 AT+SYSDBG=WNB)",
      "tui_frames_title": "帧监视器",
      "tui_freq": "频率",
      "tui_hex_even": "HEX 字节数必须是偶数",
      "tui_key_min": "KEY 需 ≥8 个 ASCII 字符",
      "tui_link_down": "链路断开",
      "tui_link_tip": "ℹ️ <b>真机↔真机</b>（RF）或 <b>虚拟机↔虚拟机</b>（虚拟空口）可互通；<b>真机↔虚拟机不互通</b>",
      "tui_link_up": "链路已建立 ✓",
      "tui_psk_hex": "PSK 必须是 64 位 hex",
      "tui_run": "运行",
      "tui_sc1": "两台 TX-AH 虚拟机（泰芯 TX-AH-MODULE，无硬件）",
      "tui_sc2": "一台 TX-AH 真机 + 虚拟机（两者不互通）",
      "tui_sc3": "两台 TX-AH 真机（真实 RF 互联）",
      "tui_sc4": "两台 T-Halow-RJ45 虚拟机（LilyGo，无硬件）",
      "tui_sc5": "两台 T-Halow-RJ45 真机（固件代次 V1.6/V2.4 自动探测，真实 RF）",
      "tui_sc6": "TH-RJ45 + TX-AH 真机（TH-RJ45 升 V2.4 也能自动识别，同代互联）",
      "tui_sc7": "两台 HT-HC01 虚拟机（惠特自动化 ESP32+MM6108 · 占位，无硬件）",
      "tui_sc8": "两台 HT-HC01 真机（真实 RF）",
      "tui_sc9": "列出本机串口",
      "tui_send": "发送",
      "tui_spam": "设备自动调试信息",
      "tui_srv_off": "未连接",
      "tui_srv_ok": "已连接",
      "tui_srv_retry": "重连中…",
      "tui_start_summary": "常用启动命令（点击展开）",
      "tui_start_title": "启动模拟器",
      "tui_th_dir": "方向",
      "tui_th_dst": "目的MAC",
      "tui_th_len": "长度",
      "tui_th_src": "源MAC",
      "tui_th_time": "时间",
      "tui_th_type": "类型",
    },
    en: {
      "actor_ph": "operator",
      "actor_title": "Operator (recorded in the audit log)",
      "at:def:AT+ACKTMO=": "[us] ACK timeout (for >1km links)",
      "at:def:AT+BSSLIST": "get scanned AP list",
      "at:def:AT+BSS_BW=": "[1/2/4/8] bandwidth MHz",
      "at:def:AT+CHAN_LIST=": "[freq1,freq2,...] channel list",
      "at:def:AT+CONN_STATE": "show connection state",
      "at:def:AT+FREQ_RANGE=": "[start,end] frequency range MHz",
      "at:def:AT+HEART_INT=": "[ms] heartbeat interval",
      "at:def:AT+JOINGROUP=": "[multicast addr,AID] join multicast group",
      "at:def:AT+KEYMGMT=": "[WPA-PSK/NONE] encryption mode",
      "at:def:AT+LOADDEF=": "[1] restore factory defaults",
      "at:def:AT+MAC_ADDR": "query local MAC address",
      "at:def:AT+MODE=": "[ap/sta/group/apsta] working mode",
      "at:def:AT+MODE?": "query current mode",
      "at:def:AT+PAIR=": "[0/1] fast pairing",
      "at:def:AT+PSK=": "[64 hex] passphrase",
      "at:def:AT+PS_MODE=": "[0..4] STA sleep mode",
      "at:def:AT+ROAM=": "[0/1] roaming switch (STA side)",
      "at:def:AT+RSSI": "[?/index/MAC] query RSSI",
      "at:def:AT+RST": "reset module",
      "at:def:AT+R_PSK=": "[64 hex] upstream AP passphrase to relay",
      "at:def:AT+R_SSID=": "[ssid] upstream AP SSID to relay",
      "at:def:AT+SCAN_AP": "scan APs (STA mode)",
      "at:def:AT+SSID=": "[ssid] network name (\u226432 chars)",
      "at:def:AT+SSID?": "query SSID",
      "at:def:AT+SYSDBG=": "[LMAC/WNB,0/1] debug print switch",
      "at:def:AT+TXDATA=": "[length] enter data mode and send",
      "at:def:AT+TXPOWER=": "[6..20] TX power dBm",
      "at:def:AT+TX_MCS=": "[0..7/255] TX MCS",
      "at:def:AT+UNPAIR=": "[mac_addr] unpair the given STA",
      "at:def:AT+VERSION": "query firmware version",
      "at:def:AT+WAKEUP": "wake a sleeping module",
      "at:def:AT+WNBCFG": "show device parameters",
      "at:v2:AT+ACK_TO=": "[us] ACK timeout (for >1km links)",
      "at:v2:AT+APHIDE=": "[0/1] hide AP (1 = unscannable)",
      "at:v2:AT+BSS_BW=": "[1/2/4/8] bandwidth MHz",
      "at:v2:AT+BSS_BW=?": "query bandwidth",
      "at:v2:AT+CHANNEL=": "[index] AP operating channel index",
      "at:v2:AT+CHAN_LIST=": "[freq1,freq2,...] channels (AP/STA must match exactly)",
      "at:v2:AT+CHAN_LIST=?": "query channel list",
      "at:v2:AT+DSLEEP=": "[1] enter sleep",
      "at:v2:AT+ENCRYPT=": "[0/1] encryption switch",
      "at:v2:AT+KEY=": "[\u22658 chars] encryption key (ASCII)",
      "at:v2:AT+LOADDEF=": "[1] restore factory defaults",
      "at:v2:AT+MAC_ADDR=?": "query local MAC",
      "at:v2:AT+PAIR=": "[0/1/2] fast pairing (then AT+PAIR=0 to build the link)",
      "at:v2:AT+PING=": "[ip,count,size] ping (needs network macro)",
      "at:v2:AT+ROAM=": "[0/1] roaming switch (STA side)",
      "at:v2:AT+RSSI=?": "query RSSI (non-zero once associated)",
      "at:v2:AT+RST": "reset module (restart firmware)",
      "at:v2:AT+R_KEY=": "[key\u22658] downstream key to relay",
      "at:v2:AT+R_SSID=": "[ssid] downstream SSID to relay",
      "at:v2:AT+SCAN": "scan nearby APs (see UMAC output AT+SYSDBG=UMAC,1)",
      "at:v2:AT+SSID=": "[ssid] network name (\u226432 chars)",
      "at:v2:AT+SSID=?": "query SSID",
      "at:v2:AT+SYSCFG": "show device parameters",
      "at:v2:AT+SYSDBG=": "[LMAC/UMAC/WNB,0/1] debug print switch",
      "at:v2:AT+TEST_START=": "[0/1] enter/exit RF test mode",
      "at:v2:AT+TXPOWER=": "[1..20] TX power dBm",
      "at:v2:AT+UNPAIR=": "[mac] unpair the given STA",
      "at:v2:AT+VERSION": "query firmware version",
      "at:v2:AT+WAKEUP=": "[mac] wake a sleeping STA (AP side)",
      "at:v2:AT+WIFIMODE=": "[ap/sta/apsta] working mode",
      "at:v2:AT+WIFIMODE=?": "query current mode",
      "bs_sim0": "CH32V203 \u00b7 no RF \u00b7 virtual air",
      "bs_virtual": "compatible \u00b7 no RF \u00b7 virtual air",
      "conn_ASSOCIATING": "Associating",
      "conn_CONNECTED": "Connected",
      "conn_DISCONNECTED": "Disconnected",
      "conn_IDLE": "Idle",
      "conn_OFFLINE": "Offline",
      "conn_PAIRING": "Pairing",
      "conn_SCANNING": "Scanning",
      "dir_down": "down",
      "dir_up": "up",
      "doc_tools": "TXW8301 simulator UI",
      "dt_pc": "virtual",
      "dt_serial": "real",
      "hint": "Client auto-reports; Server lights each row it receives.",
      "lbl_air": "air",
      "lbl_rx": "RX",
      "lbl_tx": "TX",
      "mode_AP": "AP",
      "mode_APSTA": "AP+STA",
      "mode_GROUP": "Group",
      "mode_STA": "Station",
      "pow_off": "Off",
      "pow_on": "On",
      "qt:AT+PAIR=0": "Stop pairing and build the link",
      "qt:AT+PAIR=1": "Start fast pairing",
      "qt:AT+RSSI=?": "Query RSSI (non-zero once associated)",
      "qt:AT+RST": "Reset module (restart firmware)",
      "qt:AT+SCAN": "Scan nearby APs (see UMAC output)",
      "qt:AT+SSID=?": "Query SSID",
      "qt:AT+SYSCFG": "Show device parameters",
      "qt:AT+SYSDBG=LMAC,0": "Turn off LMAC debug output",
      "qt:AT+WIFIMODE=?": "Query mode (set with AT+WIFIMODE=ap/sta)",
      "tui_air_virtual": "Virtual air (TCP)",
      "tui_brand": "TXW8301 simulator",
      "tui_bw": "BW",
      "tui_cfg_apply": "Apply config",
      "tui_cfg_bw": "BW",
      "tui_cfg_chan": "Channel",
      "tui_cfg_dev": "Device",
      "tui_cfg_enc": "Encryption",
      "tui_cfg_hint": "(generates AT commands)",
      "tui_cfg_mode": "Mode",
      "tui_cfg_psk": "PSK(64hex)",
      "tui_cfg_psk_ph": "fill in for WPA-PSK",
      "tui_cfg_title": "Config",
      "tui_clear_btn": "Clear",
      "tui_clear_console": "Clear console",
      "tui_clear_frames": "Clear frames",
      "tui_clear_title": "Clear this console (Ctrl+L)",
      "tui_cmd_ph": "AT command / HEX data",
      "tui_conn": "Link",
      "tui_console": "console",
      "tui_dev_a": "Device A",
      "tui_dev_b": "Device B",
      "tui_empty": "(empty)",
      "tui_eth_min": "Ethernet frame is at least 14 bytes (6 dst MAC + 6 src MAC + 2 type)",
      "tui_fm": "Frame monitor: {s}",
      "tui_fm_off": "off",
      "tui_fm_off_btn": "Frame monitor: off",
      "tui_fm_on": "on",
      "tui_frames_hint": "(enable \u201cframe monitor\u201d, uses AT+SYSDBG=WNB)",
      "tui_frames_title": "Frame monitor",
      "tui_freq": "Freq",
      "tui_hex_even": "HEX byte count must be even",
      "tui_key_min": "KEY must be \u22658 ASCII characters",
      "tui_link_down": "Link down",
      "tui_link_tip": "ℹ️ <b>Real\u2194real</b> (RF) or <b>virtual\u2194virtual</b> (virtual air) can talk to each other; <b>real\u2194virtual cannot</b>",
      "tui_link_up": "Link up \u2713",
      "tui_psk_hex": "PSK must be 64 hex digits",
      "tui_run": "Uptime",
      "tui_sc1": "Two TX-AH virtual devices (Taixin TX-AH-MODULE, no hardware)",
      "tui_sc2": "One TX-AH real device + one virtual (they do not interoperate)",
      "tui_sc3": "Two TX-AH real devices (real RF)",
      "tui_sc4": "Two T-Halow-RJ45 virtual devices (LilyGo, no hardware)",
      "tui_sc5": "Two T-Halow-RJ45 real devices (firmware generation V1.6/V2.4 auto-detected, real RF)",
      "tui_sc6": "TH-RJ45 + TX-AH real devices (V2.4-upgraded TH-RJ45 also auto-detected, same generation)",
      "tui_sc7": "Two HT-HC01 virtual devices (Whitelist ESP32+MM6108 \u00b7 placeholder, no hardware)",
      "tui_sc8": "Two HT-HC01 real devices (real RF)",
      "tui_sc9": "List local serial ports",
      "tui_send": "Send",
      "tui_spam": "Device debug output",
      "tui_srv_off": "Disconnected",
      "tui_srv_ok": "Connected",
      "tui_srv_retry": "Reconnecting\u2026",
      "tui_start_summary": "Common start commands (click to expand)",
      "tui_start_title": "Start the simulator",
      "tui_th_dir": "Dir",
      "tui_th_dst": "Dst MAC",
      "tui_th_len": "Len",
      "tui_th_src": "Src MAC",
      "tui_th_time": "Time",
      "tui_th_type": "Type",
    }
  };


  function detectLang() {
    try {
      var q = new URLSearchParams(location.search).get("lang");
      if (q === "zh" || q === "en") return q;
    } catch (e) { /* ignore */ }
    try {
      var s = localStorage.getItem("orpah_ui_lang");
      if (s === "zh" || s === "en") return s;
    } catch (e) { /* ignore */ }
    return "zh";
  }

  /* 操作者（审计「谁」）：值存 localStorage，跨页/刷新保持。 */
  var ACTOR_KEY = "orpah_ui_actor";

  var api = {
    lang: detectLang(),
    setLang: function (l) {
      if (l !== "zh" && l !== "en") l = "zh";
      api.lang = l;
      try { localStorage.setItem("orpah_ui_lang", l); } catch (e) { /* ignore */ }
    },
    t: function (key) {
      var v = D[api.lang] && D[api.lang][key];
      if (v === undefined) v = D.zh[key];
      return v === undefined ? key : v;
    },
    fmt: function (key, n) {
      return String(api.t(key)).replace("{n}", String(n));
    },

    /* 把字典应用到 DOM。约定属性：
     *   data-i18n            → textContent
     *   data-i18n-title      → title 属性（悬停提示）
     *   data-i18n-ph         → placeholder 属性
     *   data-i18n-doc-title  → document.title（放任一元素上，通常 <html>）
     * 页面加载后调一次；切语言后再调一次。root 默认 document。
     */
    apply: function (root) {
      root = root || document;
      function each(sel, fn) {
        var ns = root.querySelectorAll(sel);
        for (var i = 0; i < ns.length; i++) fn(ns[i]);
      }
      each("[data-i18n]", function (el) {
        el.textContent = api.t(el.getAttribute("data-i18n"));
      });
      each("[data-i18n-html]", function (el) {
        el.innerHTML = api.t(el.getAttribute("data-i18n-html"));
      });
      each("[data-i18n-title]", function (el) {
        el.title = api.t(el.getAttribute("data-i18n-title"));
      });
      each("[data-i18n-ph]", function (el) {
        el.placeholder = api.t(el.getAttribute("data-i18n-ph"));
      });
      each("[data-i18n-alt]", function (el) {
        el.alt = api.t(el.getAttribute("data-i18n-alt"));
      });
      var dt = document.querySelector("[data-i18n-doc-title]");
      if (dt) document.title = api.t(dt.getAttribute("data-i18n-doc-title"));
      document.documentElement.lang = api.lang === "en" ? "en" : "zh-CN";
      bootLangBtn();
      bootActorBox();
      return api;
    },

    /* 操作者（审计「谁」）。页面放一个容器即可：<span id="actorBox"></span>。
     * 值存 localStorage；页面 POST 时带上 actor 字段 → 落库 root.orpah.events.actor，
     * 事件历史里就能看出「哪个操作者」干的（自动事件记为 system）。 */
    actor: function () {
      try { return (localStorage.getItem(ACTOR_KEY) || "").trim(); }
      catch (e) { return ""; }
    },
    setActor: function (v) {
      v = String(v == null ? "" : v).trim();
      try {
        if (v) localStorage.setItem(ACTOR_KEY, v);
        else localStorage.removeItem(ACTOR_KEY);
      } catch (e) { /* ignore */ }
    },
    bootActorBox: bootActorBox,
  };

  /* 页头语言切换：页面只需放一个 <button id="langBtn">（内容自动填）。
   * 切换后写 localStorage 并带 ?lang= 重载，保证动态文案也重新渲染。 */
  function bootLangBtn() {
    var b = document.getElementById("langBtn");
    if (!b || b._wired) return;
    b._wired = true;
    b.textContent = api.lang === "en" ? "\u4e2d\u6587" : "EN";
    b.onclick = function () {
      var next = api.lang === "en" ? "zh" : "en";
      api.setLang(next);
      try {
        var u = new URL(location.href);
        u.searchParams.set("lang", next);
        location.href = u.toString();
      } catch (e) {
        location.reload();
      }
    };
  }

  /* 页头操作者输入框：页面只需放一个 <span id="actorBox"></span>（内容自动填）。
   * 留空 = 不记名（落库时该事件的 actor 记为空，展示为「—」）。 */
  function bootActorBox() {
    var box = document.getElementById("actorBox");
    if (!box || box._wired) return;
    box._wired = true;
    var inp = document.createElement("input");
    inp.id = "actorIn";
    inp.className = "actor-in";
    inp.type = "text";
    inp.spellcheck = false;
    inp.setAttribute("data-i18n-ph", "actor_ph");
    inp.setAttribute("data-i18n-title", "actor_title");
    inp.placeholder = api.t("actor_ph");
    inp.title = api.t("actor_title");
    inp.value = api.actor();
    inp.onchange = function () { api.setActor(inp.value); };
    inp.onblur = function () { api.setActor(inp.value); };
    box.appendChild(inp);
    box.title = api.t("actor_title");
  }

  global.OrpahI18n = api;
})(window);

