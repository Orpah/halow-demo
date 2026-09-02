# TXW8301 模拟器开发规则（simulator）

本目录是 TXW8301 的纯软件模拟器（`host/` Python 移植 + `tools/ui/` Web UI +
`firmware/` CH32V203 固件）。开发、修改、调试任何部分前，**先遵循以下规则与踩坑记录**。

## 1. 定位与启动

- 给泰芯 TXW8301（802.11ah HaLow）做的**无射频**模拟器，形态参考 T-Halow-RJ45
  （AT 命令 / AP-STA / RSSI / 数据通路一致）。项目位于仓库根 `simulator/`（2026-09 从
  `TXW8301/simulator` 移到 halow-demo 仓库根，以承载多模组）。
- **设备档案 / 协议族注册表（唯一事实来源）= `host/devprofiles.py`**：
  - target（设备档案 key）：sim / tj45 / txah / hc01，各带别名 + 中文显示名；
  - family（AT 方言）：`native`（本模拟器 CH32V203，`?` 查询 + OK）/ `tah`（泰芯 AH：
    tj45+txah）/ `hc01`（HT-HC01 占位：真实 AT 待其手册，暂复用 tah 方言）。
- Web UI 启动（不依赖 cwd，`server.py` 用 `os.path.dirname(__file__)` 定位 static/host）：
  - 两台本模拟器虚拟机：`python tools/ui/server.py --host-sim`
  - 两台 T-Halow 虚拟机：`python tools/ui/server.py --host-sim --target tj45`
  - 一台 TX-AH 真机 + 虚拟机：`python tools/ui/server.py --a pc:tj45 --b COM13:txah`
  - 两台 HT-HC01 虚拟机（占位）：`python tools/ui/server.py --host-sim --target hc01`
  - 两台真机（真实 RF）：`python tools/ui/server.py --a COM3:tj45 --b COM4:tj45`
  - 列出串口：`python tools/ui/server.py --list`
- 设备规格：`pc | pc:sim | pc:tj45 | pc:txah | pc:hc01 | COM3 | COM3:sim | COM3:tj45 | COM3:txah | COM3:hc01`
  （来源×目标；source=pc/serial；target 归一/标签一律看 devprofiles.py；
  tj45=T-Halow-RJ45、txah=泰芯 TX-AH-MODULE，两者同属泰芯 AH 固件（family=tah，
  协议一致只差显示名）；hc01=惠特自动化 HT-HC01（family=hc01，占位））。

## 2. 互联域（硬规则）

- 虚拟空口(TCP) **只在 PC↔PC 之间**建立；真机↔真机走物理 RF（802.11ah）。
- **PC↔真机不互通**：真机走真实射频、PC 模拟器无射频，二者不能自动建链，
  UI 只能同时管理。别指望"模拟器 A 发帧 → 真机 B 收帧"。
- 帧过滤：目的 MAC 必须 `FF*6`（广播）或匹配，否则对端按单播过滤丢弃（忠实模拟，**非 bug**）。

## 3. 命令 / 响应约定

- 泰芯 AH 族（family=tah：tj45/txah；hc01 占位暂同）状态响应带 `+` 前缀（`+MODE:AP`），
  且**不追加 OK**（避免轮询刷屏）；设置命令仍走 `ok()` 回 OK。
- 泰芯 AH 族查询用**裸命令**（`AT+MODE` / `AT+VERSION` / `AT+CONN_STATE` / `AT+RSSI`）。
- `AT+TXDATA` 用**等号**：`AT+TXDATA=<len≥14>`；随后数据模式收 len 字节原始数据。

## 4. 前端控制台 / UI 约定

- console 事件带 `dir`：`tx`=自己发送（命令/HEX 回显、FRAME:TX），`rx`=接收
  （OK/状态行/FRAME:RX/TX DATA OK）。
- 显示**双通道**：方向前缀 `→`/`←`（主）+ 颜色 绿`#7ee787`/蓝`#79c0ff`（辅）——
  色弱友好，**禁止只靠颜色传递收发信息**。
- 轮询响应（CONN_STATE/RSSI/MODE/SSID/VERSION）默认静默（`_poll_until` 窗口抑制），
  用户命令回显 + 状态响应才显示，避免控制台刷屏。
