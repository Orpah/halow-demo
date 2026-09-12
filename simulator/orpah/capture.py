#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture.py — 抓包文件（pcap）→ ORPAH 报文解析 + 「双源对照」。

**为什么需要它**：空口/链路上的真实报文只有在抓包里才看得到，而服务器/页面看到的是
**UDP 侧聚合后的结果**（`/api/status` 计数、IoTDB 上报流与事件）。两边对不上时
（丢帧、路由器没转发、格式不对、被拒）必须能一眼看出差在哪 —— 本工具就是那张对照表。

**做成什么样（2026-09-12 定的最小集）**：
- 只读 **classic pcap**（libpcap 默认格式；`tcpdump -w` / Wireshark 另存为 pcap 都有）。
  pcapng（Wireshark 默认新格式）**明确报错**并给出转换命令 —— 静默跳过会把
  “格式没支持”错当成“抓包里没有 ORPAH 报文”，那比报错危险得多。
- 解析**复用协议层单一源**：`orpah_proto.parse_eth_frame()` + `decode_msg()`，
  不在本模块另写一套帧/报文解析（否则抓包视图与运行时视图会漂移）。
- 「双源对照」= **通用计数差集**：本工具只算差（capture 有/参照有/两边都有但不等），
  **不猜映射** —— 参照计数由调用方自己从它的来源（`/api/status`、IoTDB 事件数…）数出来，
  因为“哪些计数该与哪些报文对齐”是业务口径，工具不该替用户决定。
- **诚实边界**：没有能抓 HaLow 空口的嗅探器时，抓包只能抓 **RJ45/网口侧**（WNB 载体上行）或
  用模拟器自己写出的 pcap；后者验证的是**解析器与对照逻辑**，不能替代真机抓包。

用法：
    python capture.py --pcap orpah.pcap                  # 解析汇总 + 逐条（默认最多 20 条）
    python capture.py --pcap orpah.pcap --limit 200       # 多看几条
    python capture.py --pcap orpah.pcap --json            # 机器可读（含逐条 rows）
    python capture.py --pcap orpah.pcap --ref-json ref.json
        # ref.json = {"ORPAH-REPORT": 12, "ORPAH-ID-REPORT": 3} 这类**你自己的参照计数**
真机抓包示例（网口侧）：
    tcpdump -i eth0 -s 0 -w orpah.pcap 'ether proto 0x88b5'
