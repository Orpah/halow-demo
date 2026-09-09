# 快速开始

本文覆盖：编译固件 → 烧录 → 两板联调 → 上位机工具使用。

## 0. 无硬件：PC 版模拟器（最快体验）

开发板未到也能完整跑通 AT / 连接 / 数据通路 / 帧监视：

```bash
cd tools/ui
python server.py --host-sim     # 进程内启动 A(AP)+B(STA) 两台 PC 模拟器，自动配对
# 浏览器打开 http://127.0.0.1:8899/
```

- 双机拓扑立即显示 CONNECTED；帧监视开启后，在设备 A 控制台
  `AT+TXDATA=20` + 20 字节原始数据，帧监视器显示 A `TX` / B `RX`。
- `host/sim.py` 是固件逻辑的 Python 移植，与固件共用同一套
  AT 命令 / 帧格式（`AA 55 TYPE LEN CRC`）/ 状态机，可交叉验证。
- 回归测试：`python host/run_tests.py`（24/24 通过，含 T-Halow-RJ45 与串口空口用例）。
- 界面截图：`docs/ui_simplified_demo.png`（混合设备演示）。
- 详细见 `tools/ui/README.md`。

## 0.1 支持 T-Halow-RJ45 与混合设备

模拟器工具也能驱动 **真实的 T-Halow-RJ45 板**（手头没有 CH32V203 板时用它联调），
且 A/B 可**逐台独立**指定「来源×目标」（CH32V203 虚拟机/真机、T-Halow-RJ45 虚拟机/真机）：

```bash
# 配置两块真实 T-Halow-RJ45（COM3=AP, COM4=STA；--variant tj45 自动关调试刷屏）
python tools/sim_config.py COM3 ap  --ssid halowlink --freq 9080 --bw 8 --open --variant tj45
python tools/sim_config.py COM4 sta --ssid halowlink --freq 9080 --bw 8 --open --variant tj45
python tools/sim_config.py COM4 status --variant tj45

# Web UI：逐台设备规格（pc / pc:tj45 / COM3 / COM3:tj45）
python tools/ui/server.py --a pc --b pc:tj45              # A=CH32V203虚拟, B=T-Halow虚拟
python tools/ui/server.py --a COM3 --b COM4:tj45          # A=CH32V203真机, B=T-Halow真机

# PC 模拟器扮演 T-Halow-RJ45（状态带 + 前缀 +MODE:AP，T-Halow 的 thalow_config.py 可直接使用）
python host/sim.py --name A --role AP --console 9001 --link 9011 --tj45
python host/sim.py --name B --role STA --console 9002 --link 9012 --peer 127.0.0.1:9011 --tj45
```

### 0.1.0 TX-AH 泰芯真机（AH-SDK V2.x 方言，--variant txah）

真实 TX-AH 模组（TX-AH-Rx00P 系列，固件 v2.4.1.x，档案 txah 的 `at='v2'`）**不是** T-Halow 方言：
设模式用 `AT+WIFIMODE=ap/sta`、查询带 `?`（`AT+WIFIMODE=?`→`+WIFIMODE:ap`、`AT+RSSI=?`、`AT+SSID=?`）、
加密用 `AT+ENCRYPT=0/1`+`AT+KEY`(≥8 ASCII)，**无 `AT+MODE`/`AT+CONN_STATE`**。
真机**一次只应答一条查询**，背靠背发会吞后面应答 —— UI 轮询已逐条错发 ≥1s。

```bash
# 配置两块真实 TX-AH（COM3=AP, COM4=STA；信道 AP/STA 须完全一致含顺序）
python tools/sim_config.py COM3 ap  --ssid txah_link --freq 9080,9160,9240 --bw 8 --open --variant txah
python tools/sim_config.py COM4 sta --ssid txah_link --freq 9080,9160,9240 --bw 8 --open --variant txah
python tools/sim_config.py COM4 status --variant txah

# 加密链路（--psk 作 KEY，≥8 ASCII；两侧须一致）
python tools/sim_config.py COM3 ap  --ssid txah_link2 --freq 9080,9160,9240 --bw 8 --psk TxAh#2026-KeepOut --variant txah
python tools/sim_config.py COM4 sta --ssid txah_link2 --freq 9080,9160,9240 --bw 8 --psk TxAh#2026-KeepOut --variant txah

# Web UI：双 TX-AH 真机（真实 RF 互联）
python tools/ui/server.py --a COM3:txah --b COM4:txah
```

