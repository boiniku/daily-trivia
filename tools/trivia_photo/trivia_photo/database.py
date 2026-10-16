from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import parse_dsn
from psycopg2.extras import Json, RealDictCursor


def fingerprint(row: dict) -> str:
    values = {key: row.get(key) for key in ("id", "title", "content", "explanation", "category")}
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Neon:
    def __init__(self, url: str, table: str = "trivia"):
        if table not in {"trivia", "map_trivia"}:
            raise ValueError("写真の反映先テーブルが不正です")
        self.table = table
        self.url = url.replace("postgresql+psycopg2://", "postgresql://", 1).replace("postgresql+psycopg://", "postgresql://", 1)
        config = parse_dsn(self.url)
        if not config.get("host", "").endswith(".neon.tech") or "," in config.get("host", ""):
            raise ValueError("Neon以外の接続先には接続しません")
        self.sslmode = config.get("sslmode", "require")
        if self.sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Neon接続にはSSLが必要です")

    @contextmanager
    def connect(self, readonly: bool = False):
        conn = psycopg2.connect(self.url, connect_timeout=10, sslmode=self.sslmode)
        conn.set_session(readonly=readonly)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def fetch(self, limit: int, ids: list[int] | None, excluded: list[int]) -> list[dict]:
        with self.connect(readonly=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '15s'")
            active = "AND is_active " if self.table == "map_trivia" else ""
            cur.execute(f"SELECT id, title, content, explanation, category, image_url, image_urls FROM public.{self.table} "
                        "WHERE (image_url IS NULL OR btrim(image_url) = '') "
                        + active +
                        "AND (%s::integer[] IS NULL OR id = ANY(%s::integer[])) "
                        "AND NOT (id = ANY(%s::integer[])) ORDER BY id LIMIT %s", (ids, ids, excluded, limit))
            return [dict(row) for row in cur.fetchall()]

    def current(self, trivia_id: int) -> dict:
        with self.connect(readonly=True) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute(f"SELECT id, title, content, explanation, category, image_url, image_urls FROM public.{self.table} WHERE id = %s", (trivia_id,))
            row = cur.fetchone()
        if not row:
            raise ValueError("雑学が削除されています")
        return dict(row)

    def publish(self, snapshot: dict, url: str, credit: str, metadata: dict) -> None:
        self.publish_gallery(snapshot, [dict(url=url, credit=credit, metadata=metadata)])

    def publish_gallery(self, snapshot: dict, photos: list[dict]) -> None:
        if not photos or len(photos) > 10 or len({photo["url"] for photo in photos}) != len(photos):
            raise ValueError("反映する写真は重複のない1〜10枚で指定してください")
        urls = [photo["url"] for photo in photos]
        cover = photos[0]
        sources = {photo["url"]: "\n".join(part for part in (
            photo["credit"], photo["metadata"].get("source_url", ""), photo["metadata"].get("license_url", ""),
        ) if part) for photo in photos}
        metadata = dict(cover["metadata"])
        if len(photos) > 1:
            metadata["photos"] = photos
        with self.connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute(f"SELECT id, title, content, explanation, category, image_url, image_urls FROM public.{self.table} WHERE id = %s FOR UPDATE", (snapshot["id"],))
            row = cur.fetchone()
            if not row or fingerprint(dict(row)) != fingerprint(snapshot):
                raise ValueError("雑学が変更されています。画像を再確認してください")
            existing_gallery = row.get("image_urls")
            if ((row["image_url"] and row["image_url"].strip() != urls[0])
                    or (existing_gallery and existing_gallery != urls)):
                raise ValueError("画像URLが既に登録されています。上書きしません")
            cur.execute(f"UPDATE public.{self.table} SET image_url = %s, image_urls = %s, image_sources = %s, "
                        "image_credit = %s, image_credit_metadata = %s WHERE id = %s",
                        (urls[0], Json(urls), Json(sources), cover["credit"], Json(metadata), snapshot["id"]))
