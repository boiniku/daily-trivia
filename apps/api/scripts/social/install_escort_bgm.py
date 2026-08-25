"""Install DOVA's Escort as an encrypted, non-distributable R2 object."""

import base64
import hashlib
import os
import re

import boto3
import requests
from botocore.config import Config as BotoConfig
from cryptography.fernet import Fernet
from dotenv import load_dotenv


SOURCE_URL = "https://dova-s.jp/bgm/detail/12633/download"
OBJECT_KEY_SUFFIX = "private-assets/bgm/escort.mp3.enc"


def main() -> None:
    load_dotenv()
    audio = _download_once()
    secret_access_key = _required("R2_SECRET_ACCESS_KEY")
    client = boto3.client(
        "s3",
        endpoint_url=_required("R2_ENDPOINT_URL"),
        aws_access_key_id=_required("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=BotoConfig(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
    )
    bucket = _required("R2_BUCKET_NAME")
    root = os.getenv("R2_SOCIAL_PREFIX", "social").strip().strip("/")
    object_key = "/".join(part for part in (root, OBJECT_KEY_SUFFIX) if part)
    encrypted = Fernet(_fernet_key(secret_access_key)).encrypt(audio)
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=encrypted,
        ContentType="application/octet-stream",
        Metadata={
            "source": "DOVA-SYNDROME",
            "source-id": "12633",
            "track": "Escort",
            "creator": "MoppySound",
        },
    )
    print(f"Uploaded {len(encrypted)} encrypted bytes to {bucket}/{object_key}")


def _download_once() -> bytes:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 DailyTrivia/1.0"})
    page = session.get(SOURCE_URL, timeout=30)
    page.raise_for_status()
    match = re.search(
        r'name="csrfmiddlewaretoken" value="([^"]+)"',
        page.text,
    )
    if not match:
        raise RuntimeError("DOVA download token was not found")
    response = session.post(
        SOURCE_URL,
        data={"csrfmiddlewaretoken": match.group(1), "track": "1"},
        headers={"Referer": SOURCE_URL},
        timeout=60,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "audio" not in content_type and not response.content.startswith((b"ID3", b"\xff")):
        raise RuntimeError(f"DOVA returned an unexpected content type: {content_type}")
    if not 100_000 <= len(response.content) <= 20 * 1024 * 1024:
        raise RuntimeError("Downloaded DOVA audio has an unexpected size")
    return response.content


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _fernet_key(secret_access_key: str) -> bytes:
    digest = hashlib.sha256(
        f"daily-trivia-private-bgm-v1:{secret_access_key}".encode("utf-8")
    ).digest()
    return base64.urlsafe_b64encode(digest)


if __name__ == "__main__":
    main()
