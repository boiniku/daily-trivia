import base64
import os
from dataclasses import dataclass
from io import BytesIO

import requests
from PIL import Image


@dataclass(frozen=True)
class PublishResult:
    remote_post_id: str
    remote_post_url: str | None = None
    raw: dict | None = None


class BufferTextPublisher:
    """Publish one image/text post through Buffer's official GraphQL API."""

    API_URL = "https://api.buffer.com"

    def __init__(
        self,
        channel_id: str,
        api_key: str | None = None,
        session=None,
    ):
        self.api_key = (api_key or os.getenv("BUFFER_API_KEY", "")).strip()
        self.channel_id = channel_id.strip()
        self.session = session or requests.Session()
        if not self.api_key or not self.channel_id:
            raise RuntimeError("BUFFER_API_KEY and a Buffer channel ID are required")

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        alt_text: str | None = None,
    ) -> PublishResult:
        # Buffer fetches the public R2 image itself. Its current image asset input
        # does not expose alt text, so keep the argument for publisher compatibility.
        del alt_text
        mutation = """
        mutation CreatePost($input: CreatePostInput!) {
          createPost(input: $input) {
            __typename
            ... on PostActionSuccess {
              post { id status }
            }
            ... on MutationError { message }
          }
        }
        """
        post_input = {
            "text": text,
            "channelId": self.channel_id,
            "schedulingType": "automatic",
            "mode": "shareNow",
            "aiAssisted": True,
            "assets": [],
        }
        if image_url:
            post_input["assets"] = [{"image": {"url": image_url}}]
        response = self.session.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"query": mutation, "variables": {"input": post_input}},
            timeout=(10, 60),
        )
        response.raise_for_status()
        raw = response.json()
        if raw.get("errors"):
            message = str((raw["errors"][0] or {}).get("message") or "unknown GraphQL error")
            raise RuntimeError(f"Buffer rejected the request: {message}")
        result = (raw.get("data") or {}).get("createPost") or {}
        post = result.get("post") or {}
        post_id = str(post.get("id") or "")
        if not post_id:
            message = str(result.get("message") or "Buffer did not return a post id")
            raise RuntimeError(f"Buffer could not create the post: {message}")
        return PublishResult(post_id, None, raw)


class BufferThreadsTextPublisher(BufferTextPublisher):
    def publish(
        self,
        text: str,
        topic_tag: str | None = None,
        image_url: str | None = None,
        alt_text: str | None = None,
    ) -> PublishResult:
        # Buffer's API currently has no Threads topic-tag field.
        del topic_tag
        return super().publish(text, image_url, alt_text)


