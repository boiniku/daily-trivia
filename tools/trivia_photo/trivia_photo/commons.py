from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests

from .licenses import licensed_metadata, non_photo, plain
from .image_format import DEFAULT_MAX_DIMENSION

API = "https://commons.wikimedia.org/w/api.php"
MAX_BYTES = 12 * 1024 * 1024
IMAGE_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}


class Commons:
    def __init__(self, user_agent: str, max_dimension: int = DEFAULT_MAX_DIMENSION):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.max_dimension = max_dimension

    def query(self, params: dict) -> dict:
        response = self.session.get(API, params={"format": "json", "formatversion": 2, "maxlag": 5, **params}, timeout=(10, 30))
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError("Commons APIエラー: " + data["error"].get("code", "unknown"))
        return data

    def search(self, query: str, limit: int = 6) -> list[dict]:
        data = self.query({"action": "query", "generator": "search", "gsrnamespace": 6,
                           "gsrsearch": query[:200] + " filetype:bitmap", "gsrlimit": limit,
                           "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": self.max_dimension})
        results = []
        for page in sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 999)):
            infos = page.get("imageinfo", [])
            if not infos or infos[0].get("mime") not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            info = infos[0]
            try:
                metadata = licensed_metadata(info, page["title"])
                if non_photo(metadata):
                    continue
            except ValueError:
                continue
            results.append({"page_id": page["pageid"], "file_title": page["title"],
                            "download_url": info.get("thumburl") or info["url"],
                            "description": plain(info.get("extmetadata", {}).get("ImageDescription", {}).get("value", ""))[:1200],
                            "metadata": metadata})
        return results

    def refresh_metadata(self, candidate: dict) -> dict:
        data = self.query({"action": "query", "pageids": candidate["page_id"],
                           "prop": "imageinfo", "iiprop": "url|extmetadata"})
        pages = data.get("query", {}).get("pages", [])
        if not pages or not pages[0].get("imageinfo"):
            raise ValueError("Commonsの画像を再確認できません")
        return licensed_metadata(pages[0]["imageinfo"][0], pages[0]["title"])

    def download(self, url: str) -> bytes:
        for _ in range(4):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS or parsed.username or parsed.password:
                raise ValueError("許可されていない画像URLです")
            with self.session.get(url, stream=True, allow_redirects=False, timeout=(10, 30)) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["Location"])
                    continue
                response.raise_for_status()
                if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                    raise ValueError("画像が12MBを超えています")
                output = bytearray()
                for part in response.iter_content(64 * 1024):
                    output.extend(part)
                    if len(output) > MAX_BYTES:
                        raise ValueError("画像が12MBを超えています")
                return bytes(output)
        raise ValueError("画像URLのリダイレクトが多すぎます")
