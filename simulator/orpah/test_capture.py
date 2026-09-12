#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_capture.py — 抓包解析 + 双源对照的自检（不依赖硬件/网络，纯文件往返）。

覆盖：
  1) pcap 往返：写→读，时间戳（us 精度）与帧字节逐字节一致；
  2) **格式错误要吵**：pcapng / 截断 / 魔数不符 → 一律 PcapError（附 editcap 提示），
     **静默降级会把“格式没支持”错当成“抓包里没有 ORPAH 报文”**；
  3) 解析：ORPAH 各类报文计数正确；非 ORPAH / 坏 JSON / 短帧各自归类；
     **一条脏帧不能让整份抓包失败**；
  4) Orpah ID 报文：从抓包里也能取出 alg/level（用于核对降级情况）；
  5) 双源对照：一致 / 条数不同 / 只在一侧 / 嵌套 counts 的参照 JSON / 非数字值跳过。

跑法：C:\\Python313\\python.exe test_capture.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import capture as cap                                          # noqa: E402
import orpah_id as oid                                         # noqa: E402
import orpah_proto as P                                        # noqa: E402

FAIL = []
TMP = tempfile.mkdtemp(prefix="orpah_cap_")
SRC = b"\x82\x59\x13\x64\x70\x90"                              # 设备侧 MAC（随便给，只为构造帧）
DST = b"\xff\xff\xff\xff\xff\xff"


