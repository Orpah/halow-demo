#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keystore.py — 密钥库的 SQLite 持久化（与设备台账同级，重启不丢）。

分层：

- **协议/生命周期逻辑** 全在 `orpah_id.KeyStore`（纯内存、不依赖数据库、可被
  `server.py`/`demo_id.py` 直接使用）；
- 本模块只加**写穿透**：每次变更落库、启动读回。UI 服务器用 `KeyStoreDB`。

表：

    keys(sn, kid, gen, pubkey_pem, hmac_b64, se_sn, model, firmware,
         created_at, state, grace_until, retired_at)     ← 每一代一行
    key_revocations(sn, at, reason, actor)              ← 设备级作废（整机）

**私钥不入库**：库里的 `pubkey` / `hmac_key` 正是 **server 侧**该持有的东西
（公钥 + 降级用的对称密钥）。模拟器自己那把私钥由
`orpah_id.derive_demo_privkey(sn, gen)` 确定派生（见该函数注释），故服务器重启后
公钥仍对得上 —— 真实设备则私钥永不出安全元件。
"""
import sqlite3
import threading

import orpah_id as oid


class KeyStoreDB(oid.KeyStore):
    """`orpah_id.KeyStore` + SQLite 写穿透（同一 `orpah.db`）。"""

    def __init__(self, db_path=":memory:", grace_sec=None):
        super().__init__(grace_sec=grace_sec)
        self._db_lock = threading.Lock()
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self._init_db()
        self._load()

    # ---------------- 建表 / 读回 ----------------
    def _init_db(self):
        with self._db_lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS keys (
                kid TEXT PRIMARY KEY, sn TEXT NOT NULL, gen INTEGER NOT NULL,
                pubkey_pem TEXT, hmac_b64 TEXT,
                se_sn TEXT DEFAULT '', model TEXT DEFAULT '', firmware TEXT DEFAULT '',
                created_at INTEGER NOT NULL, state TEXT NOT NULL,
                grace_until INTEGER, retired_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS key_revocations (
                sn TEXT PRIMARY KEY, at INTEGER NOT NULL,
                reason TEXT DEFAULT '', actor TEXT DEFAULT ''
            );
            """)
            self.db.commit()

    def _load(self):
        for r in self.db.execute("SELECT * FROM keys ORDER BY sn, gen"):
            rec = {"sn": r["sn"], "kid": r["kid"], "gen": int(r["gen"]),
                   "pubkey": (oid.pubkey_from_pem(r["pubkey_pem"])
                              if r["pubkey_pem"] else None),
                   "hmac_key": (oid.b64url_decode(r["hmac_b64"])
                                if r["hmac_b64"] else None),
                   "se_sn": r["se_sn"], "model": r["model"],
                   "firmware": r["firmware"], "created_at": int(r["created_at"]),
                   "state": r["state"], "grace_until": r["grace_until"],
                   "retired_at": r["retired_at"]}
            self._gens.setdefault(rec["sn"], []).append(rec)
        for r in self.db.execute("SELECT * FROM key_revocations"):
            self._revoked[r["sn"]] = {"at": int(r["at"]),
                                      "reason": r["reason"] or "",
                                      "actor": r["actor"] or ""}

    # ---------------- 写穿透 ----------------
    def _persist_key(self, rec):
        if rec is None:
            return
        with self._db_lock:
            self.db.execute(
                "INSERT OR REPLACE INTO keys (kid, sn, gen, pubkey_pem, hmac_b64,"
                " se_sn, model, firmware, created_at, state, grace_until, retired_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["kid"], rec["sn"], rec["gen"],
                 oid.pubkey_to_pem(rec["pubkey"]) if rec.get("pubkey") else None,
                 (oid.b64url_encode(rec["hmac_key"])
                  if rec.get("hmac_key") else None),
                 rec.get("se_sn") or "", rec.get("model") or "",
                 rec.get("firmware") or "", rec["created_at"], rec["state"],
                 rec.get("grace_until"), rec.get("retired_at")))
            self.db.commit()

    def _persist_revocation(self, sn):
        v = self._revoked.get(sn)
        with self._db_lock:
            if v is None:
                self.db.execute("DELETE FROM key_revocations WHERE sn=?", (sn,))
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO key_revocations (sn, at, reason, actor)"
                    " VALUES (?,?,?,?)", (sn, v["at"], v["reason"], v["actor"]))
            self.db.commit()

    def _persist_keys_of(self, sn):
        for r in self.list_keys(sn):
            self._persist_key(r)

    # ---------------- 覆写变更点：协议层逻辑 + 落库 ----------------
    def register(self, dev, model=None, firmware=None, ts=None, se_sn=None):
        kid = super().register(dev, model=model, firmware=firmware, ts=ts,
                               se_sn=se_sn)
        self._persist_key(self.get_key(kid))
        return kid

    def rotate(self, sn, dev, ts=None):
        r = super().rotate(sn, dev, ts=ts)
        self._persist_keys_of(sn)
        return r

    def retire(self, sn, kid=None, ts=None):
        kids = super().retire(sn, kid=kid, ts=ts)
        self._persist_keys_of(sn)
        return kids

    def sweep(self, now=None):
        out = super().sweep(now=now)
        for k, _ in out:
            self._persist_key(self.get_key(k))
        return out

    def revoke(self, sn, reason="", actor="", ts=None):
        rec = super().revoke(sn, reason=reason, actor=actor, ts=ts)
        self._persist_keys_of(sn)
        self._persist_revocation(sn)
        return rec

    def unrevoke(self, sn):
        rec = super().unrevoke(sn)
        self._persist_keys_of(sn)
        self._persist_revocation(sn)
        return rec

    def load_file(self, path):
        """JSON 导入（等价 `KeyStore.load`）**同时落库**。"""
        super().load(path)
        for r in self.list_keys():
            self._persist_key(r)
        for sn in self.sns():
            self._persist_revocation(sn)