#### 0.1.0.1 加密 / SSID / 连接状态实测要点（2026-09-07）

- **改 SSID**：`AT+SSID=<名>`（≤32）；AP/STA 必须**同 SSID**，改任一侧链路断开，两侧同改后自动重连。
- **加密**：`AT+ENCRYPT=0/1` + `AT+KEY=<≥8 ASCII>`（WPA2-PSK）。KEY 不一致时 STA 卡在
  `WPA_4WAY_HANDSHAKE → WPA_DISCONNECTED` 死循环、永远到不了 `WPA_COMPLETED` → 连不上。
- **KEY 明文可读回**（`AT+KEY=?` / `AT+SYSCFG` 显示 `passwd`）——它是“防别人连入”，不是“防改配置”；
  AT 口无鉴权锁，配置只能从串口改、无线客户端改不了，防护靠不暴露调试串口 + 用强随机 KEY。
- **UI 连接状态**：真机不再用 RSSI 推断，读 UMAC 的 running VIF `WPA_*` 状态 + AP 侧已认证 STA
  （`STA1..`/`stamap`，来自 LMAC）；仅 `WPA_COMPLETED`（STA）/ 有已认证 STA（AP）算 CONNECTED，
  KEY 错时 STA 显示 `SCANNING`、AP 显示 `OFFLINE`（RSSI 非 0 不算）。
- **中文 SSID**：实测能连。`AT+SSID=<中文>` 接受 UTF-8；AP/STA 两侧**字节一致（都 UTF-8）+ 同 KEY**
  即可正常关联（B 日志 `by SSID find 测试链路 …` 后 WPA_COMPLETED）。注意 SSID ≤32 字节，中文每字 3
  字节 → 最多约 10 个汉字。
- **PAIR 快速配对（免填 SSID/KEY）**：AP 配好 SSID+KEY 后，双端 `AT+PAIR=1`（A 侧打印
  `sta … pairing success`）→ 配对停止 `AT+PAIR=0` → STA 用**从 AP 学到的 SSID/KEY** 自动连接，
  全程不用在 STA 手填 AP 的 SSID/KEY（实测中文 SSID 也经 PAIR 字节一致传递）。常规连接 AP/STA 必须
  同 SSID，PAIR 是唯一"STA 不必预填同名 SSID"的例外。
- **隐藏 AP / 信道跟随 / 带宽（2026-09-07 实测）**：
  - `AT+APHIDE=1` 能隐藏（`APHIDE?`→1），但**已知 SSID 的定向扫描/已关联设备仍看得到、仍能连**
    （802.11 标准：隐藏只挡通配/未知发现，挡不住定向询问）；靠隐藏防不了连接，要用加密/白名单。
  - 信道跟随：AP 用 `AT+CHANNEL=n`（n 为 chan_list 内序号）切主信道，STA 会在共享 chan_list 内
    **自动跟随重连**（实测 9080↔9240 都跟）。
  - 带宽：`AT+BSS_BW` 1/2/4/8MHz，两侧须一致；同改后按新带宽重连（实测 8↔4MHz 正常）。
- **TXPOWER / 断链自愈 / 休眠（2026-09-07 实测）**：
  - `AT+TXPOWER=1..20` 生效（`TXPOWER?` 读回），但**近距离 RSSI 看不出功率差**（桌面级信号饱和），
    验证功率↔距离需拉开几米；`AT+ACK_TO=` 仅 >1km 通信才需要。
  - 断链自愈：AP 复位期间 STA 正确转 `SCANNING`，~15s 内自动重连（UI 断/连两向状态都准确）。
  - `AT+DSLEEP=1`（连接态）= 保活休眠：链路保持、AT 仍可用；AP 端 `AT+WAKEUP=<sta_mac>` 远程唤醒
    命令被接受。深度休眠（非连接态）未测——可能睡到需物理重插 USB。
