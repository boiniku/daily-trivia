"""Image framing verified against 毎日雑学/apps/mobile/app/details.tsx."""

from __future__ import annotations

import hashlib
import warnings
from io import BytesIO

from PIL import Image, ImageOps

ASPECT_WIDTH, ASPECT_HEIGHT = 16, 9
DEFAULT_MAX_DIMENSION = 1600
DEFAULT_WEBP_QUALITY = 78
APP_BORDER_RADIUS = 36


def frame_size(size: tuple[int, int], max_dimension: int = DEFAULT_MAX_DIMENSION) -> tuple[int, int]:
    """Return an exact 16:9 frame without enlarging the source image."""
    units = min(size[0] // ASPECT_WIDTH, size[1] // ASPECT_HEIGHT, max_dimension // ASPECT_WIDTH)
    if units < 1:
        raise ValueError("16:9の表示枠に使える画像サイズがありません")
    return units * ASPECT_WIDTH, units * ASPECT_HEIGHT


def app_frame(image: Image.Image, max_dimension: int = DEFAULT_MAX_DIMENSION) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    return ImageOps.fit(image, frame_size(image.size, max_dimension), Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def vision_image(data: bytes) -> bytes:
    """Show the AI the same centered cover frame that the app displays."""
    with Image.open(BytesIO(data)) as image:
        output = BytesIO()
        app_frame(image.convert("RGB"), max_dimension=512).save(output, "JPEG", quality=75)
        return output.getvalue()


def format_signature(max_dimension: int, quality: int) -> str:
    return f"app-16x9-cover-v1:{max_dimension}:{quality}"


def encode_webp(image: Image.Image, quality: int) -> dict:
    output = BytesIO()
    image.save(output, "WEBP", quality=quality, method=6)
    data = output.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    return {"data": data, "sha256": sha, "size": len(data), "width": image.width, "height": image.height}


def prepare_image(data: bytes,
                  max_dimension: int = DEFAULT_MAX_DIMENSION, quality: int = DEFAULT_WEBP_QUALITY) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"} or getattr(original, "n_frames", 1) != 1:
                raise ValueError("対応する静止写真ではありません")
            image = ImageOps.exif_transpose(original).convert("RGB")
            if min(image.size) < 240:
                raise ValueError("画像の解像度が不足しています")
            source_size = image.size
            framed = app_frame(image, max_dimension)
            source = image.copy()
            source.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            source_asset = encode_webp(source, quality)
            asset = encode_webp(framed, quality)
    asset.update(source=source_asset, format_signature=format_signature(max_dimension, quality),
                 processing={"aspect_ratio": [16, 9], "resize_mode": "cover", "position": "center",
                             "source_size": list(source_size), "max_dimension": max_dimension, "webp_quality": quality,
                             "cropped": source_size[0] * 9 != source_size[1] * 16})
    return asset


def processing_changes(asset: dict) -> list[str]:
    changes = ["縮小", "WebP変換"]
    if asset.get("processing", {}).get("cropped"):
        changes.insert(0, "16:9中央トリミング")
    return changes
