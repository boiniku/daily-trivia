"""Ordered, durable trivia images shared by every publication path.

``None`` means that the gallery was omitted (fall back to the legacy cover),
whereas ``[]`` explicitly removes every photo. Legacy cover-only edits replace
the first image while preserving the remaining photos; an empty cover clears
the gallery. New clients should always submit the complete ordered collection.
"""

from services.admin_images import normalize_image_reference


MAX_TRIVIA_IMAGES = 10
UNSET = object()


def normalize_trivia_images(image_urls=None, image_url=None) -> list[str]:
    if image_urls is not None and not isinstance(image_urls, list):
        raise ValueError("写真はURLまたはR2キーの配列で指定してください。")
    values = image_urls if image_urls is not None else ([] if image_url is None else [image_url])
    images = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("写真URLやR2キーは文字列で指定してください。")
        value = value.strip()
        if not value:
            continue
        value = normalize_image_reference(value)
        if value not in images:
            images.append(value)
    if len(images) > MAX_TRIVIA_IMAGES:
        raise ValueError(f"写真は最大{MAX_TRIVIA_IMAGES}枚まで登録できます。")
    return images


def read_trivia_images(image_urls=None, image_url=None) -> list[str]:
    """Read historical rows without letting a bad photo break their content.

    Only writes enforce collection shape and count. Old single-photo writers
    accepted arbitrary strings, including inline images, so reads keep those
    supported inline images and omit malformed references individually.
    """
    values = image_urls if isinstance(image_urls, list) else [image_url]
    images = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if not value.lower().startswith("data:"):
            try:
                value = normalize_image_reference(value)
            except ValueError:
                continue
        if value not in images:
            images.append(value)
    return images


def normalize_trivia_image_sources(image_sources, images, *, strict=True) -> dict[str, str]:
    """Keep attribution attached to its photo, independently of gallery order."""
    if image_sources is None:
        return {}
    if not isinstance(image_sources, dict):
        if strict:
            raise ValueError("写真の出典は写真URLをキーにしたオブジェクトで指定してください。")
        return {}
    sources = {}
    for image, source in image_sources.items():
        if not isinstance(image, str) or not isinstance(source, str):
            if strict:
                raise ValueError("写真URLと写真の出典は文字列で指定してください。")
            continue
        try:
            image = normalize_image_reference(image)
        except ValueError:
            if strict:
                raise
            continue
        if image in images and source.strip():
            sources[image] = source.strip()
    return sources


def trivia_image_values(image_urls=None, image_url=None, image_sources=None) -> dict:
    images = normalize_trivia_images(image_urls, image_url)
    return {"image_urls": images, "image_url": images[0] if images else None,
            "image_sources": normalize_trivia_image_sources(image_sources, images)}


def merge_trivia_image_values(item, updates: dict) -> dict:
    """Resolve a partial edit without silently dropping existing extra photos."""
    sources = updates.get("image_sources", getattr(item, "image_sources", None))
    if updates.get("image_urls") is not None:
        return trivia_image_values(updates["image_urls"], image_sources=sources)
    current = getattr(item, "image_urls", None)
    if "image_url" in updates:
        cover = normalize_trivia_images(image_url=updates["image_url"])
        if not cover:
            return trivia_image_values([])
        # The previous cover is being replaced, so a malformed legacy cover
        # must not prevent its repair. Only the retained extra photos matter.
        if current is None:
            current = []
        if not isinstance(current, list):
            raise ValueError("写真はURLまたはR2キーの配列で指定してください。")
        return trivia_image_values([*cover, *current[1:]], image_sources=sources)
    return trivia_image_values(current, item.image_url, sources)
