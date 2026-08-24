import os
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class PublishResult:
    remote_post_id: str
    remote_post_url: str | None = None
    raw: dict | None = None


class XTextPublisher:
    def __init__(self, access_token: str | None = None, session=None):
        self.access_token = (access_token or os.getenv("X_ACCESS_TOKEN", "")).strip()
        self.session = session or requests.Session()
        if not self.access_token:
            raise RuntimeError("X_ACCESS_TOKEN is not configured")

    def publish(self, text: str) -> PublishResult:
        response = self.session.post(
            "https://api.x.com/2/tweets",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            json={"text": text},
            timeout=(10, 30),
        )
        response.raise_for_status()
        raw = response.json()
        data = raw.get("data", {})
        post_id = str(data.get("id", ""))
        if not post_id:
            raise RuntimeError("X did not return a post id")
        username = os.getenv("X_USERNAME", "").strip().lstrip("@")
        url = f"https://x.com/{username}/status/{post_id}" if username else None
        return PublishResult(post_id, url, raw)


class ThreadsTextPublisher:
    def __init__(
        self,
        access_token: str | None = None,
        user_id: str | None = None,
        api_version: str | None = None,
        session=None,
    ):
        self.access_token = (access_token or os.getenv("THREADS_ACCESS_TOKEN", "")).strip()
        self.user_id = (user_id or os.getenv("THREADS_USER_ID", "")).strip()
        self.api_version = (api_version or os.getenv("THREADS_API_VERSION", "v1.0")).strip()
        self.session = session or requests.Session()
        if not self.access_token or not self.user_id:
            raise RuntimeError("THREADS_ACCESS_TOKEN and THREADS_USER_ID are required")

    def publish(self, text: str, topic_tag: str | None = None) -> PublishResult:
        params = {
            "media_type": "TEXT",
            "text": text,
            "auto_publish_text": "true",
        }
        if topic_tag:
            params["topic_tag"] = topic_tag
        response = self.session.post(
            f"https://graph.threads.net/{self.api_version}/{self.user_id}/threads",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
            timeout=(10, 30),
        )
        response.raise_for_status()
        raw = response.json()
        post_id = str(raw.get("id", ""))
        if not post_id:
            raise RuntimeError("Threads did not return a post id")
        return PublishResult(post_id, None, raw)
