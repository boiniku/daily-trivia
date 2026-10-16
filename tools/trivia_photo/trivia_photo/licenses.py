from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from .state import now


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value: str) -> str:
    parser = PlainText()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def non_photo(metadata: dict) -> bool:
    raw = metadata.get("evidence", {}).get("extmetadata", {})
    categories = plain(raw.get("Categories", {}).get("value", ""))
    return bool(re.search(r"\b(?:illustrations?|drawings?|engravings?|lithographs?|paintings?|watercolou?rs?|diagrams?|maps|ai[ -]generated|midjourney|stable diffusion)\b", categories, re.IGNORECASE))


def licensed_metadata(info: dict, title: str) -> dict:
    raw = info.get("extmetadata", {})
    get = lambda name: plain(raw.get(name, {}).get("value", ""))
    name, license_code, license_url = get("LicenseShortName"), get("License").lower(), get("LicenseUrl")
    if get("NonFree").lower() in {"true", "1"}:
        raise ValueError("非自由ライセンス")
    attribution_required = True
    match = re.fullmatch(r"CC BY(-SA)? (1\.0|2\.0|2\.5|3\.0|4\.0)", name, re.IGNORECASE)
    parsed = urlparse(license_url)
    if match:
        kind, version = ("by-sa" if match.group(1) else "by"), match.group(2)
        if parsed.scheme != "https" or parsed.hostname != "creativecommons.org" or parsed.path.rstrip("/") != f"/licenses/{kind}/{version}":
            # Old source metadata sometimes uses HTTP for the canonical CC URL.
            if parsed.scheme != "http" or parsed.hostname != "creativecommons.org" or parsed.path.rstrip("/") != f"/licenses/{kind}/{version}":
                raise ValueError("ライセンス名とURLが一致しません")
        license_url = f"https://creativecommons.org/licenses/{kind}/{version}/"
        name = f"CC {'BY-SA' if match.group(1) else 'BY'} {version}"
        if not get("Artist"):
            raise ValueError("作者の情報がありません")
    elif name.upper() in {"CC0", "CC0 1.0", "CC0 1.0 UNIVERSAL"} and license_code in {"cc-zero", "cc0"}:
        license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
        name, attribution_required = "CC0 1.0", False
    elif name.lower() in {"public domain", "パブリックドメイン"} and license_code == "pd" and get("Copyrighted").lower() == "false":
        name, attribution_required = "Public domain", False
        license_url = ""
    else:
        raise ValueError("自動採用対象外、または判定できないライセンス")
    source_url = info.get("descriptionurl", "")
    source = urlparse(source_url)
    if source.scheme != "https" or source.hostname != "commons.wikimedia.org" or not source.path.startswith("/wiki/File:"):
        raise ValueError("画像の出典ページが不明です")
    return {
        "schema_version": 1, "title": title.removeprefix("File:"),
        "author": get("Artist"), "provider": "wikimedia_commons",
        "source_url": source_url, "license": name, "license_url": license_url,
        "attribution_required": attribution_required,
        "attribution": get("Attribution"), "copyright_notice": get("Copyright"),
        "credit_line": get("Credit"), "restrictions": get("Restrictions"),
        "changes": ["縮小", "WebP変換"], "checked_at": now(),
        "evidence": {"url": source_url, "extmetadata": raw},
    }


def credit_text(metadata: dict) -> str:
    parts = ["写真：" + (metadata.get("author") or "作者表記なし"),
             metadata["title"], metadata["license"], "Wikimedia Commons経由"]
    for key in ("attribution", "copyright_notice", "credit_line"):
        if metadata.get(key) and metadata[key] not in parts:
            parts.append(metadata[key])
    parts.append("加工：" + "・".join(metadata["changes"]))
    return " / ".join(parts)