- **恢复出厂 `AT+LOADDEF=1`（2026-09-07 实测）**：
  - 双端 `AT+LOADDEF=1` 后自动复位 → 回**出厂默认**：WIFIMODE 回 `sta`、SSID 回
    `HALOW_<MAC尾3字节>`（如 `HALOW_647090`）、ENCRYPT/KEY 回默认、配置**自动保存**（再复位仍是默认）。
  - **重配加密链路的关键次序**（LOADDEF 后尤其重要）：必须 **`AT+SSID=<名>` → `AT+ENCRYPT=1` →
    `AT+KEY=<pass>`** 依序设置——`KEY` 用**当时的 SSID** 派生 PSK（PBKDF2），若次序颠倒/后改 SSID
    不重设 KEY，PSK 与 AP 不匹配：表现是 **STA 能扫到该 AP（BSSID/RSSI/WPA2-PSK 都在表里）却一直
    停在 SCANNING 不去关联**，AP 侧无 STA。按上述次序重配 + 双 `AT+RST` 后即恢复加密基线连接。
  - 长时多次 RST/LOADDEF 后若 RF 状态异常（互听不到），先按「先 SSID→ENCRYPT→KEY」重配双端再 RST；
    仍不行需物理断电重插 USB 清 RF 前端。
- **断电检测 + 串口自动重连（2026-09-07 加，server.py）**：
  - 之前真机 conn/rssi/uptime 只在“收到一行应答”才更新，**板子断电/休眠后 UI 永远冻结在旧
    CONNECTED**（实测断电后发 `AT+WIFIMODE=?` 3s 无任何应答，状态纹丝不动）。
  - 现加**看门狗**：真实串口超过 `LIVENESS_TIMEOUT=15s` 收不到任何字节（LMAC~1-6s/UMAC~6s 正常
    都在打）→ 自动 conn→`OFFLINE`、rssi→0、清陈旧 WPA/STA 快照，只在跳变时推一次。
  - **串口断开自愈**：读异常/句柄失效（休眠唤醒、COM 重枚举）→ 每 `RECONNECT_INTERVAL=2s` 自动重开
    串口并**提前重断言 SYSDBG**（`_assert_at=now+1s`），重新上电后 ~几秒自动恢复，无需重启服务器。
  - 实测：关 B → 一会 B 转 `OFFLINE`；重新上电 → B `OFFLINE→SCANNING→CONNECTED`，全程没重启服务器。
- **开机/关机（power）徽标 + 离线信号条归零 + 状态中文显示（2026-09-07 加）**：
  - 以前真机 UI 只有 conn，容易把「开机但无客户端」与「断电」混淆。现 server.py 新增 `state.power`：
    收到任何字节=开机；超过 `LIVENESS_TIMEOUT` 无字节或自(重)连后从未收到=关机。**power 与 conn 解耦**
    ——AP 开着但无客户端 → power=开机、conn=OFFLINE（不误当关机）。界面标题栏加「开机/关机」徽标（绿/灰）。
  - **RSSI 归零**：`_tahv2_conn` 判 OFFLINE 时 rssi=0；且 tahv2 的 `AT+RSSI=?` 应答在 conn=OFFLINE 时
    强制置 0——否则 AP 掉线后固件回陈旧缓存（残留如 -70）会把信号条又点亮（实测抓到并修掉）。信号条只反映
    有链路时的真实信号。
  - **前端把 conn/mode 显示成中文**（仅展示层映射；机器值仍英文，逻辑/测试/API 不受影响）：
    `CONNECTED=已连接`、`SCANNING=扫描中`、`ASSOCIATING=关联中`、`PAIRING=配对中`、`OFFLINE=离线`；
    `AP=接入点`、`STA=客户端`、`APSTA=双模`、`GROUP=组网`。
  - 实测：B 断电→关机徽标+离线；B 上电→绿色开机→扫描中→已连接；A 断电→关机徽标。
