import os
from datetime import datetime


def upload_social_asset(
    data: bytes,
    content_type: str,
    extension: str,
    *,
    prefix: str = "videos",
) -> str:
    if not data:
        raise ValueError("Social asset is empty")
    settings = {
        "endpoint_url": os.getenv("R2_ENDPOINT_URL", "").strip(),
        "aws_access_key_id": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "aws_secret_access_key": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket": os.getenv("R2_BUCKET_NAME", "").strip(),
    }
    if not all(settings.values()):
        raise RuntimeError("R2 social asset upload is not configured")

    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        endpoint_url=settings["endpoint_url"],
        aws_access_key_id=settings["aws_access_key_id"],
        aws_secret_access_key=settings["aws_secret_access_key"],
        region_name="auto",
        config=BotoConfig(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    root = os.getenv("R2_SOCIAL_PREFIX", "social").strip().strip("/")
    child = prefix.strip().strip("/")
    stamp = datetime.utcnow().strftime("%Y/%m/%d/%Y%m%d%H%M%S%f")
    object_key = "/".join(part for part in (root, child, f"{stamp}.{extension.lstrip('.')}") if part)
    client.put_object(
        Bucket=settings["bucket"],
        Key=object_key,
        Body=data,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    base_url = (
        os.getenv("SOCIAL_ASSET_R2_BASE_URL", "").strip()
        or os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip()
    ).rstrip("/")
    return f"{base_url}/{object_key}" if base_url else object_key
