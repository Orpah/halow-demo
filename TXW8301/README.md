# 天逯TXW8301开发环境

## 环境设置

泰芯TXW8301使用的MCU是玄铁E803，玄铁803官方推荐的开发工具是CDK（C-SKY development kit），CDK基于Eclipse，但是没有AI，所以我们这里转用VSCode来开发，这样你可以直接使用VSCode中的AI或AI插件，也可以使用CodeBuddy的AI。CodeBuddy基于VSCode，编译可以直接在CodeBuddy中完成，遇到任何编译和开发问题，可以直接让CodeBuddy帮你解决。

1. 下载并安装CDK
https://www.xrvm.cn/community/download?id=4478329920585535488

2. 设置环境变量

3. 安装 VSCode 扩展


## 编译


PATH
F:\C-Sky\CDK\CSKY\FlashProgrammer\Bins\


## 清理

```bash
cd FMAC_SDK/project
make -f cdkws.mk clean
```

```bash
cd WNB_SDK/project
make -f cdkws.mk clean
```



```powershell
cd f:\git\halow-demo\TXW8301
set SHELL=sh.exe
make SHELL=sh.exe -C WNB_SDK/project -f cdkws.mk All
```

```powershell
New-Item -Path "F:\git\halow-demo\TXW8301\FMAC_SDK" -ItemType Junction -Target "F:\git\tianlu\TXW8301\TX_AH_SDK_2.4_20260106160321\TX_AH_SDK_2.4\TXW8301_FMAC-v2.4.1.5-39777"
```

```powershell
New-Item -Path "F:\git\halow-demo\TXW8301\WNB_SDK" -ItemType Junction -Target "F:\git\tianlu\TXW8301\TX_AH_SDK_2.4_20260106160321\TX_AH_SDK_2.4\TXW8301_WNB-v2.4.1.3-39777"
```

### 编译环境的两条坑（2026-09-16 实测）

- **`make` 要用 CDK 自带的那个**（`F:\C-Sky\CDK\CSKY\MinGW\bin\make.exe`，GNU Make **3.82.90**）
  + 它的 msys `sh.exe`（`F:\C-Sky\CDK\CSKY\MinGW\msys\1.0\bin\sh.exe`）。
  chocolatey 装的 **GNU Make 4.4.1** 会挂在 `Project_PreBuild`：
  `process_begin: CreateProcess(NULL, echo Executing Pre Build commands ..., ...) failed`
  （即它没用上 `sh.exe`，直接把 `echo` 当程序执行）。
- 完整可用的一条（也可直接用 `.vscode/tasks.json` 的 **“Build Project (CDK)”** 任务）：

```powershell
cd F:\git\halow-demo\TXW8301\FMAC_SDK\project
$env:SHELL     = 'F:\C-Sky\CDK\CSKY\MinGW\msys\1.0\bin\sh.exe'
$env:MAKESHELL = $env:SHELL
$env:PATH = '.;F:\C-Sky\CDKRepo\Toolchain\CKV2ElfMinilib\V3.10.32\R\bin;F:\C-Sky\CDK\CSKY\MinGW\bin;F:\C-Sky\CDK\CSKY\MinGW\msys\1.0\bin;' + $env:PATH
& 'F:\C-Sky\CDK\CSKY\MinGW\bin\make.exe' SHELL=sh.exe -C F:/git/halow-demo/TXW8301/FMAC_SDK/project -f cdkws.mk All
```

- 产物：`FMAC_SDK\project\txw8301_v2.4.1.5-39777_<日期>_.bin`（同时复制成 `APP.bin`）。
  打包那步（`bakup\...`）在中文系统上会因带**中文星期/空格**的目录名报
  `'22609' is not recognized ...` / `The syntax of the command is incorrect` —— **不影响 bin 生成**。

## 主机口（mac_bus）切换：SDIO ⇄ UART

模组固件的主机口是**编译期**定的（`project/project_config.h` 的 `MACBUS_*` 宏 →
`sys_config.h` 的 `FMAC_MAC_BUS` → `main.c:262 wifi_mgr_init(...)`）。
原厂默认是 **SDIO**；SDK 里**没有 SPI 主机口的实现**（手册说「SPI 与 SDIO 是同一固件」，
即 SDIO 控制器的 SPI 模式，需要原厂主控驱动）。想让主机侧（PC / CH32V203）自己实现协议，
就编 **UART** 版：

```powershell
cd F:\git\halow-demo\TXW8301
python tools\fmac_macbus_switch.py status     # 看现在开的是哪个
python tools\fmac_macbus_switch.py uart       # 切成 UART 主机口（改两行宏，自动备份）
python tools\fmac_macbus_switch.py restore    # 用备份还原
```

切 UART 之后（`sys_config.h` 里就是这么定义的）：

| | 用哪个 UART | 模组脚 | 说明 |
|---|---|---|---|
| **数据口**（mac_bus） | `UARTBUS_DEV = HG_UART0` | **IOA10(RX) / IOA11(TX)** | 115200 8N1；`WIFIMGR_FRM_TYPE_RAW` → 线上是**裸以太网帧**（含 14B 以太头） |
| **AT/打印口** | `ATCMD_UARTDEV = HG_UART1` | **IOA12 / IOA13** | 开发板上就是"打印"那一排（2026-09-14 测 AT 用的就是它） |

- ⚠ 硬件侧：原厂 FAQ 说「角色选择 **IOB2**：RMII/USB/UART 用第 1 套方案，SDIO/SPI 用第 2 套方案」，
  以及开发板 UART 跳线要在 **A10/A11（通信）** 与 **A12/A13（打印）** 之间选。
  **跳线/电阻怎么配要找原厂确认**（本仓库只负责固件侧）。
- **怎么判一个 bin 是哪种 macbus**（不用烧板子）：看字符串 —— UART 版有
  `uart bus fixlen` + `mac_bus_uart_attach`；SDIO 版有 `mac_bus_sdio_attach`。
- 2026-09-16 实测：切 UART 后成功编出
  `txw8301_v2.4.1.5-39777_2026.9.16_.bin`（365584 B，sha1 `06ea7ec83074…`），
  特征串为上表 UART 版 ✓（**未烧录、未上机**）。

## 烧录
SecureCRT，通过串口连接设备，输入命令：
at+fwupg
出现CCC
选择【脚本】->【发送Xmodem】，选择要发送的文件，点击【Open】，等待发送完成。烧录成功，设备会自动重启。


## 调试

![XuanTieDebugServer](../images/XuantieDebugServer.png)

1. 打开VSCode

csky-elfabiv2-gdb.exe

csky-elfabiv2-gdb.exe -ex "monitor reset halt"

target remote 192.168.1.131:1025

2. 配置调试器

3. 启动调试

zadig工具可以修改设备的USB驱动，使设备在Windows中显示为COM端口。