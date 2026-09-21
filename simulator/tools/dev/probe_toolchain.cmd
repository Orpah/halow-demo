@echo off
rem ============================================================================
rem  看本机有没有编译模拟器固件所需的东西（换机器/换 shell 时先跑它）
rem
rem  为什么要 probe 而不是直接 make：这台机器上「make 报错」的原因可能是
rem  sh 不在 PATH、也可能编译器名字不同（riscv-none-embed-gcc vs -elf-），
rem  两种情况都表现为一头雾水的报错。先 probe 再决定用哪个构建脚本。
rem ============================================================================
echo === make ===
where make 2>nul && make --version 2>nul | findstr /C:"GNU Make" || echo   (没有 make：用 rebuild_fw_manual.cmd)
echo === sh（Makefile 的 recipe 要它）===
where sh 2>nul || echo   (没有 sh：make 会失败，改用 rebuild_fw_manual.cmd)
echo === riscv-none-embed-gcc ===
where riscv-none-embed-gcc 2>nul || echo   (不在 PATH)
echo === riscv-none-elf-gcc ===
where riscv-none-elf-gcc 2>nul || echo   (不在 PATH)
echo === MounRiver 默认安装位置 ===
if exist "F:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe" (echo   F: 有) else (echo   F: 没有)
if exist "C:\MounRiver\MounRiver_Studio2\resources\app\resources\win32\components\WCH\Toolchain\RISC-V Embedded GCC\bin\riscv-none-embed-gcc.exe" (echo   C: 有) else (echo   C: 没有)
echo === Git 自带的 sh（orpah 的检查脚本共用它）===
if exist "D:\Program Files\Git\bin\sh.exe" (echo   D:\Program Files\Git\bin\sh.exe 有) else (echo   D:\Program Files\Git\bin\sh.exe 没有)
if exist "C:\Program Files\Git\bin\sh.exe" (echo   C:\Program Files\Git\bin\sh.exe 有) else (echo   C:\Program Files\Git\bin\sh.exe 没有)
echo === python / playwright（截图用）===
where python 2>nul || echo   (没有 python)
for /f "delims=" %%p in ('where python 2^>nul') do (
  echo   %%p
  "%%p" -c "import playwright" 2>nul && echo      playwright OK || echo      (这个解释器里没有 playwright —— python -m pip install playwright)
)
exit /b 0
