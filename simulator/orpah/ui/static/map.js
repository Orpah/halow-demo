/* map.js — 底图源与「本地坐标 ↔ 经纬度」换算（单一源：track.html 与 replay.html 共用）

   为什么单独一个文件（不各页抄一份）：
   ① **底图许可是合规问题，不是笔误** —— 各源条款差别极大：osm.org 官方瓦片禁止离线/预取且无 SLA、
      OpenTopoMap 要求逐字署名、Esri 是商业源…… 抄两份迟早漂移（见 ROADMAP §七）；
   ② 栅格瓦片的地名是**画在图里的像素**、没有语言参数 → 「瓦片源列表」必须按界面语言给两套
      （英文界面默认给无地名的卫星图，带地名的标出 ⚠ 提醒）；
   ③ 本地坐标 → 经纬度换算（基点 + 米/度）两页必须完全一致，否则同一条轨迹在
      「定位与轨迹」和「回放」两个页面会落在不同位置。

   **Leaflet 图层管理不在这里**：实时视图（轨迹 + 测点 + 距离环）与回放视图
   （轨迹要跨缺口断开、站位固定、另有 95% 椭圆）画法不同，各页自己管；共用的只到本文件。

   依赖：`ui_i18n.js`（T()/OrpahI18n.lang）与页面自己引入的 Leaflet；元素 id 两页统一：
   `tileSrc` / `tileUrl` / `tileNote` / `baseLat` / `baseLng`。 */

/* ---- 地图（Leaflet，用户指定瓦片源）----
   每个源：url + attr（署名，必须可见）+ note（条款说明键）+ labels（**底图地名语言**）。
     labels："local" = 用当地语言标注（中国境内即中文）/ "none" = 无地名 / "user" = 自定义自负责。
   各源许可条款差别很大，尤其 osm.org 官方瓦片禁止离线/预取，且无 SLA —— 见 ROADMAP §七。
   **列表按界面语言给不同的一套**：栅格瓦片的地名是画在图里的像素、没有语言参数，
   所以英文界面不能默认给一张“中国地图 + 中文地名”——无地名的卫星图置默认，带地名的标出提醒。 */
const TILE_PROVIDERS = {
  osm: { name: "OpenStreetMap",
         url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         attr: "© OpenStreetMap contributors", note: "tile_note_osm", labels: "local" },
  opentopo: { name: "OpenTopoMap",
              url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
              // OpenTopoMap 官方要求的署名文本（不能简写成 © OpenTopoMap (CC-BY-SA)）
              attr: "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
              note: "tile_note_opentopo", labels: "local" },
  esri: { name: "Esri World Imagery",
          url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
          attr: "© Esri", note: "tile_note_esri", labels: "none" },
  custom: { i18nName: "tk_tile_custom", url: "", attr: "",
            note: "tile_note_custom", labels: "user" },
};
/* 顺序 = 列表顺序，第一项即本语言的默认。
   CartoDB Voyager 已移除：其栅格端点现在必须 API key，实测整图是 "API KEY REQUIRED" 水印。 */
const TILE_ORDER = { zh: ["osm", "opentopo", "esri", "custom"],
                     en: ["esri", "osm", "opentopo", "custom"] };
function tileLabel(key) {
  const p = TILE_PROVIDERS[key];
  let s = p.i18nName ? T(p.i18nName) : p.name;
  // 英文界面：地名为当地语言的源（中国境内会显示中文）明确标出，免得又以为是 i18n 没做
  if (OrpahI18n.lang === "en" && p.labels === "local") {
    s += " " + T("tile_labels_local_short");
  }
  return s;
}
function buildTileOptions() {
  const sel = $("tileSrc");
  if (!sel) return;
  const keys = TILE_ORDER[OrpahI18n.lang] || TILE_ORDER.zh;
  const keep = sel.value;                 // 用户选过的、仍在本语言列表里的就保留
  sel.innerHTML = "";
  for (const key of keys) {
    const o = document.createElement("option");
    o.value = key;
    o.textContent = tileLabel(key);
    sel.appendChild(o);
  }
  sel.value = keys.indexOf(keep) >= 0 ? keep : keys[0];
  refreshTileNote();
}
function refreshTileNote() {
  const el = $("tileNote");
  if (!el) return;
  const p = TILE_PROVIDERS[$("tileSrc").value] || TILE_PROVIDERS.custom;
  el.textContent = T(p.note);
}
function baseLat() { return parseFloat($("baseLat").value); }
function baseLng() { return parseFloat($("baseLng").value); }
/* 本地坐标（米，x 向东 / y 向北）→ [纬度, 经度]。
   基点由「基点纬度/经度」输入决定；米/度换算按基点纬度取经度缩放。 */
function toLatLng(x, y) {
  const lat0 = baseLat();
  const mLat = 110540, mLng = 111320 * Math.cos(lat0 * Math.PI / 180);
  return [lat0 + y / mLat, baseLng() + x / mLng];
}
function currentTileUrl() {
  const key = $("tileSrc").value;
  return key === "custom" ? $("tileUrl").value.trim() : TILE_PROVIDERS[key].url;
}
