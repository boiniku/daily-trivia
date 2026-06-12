import os
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_DIMENSION = int(os.getenv("TRIVIA_IMAGE_MAX_DIMENSION", "1600"))
WEBP_QUALITY = int(os.getenv("TRIVIA_IMAGE_WEBP_QUALITY", "78"))


def upload_trivia_image(data: bytes, content_type: str, filename: str = "image") -> str:
    if not data:
        raise ValueError("画像が空です")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("画像は12MB以下にしてください")
    if not (content_type or "").startswith("image/"):
        raise ValueError("画像ファイルを選択してください")

    try:
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=WEBP_QUALITY, method=6)
            image_data = output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("画像を読み込めませんでした") from exc

    settings = {
        "endpoint_url": os.getenv("R2_ENDPOINT_URL", "").strip(),
        "aws_access_key_id": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "aws_secret_access_key": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket": os.getenv("R2_BUCKET_NAME", "").strip(),
    }
    if not all(settings.values()):
        raise RuntimeError("R2 image upload is not configured")

    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as exc:
        raise RuntimeError("R2 image upload dependencies are not installed") from exc

    client = boto3.client(
        "s3",
        endpoint_url=settings["endpoint_url"],
        aws_access_key_id=settings["aws_access_key_id"],
        aws_secret_access_key=settings["aws_secret_access_key"],
        region_name="auto",
        config=BotoConfig(connect_timeout=5, read_timeout=15, retries={"max_attempts": 1}),
    )
    prefix = os.getenv("R2_TRIVIA_IMAGE_PREFIX", "trivia").strip().strip("/")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    object_name = f"mobile-{timestamp}.webp"
    object_key = f"{prefix}/{object_name}" if prefix else object_name
    client.put_object(
        Bucket=settings["bucket"],
        Key=object_key,
        Body=image_data,
        ContentType="image/webp",
        CacheControl="public, max-age=31536000, immutable",
    )

    base_url = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
    return f"{base_url}/{object_key}" if base_url else object_key
