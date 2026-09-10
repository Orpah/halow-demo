#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orpah_id.py — Orpah ID 协议实现层（对齐《Orpah ID 协议规范》v1.15）
====================================================================
本模块是 Orpah ID「身份与真实性层」的权威参考实现（纯 Python，独立成层，
不依赖 orpah 既有业务报文；现有 L1–L4 的 ORPAH-REPORT 等业务流不动）。

包含：
  - Crockford Base32 编解码（字母表 0123456789ABCDEFGHJKMNPQRSTVWXYZ，去 I L O U）
  - SN 生成/解析/合法性校验（CC-ORG-UNIQUE[-CHECK]，CC=ISO 3166-1 alpha-2）
  - CHECK 校验码（只算 ORG-UNIQUE，不含 CC）：Mod 97（2 位十进制）＋
    Luhn mod 32（1 位 Crockford）；Damm32 见独立参考实现 `damm32.py`
  - JCS 规范化（RFC 8785）：key 字典序、无空白、UTF-8、数字最短表示
  - 报文构建/签名：ES256（ECDSA P-256，raw R‖S 64B → base64url）、
    HS256（HMAC-SHA256 直接对 preimage）、none（L3 无签名）
  - server 验签（§9.3）：格式/alg 白名单/时间窗口(ts=0 跳过)/nonce 去重/
    SN+CHECK/撤销/密钥检索/验签/信任分级

