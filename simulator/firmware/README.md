# 固件（CH32V203）

纯软件模拟器固件，裸机、无 RTOS、无 libc（`-nostdlib`），全部自包含。

## 目录

```
firmware/
├── Makefile                  # riscv-none-elf-gcc 构建
├── ld/link.ld                # 链接脚本（64K Flash / 20K RAM）
├── startup/startup_ch32v203.S# QingKe V2 启动（向量表 + 复位）
├── Core/
│   ├── ch32v20x.h            # 寄存器定义（自包含，无 CMSIS）
│   ├── board.h               # 引脚映射 / 配置 / SIM_IRQ
│   └── main.c                # 主循环、TIM2 时基、UART/控制台 IRQ
├── Periph/
│   ├── gpio.c/h              # GPIO 驱动
│   ├── uart.c/h              # USART 中断收发 + 迷你 printf
│   └── spi_slave.c/h         # SPI1 从机（宿主接口帧协议 + IRQ）
└── Simulator/
    ├── sim_util.c/h          # 字符串 / hex / CRC8 / memcpy 工具
    ├── sim_cfg.c/h           # 配置存储（模拟 syscfg）
    ├── sim_wifi.c/h          # AP/STA/配对/RSSI/数据转发 状态机
    ├── sim_at.c/h            # AT 命令引擎（含 TXDATA 数据模式）
    ├── sim_link.c/h          # UART2 虚拟空口（组帧/CRC）
    └── sim_led.c/h           # CONN/RSSI 灯、CONNECT 键、模式拨码
```

## 构建

**必须用 MounRiver Studio 自带的那份工具链**（`-DWCH_INTERRUPT_FAST` 依赖它的
`interrupt("WCH-Interrupt-fast")` + 启动文件里的硬件栈配置；独立 xPack 版**会跑飞**）。
`Makefile` 的 `RISCV_PREFIX` **默认就指向本机 MRS2 内嵌的那份**（前缀是
**`riscv-none-embed-`**，不是 `riscv-none-elf-`），所以本机直接：

```bash
# 在 firmware/ 目录
make                       # -> build/txw8301-sim.elf / .bin
make clean
# 换机器/换工具链时覆盖前缀：
make RISCV_PREFIX='C:/别的工具链/bin/riscv-none-embed-'
```

要点：
- **Windows 上不需要 sh**（2026-09-21 实测 Win11 + GNU Make 4.4.1）：recipe 里的
  `mkdir -p` / `rm -rf` 会报「找不到指定的文件」（make 对没有 shell 元字符的行**直接
  CreateProcess**，不经 sh；本机 `sh` 也不在 PATH）⇒ 建/删目录已改成 `cmd /c`
  （`Makefile` 里的 `MKDIR`/`RMDIR`，POSIX 平台仍用 `mkdir`/`rm`）。
- `-DWCH_INTERRUPT_FAST` 使用 WCH 的 `interrupt("WCH-Interrupt-fast")` 中断模型，
  与启动文件 `csrw 0x804, 0x3`（硬件栈/嵌套）配合。
- `-msmall-data-limit=8` 需要链接脚本中的 `__global_pointer$`（已提供）。
- 主频 **8MHz HSI、无 PLL**：最简最稳；波特率 115200 误差约 0.6%。

## 烧录

- 方式 A（推荐）：**WCH-Link**（SWD）—— ★ 地址必须是 **`0x00000000`**（与 `ld/link.ld` 的链接基址一致）：
  ```bash
  openocd -f interface/wch-link.cfg -f target/ch32v20x.cfg \
          -c "program build/txw8301-sim.bin 0x00000000 verify reset exit"
  ```
  或直接用 MounRiver 的下载按钮 / WCHISPTool（**下载方式 = USB**）。
  ★ `make` 会同时出 `.hex`（**自带地址**，工具不用猜起始地址 ⇒ 更稳）与 `.bin`，WCHISPTool 选两者都能烧。
- 方式 B：串口 ISP（BOOT0 拉高 + USB-C，WCHISPTool，烧完 BOOT0 拉低复位）。
- ⚠ **下载完不会自动运行，必须按一次 `RST`**（不按 = "刷完什么也没有"，最容易被当成固件坏了）。

## 运行时行为

- 上电后 UART1（CH340C，115200 8N1）输出启动横幅；`AT` 返回 `OK`。
- UART2（PA2/PA3）为虚拟空口，两板 TX↔RX + GND 对连即可模拟 AP↔STA。
- SPI1（PA4~PA7）+ IRQ(PB0) 为宿主接口，协议见 `docs/spi_protocol.md`。
- LED/按键/拨码交互见 `docs/usage.md`。

### 控制台行为（2026-09-21 上机加固后）

