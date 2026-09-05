import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import urlencode

import requests
from PIL import Image, ImageOps

from models import SocialContentJob, SocialVideoJob, TriviaCandidate
from services.social_storage import upload_social_asset


LINE_API_BASE = "https://api.line.me/v2/bot/message"
SOCIAL_TEXT_REVIEW_MESSAGE_VERSION = 3


def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.getenv("LINE_CHANNEL_SECRET", "").encode("utf-8")
    if not secret or not signature:
        return False
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def is_allowed_user(user_id: str) -> bool:
    configured = os.getenv("LINE_ADMIN_USER_IDS", "")
    allowed = {value.strip() for value in configured.split(",") if value.strip()}
    return bool(user_id and user_id in allowed)


def reply_message(reply_token: str, messages: list[dict]) -> None:
    _send("reply", {"replyToken": reply_token, "messages": messages})


def push_message(user_id: str, messages: list[dict]) -> None:
    _send("push", {"to": user_id, "messages": messages})


def get_admin_user_ids() -> list[str]:
    configured = os.getenv("LINE_ADMIN_USER_IDS", "")
    return list(dict.fromkeys(
        value.strip() for value in configured.split(",") if value.strip()
    ))


def _send(endpoint: str, payload: dict) -> None:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is not configured")
    response = requests.post(
        f"{LINE_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


def _make_editor_token(payload: dict, expires_in: int) -> str:
    secret = os.getenv("CANDIDATE_EDITOR_SECRET") or os.getenv("LINE_CHANNEL_SECRET", "")
    if not secret:
        raise RuntimeError("CANDIDATE_EDITOR_SECRET is not configured")
    encoded_payload = json.dumps(
        {**payload, "exp": int(time.time()) + expires_in},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(encoded_payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{encoded}.{encoded_signature}"


def _read_editor_token(token: str) -> dict:
    secret = os.getenv("CANDIDATE_EDITOR_SECRET") or os.getenv("LINE_CHANNEL_SECRET", "")
    if not secret:
        raise ValueError("Editor secret is not configured")
    try:
        encoded, encoded_signature = token.split(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        expected_signature = base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")
        if not hmac.compare_digest(expected_signature, encoded_signature):
            raise ValueError("Invalid editor token")
        payload = json.loads(base64.urlsafe_b64decode(_pad_base64(encoded)))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("Editor token has expired")
        return payload
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid editor token") from exc


def make_editor_token(candidate_id: int, expires_in: int = 7 * 24 * 60 * 60) -> str:
    return _make_editor_token({"candidate_id": candidate_id}, expires_in)


def read_editor_token(token: str) -> int:
    try:
        return int(_read_editor_token(token)["candidate_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid editor token") from exc


def make_social_editor_token(
    content_job_id: int,
    expires_in: int = 7 * 24 * 60 * 60,
) -> str:
    return _make_editor_token({"social_content_job_id": content_job_id}, expires_in)


def read_social_editor_token(token: str) -> int:
    try:
        return int(_read_editor_token(token)["social_content_job_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid social editor token") from exc


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)


def candidate_flex_message(candidate: TriviaCandidate) -> dict:
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    editor_url = (
        f"{public_base_url}/admin/candidates/{candidate.id}/edit?"
        f"{urlencode({'token': make_editor_token(candidate.id)})}"
    )
    body_contents = [
        {"type": "text", "text": candidate.title or "無題", "weight": "bold", "size": "lg", "wrap": True},
        {"type": "text", "text": candidate.content or "", "wrap": True, "size": "sm"},
        {"type": "text", "text": candidate.explanation or "", "wrap": True, "size": "xs", "color": "#666666"},
        {"type": "text", "text": f"{candidate.category or 'その他'} / #{candidate.id}", "size": "xs", "color": "#888888"},
    ]
    if candidate.map_address or candidate.map_prefecture:
        location_text = f"MAP: {candidate.map_prefecture or ''} {candidate.map_address or ''}".strip()
        if candidate.map_latitude is not None and candidate.map_longitude is not None:
            location_text += f" ({candidate.map_latitude:.5f}, {candidate.map_longitude:.5f})"
        body_contents.append({"type": "text", "text": location_text, "size": "xxs", "color": "#2563eb", "wrap": True})
    body_contents.append({"type": "text", "text": candidate.source or "出典なし", "size": "xxs", "color": "#888888", "wrap": True})
    has_complete_map = bool(
        candidate.map_address
        and candidate.map_prefecture
        and candidate.map_latitude is not None
        and candidate.map_longitude is not None
        and candidate.map_radius is not None
    )
    approve_label = "MAP公開する" if has_complete_map else "公開する"
    approve_display = (
        f"「{candidate.title}」をMAP公開"
        if has_complete_map
        else f"「{candidate.title}」を公開"
    )
    return {
        "type": "flex",
        "altText": f"承認待ち: {candidate.title}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": body_contents,
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#1DB446",
                        "action": {
                            "type": "postback",
                            "label": approve_label,
                            "data": f"action=approve&candidate_id={candidate.id}",
                            "displayText": approve_display,
                        },
                    },
                    {"type": "button", "action": {"type": "uri", "label": "編集する", "uri": editor_url}},
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "却下する",
                            "data": f"action=reject&candidate_id={candidate.id}",
                            "displayText": f"「{candidate.title}」を却下",
                        },
                    },
                ],
            },
        },
    }