"""
import argparse
import json
import struct
import sys

import orpah_proto as P

# classic pcap 两个魔数（µs / ns 精度），以及 pcapng 的块类型魔数
PCAP_MAGIC_US = 0xA1B2C3D4
PCAP_MAGIC_NS = 0xA1B23C4D
PCAPNG_MAGIC = 0x0A0D0D0A

LINKTYPE_ETHERNET = 1
LINKTYPE_NAMES = {0: "NULL", 1: "Ethernet", 101: "Raw IP", 113: "Linux SLL",
                  127: "Radiotap", 276: "Linux SLL2"}


class PcapError(Exception):
    """读不了这个文件（格式/截断）—— 一律带可执行的建议，不静默降级。"""


def read_pcap(path):
    """classic pcap → `(linktype, [(ts_float, frame_bytes), ...])`。

    只支持 Ethernet 链路层；其它 linktype 也照读（帧原样给出），但解析时会对不上 ——
    调用方可用返回的 linktype 判断。pcapng / 截断 / 魔数不符 → `PcapError`。
    """
    with open(path, "rb") as f:
        head = f.read(24)
        if len(head) < 24:
            raise PcapError(f"{path}：文件太小，不是 pcap（{len(head)} 字节）")
        magic = struct.unpack("<I", head[:4])[0]
        if magic == PCAPNG_MAGIC:
            raise PcapError(
                f"{path}：这是 **pcapng**（Wireshark 默认新格式），本工具只读 classic pcap。"
                f"先转换：editcap -F pcap in.pcapng out.pcap")
        if magic in (PCAP_MAGIC_US, PCAP_MAGIC_NS):
            endian, ns = "<", (magic == PCAP_MAGIC_NS)
        else:
            magic_be = struct.unpack(">I", head[:4])[0]
            if magic_be not in (PCAP_MAGIC_US, PCAP_MAGIC_NS):
                raise PcapError(f"{path}：不是 pcap（魔数 0x{magic:08x} 不认识）")
            endian, ns = ">", (magic_be == PCAP_MAGIC_NS)
        _ver_major, _ver_minor, _tz, _sig, _snap, linktype = struct.unpack(
            endian + "HHiIII", head[4:24])
        scale = 1e-9 if ns else 1e-6
        out = []
        while True:
            ph = f.read(16)
            if not ph:
                break
            if len(ph) < 16:
                raise PcapError(f"{path}：包记录头被截断（读到 {len(ph)} 字节）")
            sec, frac, incl, _orig = struct.unpack(endian + "IIII", ph)
            data = f.read(incl)
            if len(data) < incl:
                raise PcapError(f"{path}：包数据被截断（要 {incl} 字节只读到 {len(data)}）")
            out.append((sec + frac * scale, data))
        return linktype, out


def write_pcap(path, frames, linktype=LINKTYPE_ETHERNET, ns=False):
    """`[(ts_float, frame_bytes)]` → classic pcap（写样本/导出用；Wireshark 可直接打开）。"""
    magic = PCAP_MAGIC_NS if ns else PCAP_MAGIC_US
    scale = 1e9 if ns else 1e6
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", magic, 2, 4, 0, 0, 65535, linktype))
        for ts, frame in frames:
            sec = int(ts)
            frac = int(round((float(ts) - sec) * scale))
            f.write(struct.pack("<IIII", sec, frac, len(frame), len(frame)))
            f.write(frame)


def parse_frame(frame):
    """单帧 → 一行结果（**不抛异常**：抓包里什么流量都有，不能因为一条脏帧整份失败）。

    返回 `{"ok":bool, "kind":"...", ...}`：
      - 非 ORPAH（ethertype 不是 0x88B5）/ 帧太短 → `ok=False, err="not-orpah"|"bad-frame"`
      - ORPAH 但 JSON 坏了 → `ok=False, err="bad-json"`
      - ORPAH 报文 → `ok=True, type/sn/seq/ts`
    """
    got = P.parse_eth_frame(frame)
    if got is None:
        return {"ok": False, "size": len(frame),
                "err": "bad-frame" if len(frame) < 14 else "not-orpah"}
    _ethertype, payload = got
    try:
        msg = P.decode_msg(payload)
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "size": len(payload), "err": "bad-json", "detail": str(e)}
    if not isinstance(msg, dict) or not msg.get("type"):
        return {"ok": False, "size": len(payload), "err": "bad-json", "detail": "缺 type"}
    out = {"ok": True, "type": msg.get("type"), "sn": msg.get("sn") or "-",
           "size": len(payload)}
    for k in ("seq", "ts", "rssi", "status", "code"):
        if msg.get(k) is not None:
            out[k] = msg[k]
    # Orpah ID 报文多一层 hdr/payload（§5.4）：把验签要用到的级别/算法提出来，方便对照
    inner = msg.get("report") if isinstance(msg.get("report"), dict) else None
    if inner and isinstance(inner.get("hdr"), dict):
        out["alg"] = inner["hdr"].get("alg")
        out["level"] = inner["hdr"].get("level")
        out["id_sn"] = (inner.get("payload") or {}).get("sn")
    return out


def parse_frames(frames):
    """`[(ts, frame)]` → `[row]`（每行带 `t`）；见 `parse_frame`。"""
    rows = []
    for ts, frame in frames:
        row = parse_frame(frame)
        row["t"] = ts
        rows.append(row)
    return rows


def summarize(rows):
    """行列表 → 计数汇总（`by_type` 只数 ORPAH 且解析成功的）。"""
    by_type, errs = {}, {}
    for r in rows:
        if r.get("ok"):
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        else:
            errs[r.get("err", "?")] = errs.get(r.get("err", "?"), 0) + 1
    return {"frames": len(rows), "orpah": sum(by_type.values()),
            "by_type": by_type, "errors": errs}


def compare(cap_counts, ref_counts):
    """**双源对照**：capture 侧计数 vs 参照侧计数 → 差集（不猜映射，只算差）。

    参数都是 `{类型: 条数}`（如 `{"ORPAH-REPORT": 12}`）。返回：
      - `diff`：两边都有但条数不同的类型 `{type: {"capture": n, "ref": m}}`
      - `only_capture` / `only_ref`：只在一侧出现的类型
      - `same`：完全一致的类型数（便于“一眼看有没有问题”）
    """
    cap, ref = dict(cap_counts or {}), dict(ref_counts or {})
    diff, only_cap, only_ref, same = {}, {}, {}, 0
    for k in sorted(set(cap) | set(ref)):
        c, r = cap.get(k), ref.get(k)
        if c is None:
            only_ref[k] = r
        elif r is None:
            only_cap[k] = c
        elif c != r:
            diff[k] = {"capture": c, "ref": r}
        else:
            same += 1
    return {"diff": diff, "only_capture": only_cap, "only_ref": only_ref,
            "same": same, "ok": not (diff or only_cap or only_ref)}


def _load_ref(path):
    """参照计数：`{"<类型>": n}` 或 `{"counts": {...}}`（容忍多包一层）。

    ⚠ 用 `utf-8-sig` 读：Windows 上 PowerShell 的 `Set-Content -Encoding UTF8` 与记事本
    **都会写 BOM**，用普通 utf-8 解码会报 `Unexpected UTF-8 BOM`（实测踩过）——
    而 utf-8-sig 对无 BOM 的普通 UTF-8 一样能读。
    """
    with open(path, encoding="utf-8-sig") as f:
        j = json.load(f)
    if isinstance(j, dict) and isinstance(j.get("counts"), dict):
        j = j["counts"]
    if not isinstance(j, dict):
        raise PcapError(f"{path}：参照计数应是 {{'<类型>': 条数}} 的 JSON 对象")
    out = {}
    for k, v in j.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = int(v)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="ORPAH 抓包解析 + 双源对照")
    ap.add_argument("--pcap", required=True, help="classic pcap 文件（pcapng 请先 editcap 转换）")
    ap.add_argument("--limit", type=int, default=20, help="逐条打印上限（默认 20，0=全打）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（含逐条 rows）")
    ap.add_argument("--ref-json", help="参照计数 JSON：{'<类型>': 条数}")
    a = ap.parse_args(argv)
    try:
        linktype, frames = read_pcap(a.pcap)
    except PcapError as e:
        print(f"[!!] {e}")
        return 2
    rows = parse_frames(frames)
    s = summarize(rows)
    s["linktype"] = linktype
    s["linktype_name"] = LINKTYPE_NAMES.get(linktype, f"?({linktype})")
    if linktype != LINKTYPE_ETHERNET:
        # 不是以太网链路层 → 帧解析必然对不上，明说而不是给一堆 not-orpah
        s["warn"] = (f"链路层是 {s['linktype_name']}，不是 Ethernet：本工具按以太网帧解析，"
                     f"结果会全是 not-orpah（需要先按该链路类型解封装）")
    if a.ref_json:
        try:
            ref = _load_ref(a.ref_json)
        except (PcapError, OSError, ValueError) as e:
            print(f"[!!] 读参照计数失败：{e}")
            return 2
        s["compare"] = compare(s["by_type"], ref)
    if a.json:
        print(json.dumps({"summary": s, "rows": rows if a.limit == 0 else rows[:a.limit]},
                         ensure_ascii=False, indent=2))
        return 0 if s["orpah"] or not s.get("warn") else 1
    print(f"文件：{a.pcap}")
    print(f"链路层：{s['linktype_name']}（linktype={linktype}）")
    if s.get("warn"):
        print(f"[!!] {s['warn']}")
    print(f"帧总数：{s['frames']}；ORPAH 报文：{s['orpah']}")
    for k, n in sorted(s["by_type"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<26} {n}")
    if s["errors"]:
        print("解析失败：" + ", ".join(f"{k}×{n}" for k, n in sorted(s["errors"].items())))
    if "compare" in s:
        c = s["compare"]
        print("双源对照：" + ("一致 OK" if c["ok"] else "有差异 DIFF") + f"（一致类型 {c['same']} 个）")
        for k, v in c["diff"].items():
            print(f"  条数不同 {k}：抓包 {v['capture']} / 参照 {v['ref']}")
        for k, v in c["only_capture"].items():
            print(f"  只在抓包里 {k}：{v}")
        for k, v in c["only_ref"].items():
            print(f"  只在参照里 {k}：{v}")
    if a.limit:
        print(f"逐条（最多 {a.limit} 条）：")
        for r in rows[:a.limit]:
            if r.get("ok"):
                extra = " ".join(f"{k}={r[k]}" for k in ("sn", "alg", "level", "seq", "status")
                                 if r.get(k) is not None)
                print(f"  {r['t']:.6f}  {r['type']:<26} {extra}")
            else:
                print(f"  {r['t']:.6f}  [{r['err']}] size={r.get('size')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
