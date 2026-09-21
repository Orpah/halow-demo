@echo off
rem ============================================================================
rem  用 make 重建模拟器固件 + 列出产物与哈希
rem
rem  前提：make 在 PATH 里，**且 sh 也在** —— Makefile 的 recipe 走 shell。
rem  本机（2026-09-21 实测）没有 sh：那时请用 rebuild_fw_manual.cmd（不需要 sh）。
rem  这就是本脚本里先 `where sh` 的原因：早失败 + 说清原因，别让人对着
rem  「make 报了一串看不懂的错」猜。
rem ============================================================================
setlocal
where make >nul 2>nul || (echo [!!] PATH 里没有 make & exit /b 2)
where sh   >nul 2>nul || (
  echo [!!] PATH 里没有 sh —— Makefile 的 recipe 走 shell，make 会失败。
  echo      本机没装 sh 时请改用： rebuild_fw_manual.cmd
  exit /b 2
)

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
