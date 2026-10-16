from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Settings:
    database_url: str = field(default="", repr=False)
    endpoint: str = ""
    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    bucket: str = ""
    review_bucket: str = ""
    review_prefix: str = "trivia-photo-review"
    publish_prefix: str = "trivia/auto"
    public_base: str = ""
    batch_size: int = 5
    image_max_dimension: int = 1600
    image_webp_quality: int = 78
    user_agent: str = "TriviaPhoto/0.1 (manual educational photo curation)"
    data_dir: Path = ROOT / "data"
    target_table: str = "trivia"

    def for_target(self, target: str) -> "Settings":
        if target not in {"normal", "map"}:
            raise ValueError("写真の管理対象はnormalまたはmapで指定してください")
        table = "map_trivia" if target == "map" else "trivia"
        if self.target_table == table:
            return replace(self)
        if self.target_table != "trivia":
            raise ValueError("対象の切り替えは元の設定から行ってください")
        return replace(self, target_table=table, review_prefix=self.review_prefix + "/map",
                       publish_prefix=self.publish_prefix + "/map", data_dir=self.data_dir / "map")

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        legacy = ROOT.parent / "毎日雑学" / "apps" / "api" / ".env"
        if ROOT.parent.name == "tools":
            legacy = ROOT.parents[1] / "apps" / "api" / ".env"
        values = dict(dotenv_values(legacy)) if legacy.is_file() else {}
        local = env_file or ROOT / ".env"
        if env_file and not env_file.is_file():
            raise ValueError("指定した設定ファイルが見つかりません")
        if local.is_file():
            values.update({k: v for k, v in dotenv_values(local).items() if v is not None})
        values.update(os.environ)
        get = lambda key, default="": str(values.get(key) or default).strip()
        settings = cls(
            database_url=get("TRIVIA_PHOTO_DATABASE_URL", get("DATABASE_URL")),
            endpoint=get("R2_ENDPOINT_URL"),
            access_key=get("R2_ACCESS_KEY_ID"), secret_key=get("R2_SECRET_ACCESS_KEY"),
            bucket=get("R2_BUCKET_NAME"),
            review_bucket=get("R2_REVIEW_BUCKET_NAME", get("R2_BUCKET_NAME")),
            review_prefix=get("R2_REVIEW_PREFIX", "trivia-photo-review").strip("/"),
            publish_prefix=get("R2_TRIVIA_IMAGE_PREFIX", "trivia").strip("/") + "/auto",
            public_base=get("TRIVIA_IMAGE_R2_BASE_URL").rstrip("/"),
            batch_size=int(get("TRIVIA_PHOTO_BATCH_SIZE", "5")),
            image_max_dimension=int(get("TRIVIA_IMAGE_MAX_DIMENSION", "1600")),
            image_webp_quality=int(get("TRIVIA_IMAGE_WEBP_QUALITY", "78")),
            user_agent=get("TRIVIA_PHOTO_USER_AGENT", cls.user_agent),
        )
        a, b = settings.review_prefix, settings.publish_prefix
        if not a or not b or a == b or a.startswith(b + "/") or b.startswith(a + "/"):
            raise ValueError("確認用と公開用のR2フォルダは別のパスにしてください")
        if any(part in {".", ".."} for prefix in (a, b) for part in prefix.split("/")):
            raise ValueError("R2フォルダのパスが不正です")
        if not 1 <= settings.batch_size <= 50:
            raise ValueError("1回の件数は1〜50件にしてください")
        if not 240 <= settings.image_max_dimension <= 4096 or not 1 <= settings.image_webp_quality <= 100:
            raise ValueError("画像の長辺は240〜4096px、WebP品質は1〜100にしてください")
        return settings

    def require(self, *names: str) -> None:
        missing = [name for name in names if not getattr(self, name)]
        if missing:
            raise ValueError("設定が不足しています: " + ", ".join(missing))
