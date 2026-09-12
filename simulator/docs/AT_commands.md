# 模拟器 AT 命令参考

命令集与响应格式对齐 [T-Halow-RJ45 AT_cmd.md](../../../T-Halow-RJ45/docs/AT_cmd.md) 与泰芯
TXW8301 SDK 的 AT 层（`libatcmd`）：

- 大小写不敏感；串口工具选**新行模式**发送（`\r\n` 结尾）。
- 查询命令用 `?`（`AT+MODE?`）；设置命令 `AT+XXX=val`。
- 成功响应 `OK\r\n`；带返回值 `CMD:值\r\nOK\r\n`；失败 `ERROR\r\n`。
- 事件为主动上报的 `+XXX` 行。

> 标记说明：
> - **✔ 模拟**：模拟器真实实现该行为。
> - **△ 兼容**：接受该命令、返回 OK 并保存参数，但行为在纯软件模拟中无实义
>   （如实射频参数），保留是为了 host 固件可原样移植。
> - **✖ 未实现**：返回 `ERROR`（或固定值），一般不使用。

---

## 1. 基础网络命令

### `AT+MODE`  ✔
设置/查询工作模式。

```
AT+MODE?          → MODE:AP\r\nOK
AT+MODE=AP
AT+MODE=STA
AT+MODE=GROUP
AT+MODE=APSTA
```

### `AT+SSID`  ✔
设置/查询 SSID（≤ 32 字符）。

```
AT+SSID=halowlink
AT+SSID?          → SSID:halowlink\r\nOK
```

### `AT+KEYMGMT`  ✔（仅参数/标记）
设置加密方式：`WPA-PSK` / `NONE`。纯软件模拟不做真实加解密，仅校验参数、
标记加密状态并影响配对/关联的"加密匹配"判定。

### `AT+PSK`  ✔（仅参数）
设置加密密码，必须 64 个十六进制字符；长度不合法则返回 ERROR（参考实现会清空旧值）。

### `AT+PAIR`  ✔
开启/停止配对。配对成功上报 `+PAIR SUCCESS`；`AT+PAIR=0` 停止并自动连接。

```
AT+PAIR=1
AT+PAIR=0
```

### `AT+BSS_BW`  ✔（参数/信道匹配）
设置 BSS 带宽：1 / 2 / 4 / 8 MHz。用于 STA 扫描时的信道带宽匹配。

### `AT+FREQ_RANGE`  ✔（生成信道列表）
设置连续频率范围（单位 0.1MHz）：`AT+FREQ_RANGE=9080,9240`。
内部按 `BSS_BW` 步进生成信道列表（`AT+CHAN_LIST` 优先）。

### `AT+CHAN_LIST`  ✔
设置非连续频点列表（最多 16 个）：`AT+CHAN_LIST=9080,9160,9240`。

---

## 2. 状态查询命令

### `AT+RSSI`  ✔
```
AT+RSSI?           → RSSI:-47\r\nOK
AT+RSSI=1          → 按索引（从 1 起）查某个关联 STA（AP）
AT+RSSI=-47        → 手动注入固定值（同时**关闭**距离模型）
AT+RSSI=f4:de:09:68:6c:20  → 按 MAC 查（本模拟器扩展）
```
- 单位 = **dBm（负值）**；`0` = 无链路 / 无该 STA。
- 值从哪来：默认是注入值（`sim_cfg.rssi`，默认 `-30`）；开了**距离模型**
  （`AT+DIST=<米>`，见 §8）后 = 对端自报的发射功率 − 路径损耗。
  → 即 `AT+TXPOWER` 现在**真的**会改变对端看到的信号强度（以前它只是“存起来的参数”）。
- AP 侧：`AT+RSSI=1` 取第 1 个关联 STA 的信号，该值随对端保活（每 2s）持续刷新。
- 兼容：传正值当幅度取负（旧写法 `AT+RSSI=30` → `-30`）。

