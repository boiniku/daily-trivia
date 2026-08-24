import os
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


@dataclass(frozen=True)
class SeedanceTask:
    id: str
    status: str
    video_url: str | None = None
    raw: dict | None = None


class SeedanceClient:
    """Small client for Volcengine Ark's asynchronous content generation API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key or os.getenv("SEEDANCE_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("SEEDANCE_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.session = session or requests.Session()
        if not self.api_key:
            raise RuntimeError("SEEDANCE_API_KEY is not configured")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_video(
        self,
        prompt: str,
        *,
        duration: int = 8,
        ratio: str = "9:16",
        generate_audio: bool = False,
        model: str | None = None,
    ) -> SeedanceTask:
        selected_model = (model or os.getenv("SEEDANCE_MODEL", "")).strip()
        if not selected_model:
            raise RuntimeError("SEEDANCE_MODEL is not configured")
        payload = {
            "model": selected_model,
            "content": [{"type": "text", "text": prompt}],
            "ratio": ratio,
            "duration": max(4, min(int(duration), 15)),
            "generate_audio": bool(generate_audio),
            "watermark": False,
        }
        response = self.session.post(
            f"{self.base_url}/contents/generations/tasks",
            headers=self.headers,
            json=payload,
            timeout=(10, 60),
        )
        response.raise_for_status()
        data = response.json()
        task_id = str(data.get("id") or data.get("task_id") or "")
        if not task_id:
            raise RuntimeError("Seedance did not return a task id")
        return SeedanceTask(id=task_id, status=str(data.get("status", "queued")), raw=data)

    def get_task(self, task_id: str) -> SeedanceTask:
        response = self.session.get(
            f"{self.base_url}/contents/generations/tasks/{task_id}",
            headers=self.headers,
            timeout=(10, 30),
        )
        response.raise_for_status()
        data = response.json()
        return SeedanceTask(
            id=str(data.get("id") or task_id),
            status=str(data.get("status", "unknown")).lower(),
            video_url=_extract_video_url(data),
            raw=data,
        )


def _extract_video_url(data: dict[str, Any]) -> str | None:
    candidates = [
        data.get("video_url"),
        (data.get("content") or {}).get("video_url") if isinstance(data.get("content"), dict) else None,
        (data.get("output") or {}).get("video_url") if isinstance(data.get("output"), dict) else None,
    ]
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                candidates.extend([item.get("video_url"), item.get("url")])
    return next((str(value) for value in candidates if value), None)
