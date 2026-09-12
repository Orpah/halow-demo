# 待办与结案表（backlog）

本仓原来**没有 ROADMAP**，「还欠什么」散在 5 处文档里（`docs/architecture.md` §8 扩展方向、
`docs/AT_commands.md` §7 未实现命令与 `△` 标记、`firmware/README.md` 移植/扩展、
`docs/usage.md` 实测注记、`AGENTS.md` §7 新目标清单），加上一份**不入库**的
`docs/crossfw-taixin-handoff.md`（泰芯跨固件问题）。2026-09-13 把它们收成这一张表，
并逐条结案：**已做 / 不做（附理由）/ 留待真机或外部（附触发条件）**。

> 判据：**要么做掉，要么写清为什么不做的**。含糊的「以后可能」不算结案 ——
> 那种条目不进本表，进「不做」并写理由。

## 一、已做（本仓内可验证）

| 项 | 出处 | 落地 |
|---|---|---|
| 可配置/可注入 RSSI、连接状态、STA 数 | `architecture.md` §1 设计目标 3 | RSSI 注入值 + **距离/功率模型** + AP 关联表（`AT+RSSI`/`AT+STALIST`） |
| 「模拟关联成功（可配失败概率）」 | `architecture.md` §6 | `AT+ASSOC_FAIL=<%>`（命中则请求不发，STA 继续重试） |
| 干扰/丢包注入（弱信号） | `architecture.md` §8 | `AT+LOSS=<%>`（只作用数据帧，确定性种子 → 可复现） |
| 关联 STA 数量统计 | `architecture.md` §8 | `AT+STALIST` + UI 卡片「关联 STA N」+ STA 列表（MAC/实时 RSSI） |
| 距离/路径损耗（原「`AT+RSSI` 恒定」） | `usage.md` 故障表 | `AT+DIST=<米>` / `AT+PATHLOSS=<n>`：RSSI = 对端发射功率 − PL（默认关） |
| RAW 接入窗口 | `architecture.md` §8（本仓新提） | `AT+RAW=<槽位>`：AP 分槽、STA 只在槽内发数据帧（近似模型） |
| TWT 目标唤醒时间 | 同上 | `AT+TWT=<间隔>[,<窗口>]`：STA 睡着时排队/丢下行（近似模型） |
| 虚拟空口换成 TCP/UDP（跨房间联调） | `architecture.md` §8 | **已是 TCP**（默认），另有串口空口（连真实板 UART2） |
| 帧抓包（hex dump）便于协议分析 | `architecture.md` §8 | `AT+SYSDBG=WNB,1` → `FRAME:TX/RX <hex>` + UI 帧监视器（含以太头解码） |
| 「给上层提供虚拟 host 口」正式化 | 代码注释 / 另一仓 README | **`docs/host_port.md`**（帧格式/语义/丢弃条件/端口 0）+ 回归 3 条用例 |
| 空口参数面板（发射功率 + STA 关联状态） | 用户 2026-09-13 要求 | UI 配置面板两行（功率/距离/损耗/丢包/关联失败/RAW/TWT）+ 卡片显示 |
| 聚合自检入口 | 本仓惯例缺失 | `simulator/run_checks.py`（回归 + 文案字典 + 静态检查）→ `checks_report.md` |
| `.vscode/tasks.json` 里 231 条死任务 | 迁出 ORPAH 后的残留 | 239 → 9 条（人工维护的 `sim-*`/`py-compile-sim`/`list-ports`） |

## 二、不做（附理由 —— 别再加回来）

| 项 | 出处 | 为什么不做 |
|---|---|---|
| WPA-PSK 真实加解密（AES/CCMP） | `architecture.md` §8 | 模拟器不模拟 PHY/MAC，加解密只能验证“算法库能跑”，验不了协议正确性；**做了反而给人“安全已验证”的错觉**。参数校验 + 加密标记已够用，真加解密留给真机 |
| 吞吐量 / 关联数的**速率**建模 | 用户 2026-09-13 追问项 | 事件驱动的假空口没有速率、竞争、重传模型，算出来的吞吐曲线是编的。要测吞吐上真机（iperf） |
| RAW/TWT 的**真实 PHY/MAC 时序**（优先级、退避、分片、TWT 协商） | `architecture.md` §15-18 边界 | 同上：那需要真正的 PHY 层模拟。本仓只做「窗口约束数据帧」的行为近似，边界写在 §8.1 |
| 射频测试命令（`AT+TX_CW`/`AT+QA_START`/`AT+TX_CONT`/`AT+REG_RD/WT`/`AT+ADC_DUMP`） | `AT_commands.md` §7 | 要有射频才有意义；真机请用厂商工具 |
| `AT+ACKTMO` / `AT+TX_MCS` / `AT+HEART_INT` 的“真实生效” | `AT_commands.md` §3 `△` | 没有速率/重传/心跳模型时，它们的取值不会产生任何可观测差异 —— 保持“存参数”诚实，别假装生效 |
| 串口日志**分级**（等级可调） | `architecture.md` §8 | 现在的开关（`AT+SYSDBG=LMAC/WNB`）已覆盖「要/不要调试流」；分级是 vendor 固件的家事 |

> 已用 TWT 模型替代的旧项：`AT+PS_MODE` 的「真正休眠」（`AT_commands.md` §4 `△`）——
> 见 `AT+TWT`。`AT+ROAM` 一直在真生效（影响 STA 断线后行为），保留。

## 三、留待真机 / 外部（附触发条件）

| 项 | 出处 | 触发条件 / 归谁 |
|---|---|---|
| 掉电保存配置（`sim_cfg_save()`，写 Flash 最后一页） | `firmware/README.md` | **真机阶段**：PC 侧没有“掉电”概念；上机时由用户执行烧录验证 |
| 换主频（`board.h` → 96MHz PLL） | `firmware/README.md` | 真机阶段，且**只在需要更多算力时**才做（当前 8MHz 够跑） |
| 从「SPI 从机模拟」接到**真实 TXW8301** | `firmware/README.md` | 真机阶段：需要真实 MACBUS_SPI host 驱动 + 烧录（用户执行） |
| `hc01`（HT-HC01）的真实 AT 方言 | `AGENTS.md` §7 | **拿到 HT-HC01 手册**后补方言（现在按泰芯 AH 同款占位，已在档案/UI/README 标注） |
| 泰芯跨固件互通（TX-AH ↔ TH-RJ45 代次不兼容） | `docs/crossfw-taixin-handoff.md`（不入库） | **等厂商答复/固件镜像**（已记 F-09）；本仓只留结论：同代必通、跨代必不通 |
| 多实例编排（>2 台虚拟设备一台机跑） | `architecture.md` §8 | 演示需要时再做（现在 `--host-sim` 两台够用；模拟器已支持端口 0 自动分配，多开不冲突） |
| 真机 RSSI/能量标定、`router_id` 落库等 | 不属本仓 | 在 `orpah-over-halow` 的 ROADMAP 里跟踪 |

## 四、维护约定

- 新增「以后要做」的念头 → **要么当场做，要么写进上面第二/三节并写清理由/触发条件**；
  别散落回各文档的正文里（这次收敛就是为此）。
- 本表是**唯一**的 backlog 汇总；各文档正文只保留「已做」的能力描述与指向本表的链接。
