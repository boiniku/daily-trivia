"""R2を正本にする作業履歴。PCの作業ファイルを消しても再開できる。"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .harness import digest
from .state import now


class CloudState:
    def __init__(self, storage, root: Path):
        self.storage = storage
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prefix = storage.settings.review_prefix + "/_state/batches/"

    def key(self, batch: str) -> str:
        if not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{10}", batch):
            raise ValueError("バッチIDが不正です")
        return self.prefix + batch + ".json"

    def batch_ids(self) -> list[str]:
        return sorted(key[len(self.prefix):-5] for key in self.storage.list_keys(self.prefix) if key.endswith(".json"))

    def load(self, batch: str):
        document, etag = self.storage.get_json(self.key(batch))
        if document is None:
            raise ValueError("バッチが見つかりません。旧データはmigrate-localでR2へ移行してください")
        return document, etag

    def create_batch(self, rows: list[dict]) -> str:
        batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
        self.storage.put_json(self.key(batch), {"id": batch, "created_at": now(), "status": "collecting",
            "items": {str(row["id"]): {"status": "queued", "trivia": row} for row in rows},
            "api_usage_history": {"calls": 0, "tokens": 0, "estimated_cost_usd": 0}})
        return batch

    def resolve_batch(self, batch: str) -> str:
        if batch == "latest":
            batches = self.batch_ids()
            if not batches:
                raise ValueError("バッチが見つかりません。先にcollectで対象を取得してください")
            batch = batches[-1]
        self.load(batch)
        return batch

    def items(self, batch: str) -> list[dict]:
        document, _ = self.load(batch)
        return [dict(value, batch_id=batch, trivia_id=int(key), _revision=digest(value))
                for key, value in sorted(document["items"].items(), key=lambda entry: int(entry[0]))]

    def get(self, batch: str, trivia_id: int) -> dict:
        for item in self.items(batch):
            if item["trivia_id"] == trivia_id:
                return item
        raise ValueError("指定した雑学がバッチにありません")

    def save(self, item: dict, status: str | None = None) -> None:
        batch, trivia_id = item["batch_id"], item["trivia_id"]
        document, etag = self.load(batch)
        current = document["items"][str(trivia_id)]
        if item.get("_revision") != digest(current):
            raise ValueError("別の処理がこの雑学の状態を更新しました。読み直してください")
        value = {k: v for k, v in item.items() if k not in {"batch_id", "trivia_id", "_revision"}}
        value["status"] = status or item["status"]
        document["items"][str(trivia_id)] = value
        self.storage.put_json(self.key(batch), document, etag)
        item.update(status=value["status"], _revision=digest(value))

    def attempted_ids(self, retry: bool = False) -> list[int]:
        return sorted({item["trivia_id"] for batch in self.batch_ids() for item in self.items(batch)
                       if not retry or item["status"] not in {"error", "rejected", "needs_review"}})

    def finish(self, batch: str, status: str) -> None:
        document, etag = self.load(batch)
        document["status"] = status
        self.storage.put_json(self.key(batch), document, etag)

    def usage(self, batch: str) -> dict:
        return self.load(batch)[0]["api_usage_history"]

    def asset_dir(self, batch: str) -> Path:
        self.key(batch)
        folder = self.root / batch / "images"
        return folder
