#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orpah_id.py — Orpah ID 协议实现层（对齐《Orpah ID 协议规范》v1.16）
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
import hashlib
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


def pick_level(se_ok=True, sign_ok=True, hmac_ok=True):
    """按 §8.2 降级流程选级别 → `(level, reason)`。**策略唯一源**（设备侧与测试都调它）。

    §8.2 的流程照字面实现：
      Step1 SE（ATECC608B）I2C 通信失败 → 看 CH32 有无 HMAC 密钥：有→L2 / 无→L3
      Step2 SE 通、`atcab_sign(Slot0)` 失败 → L1（改用 Slot 5 的 HMAC）
      Step2 SE 通、签名成功 → L0（正常 ECDSA）
    """
    if not se_ok:
        return (2, "se_unavailable") if hmac_ok else (3, "no_key")
    if not sign_ok:
        return 1, "slot0_sign_failed"
    return 0, "normal"


def counts_as_presence(result):
    """这条验签结果能否**当作人员出现**（§8.3）。

    能：`accepted` 且非 `coverage_only`（L0/L1/L2 —— L2 仍更新定位，只标 `degraded`）。
    不能：被拒的（伪造/重放/超窗/…）与 L3（`alg=none` 裸上报，**只做覆盖发现**）。

    为什么要抽成一个函数：服务端「刷新最近见 / 抑制长未上报告警」的依据必须与验签裁决**同一源**。
    2026-09-12 实测踩过——`ui_server._on_id_report` 原来无条件 `registry.touch()`，
    于是一条**验签失败**的伪造上报也能刷新「最近见」（静置 3.5s 后 last_seen 1789199499 →
    注入伪造报文后 1789199504）→ 攻击者只要定期往空口扔伪造报文，就能让设备永远不报「长未上报」。
    """
    if not result or not result.get("accepted"):
        return False
    return not result.get("coverage_only")

# 密钥代次状态（§6.3 生命周期）
KEY_ACTIVE = "active"      # 当前代：用于签发新报文，参与验签
KEY_GRACE = "grace"        # 已被轮换掉：宽限期内仍参与验签（等役设备更新完）
KEY_RETIRED = "retired"    # 宽限结束：不再验签（记录保留，供审计追溯）
KEY_REVOKED = "revoked"    # 整机作废：所有代立即不验签（失窃/泄露/报废）


def _env_int(name, default):
    """取整数环境变量；未设/空串/非法值 → 回退默认。"""
    try:
        return int(str(os.environ.get(name, "") or default).strip())
    except (TypeError, ValueError):
        return default


# 轮换宽限期（秒）：ORPAH_KEY_GRACE_SEC（默认 7 天；0 = 旧钥立即失效）
KEY_GRACE_SEC = _env_int("ORPAH_KEY_GRACE_SEC", 7 * 86400)

# P-256 群阶 n（派生确定私钥时把哈希折到 [1, n-1]）
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


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
    """org_unique = ORG-UNIQUE（不含 CC）→ 2 位十进制校验码（IBAN 思路，输出 02–98）。"""
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


def derive_demo_privkey(sn, gen=1):
    """**仅演示**：由 (sn, gen) 确定派生的 P-256 私钥 —— 同 SN 同代 → 同钥。

    真实设备在安全元件内生成且私钥不可导出；但模拟器若每次启动都随机生成，
    持久化的密钥库就会每次重启都对不上公钥（验签必失败）。
    gen 与密钥库代次一致：轮换后应重新派生（第 N 代 → sn|N）。
    """
    seed = hashlib.sha256(
        b"orpah-demo-ec-p256-v1|" + str(sn).encode("utf-8")
        + b"|" + str(int(gen)).encode("ascii")).digest()
    d = (int.from_bytes(seed, "big") % (_P256_ORDER - 1)) + 1
    return ec.derive_private_key(d, ec.SECP256R1())