- 真机固件周期打印（`LMAC STATUS`/`freq=`/`bgr:`/`chn:`/`buf:`/`irq:`/`tx :`/`rx :`/
  `cca:`/`chip-temperature`/`sta_list`/分隔线/`[时间戳]SSID:`）识别为 spam，折叠成
  「▶ 设备自动调试信息」可展开块；AT 响应（无时间戳的 `SSID:` 等）不误折叠。
- 改样式/脚本后刷新即生效：静态文件已加版本号查询串（`style.css?v=xxx`）+
  `Cache-Control: no-store`。

## 5. 防爆 / 健壮性

- EVENTS 事件队列**有界**（`maxsize=2000`），push 满时丢最旧（SSE 断连不再无限堆积）。
- `reader_loop` 行缓冲超 64KB 只留尾部 4KB（防无换行二进制 flood）。
- 数据模式期间暂停该设备轮询（`poll_paused_until`，`AT+TXDATA=` 后 30s），
  防轮询字节污染/提前结束数据帧。

## 6. 踩坑记录（2026-09 补，务必记住）

- **顶部 TX/RX 计数曾始终 0**：后端只初始化 `state["tx"]/["rx"]=0` 从不递增，
  须在 FRAME 分支 TX→`tx+=1`、RX→`rx+=1` 并 push status。
- **版本号防缓存的连环坑**：给 `style.css?v=xxx` 加版本号后，`server.py` 的 `do_GET`
  必须**剥离查询串**（`rel.split("?",1)[0]`），否则带 `?` 的路径被当文件名 → **404** →
  CSS/JS 全挂 → 页面无样式无 JS（表现为"未连接"、设备占位、布局乱）。曾误以为是缓存。
- **布局**：`.node` 用 `width:280px` 会在窄视口被 flex 压缩 → 设备名断行
  （"T- Halow- RJ45"）。须 `flex:1 1 280px; min-width:280px` 防压缩。
- `sim.py` Link `connect/accept` 后必须 `c.settimeout(None)`（否则 1s 空闲被 `_reader` 断开）。
- 终端 flaky：长驻服务器用 async 终端，命令被加 `^U` 前缀报错时重新 `send_to_terminal`；
  一次性命令若卡住改用 `create_and_run_task`（tasks.json）。

## 7. 新增设备类型检查清单（如 tj45→txah→hc01，勿漏）

新增 target（设备档案 key）后，以下位置**必须同步**，否则 UI/文档不一致：

- `host/devprofiles.py`（**单一事实来源**）：`PROFILES` 加一项（key/别名/中文名/family）。
  同一协议族只加档案（如 txah 加在 `FAMILY_TAH` 族）；**全新命令集则新增一个 family**，
  并在 `host/sim.py` 的 `At` 方言处实现（`tah_style`/响应格式按 family 分支）。
- `server.py`：`norm_target()` / `device_type()` / `HostSims.add()` / argparse `--target`
  已改为走 devprofiles（新增 target 通常无需再改 server.py，除非要加别名/标签以外逻辑）。
- **`index.html`「启动模拟器」常用启动命令列表（`#startsec`，最易漏）**：加一条新设备的启动示例。
- `app.js`：`AT_CMDS` 命令库若新设备有特有命令/参数需补。
- `tools/sim_config.py`：`--variant` choices（真机 variant 自动关调试刷屏）。
- `AGENTS.md`：本文件 §1 设备规格 / 启动命令同步。
- 验证：`--a pc:xxx --b pc:xxx` 看 banner / `device_type` 显示；有真机则实测 AT 响应。

（真实教训 2026-09-02：加 txah 时后端/AGENTS 都改了，唯独漏了 UI 常用命令列表，后被用户指出补上。
2026-09-02 加 hc01：HT-HC01 属**新协议族**（惠特自动化 ESP32+MM6108，非泰芯），先登记占位、
暂复用 tah 方言，收到其 AT 手册后需补真实方言并更新本清单。）

（fritzing 元件规则见 `fritzing-parts-langhua/AGENTS.md`；详细历史踩坑在仓库 docs/ 各文件。）
