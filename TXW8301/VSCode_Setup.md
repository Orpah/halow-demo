# 在 VSCode 中开发泰芯 TXW8301 项目

本指南帮助您在 Visual Studio Code 中配置泰芯 TXW8301 项目的开发环境。

## 前提条件

1. **安装 CDK 工具链**  
   确保已安装 C-Sky CDK 开发工具链。默认安装路径为 `F:/C-Sky/CDK`。如果安装在其他位置，请相应调整配置。

2. **设置环境变量**  
   将 C-Sky 工具链路径添加到系统 PATH 环境变量，或设置 `CSKY_TOOLCHAIN` 环境变量指向工具链的 `bin` 目录。
   
   例如，如果工具链路径为 `F:/C-Sky/CDKRepo/Toolchain/CKV2ElfMinilib/V3.10.32/R/bin`，则：
   - 在 Windows 命令提示符中临时设置：
     ```cmd
     set CSKY_TOOLCHAIN=F:\C-Sky\CDKRepo\Toolchain\CKV2ElfMinilib\V3.10.32\R\bin
     ```
   - 永久设置（系统属性 → 环境变量）

3. **安装 VSCode 扩展**  
   安装以下扩展：
   - **C/C++** (Microsoft)
   - **C/C++ Extension Pack**（推荐）

## 配置说明

我已经在 `.vscode/` 目录中创建了以下配置文件：

### 1. `tasks.json`
- 定义了构建任务：
  - `Build Project (CDK)`：默认构建任务（Ctrl+Shift+B）
  - `Clean Project`：清理构建输出
  - `Prebuild` / `PostBuild`：执行前后处理脚本

### 2. `c_cpp_properties.json`
- 配置了 IntelliSense 的包含路径和预处理器定义。
- **重要**：`compilerPath` 已预设为相对路径，指向工具链的 `bin` 目录。如果您的 CDK 安装路径不同，请修改该路径。
- 默认使用批处理文件 `csky-abiv2-elf-gcc.bat` 作为编译器路径。如果您已设置 `CSKY_TOOLCHAIN` 环境变量，可以取消注释相应的配置行。

### 3. `launch.json`
- 调试配置，使用 GDB 进行调试。
- `miDebuggerPath` 已预设为相对路径，指向 `csky-abiv2-elf-gdb.exe`。
- 如果已设置 `CSKY_TOOLCHAIN` 环境变量，可以取消注释相应的配置行。

## 使用方法

### 构建项目
1. 打开 VSCode 终端，确保当前目录为项目根目录。
2. 执行构建：
   - 按 `Ctrl+Shift+B`（默认构建任务）
   - 或在终端中运行：`make -f project/cdkws.mk All`

### 调试
1. 确保已构建项目（生成 `project/project.elf`）。
2. 切换到“运行和调试”侧边栏（Ctrl+Shift+D）。
3. 选择“C-Sky Debug (GDB)”配置，点击绿色播放按钮。
4. 调试器将加载程序并在 `main` 函数处暂停。

## 注意事项

1. **工具链路径**：如果您的 CDK 安装路径与项目中预设的路径（`F:/C-Sky/CDK`）不同，需要更新以下位置：
   - 环境变量 `CSKY_TOOLCHAIN`
   - 可能还需要更新 `project/cdkws.mk` 中的 `CDKPath` 和 `ToolchainPath`（可选，因为 Makefile 会自动使用环境变量）

2. **预编译步骤**：构建过程中会调用 `precompile.exe`，该程序位于 `../../../../tools/precompile/Debug/`。请确保该路径可访问，或手动将 `precompile.exe` 复制到 `project/` 目录下。

3. **后处理步骤**：构建完成后会执行 `BuildBIN.sh`，生成最终的二进制文件（如 `project.hex`、`project.bin`）。

4. **调试硬件**：调试配置假设使用 GDB 通过 JTAG 连接目标板。您可能需要根据实际调试器（如 J-Link、OpenOCD）调整 `launch.json` 中的 `setupCommands`。

## 故障排除

- **“Cannot find: ${env:CSKY_TOOLCHAIN}/csky-elfabiv2-gcc.exe”**：此错误表示环境变量 `CSKY_TOOLCHAIN` 未设置。您可以选择：
  1. 设置 `CSKY_TOOLCHAIN` 环境变量（推荐），或
  2. 修改 `.vscode/c_cpp_properties.json` 中的 `compilerPath`，取消注释使用环境变量的行并注释掉当前行。
- **“csky-elfabiv2-gcc 未找到”**：检查 `CSKY_TOOLCHAIN` 环境变量是否正确设置，并确认工具链已安装。
- **IntelliSense 错误**：检查 `c_cpp_properties.json` 中的包含路径是否正确；可以尝试重新扫描项目（命令面板：`C/C++: Reset IntelliSense Database`）。
- **构建失败**：查看终端输出，确认是否缺少依赖文件（如 `precompile.exe`）。
- **“Parameter format not correct - -Command”**：此错误通常发生在 PowerShell 终端中执行 `make` 命令时。解决方案：
  1. 在 VSCode 中执行构建任务（Ctrl+Shift+B）而非手动输入命令，任务已配置为使用 cmd.exe。
  2. 或将 VSCode 默认终端改为命令提示符（cmd.exe）：打开命令面板（Ctrl+Shift+P），搜索“Terminal: Select Default Profile”，选择“Command Prompt”。
  3. 或在手动执行命令时，确保使用 cmd.exe 终端：在 VSCode 中打开新终端，点击终端下拉菜单，选择“Command Prompt”。
- **“系统找不到指定的文件” (echo 命令)**：此错误是因为 `make` 无法找到 `echo` 可执行文件。解决方案：
  1. 确保已安装 Git for Windows（包含 `sh.exe`）并已添加到 PATH。
  2. 构建任务已配置为使用 `SHELL=sh.exe`，如果仍失败，请手动设置环境变量 `SHELL=sh.exe`。
  3. 如果上述方法无效，可能是 Windows 版 GNU Make 对不含特殊字符的命令直接执行而不调用 shell。请在 `cdkws.mk` 文件中为所有 `echo` 命令添加双引号，例如将 `@echo Done` 改为 `@echo "Done"`。
- **“csky-elfabiv2-gcc 未找到”**：编译器未在 PATH 中。解决方案：
  1. 将 C-Sky 工具链的 `bin` 目录添加到系统 PATH 环境变量中。
  2. 或设置 `CSKY_TOOLCHAIN` 环境变量指向工具链的 `bin` 目录。
  3. 示例：`set PATH=F:\C-Sky\CDKRepo\Toolchain\CKV2ElfMinilib\V3.10.32\R\bin;%PATH%`（在 cmd 中临时设置）。
- **“crc32 未找到”**：校验和工具未在 PATH 中。解决方案：
  1. 在 `txw4002a.mk` 中将 `CHECKSUM` 变量设置为绝对路径：`CHECKSUM := F:/C-Sky/CDK/CSKY/FlashProgrammer/Bins/crc32.exe`
  2. 或将该工具所在目录添加到 PATH 中。
- **“BinScript.exe 或 makecode.exe 未找到”**：后构建工具缺失。解决方案：
  1. 如果不需要后处理步骤，可以忽略该错误（已配置为忽略错误）。
  2. 如需完整后处理，请确保 `../../../../tools/makecode/` 目录中存在这些工具，或修改 `BuildBIN.sh` 脚本中的路径。

## 参考

- 泰芯官方文档（如有）
- C-Sky CDK 用户手册

---

*配置由 AI 助手自动生成，如有问题请根据实际环境调整。*