def candidate_carousel_message(candidates: list[TriviaCandidate]) -> dict:
    bubbles = [candidate_flex_message(candidate)["contents"] for candidate in candidates[:10]]
    if not bubbles:
        raise ValueError("At least one candidate is required")
    return {
        "type": "flex",
        "altText": f"承認待ちの雑学候補 {len(bubbles)}件",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def new_candidate_message(map_mode: bool = False) -> dict:
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    query = {"token": make_editor_token(0)}
    if map_mode:
        query["map"] = "1"
    url = (
        f"{public_base_url}/admin/candidates/new?"
        f"{urlencode(query)}"
    )
    title = "新しい地図用雑学" if map_mode else "新しい雑学"
    text = (
        "住所・都道府県・緯度経度も入力できます。"
        if map_mode
        else "スマホで文章と画像を入力できます。"
    )
    label = "地図用フォームを開く" if map_mode else "登録フォームを開く"
    return {
        "type": "template",
        "altText": title,
        "template": {
            "type": "buttons",
            "title": title,
            "text": text,
            "actions": [{"type": "uri", "label": label, "uri": url}],
        },
    }


def mark_line_sent(candidate: TriviaCandidate) -> None:
    candidate.line_sent_at = datetime.utcnow()


def _manual_caption(section: dict) -> str:
    caption = str(section.get("caption") or "").strip()
    hashtags = []
    for item in section.get("hashtags") or []:
        value = str(item).strip().lstrip("#")
        if value and f"#{value}" not in caption:
            hashtags.append(f"#{value}")
    return " ".join(part for part in (caption, " ".join(hashtags)) if part).strip()


def _youtube_handoff(content_job: SocialContentJob, content: dict) -> tuple[str, str]:
    youtube = content.get("youtube") or {}
    video = content.get("video") or {}
    fallback_narration = " ".join(
        str(item).strip() for item in video.get("narration", []) if str(item).strip()
    )
    title = str(youtube.get("title") or content_job.trivia.title).strip()[:100]
    description = str(youtube.get("description") or fallback_narration).strip()
    hashtags = []
    for item in [*(youtube.get("hashtags") or []), "Shorts", "雑学", "毎日雑学"]:
        value = str(item).strip().lstrip("#")
        if value and value not in hashtags and f"#{value}" not in description:
            hashtags.append(value)
    suffix = " ".join(f"#{item}" for item in hashtags[:5])
    return title, "\n\n".join(part for part in (description, suffix) if part).strip()


def social_review_messages(content_job: SocialContentJob, video_job: SocialVideoJob) -> list[dict]:
    if not video_job.final_video_url or not video_job.thumbnail_url:
        raise ValueError("A completed video and thumbnail are required for LINE review")
    content = content_job.content_json or {}
    instagram = content.get("instagram") or {}
    tiktok = content.get("tiktok") or {}
    video = content.get("video") or {}
    youtube_title, youtube_description = _youtube_handoff(content_job, content)
    title = (content_job.trivia.title or f"動画 #{content_job.id}")[:80]
    narration = " ".join(str(item).strip() for item in video.get("narration", []) if str(item).strip())
    detail_text = (
        f"【脚本】\n{narration}\n\n"
        f"【Instagram Reels】\n{_manual_caption(instagram)}\n\n"
        f"【TikTok】\n{_manual_caption(tiktok)}\n\n"
        f"【YouTube Shorts タイトル】\n{youtube_title}\n\n"
        f"【YouTube Shorts 概要欄】\n{youtube_description}"
    )[:5000]
    body = [
        {"type": "text", "text": title, "weight": "bold", "size": "lg", "wrap": True},
        {
            "type": "text",
            "text": f"動画完成（{video_job.duration_seconds or 0:.1f}秒）",
            "size": "sm",
            "wrap": True,
            "color": "#555555",
        },
        {
            "type": "text",
            "text": (
                "動画と投稿文を確認し、Instagram・TikTok・YouTube Shortsへ手動で投稿してください。"
                "投稿文は次のLINEメッセージを長押ししてコピーできます。"
            ),
            "size": "xs",
            "wrap": True,
            "color": "#888888",
        },
    ]


    card = {
        "type": "flex",
        "altText": f"動画の投稿確認: {title}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": body},
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#1DB446",
                        "action": {
                            "type": "uri",
                            "label": "動画を開く",
                            "uri": video_job.final_video_url,
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "uri",
                            "label": "サムネイルを開く",
                            "uri": video_job.thumbnail_url,
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "確認済みにする",
                            "data": f"action=social_approve&content_job_id={content_job.id}",
                            "displayText": f"「{title}」の動画を確認済みにしました",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "今回は使わない",
                            "data": f"action=social_reject&content_job_id={content_job.id}",
                            "displayText": f"「{title}」を今回は使わない",
                        },
                    },
                ],
            },
        },
    }
    return [
        {
            "type": "video",
            "originalContentUrl": video_job.final_video_url,
            "previewImageUrl": video_job.thumbnail_url,
            "trackingId": f"social-{content_job.id}-{video_job.id}",
        },
        {"type": "text", "text": detail_text},
        card,
    ]


