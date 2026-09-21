# TXW8301 Simulator — CH32V203 firmware Makefile
#
# 工具链：**必须用 MounRiver Studio 自带的那份**（`-DWCH_INTERRUPT_FAST` 依赖它的
#   interrupt("WCH-Interrupt-fast") + 启动文件里的硬件栈配置；独立 xPack 版中断模型不同、会跑飞）。
#   前缀是 **riscv-none-embed-**（不是 riscv-none-elf-）。
#
# 用法：
#   make                                          # 默认用本机 MRS2 内嵌工具链（可直接 make）
#   make RISCV_PREFIX='C:/别的工具链/bin/riscv-none-embed-'
#   make clean
#
# ★ Windows 实测（2026-09-21，Win11 + GNU Make 4.4.1 / chocolatey Windows32 版）：
#   recipe 里的 POSIX 命令**不一定经过 sh** —— 对没有 shell 元字符的行，make 会直接
#   CreateProcess 那个程序 ⇒ `mkdir -p` / `rm -rf` 报「找不到指定的文件」；
#   本机 `sh` 也不在 PATH（Git 的 sh.exe 在 D:/Program Files/Git/bin/ 里，但不在 PATH），
#   而 `make SHELL=...` 在这个组合下**改变不了**这一点。
#   ⇒ 建/删目录已改成**不依赖 sh**：Windows 走 `cmd /c`（见下面 MKDIR/RMDIR），POSIX 平台仍用 mkdir/rm。
#
# 另一条测出来的坑：变量赋值**不要写行内注释** —— 注释前的对齐空格会留在值里，
#   先决条件就变成 `../proto   /sn.c`（找不到）而规则静静失效。注释请单独一行。
#
# Output: build/txw8301-sim.elf  build/txw8301-sim.bin

RISCV_PREFIX ?= F:/MounRiver/MounRiver_Studio2/resources/app/resources/win32/components/WCH/Toolchain/RISC-V Embedded GCC/bin/riscv-none-embed-
CC      = $(RISCV_PREFIX)gcc
OBJCOPY = $(RISCV_PREFIX)objcopy
SIZE    = $(RISCV_PREFIX)size

TARGET  = txw8301-sim
BUILD   = build
STARTUP = startup/startup_ch32v203.S
LINK    = ld/link.ld

ARCH = -march=rv32imac -mabi=ilp32 -msmall-data-limit=8 -mno-save-restore

CFLAGS = $(ARCH) -Os -ffunction-sections -fdata-sections \
         -fmessage-length=0 -fsigned-char -ffreestanding -fno-builtin \
         -nostdlib -Wall -Wextra -DWCH_INTERRUPT_FAST \
         -ICore -IPeriph -ISimulator

ASFLAGS = $(ARCH) -ICore -IPeriph -ISimulator

LDFLAGS = -nostartfiles -nostdlib -T $(LINK) \
          -Wl,--gc-sections -Wl,-Map=$(BUILD)/$(TARGET).map

SRCS = Core/main.c \
       Periph/gpio.c \
       Periph/uart.c \
       Periph/spi_slave.c \
       Simulator/spi_proto.c \
       Simulator/sim_util.c \
       Simulator/sim_cfg.c \
       Simulator/sim_wifi.c \
       Simulator/sim_at.c \
       Simulator/sim_link.c \
       Simulator/sim_led.c

# 建目录 / 删目录：**不能用 `mkdir -p` / `rm -rf`** —— make 对没有 shell 元字符的行会直接
# CreateProcess 那个程序（不经 sh），而 `mkdir`/`rm` 都不是 Windows 程序（实测都报「找不到
# 指定的文件」；`SHELL=` 也改变不了）。改用 **cmd 这个真程序**（走 `cmd /c`）；
# POSIX 平台（make 的 OS 不是 Windows_NT）仍用 mkdir/rm。
ifeq ($(OS),Windows_NT)
  MKDIR = cmd /c "if not exist $(subst /,\,$(1)) mkdir $(subst /,\,$(1))"
  RMDIR = cmd /c "if exist $(subst /,\,$(1)) rmdir /s /q $(subst /,\,$(1))"
else
  MKDIR = mkdir -p $(1)
  RMDIR = rm -rf $(1)
endif

OBJS = $(addprefix $(BUILD)/, $(SRCS:.c=.o))
OBJS += $(BUILD)/startup.o

all: $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex

$(BUILD):
	@$(call MKDIR,$(BUILD))
	@$(call MKDIR,$(BUILD)/Core)
	@$(call MKDIR,$(BUILD)/Periph)
	@$(call MKDIR,$(BUILD)/Simulator)

$(BUILD)/startup.o: $(STARTUP) | $(BUILD)
	$(CC) $(ASFLAGS) -c $< -o $@

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS) $(LINK)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)
	$(SIZE) $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

# ★ .hex：**自带地址** ⇒ WCHISPTool 「下载方式 = USB」选 .hex 时不用猜起始地址。
#   （.bin 靠工具自己按某个默认地址写 —— 写错地方就是“烧进去了但一条指令都不执行”，
#   2026-09-21 实测过的坑，所以两种产物都给。）
$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

clean:
	$(call RMDIR,$(BUILD))

flash: $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex
	@echo "Flash with WCH-Link / MounRiver / openocd:"
	@echo "  openocd -f interface/wch-link.cfg -f target/ch32v20x.cfg \\"
	@echo "         -c \"program $(BUILD)/$(TARGET).bin 0x00000000 verify reset exit\""

.PHONY: all clean flash