- **数据面架构（fmac 固件 AT=控制面，无用户数据通道）+ 负向不匹配测试（2026-09-07 实测）**：
  - **数据面**：TX-AH-Rx00P 这块是 **fmac 固件**（v2.4.1.5-…，版本第 4 位 5）：AT 只有控制面，**没有
    AT 级用户数据命令**。AT 手册命令全集无“发数据”项；`AT+PING`/`AT+IPERF2` 需 `SYS_NETWORK_SUPPORT`
    +`LWIP_RAW` 宏（网络版固件才有）。实测 `AT+PING=…` 只回 OK、无结果（无 IP 栈）。真机
    `AT+SYSDBG=WNB,1` 的帧打印不进 UI 帧监视表（该表只认模拟器 `FRAME:TX/RX` 行）。**要传 payload：
    主机接 SDIO/SPI(MACBUS) 走数据面，或换网络版固件**；AT 口能验证的“联通”= 关联/WPA/空口计数/信号。
  - **信道列表不匹配（负向，应连不上）**：AP `CHAN_LIST=9080,9240`(主 9080) vs STA `9160,9240`（不含
    9080）→ STA 扫描表**无该 AP**、一直 SCANNING（rssi 0）连不上；恢复一致后自动重连。
  - **带宽不匹配（负向，应连不上）**：AP `BSS_BW=8` vs STA `4` → STA 解不出/听不到 8MHz 的 AP、
    SCANNING 连不上；恢复一致后自动重连。`AT+BSS_BW` 生效且**跨 RST 保存**（boot 日志 `bss_bw=4`）；
    设完立刻 RST 偶发不保存（时序），等 ~2-3s 再 RST 即可。
  - 两种不匹配下 AP 侧会因“固件关联表滞后”短暂显示已连接（见上），STA 恒 SCANNING——失败模式清晰。
- **角色互换（2026-09-07 实测，两块板都可当 AP）**：仅 `AT+WIFIMODE=ap/sta` 对调（SSID/KEY/信道一致不变）+
  双 RST → B 当接入点、A 当客户端，双机 CONNECTED 稳定（对称性 OK）；换回基线（A=AP/B=STA）亦正常。

关键点：T-Halow-RJ45 状态/事件带 `+` 前缀（`+MODE:AP`、`+CONNECTED`），且用**裸命令**
查询（`AT+MODE`、`AT+VERSION`）；PC 模拟器泰芯 AH 族（family=tah）完全对齐这两点。

#### 0.1.0.2 TH-RJ45 真机（T-Halow-RJ45，target=tj45，2026-09-07 实测）

- **UI 显示名 = `TH-RJ45`**（devprofiles 档案 name，内部 key 仍 tj45；别名 `rj45`/`thalow`/`t-halow` 映射）。
  实测板：A AP MAC `d6:a2:2a:82:67:c0`、B STA MAC `d6:a2:2a:6f:92:c0`，固件 `v1.6.4.3-38054`。
- **方言（与 TX-AH v2 不同）**：设 `AT+MODE=ap/sta`；查询裸命令即可（`AT+MODE`/`AT+SSID`/`AT+RSSI`/
  `AT+VERSION`，带 `?` 也认）；加密 `AT+KEYMGMT=NONE|WPA-PSK`+`AT+PSK=<64hex>`；
  `AT+CHAN_LIST=`/`AT+BSS_BW=`；`AT+CONN_STATE`→`+CONNECTED/+DISCONNECT`（事件式）；**RSSI 连上为小整数
  （如 8/7），断开=0**——tj45 真机连接判定用 RSSI≠0。
- **AT+MODE 角色不跨 RST 保存**（重启回 sta、即时生效）→ 改角色后别 RST；AP 设起来会 ACS 自动选信道
  （常选 924MHz），`AT+CHAN_LIST=9080` 可压回 9080（伴随无害 `lmac error!!!chan idx=2`）。
- **一次只应答一条查询（与 TX-AH 同坑）**：server.py 对 tj45 真机（source=serial 且 family=tah）启用
  `_spaced_real` 逐条错开 ≥1.3s 轮询——只轮 `AT+RSSI`（判连接）+ MODE/SSID 慢轮；**不轮 CONN_STATE**
  （其 `+CONNECTED` 应答是“事件”，会刷屏/误推送）。重启后状态自动刷新。
- 实测：A=ap / B=sta 开放 `halowlink@9080 bw8` 互联成功（+CONNECTED、RSSI 8）；UI 双机已连接。
- 板上每条命令后常打 `valid cmds:`（固件噪音，未折叠）。数据通路=RJ45 网口（USB-C 只供电+AT 配置）。
- **跨固件互连 TH-RJ45 ↔ TX-AH（2026-09-07 实测，双向不互通）**：同族内（TH-RJ45↔TH-RJ45、TX-AH↔TX-AH）
  都正常；**跨族 TH-RJ45(T-Halow v1.6.4.3) ↔ TX-AH(AH-SDK V2 v2.4.1.5) 连不上**——open/9080/bw8 双向都能
  听到对方 SSID/BSSID（TX-AH STA 报 `by SSID find …` + `assoc_timeout` 循环；TH-RJ45 STA 报
  `find suitable ap … freq:9080` 后也不连），但 802.11 关联完成不了 → 判定**两套固件关联握手不兼容**
  （非信道/方向 artifact，已排除信道：双方都确认在 9080）。
