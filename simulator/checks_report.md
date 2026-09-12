# halow-demo 自检报告（空口/设备侧）

- 生成时间：2026-09-13 00:44:42
- HEAD：`5902276`
- Python：3.13.14
- 结果：**3/3 通过**

> 全部套件都不需要硬件与第三方依赖；模拟器回归的结果同时写进
> `host/test_results.txt`（历史一直如此，便于对照）。

| 套件 | 结果 | 用时 |
|---|---|---|
| 模拟器回归（AT/连接/转发/配对/串口空口/host 数据口） | 通过 | 28.14s |
| 界面文案字典（zh/en 对齐 + 页面引用无缺失） | 通过 | 0.04s |
| 静态检查（py/js/json/tasks/gitignore） | 通过 | 0.20s |

## 模拟器回归（AT/连接/转发/配对/串口空口/host 数据口）

```
���: 27/27 ͨ��
returncode=0  ����: host\test_results.txt
```

## 界面文案字典（zh/en 对齐 + 页面引用无缺失）

```
PASS  字典 zh/en key 集合一致（158 / 158）
PASS  每个 key 恰好 2 次（zh + en）
PASS  扫描 2 个页面/脚本，引用 151 个 key（动态前缀家族 5 个）
PASS  页面引用的 key 全部在字典里

文案字典：全部通过（158 个 key，引用 151 个）
```

## 静态检查（py/js/json/tasks/gitignore）

```
说明：
  py_compile: 9 个文件
  node --check: 2 个 .js
  JSON: 1 个
  tasks.json: 9 个任务

无问题。
```