def derive_demo_hmac(sn, gen=1):
    """**仅演示**：由 (sn, gen) 确定派生的 32 字节 HMAC 降级密钥（HS256）。"""
    return hashlib.sha256(
        b"orpah-demo-hmac-v1|" + str(sn).encode("utf-8")
        + b"|" + str(int(gen)).encode("ascii")).digest()


# ---------------------------------------------------------------------------
# 设备 / 密钥库 / nonce 缓存
# ---------------------------------------------------------------------------
class Device:
    """Orpah ID 终端：SN + ECDSA 私钥 + HMAC 降级密钥（§6.2 产线绑定记录）。

    demo_key=True（默认）时密钥由 (sn, gen) **确定派生**，使同一 SN 在重启/多进程
    后仍是同一把钥（否则持久化密钥库每次重启都验不过）。**仅供模拟器**；
    真实设备用 demo_key=False（在安全元件/CH32 保护区内生成，私钥不可导出）。
    """

    def __init__(self, sn=None, cc="CN", org="WH01", se_sn="ATECC608B-DEMO",
                 check="mod97", demo_key=True, gen=1):
        self.sn = sn if sn is not None else gen_sn(cc=cc, org=org, check=check)
        self.se_sn = se_sn
        self.demo_key = bool(demo_key)
        self.gen = int(gen)
        self.privkey = None
        self.pubkey = None
        if not _CRYPTO_OK:
            self.hmac_key = os.urandom(32)
            return
        if self.demo_key:
            self.privkey = derive_demo_privkey(self.sn, self.gen)
            self.hmac_key = derive_demo_hmac(self.sn, self.gen)
        else:
            self.privkey = ec.generate_private_key(ec.SECP256R1())
            self.hmac_key = os.urandom(32)      # Slot 5 / CH32 保护区（降级 HS256）
        self.pubkey = self.privkey.public_key()

    def sign(self, alg, preimage):
        return sign_preimage(alg, preimage, self)

    def report(self, level=None, ts=None, nonce=None, seen_routers=None,
               battery_mv=None, firmware=None, extra=None,
               se_ok=True, sign_ok=True, hmac_ok=True):
        """构建完整已签报文（§5.4 格式）。

        `level=None`（默认）→ 按 §8.2 用 `pick_level(se_ok, sign_ok, hmac_ok)` **自动选级**
        （全部正常→L0，与老行为一致，故旧调用 `report()` 不受影响）；
        显式传 `level=0..3` 则按传的级别组包（演示/测试用）。
        """
        if level is None:
            level = pick_level(se_ok, sign_ok, hmac_ok)[0]
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
    """server 密钥库：sn → 多代密钥（§6.3/§9.1）+ 设备级撤销表。

    **为什么多代（轮换不断链）**：轮换后旧钥进入 grace 宽限期，宽限期内新旧钥**都能验签**，
    在役设备不必与 server 同时换钥；宽限结束（`sweep`）旧钥转 retired、不再参与验签。

    **不改报文格式**：报文头不引入 kid，验签按代次倒序**逐代试签**（活跃 + 宽限代通常只有
    1~2 个，代价可忽略）→ 老报文、老设备无需任何改动。

    生命周期：
        register(签发→active) → rotate(active→grace，新代→active)
        → sweep(grace 到期→retired) / retire(提前强制退役)
        revoke(整机作废：所有代立即不验签，不可逆*)
    * `unrevoke` 仅供演示；真实部署撤销不可逆（规范 §6.3.2）。撤销恢复后代次一律转 retired
      （不自动回到 active），要恢复服务需重新签发/轮换。
    """

    def __init__(self, grace_sec=None):
        self.grace_sec = KEY_GRACE_SEC if grace_sec is None else int(grace_sec)
        self._gens = {}         # sn -> [rec, ...]（按 gen 升序）
        self._revoked = {}      # sn -> {"at","reason","actor"}

    # ---------------- 签发 / 轮换 ----------------
    def register(self, dev, model=None, firmware=None, ts=None, se_sn=None):
        """登记设备的一代密钥（产线绑定，§6.2）→ 返回 kid。

        **幂等**：该 SN 已有 active 钥时不再签发，直接返回现有 kid
        （免得演示器每次启动都造出一把新钥）。要换钥请用 rotate。
        """
        cur = self.active_of(dev.sn)
        if cur is not None:
            return cur["kid"]
        return self._issue(dev.sn, getattr(dev, "pubkey", None),
                           getattr(dev, "hmac_key", None), model=model,
                           firmware=firmware, ts=ts,
                           se_sn=se_sn if se_sn is not None
                           else getattr(dev, "se_sn", None))

    def _issue(self, sn, pubkey, hmac_key, model=None, firmware=None, ts=None,
               se_sn=None):
        if sn in self._revoked:
            # 撤销不可逆（§6.3.2）：要恢复服务必须先 unrevoke（仅演示）再重新签发，
            # 否则“已作废”的设备会被重新发钥、静默复活。
            raise ValueError(f"{sn} 的密钥已作废，需先恢复（unrevoke）再签发")
        gens = self._gens.setdefault(sn, [])
        gen = (gens[-1]["gen"] + 1) if gens else 1
        rec = {"sn": sn, "kid": f"{sn}#{gen}", "gen": gen,
               "pubkey": pubkey, "hmac_key": hmac_key, "se_sn": se_sn,
               "model": model, "firmware": firmware,
               "created_at": int(ts if ts is not None else time.time()),
               "state": KEY_ACTIVE, "grace_until": None, "retired_at": None}
        gens.append(rec)
        return rec["kid"]

    def rotate(self, sn, dev, ts=None):
        """轮换：旧 active → grace（到 now+grace_sec），新钥 → active。

        返回 {"kid","prev_kid","grace_until","grace_sec"}；此前无钥时等价首次签发。
        """
        now = int(ts if ts is not None else time.time())
        prev = self.active_of(sn)
        if prev is not None:
            prev["state"] = KEY_GRACE
            prev["grace_until"] = now + self.grace_sec
        kid = self._issue(sn, getattr(dev, "pubkey", None),
                          getattr(dev, "hmac_key", None), ts=now,
                          se_sn=getattr(dev, "se_sn", None))
        return {"kid": kid, "prev_kid": prev["kid"] if prev else None,
                "grace_until": prev["grace_until"] if prev else None,
                "grace_sec": self.grace_sec}

    # ---------------- 退役 / 作废 ----------------
    def retire(self, sn, kid=None, ts=None):
        """强制退役某一代；不传 kid 时退役该 SN 所有**非 active**代。

        返回退役的 kid 列表（active 不会被静默退役，整机作废请用 revoke）。
        """
        now = int(ts if ts is not None else time.time())
        out = []
        for r in self._gens.get(sn, []):
            if r["state"] in (KEY_RETIRED, KEY_REVOKED):
                continue
            if kid is not None:
                if r["kid"] != kid:
                    continue
            elif r["state"] == KEY_ACTIVE:
                continue
            r["state"] = KEY_RETIRED
            r["retired_at"] = now
            out.append(r["kid"])
        return out

    def sweep(self, now=None):
        """宽限期已过的 grace 代 → retired。返回 [(kid, ts), ...]。"""
        now = int(now if now is not None else time.time())
        out = []
        for gens in self._gens.values():
            for r in gens:
                if (r["state"] == KEY_GRACE and r["grace_until"] is not None
                        and r["grace_until"] <= now):
                    r["state"] = KEY_RETIRED
                    r["retired_at"] = now
                    out.append((r["kid"], now))
        return out

    def revoke(self, sn, reason="", actor="", ts=None):
        """整机作废：该 SN 所有代立即不参与验签。重复调用不覆盖原记录。"""
        now = int(ts if ts is not None else time.time())
        if sn not in self._revoked:
            self._revoked[sn] = {"at": now, "reason": reason or "",
                                 "actor": actor or ""}
        # 无论是否已撤销，都把所有代置为 revoked（可能有“撤销后又冒出来的代”）
        for r in self._gens.get(sn, []):
            r["state"] = KEY_REVOKED
        return self._revoked[sn]

    def unrevoke(self, sn):
        """撤销的逆操作（**仅演示**；真实部署撤销不可逆，规范 §6.3.2）。"""
        rec = self._revoked.pop(sn, None)
        for r in self._gens.get(sn, []):
            if r["state"] == KEY_REVOKED:
                r["state"] = KEY_RETIRED
        return rec

    def is_revoked(self, sn):
        return sn in self._revoked

    def revoked_info(self, sn):
        return self._revoked.get(sn)

    # ---------------- 查询 ----------------
    def active_of(self, sn):
        for r in self._gens.get(sn, []):
            if r["state"] == KEY_ACTIVE:
                return r
        return None

    def verify_keys(self, sn, now=None):
        """可用于验签的密钥（active 在前，其次未过期的 grace），按代次倒序。

        报文本就不带 kid，故 server 按代次倒序**逐代试签**，轮换期间新旧都能过。
        """
        now = int(now if now is not None else time.time())
        out = []
        for r in sorted(self._gens.get(sn, []), key=lambda x: -x["gen"]):
            if r["state"] == KEY_ACTIVE:
                out.append(r)
            elif r["state"] == KEY_GRACE and (r["grace_until"] is None
                                              or r["grace_until"] > now):
                out.append(r)
        return out

    def get_by_sn(self, sn):
        """兼容旧接口：返回该 SN 的 **active** 记录（无则 None）。"""
        return self.active_of(sn)

    def get_key(self, kid):
        sn, _, gen = str(kid).rpartition("#")
        for r in self._gens.get(sn, []):
            if str(r["gen"]) == gen:
                return r
        return None

    def list_keys(self, sn=None):
        """全部密钥记录（可按 sn 过滤），按 (sn, 代次降序) 排序。"""
        if sn is not None:
            return sorted(self._gens.get(sn, []), key=lambda x: -x["gen"])
        return [r for s in sorted(self._gens) for r in
                sorted(self._gens[s], key=lambda x: -x["gen"])]

    def sns(self):
        return sorted(self._gens)

    # ---------------- 导入导出（server.py --keystore-file） ----------------
    def save(self, path):
        """导出为 JSON（含每一代与撤销表）。"""
        recs = []
        for sn in self.sns():
            for r in self._gens[sn]:
                recs.append({
                    "sn": r["sn"], "kid": r["kid"], "gen": r["gen"],
                    "pubkey_pem": (pubkey_to_pem(r["pubkey"])
                                   if r.get("pubkey") else None),
                    "hmac_key_b64": (b64url_encode(r["hmac_key"])
                                     if r.get("hmac_key") else None),
                    "se_sn": r.get("se_sn"), "model": r.get("model"),
                    "firmware": r.get("firmware"), "created_at": r["created_at"],
                    "state": r["state"], "grace_until": r.get("grace_until"),
                    "retired_at": r.get("retired_at"),
                })
        data = {"devices": recs,
                "revocations": [dict(sn=sn, **v)
                                for sn, v in sorted(self._revoked.items())]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path):
        """从 JSON 加载；**兼容旧格式**（无 kid/gen/state → 视作第 1 代 active）。"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for d in data.get("devices", []):
            gen = int(d.get("gen") or 1)
            rec = {"sn": d["sn"], "kid": d.get("kid") or f"{d['sn']}#{gen}",
                   "gen": gen,
                   "pubkey": (pubkey_from_pem(d["pubkey_pem"])
                              if d.get("pubkey_pem") else None),
                   "hmac_key": (b64url_decode(d["hmac_key_b64"])
                                if d.get("hmac_key_b64") else None),
                   "se_sn": d.get("se_sn"), "model": d.get("model"),
                   "firmware": d.get("firmware"),
                   "created_at": int(d.get("created_at") or 0),
                   "state": d.get("state") or KEY_ACTIVE,
                   "grace_until": d.get("grace_until"),
                   "retired_at": d.get("retired_at")}
            gens = self._gens.setdefault(rec["sn"], [])
            gens[:] = [r for r in gens if r["gen"] != gen]
            gens.append(rec)
            gens.sort(key=lambda x: x["gen"])
        for v in data.get("revocations", []):
            self._revoked[v["sn"]] = {"at": int(v.get("at") or 0),
                                      "reason": v.get("reason") or "",
                                      "actor": v.get("actor") or ""}

    # ---------------- 展示（UI / API） ----------------
    def to_dict(self, sn, registry=None, now=None):
        """单个 SN 的密钥视图（可带上设备台账信息，供页面一屏看完）。"""
        now = int(now if now is not None else time.time())
        dev = None
        if registry is not None:
            d = registry.devices.get(sn)
            if d is not None:
                dev = {"status": d.status, "person_id": d.person_id,
                       "org": d.org, "cc": d.cc, "last_seen": d.last_seen}
        out = {"sn": sn, "revoked": self._revoked.get(sn), "device": dev,
               "keys": []}
        for k in sorted(self._gens.get(sn, []), key=lambda x: -x["gen"]):
            gu = k.get("grace_until")
            out["keys"].append({
                "kid": k["kid"], "gen": k["gen"], "state": k["state"],
                "created_at": k["created_at"], "grace_until": gu,
                "grace_left": (max(0, gu - now)
                               if gu and k["state"] == KEY_GRACE else None),
                "retired_at": k.get("retired_at"), "se_sn": k.get("se_sn"),
                "model": k.get("model"), "firmware": k.get("firmware"),
                "has_pubkey": k.get("pubkey") is not None,
                "has_hmac": k.get("hmac_key") is not None,
                "pubkey_pem": (pubkey_to_pem(k["pubkey"])
                               if k.get("pubkey") else None),
            })
        return out


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
                "coverage_only": True, "degraded": False}

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

    # 5. 撤销检查（设备级：整机作废 → 所有代立即拒）
    if ks is not None and ks.is_revoked(sn):
        return _reject("revoked", level, alg)

    # 6. 取可用密钥（active + 未过期的 grace）：轮换宽限期内新旧钥都能过（§6.3）
    recs = ks.verify_keys(sn) if ks is not None else []
    if not recs:
        return _reject("unknown_device", level, alg)

    # 7. 验签：报文不带 kid → 按代次倒序**逐代试签**到匹配为止
    if not isinstance(sig, str) or not sig:
        return _reject("missing_sig", level, alg)
    preimage = jcs({"hdr": hdr, "payload": payload})
    hit = None
    hmac_missing = False
    for rec in recs:
        if alg == ALG_ES256:
            if rec.get("pubkey") and _verify_es256(rec["pubkey"], preimage, sig):
                hit = rec
                break
        else:  # HS256：直接对 preimage 做 HMAC
            hk = rec.get("hmac_key")
            if not hk:
                hmac_missing = True
                continue
            if _verify_hs256(hk, preimage, sig):
                hit = rec
                break
    if hit is None:
        # 降级到 HS256 但库里没有对称密钥 → 明确报错（§9.1）
        return _reject("no_hmac_key" if (alg == ALG_HS256 and hmac_missing)
                       else "signature_invalid", level, alg)

    return {"accepted": True, "trust": TRUST_BY_LEVEL.get(level, "low"),
            "level": level, "alg": alg, "kid": hit["kid"], "gen": hit["gen"],
            # §8.3：L2（SE 完全不可用、用 CH32 对称密钥）→ 标记 degraded（仍更新定位）；
            # L3 走上面提前返回（coverage_only）。两个字段给下游（存在性/告警/指标）判定用。
            "coverage_only": False, "degraded": level == 2}


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
