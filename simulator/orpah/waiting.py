#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""waiting.py — 等待异步条件（**只此一份实现**，别在脚本里各写“猜次数”的循环）

为什么要单独一个文件：这类等待散落在 demo 脚本与服务器启动路径里（等 STA 关联、等 Server 收到…），
以前每处都写成：

    for _ in range(100):
        if cond(): break
        time.sleep(0.1)

两个毛病：
  ① **猜次数**：`N × interval` 是拍脑袋的预算，机器/环境慢一点就悄悄用完；
  ② **静默放弃**：没等到也照常往下跑，最后表现成“数据是 0 条”这类难定位的现象。

本模块统一成**按截止时间等待**，并把“到底有没有等到”如实返回给调用方
（**不抛异常** —— 不同场景处置不同：验收脚本该直接失败退出，UI 启动该只告警继续）。

判据必须是**本地状态**（`wifi.conn`、计数器…）。等的是“另一条线程/进程的答复”，
请用回调或队列（例：`test_clock.py` 用 `OrpahServer(on_id_report=queue.put)`）；
轮询网络往返既慢又不可靠。
"""
import time

__all__ = ["wait_until", "wait_new"]


def wait_until(cond, timeout=10.0, interval=0.05):
    """轮询 cond()，条件为真 → True；到 timeout（秒）仍不满足 → False。

    - `cond`：无参可调用，返回真值即认为满足。
    - 会**先判一次**再睡眠（条件已满足时零等待，不引入无谓延迟）。
    - `interval` 只是轮询间隔；总时长由 `timeout` 说了算，不受 interval 影响。
    """
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        if cond():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(interval)


def wait_new(lst, pred, timeout=5.0, interval=0.1):
    """等 `lst` **新增**了满足 `pred` 的元素 → True；超时 → False。

    为什么不能直接 `wait_until(lambda: pred(lst[-1]))`：列表里**已有**的历史元素会立刻满足条件
    → 假 PASS（本仓库踩过：漫游场景下等 R2 的回执，却匹配到 R1 时期的旧记录）。
    只有「长度增加 且 新元素满足」才算等到。
    """
    n0 = len(lst)
    return wait_until(lambda: len(lst) > n0 and bool(pred(lst[-1])),
                      timeout=timeout, interval=interval)