- **`\r` 与 `\n` 都当行尾**（CRLF 也行：尾随的 `\n` 不会执行一条空命令）⇒ 终端行尾设置不再敏感。
- **会回显可打印字符**（输入完敲回车，响应从新行开始）。
  ⚠ **数据模式例外**：`AT+TXDATA=<len>` 之后那 `<len>` 个字节是**二进制裸帧**，
  **不当行、也不回显**（`console_on_byte` 里 txdata 分支在最前面）。
- 应答格式（`sim_at.c` 文件头）：成功 `OK\r\n`、失败 `ERROR\r\n`、取值 `XXX:值\r\nOK\r\n`。
- ★ **背景（加固前的坑）**：加固前只认 `\n`、`\r` 被丢弃**且不清行缓冲** ⇒ 只会发 CR 的终端
  （PuTTY 默认）敲 `AT` 毫无反应，且下一条命令会被残留字符粘成一条（`AT\r` 后发 `AT\r\n`
  ⇒ 实际执行 `ATAT` ⇒ `ERROR`）；而且不回显。**手上是加固前那版**（`text 14818`）时：
  终端设成发 LF（PuTTY 勾 `Implicit LF in every CR`；WindTerm 发送后缀设 LF）。

## ✔ 上机记录（2026-09-21，nanoCH32V203）

台架：nanoCH32V203（刷本仓 `txw8301-sim.hex`）+ CH347F `P2/UART0` = COM23 ↔ 板 `PA9/PA10`(USART1)，
115200 8N1。

**已实测成立（T1）**：

| 现象 | 证明了什么 |
|---|---|
| 横幅 `TXW8301 Simulator v0.1.0 (CH32V203, no RF)` + `AT console ready.` | 链接基址 `0x0` 对（+ 时钟/GPIO 正常） |
| `AT`（LF 结尾）→ `OK` | `IRQn_Type` +16 对（RX 中断真的进来了） |
| `AT+SYSDBG=WNB,1` / `=LMAC,1` → **每秒一行** | 1 ms 时基 + 主循环在转（TIM `INTFR`/`ATRLR`） |
| `LMAC: link_tx=3818 → 3832…`（**每秒 +2**） | 空口 TX 真的在发字节（AP 信标 500 ms 一次）⇒ **USART2 外设时钟也对**（若时钟没开，`uart_putc` 会卡在等 `TXE` 的死循环，主循环早该冻住）|

★ 上电时是 **AP 模式**（不是 `sim_cfg` 默认的 STA）：nano 上**没有模式拨码** ⇒ `PA1/PB5` 悬空被上拉读高
⇒ `dip_read()` = `00` = AP（`sim_led.c` 启动时会把拨码值写进 mode）。`AT+MODE=` 之后能覆盖它。

★ 上面那轮（`text 14818`）用的是**加固前**版本；**加固后（`text 14862`，2026-09-21 当晚已重烧）实测**：

- ✔ **回显**：控制台能看到自己敲的 `AT+SYSDBG=WNB,1` / `AT+SYSDBG=LMAC,1`，随后 `OK` —— 与加固前"敲字屏幕不动"完全不同。
- ✔ 周期行照旧（`WNB: …` / `LMAC: link_tx=… link_rx=0`），说明加固没碰到数据面/时基。
- ○ **`\r` 也当行尾**这条**未单独实测**（重烧后用的终端本来就发 LF）—— 要真验就发一次 `AT\r`：
  现在应该回 `OK`，而不再是"无反应 + 把下一条命令粘成 `ATAT`"。
- 该版产物：`txw8301-sim.hex` 41875 B（`sha256 0D4543E9BCE1AA8C…`）、`.bin` 14875 B（`B26636ACBDA33465…`）。

**仍未验证（如实）**：两板或 PC↔板的 AP↔STA 配对（虚拟空口 `link_rx` 一直 0，没接对端）；
SPI 宿主口；LED/按键/拨码交互（**nano 板上没有这些器件**）；`AT+TXDATA` 数据面。

## 移植 / 扩展
- **换主频**：`board.h` 中 `SYSTEM_CLOCK_HZ`，并在 `SystemInit` 配置 PLL。
- **掉电保存配置**：实现 `sim_cfg_save()`（写最后一页 Flash，1KB @ 0x0800FC00）。
- **改引脚**：`board.h` 与 `docs/hardware.md` 保持一致。
- **接入真实 TXW8301**：把 SPI 从机驱动换成真实 MACBUS_SPI host 驱动，AT 引擎可直接复用。

> 上面这几项的**结案**（做 / 不做附理由 / 留待真机的触发条件）统一记在
> [`../docs/backlog.md`](../docs/backlog.md)。新增待办请写那里，不要只写在本节里。
