"""CodexへR2の画像を渡す。画像をディスクへ書き出さない。"""
from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image, ImageOps


def inspect_image(workflow, batch: str, trivia_id: int, candidate: int | None = None, source: bool = False) -> dict:
    item = workflow.state.get(workflow.state.resolve_batch(batch), trivia_id)
    if candidate is None:
        asset = item["asset"]
    else:
        if not 0 <= candidate < len(item.get("candidates", [])):
            raise ValueError("候補番号が不正です")
        asset = item["candidates"][candidate]["asset"]
    if source:
        asset = asset.get("source", asset)
    data = workflow.asset_bytes(asset)
    with Image.open(BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((768, 768))
        # base64はモデルへ文章として渡さず、画像表示ツールへ直接渡す。
        for _ in range(8):
            buffer = BytesIO()
            image.save(buffer, "JPEG", quality=65, optimize=True)
            if len(buffer.getvalue()) <= 20 * 1024:
                break
            image.thumbnail((max(64, int(image.width * .8)), max(64, int(image.height * .8))))
    return {"sha256": asset["sha256"], "width": asset.get("width"), "height": asset.get("height"),
            "image_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()}
