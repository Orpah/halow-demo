# 天逯TXW8301开发环境

## 环境设置

泰芯TXW8301使用的MCU是玄铁E803，玄铁803官方推荐的开发工具是CDK，CDK基于Eclipse，但是没有AI，所以我们这里转用VSCode来开发，这样你可以直接使用VSCode中的AI或AI插件，也可以使用CodeBuddy的AI。CodeBuddy基于VSCode，编译可以直接在CodeBuddy中完成，遇到任何问题，可以直接让CodeBuddy帮你解决。

1. 下载并安装CDK


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
