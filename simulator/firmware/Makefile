# TXW8301 Simulator — CH32V203 firmware Makefile
#
# Requires a RISC-V GCC toolchain. Two options:
#   A) MounRiver Studio (recommended):  riscv-none-elf-gcc in PATH
#   B) xPack riscv-none-elf-gcc
#
# Set RISCV_PREFIX to your toolchain prefix, e.g.:
#   make RISCV_PREFIX="C:/MounRiver/MounRiver_Studio/toolchain/RISC-V\ GCC\ Toolchain/bin/riscv-none-elf-"
#
# Output: build/txw8301-sim.elf  build/txw8301-sim.bin

RISCV_PREFIX ?= riscv-none-elf-
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
       Simulator/sim_util.c \
       Simulator/sim_cfg.c \
       Simulator/sim_wifi.c \
       Simulator/sim_at.c \
       Simulator/sim_link.c \
       Simulator/sim_led.c

OBJS = $(addprefix $(BUILD)/, $(SRCS:.c=.o))
OBJS += $(BUILD)/startup.o

all: $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin

$(BUILD):
	@mkdir -p $(BUILD)/Core $(BUILD)/Periph $(BUILD)/Simulator

$(BUILD)/startup.o: $(STARTUP) | $(BUILD)
	$(CC) $(ASFLAGS) -c $< -o $@

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS) $(LINK)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)
	$(SIZE) $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $@ $<

clean:
	rm -rf $(BUILD)

flash: $(BUILD)/$(TARGET).bin
	@echo "Flash with WCH-Link / MounRiver / openocd:"
	@echo "  openocd -f interface/wch-link.cfg -f target/ch32v20x.cfg \\"
	@echo "         -c \"program $(BUILD)/$(TARGET).bin 0x08000000 verify reset exit\""

.PHONY: all clean flash
