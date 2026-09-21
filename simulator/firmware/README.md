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
  或直接用 MounRiver 的下载按钮 / WCHISPTool（下载方式 = USB，选 `.bin`）。
- 方式 B：串口 ISP（BOOT0 拉高 + USB-C，WCHISPTool，烧完 BOOT0 拉低复位）。
- ⚠ **下载完不会自动运行，必须按一次 `RST`**（不按 = "刷完什么也没有"，最容易被当成固件坏了）。

## 运行时行为

- 上电后 UART1（CH340C，115200 8N1）输出启动横幅；`AT` 返回 `OK`。
- UART2（PA2/PA3）为虚拟空口，两板 TX↔RX + GND 对连即可模拟 AP↔STA。
- SPI1（PA4~PA7）+ IRQ(PB0) 为宿主接口，协议见 `docs/spi_protocol.md`。
- LED/按键/拨码交互见 `docs/usage.md`。

## 移植 / 扩展
- **换主频**：`board.h` 中 `SYSTEM_CLOCK_HZ`，并在 `SystemInit` 配置 PLL。
- **掉电保存配置**：实现 `sim_cfg_save()`（写最后一页 Flash，1KB @ 0x0800FC00）。
- **改引脚**：`board.h` 与 `docs/hardware.md` 保持一致。
- **接入真实 TXW8301**：把 SPI 从机驱动换成真实 MACBUS_SPI host 驱动，AT 引擎可直接复用。

> 上面这几项的**结案**（做 / 不做附理由 / 留待真机的触发条件）统一记在
> [`../docs/backlog.md`](../docs/backlog.md)。新增待办请写那里，不要只写在本节里。
