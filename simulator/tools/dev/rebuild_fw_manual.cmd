@echo off
rem ============================================================================
rem  手工编译模拟器固件（**不需要 make / sh**）
rem
rem  为什么需要它：本机没装 sh，而 Makefile 的 recipe 走 shell —— make 会直接失败。
rem  这个脚本自己调 RISC-V 工具链逐文件编译再链接（等于把 Makefile 那套手做一遍）。
rem  能跑通 make 的机器用 build_fw.cmd 即可。
rem
rem  工具链查找顺序：环境变量 FW_CC -> PATH 里的 riscv-none-embed-gcc /
rem  riscv-none-elf-gcc -> MounRiver 默认安装位置。
rem  源码：Core\*.c Periph\*.c Simulator\*.c + startup\startup_ch32v203.S（用通配收集，
rem  所以 Makefile 的 SRCS 改了这里也跟得上）。
rem
rem  产物：simulator\firmware\build\txw8301-sim.{elf,bin,hex,map}
rem ============================================================================
setlocal enabledelayedexpansion
set "FW=%~dp0..\..\firmware"
cd /d "%FW%" || exit /b 2

rem ---- 找编译器 ----
set "CC="
if defined FW_CC set "CC=%FW_CC%"
if not defined CC for /f "delims=" %%p in ('where riscv-none-embed-gcc 2^>nul') do if not defined CC set "CC=%%p"
if not defined CC for /f "delims=" %%p in ('where riscv-none-elf-gcc 2^>nul') do if not defined CC set "CC=%%p"
if not defined CC if exist "F:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe" set "CC=F:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe"
if not defined CC if exist "C:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe" set "CC=C:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe"
if not defined CC (
  echo [!!] 找不到 RISC-V 编译器。装 MounRiver 后把 gcc 加进 PATH，或设 FW_CC 指向它。
  echo      也可以先跑 probe_toolchain.cmd 看本机有什么。
  exit /b 2
)
for %%i in ("%CC%") do (set "BIN=%%~dpi" & set "EXE=%%~ni")
set "PFX=!EXE:gcc=!"
echo 编译器: "%BIN%!PFX!gcc"

rem ---- 清理 + 建目录 ----
if exist build rmdir /s /q build
mkdir build\Core build\Periph build\Simulator || exit /b 2

set "ARCH=-march=rv32imac -mabi=ilp32 -msmall-data-limit=8 -mno-save-restore"
set "CFLAGS=%ARCH% -Os -ffunction-sections -fdata-sections -fmessage-length=0 -fsigned-char -ffreestanding -fno-builtin -nostdlib -Wall -Wextra -DWCH_INTERRUPT_FAST -ICore -IPeriph -ISimulator"

echo ==== 编译 ====
for %%f in (Core\*.c Periph\*.c Simulator\*.c) do (
  echo -- %%f
  "%BIN%!PFX!gcc" %CFLAGS% -c "%%f" -o "build\%%~nf.o" || exit /b 1
)
"%BIN%!PFX!gcc" %ARCH% -ICore -IPeriph -ISimulator -c startup\startup_ch32v203.S -o build\startup.o || exit /b 1

echo ==== 链接 ====
set "OBJS="
for %%f in (build\*.o) do set "OBJS=!OBJS! %%f"
"%BIN%!PFX!gcc" -nostartfiles -nostdlib -T ld\link.ld -Wl,--gc-sections -Wl,-Map=build\txw8301-sim.map -o build\txw8301-sim.elf !OBJS! || (
  echo -- 重试（加 -lgcc）
  "%BIN%!PFX!gcc" -nostartfiles -nostdlib -T ld\link.ld -Wl,--gc-sections -Wl,-Map=build\txw8301-sim.map -o build\txw8301-sim.elf !OBJS! -lgcc
) || exit /b 1

"%BIN%!PFX!size" build\txw8301-sim.elf
"%BIN%!PFX!objcopy" -O binary build\txw8301-sim.elf build\txw8301-sim.bin
"%BIN%!PFX!objcopy" -O ihex   build\txw8301-sim.elf build\txw8301-sim.hex
echo ==== 关键符号 ====
"%BIN%!PFX!readelf" -s build\txw8301-sim.elf | findstr /C:"_vector_base" /C:"_start" /C:" main" /C:"_eusrstack"
echo ==== 产物 ====
dir /b build\txw8301-sim.*