依赖：`cryptography`（ES256/HS256 需要；缺失时仅 L3 none 可用）。
"""
import base64
import hmac as _hmac_stdlib
import json
import os
import re
import time

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives import hmac as _chmac
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.utils import (
        encode_dss_signature, decode_dss_signature)
    _CRYPTO_OK = True
except Exception:  # pragma: no cover - 无 cryptography 时仅 L3 可用
    _CRYPTO_OK = False

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# Crockford Base32 字母表（去易混 I L O U）
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {c: i for i, c in enumerate(CROCKFORD)}

SN_MAX_LEN = 32

# SN 正则：CC-ORG-UNIQUE[-CHECK]（CC 不套用 Crockford 限制，可含 I/L/O/U）
_SN_RE = re.compile(
    r"^[A-Z]{2}-[0-9A-HJKMNP-TV-Z]{2,6}-[0-9A-HJKMNP-TV-Z]{8,16}"
    r"(-[0-9A-HJKMNP-TV-Z]{1,2})?$")

# 签名算法
ALG_ES256 = "ES256"
ALG_HS256 = "HS256"
ALG_NONE = "none"

# 降级级别 → 算法（§8.1：L0=ECDSA；L1/L2=HMAC；L3=无签名）
LEVEL_TO_ALG = {0: ALG_ES256, 1: ALG_HS256, 2: ALG_HS256, 3: ALG_NONE}

# 信任分级（§8.1/§8.3）
TRUST_BY_LEVEL = {0: "high", 1: "medium", 2: "low", 3: "none"}


# ---------------------------------------------------------------------------
# Crockford Base32
# ---------------------------------------------------------------------------
def crockford_index(ch):
    """Crockford 字符 → 0–31；非法字符返回 None。"""
    if not isinstance(ch, str) or len(ch) != 1:
        return None
    ch = ch.upper()
    return _CROCKFORD_INDEX.get(ch)


def crockford_encode(n):
    """0–31 → Crockford 字符。"""
    if not 0 <= n < 32:
        raise ValueError("crockford_encode: n must be 0..31")
    return CROCKFORD[n]


def crockford_from_bytes(data, width):
    """字节串 → 定长 Crockford 字符串（取低若干位，宽度 width）。"""
    n = int.from_bytes(data, "big")
    chars = []
    for _ in range(width):
        chars.append(CROCKFORD[n % 32])
        n //= 32
    return "".join(reversed(chars))


# ---------------------------------------------------------------------------
# SN：解析 / 合法性 / 生成
# ---------------------------------------------------------------------------
def sn_ok(sn):
    """SN 是否合法（CC-ORG-UNIQUE[-CHECK]，Crockford Base32）。"""
    return (isinstance(sn, str) and 0 < len(sn) <= SN_MAX_LEN
            and bool(_SN_RE.match(sn)))


def sn_err(sn):
    """SN 校验失败原因；合法返回 None。"""
    if not isinstance(sn, str) or not sn:
        return "empty"
    if len(sn) > SN_MAX_LEN:
        return "too-long"
    if not _SN_RE.match(sn):
        return "bad-format"
    return None


def parse_sn(sn):
    """解析 SN → {cc, org, unique, check}；非法返回 None。"""
    if not sn_ok(sn):
        return None
    parts = sn.split("-")
    cc, org, unique = parts[0], parts[1], parts[2]
    check = parts[3] if len(parts) == 4 else ""
    return {"cc": cc, "org": org, "unique": unique, "check": check}


def gen_unique(length=10):
    """用 OS RNG 生成 length 位 Crockford 流水号（§2.4 SE RNG 思路）。"""
    if not 8 <= length <= 16:
        raise ValueError("gen_unique: length must be 8..16")
    return crockford_from_bytes(os.urandom(length), length)


def gen_sn(cc="CN", org="WH01", unique_len=10, check="mod97"):
    """生成完整 SN。check 取 "mod97" / "luhn32" / ""（无校验）。"""
    unique = gen_unique(unique_len)
    org_unique = f"{org}-{unique}"
    sn = f"{cc}-{org_unique}"
    if check:
        sn += "-" + compute_check(org_unique, check)   # 校验位只算 ORG-UNIQUE（不含 CC）
    return sn


# ---------------------------------------------------------------------------
# CHECK 校验码
# ---------------------------------------------------------------------------
def _mod97(s):
    """对字母数字串（跳过 '-'）取模 97。字母 A=10..Z=35，数字 0–9。"""
    r = 0
    for ch in s:
        if ch == "-":
            continue
        if "0" <= ch <= "9":
            r = (r * 10 + (ord(ch) - 48)) % 97
        elif "A" <= ch <= "Z":
            r = (r * 100 + (ord(ch) - 55)) % 97
    return r


def compute_check_mod97(org_unique):
    """org_unique = ORG-UNIQUE（不含 CC）→ 2 位十进制校验码（IBAN 思路，输出 00–96）。"""
    return "%02d" % (98 - _mod97(org_unique + "00"))


def verify_check_mod97(org_unique_check):
    """ORG-UNIQUE-CHECK（不含 CC，含 2 位校验码）取模 97 应等于 1。"""
    return _mod97(org_unique_check) == 1


def _luhn_sum(digits):
    """Luhn 校验和（从右往左隔位翻倍，模 32）。"""
    s = 0
    double = False
    for d in reversed(digits):
        if double:
            d2 = d * 2
            s += d2 // 32 + d2 % 32
        else:
            s += d
        double = not double
    return s


def compute_check_luhn32(org_unique):
    """org_unique = ORG-UNIQUE（不含 CC）→ 1 位 Crockford 校验码（Luhn mod 32）。"""
    digits = [crockford_index(c) for c in org_unique if c != "-"]
    for c in range(32):
        if _luhn_sum(digits + [c]) % 32 == 0:
            return crockford_encode(c)
    return "0"  # 理论不可达


def verify_check_luhn32(org_unique_check):
    """ORG-UNIQUE-CHECK（不含 CC，含 1 位校验码）Luhn 和模 32 应等于 0。"""
    digits = [crockford_index(c) for c in org_unique_check if c != "-"]
    if any(d is None for d in digits):
        return False
    return _luhn_sum(digits) % 32 == 0


def compute_check(org_unique, algo="mod97"):
    """给 ORG-UNIQUE（不含 CC）算校验码：algo="mod97"（2 位）或 "luhn32"（1 位）。"""
    if algo == "mod97":
        return compute_check_mod97(org_unique)
    if algo == "luhn32":
        return compute_check_luhn32(org_unique)
    raise ValueError(f"unknown check algo: {algo}")


def verify_check(sn):
    """整串 SN（CC-ORG-UNIQUE[-CHECK]）按 CHECK 长度选择算法验证。

    CC 不参与校验（校验位只算 ORG-UNIQUE）：0 位=无校验(通过)；1 位=Luhn32；2 位=Mod97。
    """
    p = parse_sn(sn)
    if p is None:
        return False
    if not p["check"]:
        return True
    body = f"{p['org']}-{p['unique']}-{p['check']}"   # 不含 CC
    if len(p["check"]) == 1:
        return verify_check_luhn32(body)
    if len(p["check"]) == 2:
        return verify_check_mod97(body)
    return False


# ---------------------------------------------------------------------------
# JCS（RFC 8785）规范化 + base64url
# ---------------------------------------------------------------------------
def jcs(obj):
    """RFC 8785 JCS：key 字典序、无空白、UTF-8、数字最短表示。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def b64url_encode(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64url_decode(s):
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def preimage_of(report):
    """签名预像 = JCS({"hdr": hdr, "payload": payload})（不含 sig，见 §5.1）。"""
    return jcs({"hdr": report["hdr"], "payload": report["payload"]})


# ---------------------------------------------------------------------------
# 签名 / 验签原语
# ---------------------------------------------------------------------------
def sign_preimage(alg, preimage, signer):
    """对 preimage 签名，返回 bytes（alg=none 返回 None）。

    signer 须提供：alg=ES256 时 .privkey；alg=HS256 时 .hmac_key。
    """
    if alg == ALG_ES256:
        if not _CRYPTO_OK:
            raise RuntimeError("ES256 需要 cryptography 库")
        der = signer.privkey.sign(preimage, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")
    if alg == ALG_HS256:
        if not _CRYPTO_OK:
            raise RuntimeError("HS256 需要 cryptography 库")
        h = _chmac.HMAC(signer.hmac_key, hashes.SHA256())
        h.update(preimage)
        return h.finalize()
    if alg == ALG_NONE:
        return None
    raise ValueError(f"unknown alg: {alg}")


def _verify_es256(pubkey, preimage, sig):
    try:
        raw = b64url_decode(sig)
        if len(raw) != 64:
            return False
        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        der = encode_dss_signature(r, s)
        pubkey.verify(der, preimage, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def _verify_hs256(hmac_key, preimage, sig):
    try:
        expected = b64url_decode(sig)
    except Exception:
        return False
    h = _chmac.HMAC(hmac_key, hashes.SHA256())
    h.update(preimage)
    return _hmac_stdlib.compare_digest(h.finalize(), expected)


def pubkey_to_pem(pubkey):
    """ECDSA 公钥 → PEM 字符串（SubjectPublicKeyInfo）。"""
    if not _CRYPTO_OK:
        raise RuntimeError("pubkey_to_pem 需要 cryptography 库")
    return pubkey.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def pubkey_from_pem(pem):
    """PEM 字符串 → ECDSA 公钥对象。"""
    if not _CRYPTO_OK:
        raise RuntimeError("pubkey_from_pem 需要 cryptography 库")
    return serialization.load_pem_public_key(pem.encode("ascii"))


# ---------------------------------------------------------------------------
# 设备 / 密钥库 / nonce 缓存
# ---------------------------------------------------------------------------
class Device:
    """Orpah ID 终端：SN + ECDSA 私钥 + HMAC 降级密钥（§6.2 产线绑定记录）。"""

    def __init__(self, sn=None, cc="CN", org="WH01", se_sn="ATECC608B-DEMO",
                 check="mod97"):
        self.sn = sn if sn is not None else gen_sn(cc=cc, org=org, check=check)
        self.se_sn = se_sn
        self.hmac_key = os.urandom(32)          # Slot 5 / CH32 保护区（降级 HS256）
        self.privkey = None
        self.pubkey = None
        if _CRYPTO_OK:
            self.privkey = ec.generate_private_key(ec.SECP256R1())
            self.pubkey = self.privkey.public_key()

    def sign(self, alg, preimage):
        return sign_preimage(alg, preimage, self)

    def report(self, level=0, ts=None, nonce=None, seen_routers=None,
               battery_mv=None, firmware=None, extra=None):
        """按降级级别构建完整已签报文（§5.4 格式）。"""
        alg = LEVEL_TO_ALG[level]
        hdr = {"typ": "orpah-id-report", "ver": 1, "alg": alg, "level": level}
        payload = {
            "sn": self.sn,
            "ts": int(ts if ts is not None else time.time()),
            "nonce": nonce if nonce is not None else os.urandom(16).hex().upper(),
            "seen_routers": seen_routers or [],
        }
        if battery_mv is not None:
            payload["battery_mv"] = int(battery_mv)
        if firmware is not None:
            payload["firmware"] = firmware
        if extra:
            payload.update(extra)
        preimage = jcs({"hdr": hdr, "payload": payload})
        sig = self.sign(alg, preimage)
        report = {"hdr": hdr, "payload": payload}
        if sig is not None:
            report["sig"] = b64url_encode(sig)
        return report


class KeyStore:
    """server 密钥库：sn → {pubkey, hmac_key, se_sn, ...} + 撤销表（§6.3/§9.1）。"""

    def __init__(self):
        self._records = {}
        self._revoked = set()

    def register(self, dev, model=None, firmware=None):
        self._records[dev.sn] = {
            "pubkey": dev.pubkey,
            "hmac_key": dev.hmac_key,
            "se_sn": getattr(dev, "se_sn", None),
            "model": model,
            "firmware": firmware,
        }

    def get_by_sn(self, sn):
        return self._records.get(sn)

    def revoke(self, sn):
        self._revoked.add(sn)

    def unrevoke(self, sn):
        """撤销的逆操作（仅演示用；真实部署撤销不可逆，见规范 §6.3.2）。"""
        self._revoked.discard(sn)

    def is_revoked(self, sn):
        return sn in self._revoked

    def save(self, path):
        """导出密钥库为 JSON 文件（供 server.py --keystore-file 加载）。"""
        recs = []
        for sn, r in self._records.items():
            recs.append({
                "sn": sn,
                "pubkey_pem": pubkey_to_pem(r["pubkey"]),
                "hmac_key_b64": b64url_encode(r["hmac_key"]),
                "se_sn": r.get("se_sn"),
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"devices": recs}, f, ensure_ascii=False, indent=2)

    def load(self, path):
        """从 JSON 文件加载设备并注册（server.py --keystore-file）。"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for d in data.get("devices", []):
            self._records[d["sn"]] = {
                "pubkey": pubkey_from_pem(d["pubkey_pem"]),
                "hmac_key": b64url_decode(d["hmac_key_b64"]),
                "se_sn": d.get("se_sn"),
            }


class NonceCache:
    """按 sn 缓存近期 nonce（防重放，§5.5；每设备容量上限）。"""

    def __init__(self, per_device=1024):
        self._per_device = per_device
        self._cache = {}

    def seen(self, sn, nonce):
        s = self._cache.get(sn)
        return nonce in s if s else False

    def add(self, sn, nonce):
        s = self._cache.setdefault(sn, set())
        if len(s) >= self._per_device:
            s.clear()          # 简化：满了清空（真实部署用 LRU）
        s.add(nonce)


# ---------------------------------------------------------------------------
# server 验签（§9.3）
# ---------------------------------------------------------------------------
def _reject(code, level=None, alg=None):
    return {"accepted": False, "error": code, "trust": "none",
            "level": level, "alg": alg}


def verify_report(report, ks, now=None, used_nonces=None, window=300):
    """server 验签（对齐 §9.3 伪代码）。

    ks：KeyStore（含公钥/hmac_key/撤销表）
    used_nonces：NonceCache 或 None（None 表示跳过 nonce 去重，仅测试用）
    返回：{"accepted": bool, "trust": str, ...} 或 {"accepted": False, "error": code}
    """
    if now is None:
        now = int(time.time())

    # 1. 格式校验
    if not isinstance(report, dict):
        return _reject("bad_format")
    hdr = report.get("hdr")
    payload = report.get("payload")
    sig = report.get("sig")
    if not isinstance(hdr, dict) or not isinstance(payload, dict):
        return _reject("bad_format")
    if hdr.get("typ") != "orpah-id-report":
        return _reject("bad_typ", hdr.get("level"), hdr.get("alg"))
    if hdr.get("ver") != 1:
        return _reject("bad_ver", hdr.get("level"), hdr.get("alg"))
    alg = hdr.get("alg")
    level = hdr.get("level")
    if alg not in (ALG_ES256, ALG_HS256, ALG_NONE):
        return _reject("bad_alg", level, alg)
    if not isinstance(level, int) or level not in (0, 1, 2, 3):
        return _reject("bad_level", level, alg)

    # alg=none：L3 无签名，仅覆盖发现，不用于人员确认（§8.3）
    if alg == ALG_NONE:
        if level != 3:
            return _reject("none_requires_level3", level, alg)
        return {"accepted": True, "trust": "none", "level": 3, "alg": alg,
                "coverage_only": True}

    # 2. 时间窗口（ts=0 表示未知：跳过窗口，仅靠 nonce 防重放，§5.5）
    ts = payload.get("ts")
    if not isinstance(ts, int) or isinstance(ts, bool):
        return _reject("bad_ts", level, alg)
    if ts != 0 and abs(now - ts) > window:
        return _reject("timestamp_out_of_window", level, alg)

    # 3. SN / nonce 必填
    sn = payload.get("sn")
    nonce = payload.get("nonce")
    if not sn_ok(sn):
        return _reject("bad_sn", level, alg)
    if not isinstance(nonce, str) or not nonce:
        return _reject("bad_nonce", level, alg)

    # 3.5 nonce 去重（防重放主手段）
    if used_nonces is not None:
        if used_nonces.seen(sn, nonce):
            return _reject("replay_detected", level, alg)
        used_nonces.add(sn, nonce)

    # 4. SN 合法性 + CHECK 校验（有校验位则验证）
    if not verify_check(sn):
        return _reject("bad_check", level, alg)

    # 5. 撤销检查
    if ks is not None and ks.is_revoked(sn):
        return _reject("revoked", level, alg)

    # 6. 查密钥（以 sn 为检索键，每设备仅一个活跃密钥，§6.3）
    rec = ks.get_by_sn(sn) if ks is not None else None
    if not rec:
        return _reject("unknown_device", level, alg)

    # 7. 验签
    if not isinstance(sig, str) or not sig:
        return _reject("missing_sig", level, alg)
    preimage = jcs({"hdr": hdr, "payload": payload})
    if alg == ALG_ES256:
        ok = _verify_es256(rec["pubkey"], preimage, sig)
    else:  # HS256：直接对 preimage 做 HMAC
        hk = rec.get("hmac_key")
        if not hk:
            return _reject("no_hmac_key", level, alg)  # 降级需对称密钥（§9.1）
        ok = _verify_hs256(hk, preimage, sig)
    if not ok:
        return _reject("signature_invalid", level, alg)

    return {"accepted": True, "trust": TRUST_BY_LEVEL.get(level, "low"),
            "level": level, "alg": alg}


# ---------------------------------------------------------------------------
# xport（router 侧观测，不参与验签，§5.7）
# ---------------------------------------------------------------------------
def attach_xport(report, router_bssid, router_ssid, router_rssi, rx_ts=None):
    """router 转发时在其外附加观测（不得修改 hdr/payload/sig）。"""
    x = report.copy()
    x["xport"] = {
        "router_bssid": router_bssid,
        "router_ssid": router_ssid,
        "router_rssi": router_rssi,
        "rx_ts": int(rx_ts if rx_ts is not None else time.time()),
    }
    return x
