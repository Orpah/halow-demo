# 阶段二真机侧：上机手册与验证清单

> 记录于 2026-09-12。**烧录/上机一律由用户执行**（AI 不直接烧录任何板子，见 `AGENTS.md` §0 与用户约定）。
> 配套可执行脚本：`orpah/demo_hw1.py`（**未经真机验证**——写它时手上没有板子，第一次上机请逐项核对）。
> 相关：`ROADMAP.md` §二（真实 report 聚合·阶段二）、§四（传输与真机适配）；
> `Protocol/docs/orpah-over-halow/SPEC.md` §3（网络/物理层实测约束）、§9（L2.5 真机最终形态）。

## 0. 这份文档做什么 / 不做什么

**做**：把「上机之后必须确认什么」列成可勾选的清单，并把能自动判的判据交给脚本。
**不做**：
- **不预设数据通路**（2026-09-12 用户定）——两条候选通路（RJ45 透明桥 / host SPI）都只是候选，
  哪条通就走哪条，清单按"要验证什么"写，不按"该怎么搭"写。
- **不包含烧录操作**（用户执行）；本手册只写"刷哪个固件、怎么判断刷对了"。

## 1. 硬规则（本项目已实测的结论，违反必踩坑）

| 规则 | 内容 | 违反的症状 |
|---|---|---|
| **同代互通** | 固件**代次**决定能不能通：同代必通、跨代必不通（V1.6 ↔ V2.4 互不兼容） | STA 恒 `SCANNING` / TX-AH 报 `channel 0` + `assoc_timeout`；AP 侧无 STA |
| **族与载板匹配** | 版本第 4 段首位：`3`=WNB、`5`=FMAC。**WNB 需要 RJ45 以太网 PHY**（TH-RJ45 载板） | 裸 TX-AH 载板刷 WNB → `hg_gmac_open` assert → 反复重启 |
| **FMAC 无 AT 数据面** | TX-AH（FMAC）AT 只能控制面；payload 必须走 host SPI（需 MCU） | 找不到任何 AT 发数据的命令；`AT+PING` 只回 OK 无结果 |
| **AT 一次只应答一条** | 背靠背发两条查询会吞掉第二条 → 轮询必须**逐条错开 ≥1 s** | 状态偶发不刷新、查询无应答 |
| **加密链路配置次序** | `AT+SSID` → `AT+ENCRYPT` → `AT+KEY`（KEY 用**当时 SSID** 派生 PSK） | STA 扫得到 AP（BSSID/RSSI/WPA2 齐全）却一直不关联 |
| **RSSI 语义分代次** | V1.6 = 档位小整数（-3…3，不是 dBm）；V2.4 = dBm | 拿 V1.6 的 "2" 当 2 dBm 用 |
| **SYSDBG 会丢** | 板子 RST 后 SYSDBG 设置被重置 → 需周期重断言（tools UI 已每 20 s 重发） | TX/RX 计数或状态流"莫名停了" |

## 2. 硬件与固件清单（你执行刷写）

- 两块无线模组：**TX-AH-RX00P（TXW8301）**；载体二选一或都备：
  - **TH-RJ45**（模组 + IP101GRR PHY + RJ45）→ 刷 **WNB** 固件（当前基线 `v2.4.1.3-40938`）
  - **TX-AH 载板**（无 PHY）→ 只能刷 **FMAC**（当前基线 `v2.4.1.5-39777`）
- 烧录工具：CH341B（整片烧 `0x0`）；串口升级可用 `AT+FWUPG` → 打印 `CCC…` → **XMODEM** 发 bin（若该代支持）
- 网线 ×2（RJ45 侧）、USB 转串口（AT 配置，TH-RJ45 的 USB-C 只做 AT）
- 判"刷对了"：页面/串口 `AT+VERSION` 的**代次与族**同时正确（脚本会自动读并判定，见 §5）

## 3. 上机验证清单（逐组做，做完在 `[ ]` 打勾）

### A 设备与配置（先决条件，不通后面全白做）
- [ ] 两板都上电，tools UI（`sim-server-host-<型号>` 任务，`:8899`）认到两台设备、串口稳定
- [ ] `AT+VERSION` 读出**代次一致**、族与载板匹配（WNB↔RJ45 / FMAC↔TX-AH 载体）
- [ ] 角色一个 AP 一个 STA；`AT+WIFIMODE` 读回正确
- [ ] SSID / `AT+CHAN_LIST` / `AT+BSS_BW` 两侧**完全一致**（含顺序）；加密按需（open 或 `ENCRYPT=1`+`KEY` 按次序配）
- [ ] `AT+SYSCFG` 存档两份（对照用，排障时是第一手证据）

### B 空口链路
- [ ] AP 侧关联表出现该 STA（`STA1:` / `stamap`），STA 侧到 `WPA_COMPLETED`（tools UI 把这两个都转成 `CONNECTED`）
- [ ] RSSI 有值；**把两块板拉开 5–10 m** 看数值是否随之变化（桌面近距离会饱和，看不出差别）
- [ ] AP 复位一次 → STA 应 `SCANNING` → 约 15 s 内自动重连（验证重连与看门狗）
- [ ] 记录：RSSI 语义（dBm 还是档位）、关联耗时、断连恢复耗时

### C 数据通路（**本阶段的关键未知项**）
- [ ] 两侧 RJ45 各接一台 PC，两 PC 拿到**同网段** IP（DHCP 或静态；记录网段/网关）
- [ ] `ping <对端>` 通（不通 → 回 B 组，别急着调 ORPAH）
- [ ] **自定义 ethertype `0x88B5` 是否透传**（这是 L2 路线成立与否的分水岭）：
      PC-A `python orpah/demo_hw1.py --raw-send --iface <网卡>` ↔ PC-B `--raw-sniff --iface <网卡>`
      - 对端嗅到同标记 → 可透传 → Client/Router 都不需要 UDP 封装，直接走 SPEC §6 的 L2 语义
      - 对端嗅不到但 ping 通 → 桥只转发 IP/ARP → 退而用 UDP 封装（`--peer` 模式，同样能验证端到端）