### `AT+CONN_STATE`  ✔
```
AT+CONN_STATE      → CONN_STATE:CONNECTED\r\nOK
```
取值：`IDLE` / `SCANNING` / `ASSOCIATING` / `CONNECTED` / `DISCONNECTED`。

### `AT+WNBCFG`  ✔
查看设备参数（类似真实固件的 syscfg dump）。本模拟器还会打出 `TXPOWER` / `DIST` /
`PATHLOSS`（空口参数面板读的就是这几个值）。

### `AT+SCAN_AP`  ✔（模拟扫描）
```
AT+SCAN_AP=2       → 模拟扫描 N 秒，随后用 AT+BSSLIST 读取
```

### `AT+BSSLIST`  ✔
返回"扫描到"的 AP 列表（由虚拟空口上的对端 AP 生成）。

### `AT+MAC_ADDR`  ✔
查看/设置设备 MAC（默认 4A:06:59:7B:6C:98 之类本地管理地址）。

### `AT+VERSION`  ✔
查看固件版本（模拟器返回 `TXW8301-SIM` 版本串，格式仿真实固件）。

---

## 3. 高级参数

| 命令 | 说明 | 状态 |
|------|------|------|
| `AT+TXPOWER=[6~20]` | 发射功率(dBm) | ✔ 影响对端 RSSI（需 `AT+DIST`>0，见 §8） |
| `AT+ACKTMO=[us]` | ACK 超时 | △ 保存参数 |
| `AT+TX_MCS=[0~7/255]` | TX MCS，255=自动 | △ 保存参数 |
| `AT+HEART_INT=[ms]` | 心跳间隔 | △ 保存参数（AP 同步给 STA） |
| `AT+ROAM=[0/1]` | 漫游开关 | ✔ 影响 STA 断线后行为 |

---

## 4. 中继 / 组播 / 休眠

### `AT+R_SSID` / `AT+R_PSK`  ✔（APSTA 参数）
APSTA 模式连接上级 AP 的 SSID / PSK（只支持一级中继）。

### `AT+JOINGROUP`  ✔
```
AT+MODE=GROUP
AT+JOINGROUP=11:22:33:44:55:66,3   // 组播组地址, AID=3
```

### `AT+PS_MODE=[0..4]`  △
设置 STA 休眠模式；纯软件模拟中接受参数并返回 OK，不真正休眠（避免调试时失联）。

---

## 5. 调试 / 维护

| 命令 | 说明 | 状态 |
|------|------|------|
| `AT+LOADDEF=1` | 恢复出厂设置（清配置并重启） | ✔ |
| `AT+SYSDBG=LMAC,0/1` | 空口统计打印 | ✔（虚拟空口帧统计） |
| `AT+SYSDBG=WNB,0/1` | 网络层统计打印 | ✔ |
| `AT+RST` | 软复位 | ✔ |
| `AT+FWUPG` | Xmodem 固件升级入口（打印 CCC） | △ 预留（可用 WCH-Link 烧录代替） |

---

## 6. 数据命令

### `AT+TXDATA`  ✔（UART 直发调试口）
与真实固件一致：在非透传模式通过串口发一帧数据，需先补 14 字节以太网头。

```
at+txdata=24                 // 14字节以太网头 + 10字节数据
4A 06 59 A5 81 98 4A 06 59 7B 6C 98 30 30 31 32 33 34 35 36 37 38 39 30
```

> 注意：**数据通路在 SPI 宿主接口**，`AT+TXDATA` 只是单帧调试口（与参考板一致）。

---

## 7. 未实现命令

`AT+SCAN_AP` 之外的射频测试命令（`AT+TX_CW`、`AT+QA_START`、`AT+TX_CONT`、
`AT+REG_RD/WT`、`AT+ADC_DUMP` 等）统一返回 `ERROR`，避免 host 误以为已执行。
如需扩展，在 `sim_at.c` 命令表追加即可。

---

