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
from PIL import Image

from models import SocialContentJob, SocialVideoJob, TriviaCandidate
from services.social_storage import upload_social_asset


LINE_API_BASE = "https://api.line.me/v2/bot/message"


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


def make_editor_token(candidate_id: int, expires_in: int = 7 * 24 * 60 * 60) -> str:
    secret = os.getenv("CANDIDATE_EDITOR_SECRET") or os.getenv("LINE_CHANNEL_SECRET", "")
    if not secret:
        raise RuntimeError("CANDIDATE_EDITOR_SECRET is not configured")
    payload = json.dumps(
        {"candidate_id": candidate_id, "exp": int(time.time()) + expires_in},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{encoded}.{encoded_signature}"


def read_editor_token(token: str) -> int:
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
        return int(payload["candidate_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid editor token") from exc


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


def social_review_messages(content_job: SocialContentJob, video_job: SocialVideoJob) -> list[dict]:
    if not video_job.final_video_url or not video_job.thumbnail_url:
        raise ValueError("A completed video and thumbnail are required for LINE review")
    content = content_job.content_json or {}
    instagram = content.get("instagram") or {}
    tiktok = content.get("tiktok") or {}
    x_content = content.get("x") or {}
    threads = content.get("threads") or {}
    video = content.get("video") or {}
    title = (content_job.trivia.title or f"動画 #{content_job.id}")[:80]
    narration = " ".join(str(item).strip() for item in video.get("narration", []) if str(item).strip())
    detail_text = (
        f"【脚本】\n{narration}\n\n"
        f"【X】\n{x_content.get('text', '')}\n\n"
        f"【Threads】\n{threads.get('text', '')}\n\n"
        f"【Instagram】\n{instagram.get('caption', '')}\n\n"
        f"【TikTok】\n{tiktok.get('caption', '')}"
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
                "承認すると、有効化済みのX・Threads・Instagram・TikTokへ投稿を開始します。"
                f"\nTikTok公開範囲: {os.getenv('TIKTOK_PRIVACY_LEVEL', 'SELF_ONLY')}"
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
                            "type": "postback",
                            "label": "承認して投稿",
                            "data": f"action=social_approve&content_job_id={content_job.id}",
                            "displayText": f"「{title}」の投稿を承認",
                        },
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": "今回は投稿しない",
                            "data": f"action=social_reject&content_job_id={content_job.id}",
                            "displayText": f"「{title}」を今回は投稿しない",
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


def push_social_review(content_job: SocialContentJob, video_job: SocialVideoJob) -> int:
    messages = social_review_messages(content_job, video_job)
    admin_ids = get_admin_user_ids()
    if not admin_ids:
        raise RuntimeError("LINE_ADMIN_USER_IDS is not configured")
    response = requests.get(video_job.thumbnail_url, timeout=(10, 30))
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as preview:
        preview = preview.convert("RGB")
        preview.thumbnail((720, 1280), Image.Resampling.LANCZOS)
        output = BytesIO()
        preview.save(output, format="JPEG", quality=78, optimize=True)
    messages[0]["previewImageUrl"] = upload_social_asset(
        output.getvalue(),
        "image/jpeg",
        "jpg",
        prefix="line-previews",
    )
    for user_id in admin_ids:
        push_message(user_id, messages)
    return len(admin_ids)
