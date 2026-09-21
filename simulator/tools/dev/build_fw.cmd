@echo off
rem ============================================================================
rem  用 make 重建模拟器固件 + 列出产物与哈希
rem
rem  前提：make 在 PATH 里。**不需要 sh** —— firmware/Makefile 的建/删目录已在 Windows 上
rem  改走 `cmd /c`（不用 mkdir -p / rm -rf），工具链也默认指向 MounRiver 的绝对路径
rem  （可用 `make RISCV_PREFIX=...` 覆盖）。所以不要再加「先查 sh、没有就退出」这种闸门：
rem  那会挡住本来能跑的构建（我 2026-09-22 就这么错过一次）。
rem  本机确实没 sh，但 make 仍然能编过 —— 需要看环境时跑 probe_toolchain.cmd。
rem ============================================================================
setlocal
where make >nul 2>nul || (echo [!!] PATH 里没有 make & exit /b 2)

set "FW=%~dp0..\..\firmware"
cd /d "%FW%" || exit /b 2

echo ===== make clean =====
make clean
echo [clean exit=%errorlevel%]
echo ===== make =====
make
echo [make exit=%errorlevel%]

echo ===== 产物 =====
if exist build\txw8301-sim.bin (
  powershell -NoProfile -Command "Get-Item build\txw8301-sim.bin,build\txw8301-sim.hex,build\txw8301-sim.elf -ErrorAction SilentlyContinue | ForEach-Object { $_.Name + '  ' + $_.Length + ' B  ' + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') + '  sha256=' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash.Substring(0,16) }"
) else (
  echo   没有产物 —— make 没成功（先看上面的 exit 码）
)
