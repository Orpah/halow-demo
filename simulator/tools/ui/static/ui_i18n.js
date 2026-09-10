/* ui_i18n.js — 共享 UI 文案字典（单一源，zh/en 双语）
 * ==================================================
 * halow-demo 主 UI（tools/ui/static/）与 orpah demo UI（orpah/ui/static/）
 * 共用同一份文案与术语翻译，避免各处硬编码中文、将来做英文界面时改一处即生效。
 *
 * 用法：
 *   <script src="ui_i18n.js"></script>   // 两个 UI 的 index.html 都引它
 *   OrpahI18n.lang            // 当前语言 "zh" / "en"
 *   OrpahI18n.setLang("en")   // 切换（orpah UI 用 ?lang=en / ?lang=zh 或 localStorage）
 *   OrpahI18n.t("conn_CONNECTED")   // 取文案（无则回退 zh，再无则返回 key）
 *   OrpahI18n.fmt("lbl_sent", 5)     // 带 {n} 占位的文案
 *
 * 语言解析顺序：URL ?lang= → localStorage("orpah_ui_lang") → 默认 zh。
 * 文件必须 UTF-8；新文案：两边 key 都要补（zh/en）。
 */
(function (global) {
  "use strict";

  var D = {
    zh: {
      /* 连接状态 / 工作模式 / 电源（halow-demo 主 UI 与 orpah 共用） */
      "conn_CONNECTED": "已连接",
      "conn_SCANNING": "扫描中",
      "conn_ASSOCIATING": "关联中",
      "conn_PAIRING": "配对中",
      "conn_OFFLINE": "离线",
      "conn_IDLE": "空闲",
      "conn_DISCONNECTED": "已断开",
      "mode_AP": "接入点",
      "mode_STA": "客户端",
      "mode_APSTA": "双模",
      "mode_GROUP": "组网",
      "pow_on": "开机",
      "pow_off": "关机",
      "srv_connected": "已连接",
      "srv_disconnected": "连接断开",

      /* orpah demo UI（精简 3 节点：客户端/路由器/服务器；host=主机） */
      "brand_sub": "L1 数据通路演示 · 纯软件模拟器",
      "node_client": "客户端",
      "node_router": "路由器",
      "node_server": "服务器",
      "sub_client": "主机 · 组 ORPAH-REPORT",
      "sub_router": "空口收 · UDP 上行",
      "sub_server": "Python UDP",
      "lbl_sn": "序列号",
      "lbl_sent": "上报 {n} 条",
      "lbl_up": "上行 {n} 条",
      "lbl_recv": "收到 {n} 条",
      "lbl_pub": "发布走失表 {n} 次",
      "lbl_lost_recv": "收到走失表 {n} 次",
      "lbl_tx": "发送",
      "lbl_rx": "接收",
      "lbl_air": "空口",
      "lbl_frame": "帧",
      "link_air": "HaLow 虚拟空口",
      "link_udp": "UDP :19447",
      "msg_title": "ORPAH-REPORT 实时报文流",
      "flow_title": "L2 协议消息流",
      "th_dir": "方向",
      "th_mtype": "报文",
      "th_status": "状态",
      "th_node": "节点",
      "dir_up": "上行",
      "dir_down": "下行",
      "lost_title": "走失表（服务器权威）",
      "lost_none": "（空）",
      "lost_yes": "走失",
      "lost_no": "未走失",
      "btn_mark": "标记为走失",
      "btn_untrack": "取消走失",
      "pub_head": "服务器发布记录",
      "pub_empty": "（暂无发布）",
      "pub_action": "发布走失表 {n} 项 → {k} 台路由器",
      "lbl_found": "发现 {n} 次",
      "lbl_found_recv": "收到发现 {n} 次",
      "found_title": "发现记录（走失命中）",
      "found_empty": "（暂无发现）",
      "found_line": "发现 {sn}",
      "ctl_title": "上报控制",
      "th_time": "时间",
      "th_seq": "序号",
      "th_sn": "序列号",
      "th_rssi": "信号",
      "th_client": "客户端注入",
      "th_router": "路由器上行",
      "th_server": "服务器收到",
      "ctl_every": "间隔",
      "ctl_sn": "序列号",
      "ctl_sec": "秒",
      "btn_apply": "应用",
      "btn_pause": "暂停上报",
      "btn_resume": "继续上报",
      "btn_clear": "清空列表",
      "hint": "客户端自动周期上报；服务器每收到一条即点亮对应行。",
      "chip_run": "运行",
      "chip_listen": "监听",
      "id_title": "Orpah ID 签名上报（真实密钥）",
      "id_alg": "算法",
      "id_level": "降级级别",
      "id_trust": "验签结果",
      "id_sig": "签名 sig",
      "id_nonce": "nonce",
      "id_ok": "✓ 验签通过",
      "id_bad": "✗ 验签失败",
      "trust_high": "高 · ECDSA",
      "trust_medium": "中 · HMAC(L1)",
      "trust_low": "低 · HMAC(L2)",
      "trust_none": "无签名 · 覆盖发现",
    },
    en: {
      "conn_CONNECTED": "Connected",
      "conn_SCANNING": "Scanning",
      "conn_ASSOCIATING": "Associating",
      "conn_PAIRING": "Pairing",
      "conn_OFFLINE": "Offline",
      "conn_IDLE": "Idle",
      "conn_DISCONNECTED": "Disconnected",
      "mode_AP": "AP",
      "mode_STA": "Station",
      "mode_APSTA": "AP+STA",
      "mode_GROUP": "Group",
      "pow_on": "On",
      "pow_off": "Off",
      "srv_connected": "Connected",
      "srv_disconnected": "Disconnected",

      "brand_sub": "L1 data-path demo · pure software",
      "node_client": "Client",
      "node_router": "Router",
      "node_server": "Server",
      "sub_client": "host · builds ORPAH-REPORT",
      "sub_router": "air RX · UDP uplink",
      "sub_server": "Python UDP",
      "lbl_sn": "Serial",
      "lbl_sent": "{n} sent",
      "lbl_up": "{n} uplinked",
      "lbl_recv": "{n} received",
      "lbl_pub": "{n} lost-table publish",
      "lbl_lost_recv": "{n} lost-table received",
      "lbl_tx": "TX",
      "lbl_rx": "RX",
      "lbl_air": "air",
      "lbl_frame": "frames",
      "link_air": "HaLow virtual air",
      "link_udp": "UDP :19447",
      "msg_title": "ORPAH-REPORT live stream",
      "flow_title": "L2 message flow",
      "th_dir": "Dir",
      "th_mtype": "Msg",
      "th_status": "Status",
      "th_node": "Node",
      "dir_up": "up",
      "dir_down": "down",
      "lost_title": "Lost table (server auth)",
      "lost_none": "(empty)",
      "lost_yes": "Lost",
      "lost_no": "Not lost",
      "btn_mark": "Mark lost",
      "btn_untrack": "Untrack",
      "pub_head": "Server publishes",
      "pub_empty": "(no publish yet)",
      "pub_action": "published lost table {n} item(s) \u2192 {k} router(s)",
      "lbl_found": "{n} found",
      "lbl_found_recv": "{n} found received",
      "found_title": "Discovery feed (lost hit)",
      "found_empty": "(no discovery yet)",
      "found_line": "Found {sn}",
      "ctl_title": "Report control",
      "th_time": "Time",
      "th_seq": "Seq",
      "th_sn": "Serial",
      "th_rssi": "RSSI",
      "th_client": "Client",
      "th_router": "Router",
      "th_server": "Server",
      "ctl_every": "Interval",
      "ctl_sn": "Serial",
      "ctl_sec": "s",
      "btn_apply": "Apply",
      "btn_pause": "Pause",
      "btn_resume": "Resume",
      "btn_clear": "Clear",
      "hint": "Client auto-reports; Server lights each row it receives.",
      "chip_run": "Running",
      "chip_listen": "Listening",
      "id_title": "Orpah ID signed report (real key)",
      "id_alg": "Algorithm",
      "id_level": "Level",
      "id_trust": "Verify",
      "id_sig": "sig",
      "id_nonce": "nonce",
      "id_ok": "\u2713 verified",
      "id_bad": "\u2717 rejected",
      "trust_high": "High \u00b7 ECDSA",
      "trust_medium": "Medium \u00b7 HMAC(L1)",
      "trust_low": "Low \u00b7 HMAC(L2)",
      "trust_none": "Unsigned \u00b7 coverage",
    },
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
  };

  global.OrpahI18n = api;
})(window);