class XTextPublisher:
    def __init__(self, access_token: str | None = None, session=None):
        self.access_token = (access_token or os.getenv("X_ACCESS_TOKEN", "")).strip()
        self.session = session or requests.Session()
        if not self.access_token:
            raise RuntimeError("X_ACCESS_TOKEN is not configured")

    def publish(
        self,
        text: str,
        image_url: str | None = None,
        alt_text: str | None = None,
    ) -> PublishResult:
        media_ids = []
        if image_url:
            image_response = self.session.get(image_url, timeout=(10, 30))
            image_response.raise_for_status()
            image_data, media_type = _x_ready_image(
                image_response.content,
                image_response.headers.get("content-type", ""),
            )
            upload_response = self.session.post(
                "https://api.x.com/2/media/upload",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "media": base64.b64encode(image_data).decode("ascii"),
                    "media_category": "tweet_image",
                    "media_type": media_type,
                    "shared": False,
                },
                timeout=(10, 60),
            )
            upload_response.raise_for_status()
            media_id = str((upload_response.json().get("data") or {}).get("id", ""))
            if not media_id:
                raise RuntimeError("X did not return a media id")
            media_ids.append(media_id)
        payload = {"text": text, "made_with_ai": True}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        response = self.session.post(
            "https://api.x.com/2/tweets",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
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

    def publish(
        self,
        text: str,
        topic_tag: str | None = None,
        image_url: str | None = None,
        alt_text: str | None = None,
    ) -> PublishResult:
        params = {
            "media_type": "IMAGE" if image_url else "TEXT",
            "text": text,
        }
        if image_url:
            params["image_url"] = image_url
            if alt_text:
                params["alt_text"] = alt_text
        else:
            params["auto_publish_text"] = "true"
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
            raise RuntimeError("Threads did not return a container id")
        if not image_url:
            return PublishResult(post_id, None, raw)
        publish_response = self.session.post(
            f"https://graph.threads.net/{self.api_version}/{self.user_id}/threads_publish",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params={"creation_id": post_id},
            timeout=(10, 30),
        )
        publish_response.raise_for_status()
        published_raw = publish_response.json()
        published_id = str(published_raw.get("id", ""))
        if not published_id:
            raise RuntimeError("Threads did not return a published post id")
        return PublishResult(published_id, None, published_raw)


def _x_ready_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type in {"image/jpeg", "image/png", "image/webp"} and len(data) <= 5 * 1024 * 1024:
        return data, normalized_type
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGB")
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        ready = output.getvalue()
    if len(ready) > 5 * 1024 * 1024:
        raise ValueError("Image remains larger than X's 5 MB limit")
    return ready, "image/jpeg"


class InstagramReelPublisher:
    def __init__(
        self,
        access_token: str | None = None,
        user_id: str | None = None,
        api_version: str | None = None,
        session=None,
    ):
        self.access_token = (access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN", "")).strip()
        self.user_id = (user_id or os.getenv("INSTAGRAM_USER_ID", "")).strip()
        self.api_version = (api_version or os.getenv("INSTAGRAM_API_VERSION", "v23.0")).strip()
        self.session = session or requests.Session()
        if not self.access_token or not self.user_id:
            raise RuntimeError("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID are required")

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    def submit(self, video_url: str, caption: str) -> PublishResult:
        response = self.session.post(
            f"{self.base_url}/{self.user_id}/media",
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
                "access_token": self.access_token,
            },
            timeout=(10, 60),
        )
        response.raise_for_status()
        raw = response.json()
        container_id = str(raw.get("id", ""))
        if not container_id:
            raise RuntimeError("Instagram did not return a container id")
        return PublishResult(container_id, None, raw)

    def status(self, container_id: str) -> str:
        response = self.session.get(
            f"{self.base_url}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": self.access_token,
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        return str(response.json().get("status_code", "")).upper()

    def publish(self, container_id: str) -> PublishResult:
        response = self.session.post(
            f"{self.base_url}/{self.user_id}/media_publish",
            params={"creation_id": container_id, "access_token": self.access_token},
            timeout=(10, 60),
        )
        response.raise_for_status()
        raw = response.json()
        media_id = str(raw.get("id", ""))
        if not media_id:
            raise RuntimeError("Instagram did not return a media id")
        return PublishResult(media_id, None, raw)


class TikTokVideoPublisher:
    API_BASE = "https://open.tiktokapis.com/v2/post/publish"

    def __init__(self, access_token: str | None = None, session=None):
        self.access_token = (access_token or os.getenv("TIKTOK_ACCESS_TOKEN", "")).strip()
        self.session = session or requests.Session()
        if not self.access_token:
            raise RuntimeError("TIKTOK_ACCESS_TOKEN is required")

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def submit(self, video_url: str, caption: str) -> PublishResult:
        creator = self.creator_info()
        privacy_level = os.getenv("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")
        allowed_privacy = creator.get("privacy_level_options") or []
        if privacy_level not in allowed_privacy:
            raise RuntimeError(
                f"TikTok privacy level {privacy_level} is not allowed for this creator"
            )
        response = self.session.post(
            f"{self.API_BASE}/video/init/",
            headers=self.headers,
            json={
                "post_info": {
                    "title": caption,
                    "privacy_level": privacy_level,
                    "disable_duet": os.getenv("TIKTOK_DISABLE_DUET", "false").lower() == "true",
                    "disable_comment": os.getenv("TIKTOK_DISABLE_COMMENT", "false").lower() == "true",
                    "disable_stitch": os.getenv("TIKTOK_DISABLE_STITCH", "false").lower() == "true",
                    "brand_organic_toggle": True,
                    "is_aigc": True,
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            },
            timeout=(10, 60),
        )
        response.raise_for_status()
        raw = response.json()
        error = raw.get("error") or {}
        if error.get("code") not in {None, "", "ok"}:
            raise RuntimeError(f"TikTok rejected the post: {error.get('code')}: {error.get('message', '')}")
        publish_id = str((raw.get("data") or {}).get("publish_id", ""))
        if not publish_id:
            raise RuntimeError("TikTok did not return a publish id")
        return PublishResult(publish_id, None, raw)

    def creator_info(self) -> dict:
        response = self.session.post(
            f"{self.API_BASE}/creator_info/query/",
            headers=self.headers,
            timeout=(10, 30),
        )
        response.raise_for_status()
        raw = response.json()
        error = raw.get("error") or {}
        if error.get("code") not in {None, "", "ok"}:
            raise RuntimeError(
                f"TikTok creator info failed: {error.get('code')}: {error.get('message', '')}"
            )
        return raw.get("data") or {}

    def status(self, publish_id: str) -> tuple[str, str | None]:
        response = self.session.post(
            f"{self.API_BASE}/status/fetch/",
            headers=self.headers,
            json={"publish_id": publish_id},
            timeout=(10, 30),
        )
        response.raise_for_status()
        raw = response.json()
        error = raw.get("error") or {}
        if error.get("code") not in {None, "", "ok"}:
            raise RuntimeError(f"TikTok status failed: {error.get('code')}: {error.get('message', '')}")
        data = raw.get("data") or {}
        post_ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
        post_id = str(post_ids[0]) if post_ids else None
        return str(data.get("status", "")).upper(), post_id
