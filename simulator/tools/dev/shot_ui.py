# -*- coding: utf-8 -*-
"""截模拟器 Web UI 的**真实页面**（给 README 的图用，不是手绘）。

前置：先起 UI —— `python server.py --host-sim`（在 `simulator/tools/ui/` 下），
默认地址 http://127.0.0.1:8899/ 。

用法：
  python simulator/tools/dev/shot_ui.py                    # 截 3 张到 tools/ui/images/
  python simulator/tools/dev/shot_ui.py --frames --rssi 2  # 先开帧监视、A/B 各点一次 RSSI（图里才有内容）
  python simulator/tools/dev/shot_ui.py --url http://127.0.0.1:8899/ --wait 8000

两点经验（都实测踩过）：
  · **别用 VS Code 内嵌浏览器截图** —— 它能绘制的区域只有约 364×490 CSS px，超出部分全黑；
    这里用系统 Edge（`channel="msedge"`），需要 `pip install playwright`（不必再下 Chromium）。
  · 页面刚打开时 A/B 还没配对、控制台是空的 —— 所以要 `--wait` 等一会儿，
    想看帧监视器与 AT 往来就带 `--frames --rssi 2`。
"""
import argparse
import os
import sys

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

# dev/ -> tools/ -> simulator/ -> 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    ap = argparse.ArgumentParser(description="截模拟器 Web UI 真实页面")
    ap.add_argument("--url", default="http://127.0.0.1:8899/", help="UI 地址")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "simulator", "tools", "ui", "images"),
                    help="输出目录（默认 tools/ui/images/，已 gitignore）")
    ap.add_argument("--prefix", default="ui", help="文件名前缀，出 <prefix>-top/-consoles/-panels.png")
    ap.add_argument("--scrolls", default="0,560,1080", help="三张图各自的纵向滚动位置")
    ap.add_argument("--wait", type=int, default=9000, help="打开后先等多少毫秒（等 A/B 配对）")
    ap.add_argument("--frames", action="store_true", help="先点「帧监视」再截")
    ap.add_argument("--rssi", type=int, default=0, help="对前 N 台设备各点一次「RSSI」")
    ap.add_argument("--browser", default="msedge", help="playwright 的 channel（msedge/chrome）")
    ap.add_argument("--width", type=int, default=1440, help="视口宽")
    ap.add_argument("--height", type=int, default=1000, help="视口高")
    ap.add_argument("--wait-server", type=int, default=30,
                    help="先等 UI 起来（秒；0 = 不等）——省得靠人掐时间")
    args = ap.parse_args()

    if args.wait_server:
        import socket
        import time
        from urllib.parse import urlparse
        u = urlparse(args.url)
        host, port = u.hostname or "127.0.0.1", u.port or 80
        t0 = time.time()
        while time.time() - t0 < args.wait_server:
            s = socket.socket()
            s.settimeout(1.0)
            try:
                s.connect((host, port))
                s.close()
                print("UI 已就绪（%s:%d，等了 %.1fs）" % (host, port, time.time() - t0))
                break
            except OSError:
                s.close()
                time.sleep(0.5)
        else:
            print("[!!] 等了 %d s 也连不上 %s —— 先用 python server.py --host-sim 起 UI"
                  % (args.wait_server, args.url))
            return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!!] 缺少 playwright：python -m pip install playwright")
        return 2

    names = ["top", "consoles", "panels"]
    scrolls = [int(x) for x in args.scrolls.split(",")]
    if len(scrolls) != len(names):
        print("[!!] --scrolls 需要 3 个值（对应 top/consoles/panels）")
        return 2

    os.makedirs(args.out_dir, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel=args.browser)
        pg = b.new_page(viewport={"width": args.width, "height": args.height},
                        device_scale_factor=1)
        pg.goto(args.url, wait_until="load")
        pg.wait_for_timeout(args.wait)
        print("title:", pg.title())
        if args.frames:
            try:
                pg.locator("button:has-text('帧监视')").first.click()
                pg.wait_for_timeout(2500)
            except Exception as e:                      # noqa: BLE001
                print("[!] 帧监视按钮点击失败:", e)
        for i in range(args.rssi):
            try:
                pg.locator("button:has-text('RSSI')").nth(i).click()
                pg.wait_for_timeout(1500)
            except Exception as e:                      # noqa: BLE001
                print("[!] 第 %d 个 RSSI 按钮失败:" % (i + 1), e)
        pg.wait_for_timeout(2500)

        for name, y in zip(names, scrolls):
            pg.evaluate("() => window.scrollTo(0, %d)" % y)
            pg.wait_for_timeout(1000)
            out = os.path.join(args.out_dir, "%s-%s.png" % (args.prefix, name))
            pg.screenshot(path=out)
            print("  ->", os.path.relpath(out, ROOT), "%d B" % os.path.getsize(out))
        print("buttons:", pg.locator("button").count())
        b.close()
    print("完成。图放 %s（目录已 gitignore；要入库请另存到 simulator/docs/ 并改 README 引用）"
          % os.path.relpath(args.out_dir, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
