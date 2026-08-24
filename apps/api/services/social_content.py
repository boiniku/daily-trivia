import json
import os
import re
from typing import Any

from openai import OpenAI


URL_PATTERN = re.compile(r"https?://\S+")


def x_weighted_length(text: str) -> int:
    """Close server-side guard for X's weighted 280-character limit."""
    total = 0
    position = 0
    for match in URL_PATTERN.finditer(text):
        total += _weighted_plain_text(text[position:match.start()])
        total += 23
        position = match.end()
    return total + _weighted_plain_text(text[position:])


def _weighted_plain_text(text: str) -> int:
    total = 0
    for char in text:
        codepoint = ord(char)
        is_cjk = (
            0x3000 <= codepoint <= 0x9FFF
            or 0xF900 <= codepoint <= 0xFAFF
            or 0xFF00 <= codepoint <= 0xFFEF
        )
        is_emoji = codepoint >= 0x1F000
        total += 2 if is_cjk or is_emoji else 1
    return total


def trim_for_x(text: str, limit: int = 280) -> str:
    value = (text or "").strip()
    if x_weighted_length(value) <= limit:
        return value
    suffix = "…"
    while value and x_weighted_length(value.rstrip() + suffix) > limit:
        value = value[:-1]
    return value.rstrip() + suffix


def build_social_prompt(trivia: Any) -> str:
    return f"""
次の承認済み雑学だけを根拠に、SNS投稿セットを日本語で作成してください。
元データにない数値、固有名詞、因果関係、断定を追加してはいけません。

タイトル: {trivia.title}
本文: {trivia.content}
解説: {trivia.explanation or ''}
カテゴリ: {trivia.category or 'その他'}
出典: {trivia.source or ''}

JSONオブジェクトだけを返してください。形式:
{{
  "x": {{"text": "280ウェイト以内の短い投稿。日本語は1文字を概ね2として、ハッシュタグ込みで120文字程度"}},
  "threads": {{"text": "結論、説明、最後の問いかけを含む読みやすい投稿", "topic_tag": "雑学"}},
  "instagram": {{"caption": "動画用キャプション", "hashtags": ["雑学", "毎日雑学"]}},
  "tiktok": {{"caption": "短い動画用キャプション", "hashtags": ["雑学", "豆知識"]}},
  "video": {{
    "narration": ["短いナレーション1", "短いナレーション2", "短いナレーション3"],
    "subtitles": ["短い字幕1", "短い字幕2", "短い字幕3"],
    "image_prompt": "英語の9:16イラスト生成プロンプト。文字、字幕、ロゴ、透かしは禁止",
    "visual_prompts": [
      {{"duration": 8, "prompt": "英語の9:16ドキュメンタリー映像プロンプト。文字、字幕、ロゴ、透かしは禁止"}},
      {{"duration": 8, "prompt": "英語の9:16ドキュメンタリー映像プロンプト。文字、字幕、ロゴ、透かしは禁止"}}
    ]
  }}
}}
""".strip()


def normalize_social_content(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Social content response must be an object")
    required = ("x", "threads", "instagram", "tiktok", "video")
    missing = [key for key in required if not isinstance(data.get(key), dict)]
    if missing:
        raise ValueError(f"Social content is missing sections: {', '.join(missing)}")

    data["x"]["text"] = trim_for_x(str(data["x"].get("text", "")))
    if not data["x"]["text"]:
        raise ValueError("X text is empty")
    if not str(data["threads"].get("text", "")).strip():
        raise ValueError("Threads text is empty")

    narration = [str(item).strip() for item in data["video"].get("narration", []) if str(item).strip()]
    subtitles = [str(item).strip() for item in data["video"].get("subtitles", []) if str(item).strip()]
    if not narration or not subtitles:
        raise ValueError("Video narration and subtitles are required")
    data["video"]["narration"] = narration[:5]
    data["video"]["subtitles"] = subtitles[:5]

    image_prompt = str(data["video"].get("image_prompt", "")).strip()
    if not image_prompt:
        # Backward compatibility for content generated before static videos
        # became the default.
        old_prompts = data["video"].get("visual_prompts") or []
        if old_prompts and isinstance(old_prompts[0], dict):
            image_prompt = str(old_prompts[0].get("prompt", "")).strip()
    if not image_prompt:
        raise ValueError("A static video image prompt is required")
    if "no text" not in image_prompt.lower():
        image_prompt += " No text, no subtitles, no labels, no logo, no watermark."
    data["video"]["image_prompt"] = image_prompt

    prompts = data["video"].get("visual_prompts")
    if not isinstance(prompts, list):
        prompts = []
    normalized_prompts = []
    for item in prompts[:3]:
        if not isinstance(item, dict) or not str(item.get("prompt", "")).strip():
            continue
        duration = max(4, min(int(item.get("duration", 8)), 15))
        prompt = str(item["prompt"]).strip()
        guard = " No text, no subtitles, no labels, no logo, no watermark."
        if "no text" not in prompt.lower():
            prompt += guard
        normalized_prompts.append({"duration": duration, "prompt": prompt})
    data["video"]["visual_prompts"] = normalized_prompts
    return data


def generate_social_content(trivia: Any, client: OpenAI | None = None) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if client is None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("SOCIAL_CONTENT_MODEL", "gpt-5-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You adapt already-verified Japanese trivia for social media. "
                    "Never introduce facts that are absent from the supplied record. Return JSON only."
                ),
            },
            {"role": "user", "content": build_social_prompt(trivia)},
        ],
        response_format={"type": "json_object"},
    )
    return normalize_social_content(json.loads(response.choices[0].message.content))