def ck(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


def eth(msg, ethertype=P.ORPAH_ETHERTYPE):
    """用**协议层单一源**构造以太网帧（不手搓字节，否则测的是我自己写的第二套）。"""
    return P.build_eth_frame(P.encode_msg(msg), src_mac=SRC, dst_mac=DST,
                             ethertype=ethertype)


TS0 = 1800000000.123456


def frames():
    """一小组覆盖各类型的帧（含 1 条 ID 报文 + 2 条脏帧）。"""
    dev = oid.Device(sn="CN-WH01-9AF3C1D2", demo_key=True)
    out = [
        (TS0 + 0.0, eth(P.build_req_connect("CN-WH01-9AF3C1D2"))),
        (TS0 + 0.1, eth(P.build_report("CN-WH01-9AF3C1D2", ts=1800000000, rssi=-70, seq=1))),
        (TS0 + 0.2, eth(P.build_report("CN-WH01-9AF3C1D2", ts=1800000001, rssi=-72, seq=2))),
        (TS0 + 0.3, eth(P.build_access_info("CN-WH01-9AF3C1D2", True))),
        (TS0 + 0.4, eth(P.build_id_report(dev.report(level=3, ts=1800000000)))),
        # ① 非 ORPAH：IPv4 的 ethertype（抓包里必然混着别的流量）
        (TS0 + 0.5, P.build_eth_frame(b"\x45\x00\x00\x14" + b"\x00" * 16, src_mac=SRC,
                                      dst_mac=DST, ethertype=0x0800)),
        # ② ORPAH ethertype 但 JSON 坏了
        (TS0 + 0.6, P.build_eth_frame(b"{not json", src_mac=SRC, dst_mac=DST)),
        # ③ 不足 14 字节的短帧
        (TS0 + 0.7, b"\x00\x01\x02"),
    ]
    return out


print("== 1. pcap 往返（写→读） ==")
p1 = os.path.join(TMP, "a.pcap")
fs = frames()
cap.write_pcap(p1, fs)
lt, back = cap.read_pcap(p1)
ck("linktype = Ethernet(1)", lt == 1, str(lt))
ck("帧数一致", len(back) == len(fs), f"{len(back)} vs {len(fs)}")
ck("帧字节逐字节一致", all(a[1] == b[1] for a, b in zip(fs, back)))
ck("时间戳保留到 us", abs(back[1][0] - (TS0 + 0.1)) < 1e-6,
   f"{back[1][0]} vs {TS0 + 0.1}")
p1ns = os.path.join(TMP, "a_ns.pcap")
cap.write_pcap(p1ns, fs, ns=True)
_lt, back_ns = cap.read_pcap(p1ns)
ck("纳秒变体也能读", len(back_ns) == len(fs) and abs(back_ns[2][0] - (TS0 + 0.2)) < 1e-6)

print("== 2. 格式错误必须吵（不静默降级） ==")
p2 = os.path.join(TMP, "ng.pcap")
with open(p2, "wb") as f:                       # pcapng：魔数 0x0A0D0D0A
    f.write(b"\x0a\x0d\x0d\x0a" + b"\x00" * 24)
try:
    cap.read_pcap(p2)
    ck("pcapng → PcapError", False, "没报错")
except cap.PcapError as e:
    ck("pcapng → PcapError 且提示 editcap", "editcap" in str(e), str(e)[:60])
p3 = os.path.join(TMP, "junk.pcap")
with open(p3, "wb") as f:
    f.write(b"\xde\xad\xbe\xef" + b"\x00" * 20)
try:
    cap.read_pcap(p3)
    ck("魔数不符 → PcapError", False, "没报错")
except cap.PcapError:
    ck("魔数不符 → PcapError", True)
p4 = os.path.join(TMP, "trunc.pcap")
with open(p4, "wb") as f:
    f.write(open(p1, "rb").read()[:40])         # 包记录头被截断
try:
    cap.read_pcap(p4)
    ck("截断 → PcapError", False, "没报错")
except cap.PcapError:
    ck("截断 → PcapError", True)

print("== 3. 解析与分类 ==")
rows = cap.parse_frames(back)
s = cap.summarize(rows)
ck("帧总数", s["frames"] == len(fs), str(s["frames"]))
ck("ORPAH 报文数 = 5（其余 3 条是脏帧/别的流量）", s["orpah"] == 5, str(s["orpah"]))
ck("按类型计数正确",
   s["by_type"] == {"ORPAH-REQ-CONNECT": 1, "ORPAH-REPORT": 2,
                    "ORPAH-ACCESS-INFO": 1, "ORPAH-ID-REPORT": 1}, str(s["by_type"]))
ck("错误分类：not-orpah / bad-json / bad-frame 各 1",
   s["errors"] == {"not-orpah": 1, "bad-json": 1, "bad-frame": 1}, str(s["errors"]))
ck("一条脏帧不影响其它帧（整份没失败）", len(rows) == len(fs) and s["orpah"] == 5)
rep = [r for r in rows if r.get("type") == "ORPAH-REPORT"]
ck("字段抽取：seq/rssi/ts", rep and rep[0]["seq"] == 1 and rep[0]["rssi"] == -70
   and rep[0]["ts"] == 1800000000, str(rep[0]) if rep else "无")
idr = [r for r in rows if r.get("type") == "ORPAH-ID-REPORT"]
ck("ID 报文抽出 alg/level（抓包里也能核对降级）",
   idr and idr[0].get("alg") == "none" and idr[0].get("level") == 3, str(idr[0]) if idr else "无")
ck("空 pcap（0 帧）不炸",
   cap.summarize(cap.parse_frames([])) == {"frames": 0, "orpah": 0, "by_type": {},
                                          "errors": {}})

print("== 4. 双源对照（只算差，不猜映射） ==")
c = cap.compare({"ORPAH-REPORT": 2, "ORPAH-ID-REPORT": 1},
                {"ORPAH-REPORT": 2, "ORPAH-ID-REPORT": 1})
ck("完全一致 → ok", c["ok"] and c["same"] == 2 and not c["diff"], str(c))
c = cap.compare({"ORPAH-REPORT": 2}, {"ORPAH-REPORT": 3})
ck("条数不同 → diff（不判谁对，只报差）",
   not c["ok"] and c["diff"]["ORPAH-REPORT"] == {"capture": 2, "ref": 3}, str(c))
c = cap.compare({"ORPAH-REPORT": 2}, {"ORPAH-FOUND": 1})
ck("只在一侧 → only_capture / only_ref",
   c["only_capture"] == {"ORPAH-REPORT": 2} and c["only_ref"] == {"ORPAH-FOUND": 1}, str(c))
ck("两边都空 → ok（空抓包 + 空参照 也是一种一致）", cap.compare({}, {})["ok"])

print("== 5. 参照 JSON 读取 ==")
pr = os.path.join(TMP, "ref.json")
with open(pr, "w", encoding="utf-8") as f:
    json.dump({"ORPAH-REPORT": 12, "ORPAH-ID-REPORT": 3, "note": "x", "bad": None}, f)
ref = cap._load_ref(pr)
ck("只取数字项（字符串/None 跳过）", ref == {"ORPAH-REPORT": 12, "ORPAH-ID-REPORT": 3}, str(ref))
with open(pr, "w", encoding="utf-8") as f:
    json.dump({"counts": {"ORPAH-REPORT": 7}}, f)
ck("容忍多层 {\"counts\": {...}}", cap._load_ref(pr) == {"ORPAH-REPORT": 7})
# Windows 现实：PowerShell 5.1 的 Set-Content -Encoding UTF8 / 记事本 都会写 BOM
with open(pr, "w", encoding="utf-8-sig") as f:
    json.dump({"ORPAH-REPORT": 5}, f)
with open(pr, "rb") as f:
    _head = f.read(3)
ck("带 BOM 的参照 JSON 也能读（utf-8-sig）",
   _head == b"\xef\xbb\xbf" and cap._load_ref(pr) == {"ORPAH-REPORT": 5}, repr(_head))
with open(pr, "w", encoding="utf-8") as f:
    json.dump([1, 2, 3], f)
try:
    cap._load_ref(pr)
    ck("非对象 → PcapError", False, "没报错")
except cap.PcapError:
    ck("非对象 → PcapError", True)

print("== 6. CLI 冒烟（真跑一遍，退出码要对） ==")
rc = cap.main(["--pcap", p1, "--limit", "3"])
ck("解析一个正常抓包 → 退出码 0", rc == 0, str(rc))
rc = cap.main(["--pcap", p2])
ck("pcapng → 退出码 2（不是崩栈）", rc == 2, str(rc))
json_out = os.path.join(TMP, "out.json")
sys.stdout = open(json_out, "w", encoding="utf-8")
try:
    rc = cap.main(["--pcap", p1, "--json", "--limit", "0"])
finally:
    sys.stdout = sys.__stdout__
ck("--json 退出码 0", rc == 0, str(rc))
with open(json_out, encoding="utf-8") as f:
    j = json.load(f)
ck("--json 结构含 summary+rows 且 rows 全量",
   j["summary"]["orpah"] == 5 and len(j["rows"]) == len(fs), str(j["summary"]))

print()
if FAIL:
    print(f"失败 {len(FAIL)} 项：" + "；".join(FAIL))
    raise SystemExit(1)
print("全部通过")