- [ ] **广播/多播是否透传**（Client 下行依赖广播帧；不通则下行要改成单播寻址）
- [ ] MTU / 分片：分别发 100 B / 512 B / 1400 B 的 ORPAH 报文，记录能通过的最大长度
- [ ] 双向：A→B 与 B→A 都要测（单向公告和双向数据是两件事）

### D ORPAH 业务（在真机链路上跑一遍协议）
- [ ] `REQ-CONNECT` → `ACCESS-INFO`（`tracked` 与走失表一致）
- [ ] `REPORT` 上行到 Server 并落库（`root.orpah.devices.<sn>`）
- [ ] mark 走失 → `LOST-TABLE` 下发到 Router → `REQ-CONNECT` 命中 → `ORPAH-FOUND` 上报
- [ ] `TRACKING-STATUS` 回执回到 Client（下行通路的端到端证据）
- [ ] (sn,seq) 去重、漫游（换 Router）在新链路上的行为与模拟器一致

### E 定位与安全（真机数据换掉模拟器数据）
- [ ] **真实 `router_id` 落库**：Server 收到上报时不再是空串（当前 `ui_server.py` 没传 → 需改）
- [ ] **真实观测写入 `root.orpah.routers.<sid>.<sn>`**：RSSI 由**真机测量**提供（哪一端可得见下），
      站位坐标用已知位置 → 回放页能解出轨迹
- [ ] 真机 RSSI 的 A/n 标定（跑几个已知距离点，拟合 `rssi = A - 10n·log10 d`，替换默认 `A=-40, n=2.5`）
- [ ] 防 spoof：空口开放 → 在真机上重跑一遍 `spoof.py` 的攻击（预期与模拟器一致：被拒）
- [ ] 验签：真机若要做签名上报，需设备侧实现《Orpah ID 协议规范》的 ES256 签名（**未做**）

## 4. 两条候选通路（仅供对照，不预设）

| | A · 两块 TH-RJ45 走 RJ45 透明桥 | B · TX-AH(FMAC) + CH32V203 走 SPI |
|---|---|---|
| 需要 | 两块 TH-RJ45 + 网线 + 两 PC | TX-AH 载体 + CH32V203 + SPI 主机固件 |
| 数据面 | RJ45 网口（WNB = 无线网桥，L2 透传） | SPI MACBUS（`DATA_TX`/`DATA_RX`，帧格同空口） |
| 优点 | 最快能跑通；PC 侧零额外硬件 | 最接近最终形态（免电池客户端） |
| 待验证 | `0x88B5`/广播是否透传、MTU、RSSI 哪端可读 | SPI 时序/流控、CH32V203 固件、低功耗策略 |
| 与本项目关系 | 协议/软件**不用改**（`orpah/host_bus.py` 已对齐 SPI 帧格式，桥接层可替换） | 需要新增 MCU 固件（本仓库不含） |

**RSSI 来源**：V2.4 的 AP 侧可用 `AT+RSSI=?` 读（dBm），V1.6 是档位值 → 若走 A 路线，
观测值来自 **Router（AP 侧）** 的 AT 读取；这与"客户端自报 RSSI"不是一回事，落库语义要对齐。

## 5. 脚本用法（`orpah/demo_hw1.py`）

```text
python demo_hw1.py                             # 环境 + 两块板状态自检（tools UI 需在跑）
python demo_hw1.py --peer 192.168.x.y          # 跨空口 UDP 通路探测（对端跑 orpah/server.py）
python demo_hw1.py --listen                    # 当对端接收端：打印收到的 ORPAH 报文
python demo_hw1.py --raw-send   --iface 以太网  # 发 0x88B5 帧（需 scapy + Npcap + 管理员）
python demo_hw1.py --raw-sniff  --iface 以太网  # 嗅探 0x88B5 帧（对端同时 --raw-send）
```

输出怎么读：
- `[OK]` 判据成立；`[!!]` 判据不成立（附排查顺序）；`[??]` 信息不足（还没上机/工具没跑）；`[--]` 需人工确认
- 脚本**不重复实现 AT 逻辑**：板卡状态一律读 `tools/ui` 的 `/api/info`、`/api/status`
  （方言探测、逐条错开轮询、LMAC/UMAC 块抑制这些坑都已在 `tools/ui/server.py` 里修好）
- `--peer` 探测结论的判据：**收到任何 ORPAH 应答**（含 `ERROR`）就算通路通 —— 业务拒绝是另一回事

## 6. 已知缺口（本阶段结束前不做）

- 设备侧签名上报（《Orpah ID 协议规范》ES256）在真机设备上尚未实现 → 真机只能跑"无认证"那段
- `ui_server.py` 尚未把真实 `router_id` / 真实 RSSI 观测接进来（等 C 组通过后再改，避免写了没法验的码）
- 免电池/低功耗策略（唤醒周期、能量采集、上报间隔）未建模
- 多 Router 真机并发（每台各自带编号 + 坐标上报）未做

## 7. 未验证声明（务必先读）

`demo_hw1.py` 与本文档的**代码部分均未经真机验证**（写它时没有硬件）。
上机时若脚本行为与手册判据冲突：**以手册判据为准**（判据来自实测结论），
然后把脚本改对；发现新结论请回填本节与 `ROADMAP.md`。