def social_text_review_messages(content_job: SocialContentJob, image_url: str) -> list[dict]:
    content = content_job.content_json or {}
    text = str((content.get("x") or {}).get("text") or "").strip()
    reply_text = str((content.get("x") or {}).get("reply_text") or "").strip()
    if not text or not image_url:
        raise ValueError("Text and image are required for LINE review")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    editor_url = (
        f"{public_base_url}/admin/social/{content_job.id}/edit?"
        f"{urlencode({'token': make_social_editor_token(content_job.id)})}"
    )
    title = (content_job.trivia.title or f"投稿案 #{content_job.id}")[:80]
    detail = f"【X投稿案】\n{text}"
    if reply_text:
        detail += f"\n\n【投稿後のリプライ】\n{reply_text}"
    card = {
        "type": "flex",
        "altText": f"X投稿の確認: {title}",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold", "size": "lg", "wrap": True},
                    {
                        "type": "text",
                        "text": "文章と画像を確認してください。承認するとXへ投稿します。",
                        "size": "sm",
                        "wrap": True,
                        "color": "#555555",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "uri",
                            "label": "文章を編集",
                            "uri": editor_url,
                        },
                    },
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#1DB446",
                        "action": {
                            "type": "postback",
                            "label": "Xへ投稿",
                            "data": f"action=social_approve&content_job_id={content_job.id}",
                            "displayText": f"「{title}」をXへ投稿します",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "今回は使わない",
                            "data": f"action=social_reject&content_job_id={content_job.id}",
                            "displayText": f"「{title}」を今回は使わない",
                        },
                    },
                ],
            },
        },
    }
    return [
        {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url},
        {"type": "text", "text": detail[:5000]},
        card,
    ]


def push_social_text_review(content_job: SocialContentJob) -> int:
    source_url = str(
        ((content_job.content_json or {}).get("shared_image") or {}).get("url") or ""
    ).strip()
    if not source_url:
        raise ValueError("A public image is required for LINE review")
    response = requests.get(source_url, timeout=(10, 30))
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
    line_image_url = upload_social_asset(
        output.getvalue(), "image/jpeg", "jpg", prefix="line-text-previews"
    )
    messages = social_text_review_messages(content_job, line_image_url)
    admin_ids = get_admin_user_ids()
    if not admin_ids:
        raise RuntimeError("LINE_ADMIN_USER_IDS is not configured")
    for user_id in admin_ids:
        push_message(user_id, messages)
    return len(admin_ids)


def push_social_review(content_job: SocialContentJob, video_job: SocialVideoJob) -> int:
    messages = social_review_messages(content_job, video_job)
    admin_ids = get_admin_user_ids()
    if not admin_ids:
        raise RuntimeError("LINE_ADMIN_USER_IDS is not configured")
    response = requests.get(video_job.thumbnail_url, timeout=(10, 30))
    response.raise_for_status()
    preview_data = make_line_video_preview(response.content)
    messages[0]["previewImageUrl"] = upload_social_asset(
        preview_data,
        "image/jpeg",
        "jpg",
        prefix="line-previews",
    )
    for user_id in admin_ids:
        push_message(user_id, messages)
    return len(admin_ids)


def make_line_video_preview(image_data: bytes) -> bytes:
    """Create the exact 9:16 preview ratio required by LINE video messages."""
    with Image.open(BytesIO(image_data)) as source:
        preview = ImageOps.fit(
            source.convert("RGB"),
            (720, 1280),
            method=Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        preview.save(output, format="JPEG", quality=78, optimize=True)
        return output.getvalue()
