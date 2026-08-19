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

需要 RISC-V GCC 工具链（推荐 **MounRiver Studio** 自带，或 xPack 版）：

```bash
# 在 firmware/ 目录
make                       # -> build/txw8301-sim.elf / .bin
# 指定工具链前缀（如 MounRiver 安装路径）
make RISCV_PREFIX="C:/MounRiver/MounRiver_Studio/toolchain/RISC-V GCC Toolchain/bin/riscv-none-elf-"
make clean
```

要点：
- `-DWCH_INTERRUPT_FAST` 使用 WCH 的 `interrupt("WCH-Interrupt-fast")` 中断模型，
  与启动文件 `csrw 0x804, 0x3`（硬件栈/嵌套）配合，**必须用 MounRiver 工具链**。
- `-msmall-data-limit=8` 需要链接脚本中的 `__global_pointer$`（已提供）。
- 主频 **8MHz HSI、无 PLL**：最简最稳；波特率 115200 误差约 0.6%。

## 烧录

- 方式 A（推荐）：**WCH-Link**（SWD）：
  ```bash
  openocd -f interface/wch-link.cfg -f target/ch32v20x.cfg \
          -c "program build/txw8301-sim.bin 0x08000000 verify reset exit"
  ```
  或直接用 MounRiver 的下载按钮 / WCHISPTool。
- 方式 B：串口 ISP（BOOT0 拉高 + USB-C，WCHISPTool，烧完 BOOT0 拉低复位）。

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
