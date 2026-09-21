# -*- coding: utf-8 -*-
"""停掉模拟器 UI / 串口空口等占用的端口，并确认已释放。

为什么要有它：模拟器的**组件端口是固定常量**（HTTP 8899、PC 模拟器 A/B 的
console/link = 9001/9002/9011/9012）—— 多开一个实例不会报错，只会让先起的那个
把数据报收走，现象是「页面在动、数据却不对」（很难查）。起服务/截图前先跑一下它。

用法：
  python simulator/tools/dev/stop_ui.py                 # 默认清 8899/9001/9002/9011/9012
  python simulator/tools/dev/stop_ui.py --ports 8899    # 只清 HTTP
  python simulator/tools/dev/stop_ui.py --dry           # 只看谁占着，不动手
"""
import argparse
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_PORTS = [8899, 9001, 9002, 9011, 9012]


def listeners(ports):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                         encoding="utf-8", errors="replace").stdout
    owners = {}
    for line in out.splitlines():
        m = re.search(r":(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
        if m and int(m.group(1)) in ports:
            owners.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
    return owners


def main():
    ap = argparse.ArgumentParser(description="清掉模拟器 UI 占用的端口")
    ap.add_argument("--ports", default=",".join(str(p) for p in DEFAULT_PORTS),
                    help="逗号分隔的端口列表")
    ap.add_argument("--dry", action="store_true", help="只看占用，不杀进程")
    args = ap.parse_args()
    ports = [int(x) for x in args.ports.split(",") if x.strip()]

    owners = listeners(ports)
    if not owners:
        print("这些端口都没在监听：", ports)
        return 0
    pids = set()
    for port, ps in sorted(owners.items()):
        print("占用 :%d -> pid %s" % (port, ", ".join(str(p) for p in sorted(ps))))
        pids |= ps
    if args.dry:
        return 0
    # 同一个进程常常同时占着好几个端口 —— 去重后再杀，别重复报 “not found” 刷屏
    for pid in sorted(pids):
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, encoding="utf-8", errors="replace")
        print("   kill pid %d: %s" % (pid, (r.stdout or r.stderr).strip()))
    alive = [p for p in ports if p in listeners(ports)]
    print("仍在监听：", alive if alive else "无（干净）")
    return 0 if not alive else 1


if __name__ == "__main__":
    sys.exit(main())
