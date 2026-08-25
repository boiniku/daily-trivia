import os
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_BASE_URL = "https://api-singapore.klingai.com"


@dataclass(frozen=True)
class KlingTask:
    id: str
    status: str
    video_url: str | None = None
    duration: float | None = None
    error: str | None = None
    raw: dict | None = None


class KlingClient:
    """Client for Kling API 2.0's asynchronous image-to-video endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        session: requests.Session | None = None,
    ):
        self.api_key = (api_key or os.getenv("KLING_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("KLING_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.session = session or requests.Session()
        if not self.api_key:
            raise RuntimeError("KLING_API_KEY is not configured")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_image_video(
        self,
        prompt: str,
        first_frame_url: str,
        *,
        duration: int = 5,
        resolution: str = "720p",
        audio: bool = False,
        multi_shot: bool = False,
        model: str = "kling-3.0",
        external_task_id: str | None = None,
    ) -> KlingTask:
        if not first_frame_url.startswith(("http://", "https://")):
            raise ValueError("Kling first frame must use a public HTTP(S) URL")
        if resolution not in {"720p", "1080p", "4k"}:
            raise ValueError("Kling resolution must be 720p, 1080p, or 4k")
        duration = max(3, min(int(duration), 15))
        contents = [
            {"type": "prompt", "text": prompt[:3072]},
            {"type": "first_frame", "url": first_frame_url},
        ]
        options: dict[str, Any] = {"watermark_info": {"enabled": False}}
        if external_task_id:
            options["external_task_id"] = external_task_id
        payload = {
            "contents": contents,
            "settings": {
                "resolution": resolution,
                "duration": duration,
                "audio": "native" if audio else "off",
                "multi_shot": bool(multi_shot),
            },
            "options": options,
        }
        response = self.session.post(
            f"{self.base_url}/image-to-video/{model}",
            headers=self.headers,
            json=payload,
            timeout=(10, 60),
        )
        response.raise_for_status()
        data = response.json()
        _raise_api_error(data)
        task = data.get("data") or {}
        task_id = str(task.get("id") or "")
        if not task_id:
            raise RuntimeError("Kling did not return a task id")
        return KlingTask(
            id=task_id,
            status=str(task.get("status", "submitted")).lower(),
            raw=data,
        )

    def get_task(self, task_id: str) -> KlingTask:
        response = self.session.get(
            f"{self.base_url}/tasks",
            headers=self.headers,
            params={"task_ids": task_id},
            timeout=(10, 30),
        )
        response.raise_for_status()
        data = response.json()
        _raise_api_error(data)
        tasks = data.get("data") or []
        if isinstance(tasks, dict):
            tasks = tasks.get("result") or []
        if not tasks:
            raise RuntimeError(f"Kling task was not found: {task_id}")
        task = tasks[0]
        output = next(
            (
                item
                for item in task.get("outputs") or []
                if isinstance(item, dict) and item.get("type") == "video"
            ),
            {},
        )
        duration = output.get("duration")
        try:
            duration_value = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_value = None
        return KlingTask(
            id=str(task.get("id") or task_id),
            status=str(task.get("status", "unknown")).lower(),
            video_url=str(output.get("url")) if output.get("url") else None,
            duration=duration_value,
            error=str(task.get("message")) if task.get("message") else None,
            raw=data,
        )


def download_kling_video(url: str, session=requests) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Kling video URL must use HTTP(S)")
    response = session.get(url, timeout=(10, 120))
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and not (content_type.startswith("video/") or "octet-stream" in content_type):
        raise ValueError(f"Expected a video but received {content_type}")
    if not response.content:
        raise ValueError("Kling returned an empty video")
    if len(response.content) > 100 * 1024 * 1024:
        raise ValueError("Kling video exceeds 100 MB")
    return response.content


def _raise_api_error(data: dict) -> None:
    code = data.get("code")
    if code not in (None, 0, "0"):
        raise RuntimeError(f"Kling API error {code}: {data.get('message') or 'unknown error'}")