- **混接 UI（A=TH-RJ45 + B=TX-AH 同页）**：命令提示/快捷按钮**按每台设备方言自动切换**（T-Halow 风格 vs
  AH-SDK V2 风格），`/api/info` 的 `v2` 标记逐设备，验证 OK。
- **跨固件互通已解决（2026-09-09 实测）**：真根因 = TH-RJ45 停留在 **V1.6** 旧 WNB（`v1.6.4.3-38054`），
  与 TX-AH 的 **V2.4**（FMAC v2.4.1.5）**跨代不兼容**（TX-AH 报 `at channel 0`+assoc_timeout，且
  9080/9160 都失败）——不是 AH-vs-WNB 族间缺陷。**解法**：把 TH-RJ45 也升到 **V2.4 WNB**
  （`txw8301_v2.4.1.3-39777`，CH341B 整片烧 0x0）后，**V2.4-WNB(AP) ↔ V2.4-FMAC(STA) 在 916MHz 完全互通**：
  A 侧 `STA1: 82:59:13:64:70:90`、B 侧 `STA0: d6:a2:2a:82:67:c0`、RSSI -55、双向数据流，无 channel0/timeout。
  烧录一律由用户执行（CH341B+夹子；官方 bin 从 0x0 整片写，头 `5A69`）。
- **UI 频率/带宽行（2026-09-07 加，server.py + app.js/index.html）**：设备卡新增
  「频率 x MHz · 带宽 y MHz」；server 慢轮询 `AT+CHAN_LIST?`（tj45）/ `AT+CHAN_LIST=?`（txah）→
  `+CHAN_LIST:9160`，`AT+BSS_BW?`（应答 `+BSS_BW:8MHz` 带单位 → 解析取数字）；前端 `chan`÷10 显
  示 MHz、`bw` 直显。**TH-RJ45 常把 `OK` 与 `+KEY:val` 合并成一行**（`OK+RSSI:0` / `OK+BSS_BW:8MHz`）
  → server 剥前导 `OK` 再按 `+KEY:val` 解析（也顺带修正 tj45 的 RSSI 等合并行）。
- **跨固件再证非频段（2026-09-07 实测）**：此刻双端 `chan_list` 均读回 **9160**（非早前测试的 9080；
  SYSCFG/WNBCFG + CHAN_LIST 查询一致）→ 双卡同显 **916 MHz · 8 MHz**，跨族 STA 仍 `at channel 0` +
  `assoc_timeout` → 现已有 **9080 与 9160 两个单频点同样失败**，与频点/频段/带宽无关。

### 0.1.1 多模组（设备档案见 `host/devprofiles.py`）

目标 key：`sim`（CH32V203）/ `tj45`（T-Halow-RJ45）/ `txah`（TX-AH，泰芯原厂，同族）/ `hc01`
（HT-HC01，惠特自动化 ESP32+MM6108，**占位**：真实 AT 待其手册，暂按泰芯 AH 方言）。

```bash
# 两台 HT-HC01 虚拟机（占位）
python tools/ui/server.py --host-sim --target hc01
python host/sim.py --name A --role AP --console 9001 --link 9011 --family hc01

# 配置真实 HT-HC01 板（占位，同款处理）
python tools/sim_config.py COM3 status --variant hc01
```

> **互联域限制**：只有「PC↔PC」能通过虚拟空口(TCP)互联；「真机↔真机」靠物理
> UART2（CH32V203 模拟器板）或 RF（T-Halow-RJ45）互联；PC 与真机之间无法自动建链，
> 但 UI 可同时管理任意组合（各自 AT/配置/状态照常可用）。
>
> **PC ↔ 真实 CH32V203 板**：PC 模拟器空口可改走**串口**直连板子 UART2 建链：
> `server.py --a pc --a-link COM5 --b COM4`（A 空口走 COM5，B 真机 AT 在 COM4；
> 板 UART2 经 USB 转串口接 PC）。自动打开/重连；T-Halow-RJ45 真机除外（射频）。

