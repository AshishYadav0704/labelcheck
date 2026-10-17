"""SQLite storage: products seen by the app (to power alternatives), saved
reports (for shareable links) and a small key-value cache for API responses.

SQLite in WAL mode handles a single server comfortably. Images and personal
health profiles are never stored.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    barcode TEXT,
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT NOT NULL,
    score INTEGER NOT NULL,
    grade TEXT NOT NULL,
    data_json TEXT NOT NULL,
    source TEXT NOT NULL,
    scan_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_category_score ON products(category, score DESC);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    product_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def product_id(barcode: str | None, name: str, brand: str | None) -> str:
    if barcode:
        return f"b{barcode}"
    key = f"{(brand or '').strip().lower()}|{name.strip().lower()}"
    return "l" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
            with self._all_lock:
                self._all.append(conn)
        return conn

    def close(self) -> None:
        """Close every connection opened by any thread (called on shutdown)."""
        with self._all_lock:
            for conn in self._all:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._all.clear()
        self._local = threading.local()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---- products -------------------------------------------------------
    def upsert_product(self, pid: str, product: dict[str, Any], score: int, grade: str) -> None:
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO products (id, barcode, name, brand, category, score, grade, data_json, source,
                                         scan_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, brand=excluded.brand, category=excluded.category,
                     score=excluded.score, grade=excluded.grade, data_json=excluded.data_json,
                     source=excluded.source, scan_count=products.scan_count + 1, updated_at=excluded.updated_at""",
                (pid, product.get("barcode"), product.get("name", ""), product.get("brand"), product.get("category", "other"),
                 score, grade, json.dumps(product, ensure_ascii=False), product.get("source", "manual"), now, now),
            )

    def get_product_by_barcode(self, barcode: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT data_json FROM products WHERE barcode = ? ORDER BY updated_at DESC LIMIT 1",
                               (barcode,)).fetchone()
        return json.loads(row["data_json"]) if row else None

    def better_in_category(self, category: str, min_score: int, exclude_id: str, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, barcode, name, brand, score, grade, scan_count FROM products
                   WHERE category = ? AND score >= ? AND id != ?
                   ORDER BY score DESC, scan_count DESC LIMIT ?""",
                (category, min_score, exclude_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        return {"products": products, "reports": reports}

    # ---- reports --------------------------------------------------------
    def save_report(self, pid: str, product: dict[str, Any]) -> str:
        rid = secrets.token_urlsafe(9)
        with self.connect() as conn:
            conn.execute("INSERT INTO reports (id, product_id, product_json, created_at) VALUES (?, ?, ?, ?)",
                         (rid, pid, json.dumps(product, ensure_ascii=False), _now()))
        return rid

    def get_report(self, rid: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT id, product_id, product_json, created_at FROM reports WHERE id = ?",
                               (rid,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "product_id": row["product_id"], "product": json.loads(row["product_json"]),
                "created_at": row["created_at"]}

    # ---- cache ----------------------------------------------------------
    def cache_get(self, key: str) -> Any | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        return json.loads(row["value"])

    def cache_set(self, key: str, value: Any, ttl_s: int) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                         (key, json.dumps(value, ensure_ascii=False), time.time() + ttl_s))

    def cache_prune(self) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            return cur.rowcount
