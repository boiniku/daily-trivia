from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    batch_id TEXT NOT NULL, trivia_id INTEGER NOT NULL,
                    status TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (batch_id, trivia_id)
                );
                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL, purpose TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                    cost REAL NOT NULL, status TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_batch(self, rows: list[dict]) -> str:
        batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        with self.connect() as db:
            db.execute("INSERT INTO batches VALUES (?, ?, 'collecting')", (batch, now()))
            for row in rows:
                db.execute("INSERT INTO items VALUES (?, ?, 'queued', ?)",
                           (batch, row["id"], json.dumps({"trivia": row}, ensure_ascii=False)))
        return batch

    def resolve_batch(self, batch: str) -> str:
        with self.connect() as db:
            if batch == "latest":
                row = db.execute("SELECT id FROM batches ORDER BY created_at DESC LIMIT 1").fetchone()
            else:
                row = db.execute("SELECT id FROM batches WHERE id = ?", (batch,)).fetchone()
        if not row:
            raise ValueError("バッチが見つかりません。先にcollectで対象を取得してください")
        return row["id"]

    def items(self, batch: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM items WHERE batch_id = ? ORDER BY trivia_id", (batch,)).fetchall()
        return [dict(json.loads(row["data"]), batch_id=row["batch_id"], trivia_id=row["trivia_id"], status=row["status"]) for row in rows]

    def get(self, batch: str, trivia_id: int) -> dict:
        for item in self.items(batch):
            if item["trivia_id"] == trivia_id:
                return item
        raise ValueError("指定した雑学がバッチにありません")

    def save(self, item: dict, status: str | None = None) -> None:
        item = dict(item)
        batch, trivia_id = item.pop("batch_id"), item.pop("trivia_id")
        status = status or item.pop("status")
        item.pop("status", None)
        with self.connect() as db:
            db.execute("UPDATE items SET status = ?, data = ? WHERE batch_id = ? AND trivia_id = ?",
                       (status, json.dumps(item, ensure_ascii=False), batch, trivia_id))

    def attempted_ids(self, retry: bool = False) -> list[int]:
        with self.connect() as db:
            query = "SELECT DISTINCT trivia_id FROM items"
            if retry:
                query += " WHERE status NOT IN ('error', 'rejected', 'needs_review')"
            return [row[0] for row in db.execute(query)]

    def finish(self, batch: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE batches SET status = ? WHERE id = ?", (status, batch))

    def usage(self, batch: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) calls, COALESCE(SUM(input_tokens + output_tokens), 0) tokens, "
                             "COALESCE(SUM(cost), 0) estimated_cost_usd FROM usage WHERE batch_id = ?", (batch,)).fetchone()
        return dict(row)

    def asset_dir(self, batch: str) -> Path:
        root = (self.root / batch / "images").resolve()
        if not root.is_relative_to(self.root):
            raise ValueError("保存パスが不正です")
        root.mkdir(parents=True, exist_ok=True)
        return root