## 1. 准备

- **硬件**：按 `hardware/`（Fritzing 元件 `.fzpz` + 搭建指南 + BOM + docs/hardware.md 接线）准备 1~2 块板。
- **烧录器**：WCH-Link（SWD 四线：3.3V / SWDIO / SWCLK / GND）。
- **工具链**：`riscv-none-elf-gcc`（MounRiver 自带，或 xPack 版）。见 `firmware/README.md`。
- **Python 3 + pyserial**（上位机工具）。

## 2. 编译固件

```bash
cd firmware
make                 # 生成 build/txw8301-sim.bin
```

工具链路径在 `Makefile` 顶部 `RISCV_PREFIX` / `CROSS_COMPILE` 配置。

## 3. 烧录

方式 A（推荐，WCH-Link）：
```bash
# 用 WCH 的 ISP/下载工具或 openocd 均可；MounRiver 里直接点下载
openocd -f interface/wch-link.cfg -f target/ch32v20x.cfg \
        -c "program build/txw8301-sim.bin 0x08000000 verify reset exit"
```

方式 B（串口 ISP，可选）：连接 BOOT0 到高，用 WCHISPTool 通过 USB-C 烧录，
烧完把 BOOT0 拉回低复位。

## 4. 单板自检（可选）

- 上电：PWR（若有）亮，CONN 灯灭。
- PC 打开串口（CH340C，115200 8N1），发送 `AT` → 返回 `OK`。
- `AT+VERSION` → 返回模拟器版本。

## 5. 两板联调（AP + STA）

### 接线

```
[模拟器 A · AP]                     [模拟器 B · STA]
  PA2(TX2) ────────────────▶ PA3(RX2)
  PA3(RX2) ◀──────────────── PA2(TX2)
  GND     ──────── GND ────── GND
```

PC 用两根 USB 线分别接 A/B 的 CH340C 控制台。

### 配置（命令行）

```bash
# 板 A 为 AP，板 B 为 STA，同 SSID/带宽/频率，无加密
python tools/sim_config.py COM3 ap  --ssid halowlink --freq 9080 --bw 8 --open
python tools/sim_config.py COM4 sta --ssid halowlink --freq 9080 --bw 8 --open
```

或手动 AT：

```
A: AT+MODE=AP
A: AT+SSID=halowlink
A: AT+BSS_BW=8
A: AT+CHAN_LIST=9080
B: AT+MODE=STA
B: AT+SSID=halowlink
B: AT+BSS_BW=8
B: AT+CHAN_LIST=9080
```

### 验证

```bash
python tools/sim_config.py COM4 status
# 期望看到 CONN_STATE:CONNECTED 和合理 RSSI
```

- 板 A CONN 灯亮，板 B CONN 灯亮；两侧 RSSI 灯按模拟信号强度点亮。
- 未配对用 `AT+PAIR=1`（双端同时开）也能快速配对。

## 6. 数据联调（SPI 宿主总线）

1. Host（你的 MCU 或 USB-SPI 适配器，如 CH341A/CH347A）接模拟器 SPI 口。
2. 按 `docs/spi_protocol.md` 组帧：
   - `SET_CFG` / `AT_CMD` 配置；
   - `DATA_TX` 发以太网帧（≥14B 头）；
   - 观察对端模拟器 `IRQ` 拉高 → `DATA_RX` 取帧。
3. 用 `tools/sim_config.py` 的 `--bus spi` 走 CH341A 通道（见 tools/README.md）。

## 7. 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| 串口无 `OK` | 波特率不对（应为 115200）/ 线没接 / BOOT0 状态异常 |
| 两板连不上 | 确认 SSID、BSS_BW、CHAN_LIST 一致；虚拟空口 TX↔RX 交叉且共地 |
| `AT+RSSI` 恒定 | 模拟 RSSI 默认固定，可在 `sim_cfg` 调整或注入 |
| CONN 灯不亮 | 检查 PC13 接线与 `board.h` 中 `CONN_LED_ACTIVE_LOW` |
| SPI 无应答 | 检查模式 0、CS/IRQ 电平、`AT_CMD` 需以 `\r\n` 结尾 |

## 8. 出厂复位

```bash
python tools/sim_config.py COM3 reset   # AT+LOADDEF=1，恢复默认并重启
```
