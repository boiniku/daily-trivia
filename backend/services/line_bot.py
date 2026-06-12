import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from urllib.parse import urlencode

import requests

from models import TriviaCandidate


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
        actual = base64.urlsafe_b64decode(_pad_base64(encoded_signature))
        if not hmac.compare_digest(expected, actual):
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
                "contents": [
                    {"type": "text", "text": candidate.title or "無題", "weight": "bold", "size": "lg", "wrap": True},
                    {"type": "text", "text": candidate.content or "", "wrap": True, "size": "sm"},
                    {"type": "text", "text": candidate.explanation or "", "wrap": True, "size": "xs", "color": "#666666"},
                    {"type": "text", "text": f"{candidate.category or 'その他'} / #{candidate.id}", "size": "xs", "color": "#888888"},
                    {"type": "text", "text": candidate.source or "出典なし", "size": "xxs", "color": "#888888", "wrap": True},
                ],
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
                            "label": "公開する",
                            "data": f"action=approve&candidate_id={candidate.id}",
                            "displayText": f"「{candidate.title}」を公開",
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


def new_candidate_message() -> dict:
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    url = (
        f"{public_base_url}/admin/candidates/new?"
        f"{urlencode({'token': make_editor_token(0)})}"
    )
    return {
        "type": "template",
        "altText": "新しい雑学を手入力",
        "template": {
            "type": "buttons",
            "title": "新しい雑学",
            "text": "スマホで文章と画像を入力できます。",
            "actions": [{"type": "uri", "label": "登録フォームを開く", "uri": url}],
        },
    }


def mark_line_sent(candidate: TriviaCandidate) -> None:
    candidate.line_sent_at = datetime.utcnow()
