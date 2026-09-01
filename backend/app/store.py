"""Provider 档案存储。

不把任何厂商写死：任何 OpenAI 兼容端点都能用，配置存本地 SQLite，
运行时可改。.env 只在库为空时做一次种子导入，之后以库为准。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field

from .config import CACHE_DB, settings as env

_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    id             TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    base_url       TEXT NOT NULL,
    api_key        TEXT NOT NULL DEFAULT '',
    model_translate TEXT NOT NULL DEFAULT '',
    model_gloss    TEXT NOT NULL DEFAULT '',
    extra_body     TEXT NOT NULL DEFAULT '{}',
    created_at     REAL DEFAULT (strftime('%s','now'))
);
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class ProviderProfile:
    id: str
    label: str
    base_url: str
    api_key: str = ""
    model_translate: str = ""
    model_gloss: str = ""
    #: 附加请求体字段。通义系必须带 enable_thinking:false（否则推理输出让成本涨约 40 倍），
    #: 但该参数是厂商特有的，发给 OpenAI 会 400 —— 所以按档案配置，不写死。
    extra_body: dict = field(default_factory=dict)

    def masked(self) -> dict:
        """对外返回时遮蔽密钥，只留首尾便于用户辨认。"""
        d = asdict(self)
        k = self.api_key
        d["api_key"] = (f"{k[:6]}…{k[-4:]}" if len(k) > 12 else ("已设置" if k else ""))
        d["has_key"] = bool(k)
        return d


class SettingsStore:
    def __init__(self, path=CACHE_DB, *, seed: bool = True):
        """seed=False 用于测试，避免开发者本机的 .env 渗进测试库。"""
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        if seed:
            self._seed_from_env()

    # ---------- 种子 ----------

    #: 一眼可辨的占位符，不能当成真密钥
    _PLACEHOLDER = ("sk-xxxxxxxx", "sk-xxx", "your-api-key", "changeme")

    def _seed_from_env(self) -> None:
        """库为空时，用 .env 建一个初始档案，让开箱即用。

        占位符要当成"没填"：否则全新部署会显示"已配置"，
        用户以为能用，一调就报鉴权失败。
        """
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        if n or not env.qwen_base_url:
            return
        key = env.qwen_api_key.strip()
        if key in self._PLACEHOLDER or "xxxx" in key.lower():
            key = ""
        self.upsert(
            ProviderProfile(
                id="default",
                label="我的 Qwen",
                base_url=env.qwen_base_url,
                api_key=key,
                model_translate=env.qwen_model_translate,
                model_gloss=env.qwen_model_gloss,
                extra_body={"enable_thinking": False},
            )
        )
        self.set_active("default")

    # ---------- 档案 ----------

    def list(self) -> list[ProviderProfile]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM providers ORDER BY created_at"
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, pid: str) -> ProviderProfile | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM providers WHERE id=?", (pid,)).fetchone()
        return self._row(r) if r else None

    @staticmethod
    def _row(r: sqlite3.Row) -> ProviderProfile:
        return ProviderProfile(
            id=r["id"], label=r["label"], base_url=r["base_url"], api_key=r["api_key"],
            model_translate=r["model_translate"], model_gloss=r["model_gloss"],
            extra_body=json.loads(r["extra_body"] or "{}"),
        )

    def upsert(self, p: ProviderProfile) -> ProviderProfile:
        if not p.id:
            p.id = uuid.uuid4().hex[:12]
        # 空 api_key 视为"不改动"，避免前端回显遮蔽值时把真 key 覆盖掉
        existing = self.get(p.id)
        if existing and not p.api_key:
            p.api_key = existing.api_key
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO providers"
                " (id,label,base_url,api_key,model_translate,model_gloss,extra_body)"
                " VALUES (?,?,?,?,?,?,?)",
                (p.id, p.label, p.base_url.rstrip("/"), p.api_key,
                 p.model_translate, p.model_gloss, json.dumps(p.extra_body)),
            )
            self._conn.commit()
        if not self.active_id():
            self.set_active(p.id)
        return p

    def delete(self, pid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM providers WHERE id=?", (pid,))
            self._conn.commit()
        if self.active_id() == pid:
            rest = self.list()
            self.set_active(rest[0].id if rest else "")

    # ---------- 当前选用 ----------

    def active_id(self) -> str:
        with self._lock:
            r = self._conn.execute(
                "SELECT value FROM app_settings WHERE key='active_provider'"
            ).fetchone()
        return r["value"] if r else ""

    def set_active(self, pid: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO app_settings (key,value) VALUES ('active_provider',?)",
                (pid,),
            )
            self._conn.commit()

    def active(self) -> ProviderProfile | None:
        pid = self.active_id()
        return self.get(pid) if pid else None

    # ---------- 通用设置 ----------

    def get_setting(self, key: str, default=None):
        with self._lock:
            r = self._conn.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
        return json.loads(r["value"]) if r else default

    def set_setting(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO app_settings (key,value) VALUES (?,?)",
                (key, json.dumps(value)),
            )
            self._conn.commit()


_store: SettingsStore | None = None


def get_store() -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store