## 8. 模拟器扩展命令（真实模块没有）

为「无射频调参」而加：真机收到会回 `ERROR`。UI 的配置面板会用到它们。

### `AT+STALIST`  ✔
AP 的关联 STA 表，**单行**输出（便于轮询解析；空表 = `STALIST:0`）：
```
AT+STALIST   → STALIST:2,82:59:13:64:70:90=-55,aa:bb:cc:dd:ee:ff=-61\r\nOK
```
> 真机的 STA 信息在固件的周期调试块里（`STA1: <mac>`），本模拟器把它做成了可查询的 AT。
> PC 模拟器的 UI 直接读进程内状态（不走 AT）——两条路径填同一组字段。

### `AT+DIST=<米>` / `AT+PATHLOSS=<n>`  ✔
距离模型：`RSSI = 对端自报的发射功率 − PL`，其中

$$
PL(dB) = 20\lg(f_{MHz}) - 27.55 + 10n\lg(d_m)
$$

- `AT+DIST=0`（默认）= **不建模**，RSSI 用注入值 → 行为与以前完全一致；
- `n` = 路径损耗指数：**2 = 自由空间**，2.7~4 = 室内；范围 1~8；
- 例：f=908MHz、d=10m、n=2 → PL≈51.6dB；AP 发 20dBm → 对端收到 ≈ **-32 dBm**；
- ⚠ 距离是**链路属性**，而且每个方向各自算（本机拿「对端自报的功率」− 「本机设的距离」）
  → 想让两端都按 10m 算，就**两端都设**（UI 的配置面板会把 `AT+DIST`/`AT+PATHLOSS`
  同时下发给两台模拟器）。
### `AT+LOSS=<百分比 0..100>`  ✔
数据帧**丢包注入**（0 = 默认关）。只作用**数据帧**，控制帧（beacon/assoc/保活）不受影响。
确定性：同一个 `seed` + 同样的调用序列 → 同样的丢包序列（演示/测试可复现），
计数字段 `loss`（`WNBCFG` / `AT+SYSDBG=WNB,1` 里能看到）。

### `AT+ASSOC_FAIL=<百分比 0..100>`  ✔
**关联请求失败概率**（0 = 默认关）：命中则本次 ASSOC_REQ 不发出去（模拟丢/被拒），
STA 继续 0.5s 重试、AP 侧根本看不到它 → 界面上表现为一直 `SCANNING`。该行为即
`docs/architecture.md` §6 早先写的“模拟关联成功（可配失败概率）”。

### `AT+RAW=<槽位数 0..16>`  ✔
**RAW（Restricted Access Window）接入窗口**（0 = 默认关）：>0 时 AP 把 beacon 周期
（0.5s）均分成 n 个槽，每个关联 STA 分一个槽（轮转；`ASSOC_RESP` 第 3/4 字节下发
「槽位 / 槽数」），STA **只在自己的槽内发数据帧**；窗口外发的帧**排队**等下一个
beacon（不是丢），计数 `raw_defer`。

> ⚠ `AT+RAW` **只在 AP 上有意义**（RAW 调度是 AP 的事）；STA 不需要配，它从
> `ASSOC_RESP` 学。本模型只约束 **STA 上行数据帧**（AP 下行不约束）。

### `AT+TWT=<间隔ms>[,<窗口ms>]`  ✔
**TWT（Target Wake Time）唤醒窗口**（0 = 默认关）：STA 每 `间隔ms` 只醒 `窗口ms`
（默认 50ms，窗口与上一个 beacon 对齐）。睡着时：自己要发的数据帧**排队**，
收到的**下行数据帧丢掉**（计数 `twt_defer` / `twt_drop`）。

> ⚠ TWT 是 **STA 侧休眠**模型，只在 STA/APSTA 上生效；控制帧不受影响。
> 与 `AT+PS_MODE` 的关系：`PS_MODE` 仍只是“存参数”，真正的休眠行为在这个模型里。