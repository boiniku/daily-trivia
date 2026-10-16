from __future__ import annotations

import hashlib
import json
from urllib.parse import quote, urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings


class R2:
    def __init__(self, settings: Settings):
        settings.require("endpoint", "access_key", "secret_key", "bucket", "review_bucket")
        self.settings = settings
        self.client = boto3.client("s3", endpoint_url=settings.endpoint,
                                   aws_access_key_id=settings.access_key, aws_secret_access_key=settings.secret_key,
                                   region_name="auto", config=Config(connect_timeout=10, read_timeout=30, retries={"total_max_attempts": 2}))

    def head(self, bucket: str, key: str) -> dict | None:
        try:
            return self.client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    @staticmethod
    def check_object(head: dict, sha: str, size: int) -> None:
        if head.get("Metadata", {}).get("sha256") != sha or head.get("ContentLength") != size:
            raise ValueError("R2画像のハッシュ情報またはサイズが一致しません")

    def stage(self, batch: str, trivia_id: int, sha: str, data: bytes) -> dict:
        bucket = self.settings.review_bucket
        key = f"{self.settings.review_prefix}/{batch}/{trivia_id}-{sha[:20]}.webp"
        head = self.head(bucket, key)
        if head is None:
            self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/webp",
                                   CacheControl="no-store", Metadata={"sha256": sha, "trivia-id": str(trivia_id)})
            head = self.head(bucket, key)
        if head is None:
            raise ValueError("確認用画像の保存を確認できません")
        self.check_object(head, sha, len(data))
        return {"bucket": bucket, "key": key}

    def store_asset(self, batch: str, trivia_id: int, asset: dict, source: bool = False) -> dict:
        data = asset["data"]
        if hashlib.sha256(data).hexdigest() != asset["sha256"] or len(data) != asset["size"]:
            raise ValueError("加工した画像のハッシュまたはサイズが不正です")
        suffix = "-source" if source else ""
        location = {"bucket": self.settings.review_bucket,
                    "key": f"{self.settings.review_prefix}/{batch}/assets/{trivia_id}-{asset['sha256'][:20]}{suffix}.webp"}
        head = self.head(location["bucket"], location["key"])
        if head is None:
            self.client.put_object(Bucket=location["bucket"], Key=location["key"], Body=data,
                                   ContentType="image/webp", CacheControl="no-store",
                                   Metadata={"sha256": asset["sha256"], "trivia-id": str(trivia_id)})
            head = self.head(location["bucket"], location["key"])
        if head is None:
            raise ValueError("R2画像の保存を確認できません")
        self.check_object(head, asset["sha256"], asset["size"])
        return dict({k: v for k, v in asset.items() if k not in {"data", "source", "path"}}, r2=location)

    def read_asset(self, asset: dict) -> bytes:
        location = asset.get("r2")
        if not location:
            raise ValueError("R2へ移行されていない画像です。migrate-localを実行してください")
        response = self.client.get_object(Bucket=location["bucket"], Key=location["key"])
        self.check_object(response, asset["sha256"], asset["size"])
        with response["Body"] as body:
            data = body.read(12 * 1024 * 1024 + 1)
        if len(data) != asset["size"] or hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("R2画像が変更されています")
        return data

    def confirm_asset(self, asset: dict) -> dict:
        location = asset["r2"]
        head = self.head(location["bucket"], location["key"])
        if head is None:
            raise ValueError("確認用のR2画像が見つかりません")
        self.check_object(head, asset["sha256"], asset["size"])
        return dict(location)

    def image_url(self, asset: dict) -> str:
        location = asset.get("r2")
        if not location:
            return ""
        # 非公開バケットも同じ確認画面で扱い、画像をPCへ保存しない。
        return self.client.generate_presigned_url("get_object", Params={"Bucket": location["bucket"], "Key": location["key"]}, ExpiresIn=900)

    def list_keys(self, prefix: str) -> list[str]:
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.settings.review_bucket, Prefix=prefix)
        return [obj["Key"] for page in pages for obj in page.get("Contents", [])]

    def get_json(self, key: str) -> tuple[dict | None, str | None]:
        try:
            response = self.client.get_object(Bucket=self.settings.review_bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None, None
            raise
        with response["Body"] as body:
            data = body.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != response.get("Metadata", {}).get("sha256"):
            raise ValueError("R2の作業記録のサイズまたはハッシュが不正です")
        return json.loads(data), response["ETag"]

    def put_json(self, key: str, value: dict, etag: str | None = None) -> None:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            self.client.put_object(Bucket=self.settings.review_bucket, Key=key, Body=data,
                                   ContentType="application/json", CacheControl="no-store",
                                   Metadata={"sha256": hashlib.sha256(data).hexdigest()}, **condition)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
                raise ValueError("別の処理がR2の作業記録を更新しました。状態を読み直してください") from None
            raise

    def publish(self, item: dict) -> str:
        self.settings.require("public_base")
        if urlparse(self.settings.public_base).scheme != "https":
            raise ValueError("公開画像のベースURLにはHTTPSを設定してください")
        source, asset = item["staging"], item["asset"]
        head = self.head(source["bucket"], source["key"])
        if head is None:
            raise ValueError("確認用のR2画像が見つかりません")
        self.check_object(head, asset["sha256"], asset["size"])
        key = f"{self.settings.publish_prefix}/{item['trivia_id']}-{asset['sha256'][:20]}.webp"
        existing = self.head(self.settings.bucket, key)
        if existing:
            self.check_object(existing, asset["sha256"], asset["size"])
        else:
            self.client.copy_object(Bucket=self.settings.bucket, Key=key,
                                    CopySource={"Bucket": source["bucket"], "Key": source["key"]},
                                    MetadataDirective="REPLACE", ContentType="image/webp",
                                    CacheControl="public, max-age=31536000, immutable",
                                    Metadata={"sha256": asset["sha256"], "trivia-id": str(item["trivia_id"])})
            published = self.head(self.settings.bucket, key)
            if published is None:
                raise ValueError("公開用画像のコピーを確認できません")
            self.check_object(published, asset["sha256"], asset["size"])
        return self.settings.public_base + "/" + quote(key, safe="/")
