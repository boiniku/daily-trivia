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
    "hook_candidates": ["意外性のある冒頭案1", "疑問形の冒頭案2", "常識を覆す冒頭案3"],
    "scenes": [
      {{"duration": 2.5, "role": "hook", "narration": "最初の2秒で続きを見たくなる一言", "subtitle": "短く強い字幕", "image_prompt": "英語の9:16画像プロンプト", "motion": "zoom_in"}},
      {{"duration": 3.5, "role": "question", "narration": "答えをまだ明かさず疑問を深める", "subtitle": "疑問を示す字幕", "image_prompt": "英語の9:16画像プロンプト", "motion": "pan_left"}},
      {{"duration": 7.0, "role": "reveal", "narration": "答えと根拠を分かりやすく明かす", "subtitle": "答えの要点", "image_prompt": "英語の9:16画像プロンプト", "motion": "zoom_in"}},
      {{"duration": 6.0, "role": "payoff", "narration": "具体例と記憶に残る締め。過度なフォロー誘導は禁止", "subtitle": "覚えやすい締め", "image_prompt": "英語の9:16画像プロンプト", "motion": "pan_right"}}
    ],
    "visual_prompts": [
      {{"duration": 8, "prompt": "英語の9:16ドキュメンタリー映像プロンプト。文字、字幕、ロゴ、透かしは禁止"}},
      {{"duration": 8, "prompt": "英語の9:16ドキュメンタリー映像プロンプト。文字、字幕、ロゴ、透かしは禁止"}}
    ]
  }}
}}

動画脚本の条件:
- 全体を18〜22秒、4シーンにする
- 最初の2秒は挨拶やタイトル紹介をせず、意外な事実・矛盾・問いのいずれかから始める
- hookでは結論を全部説明せず、questionで知識の空白を作り、revealで答えを明かす
- 最後は「フォローして」だけで終わらず、誰かに出題したくなる一言や冒頭につながる言葉で締める
- 字幕は1シーン18文字程度まで。ナレーションの全文をそのまま字幕にしない
- 断定できない内容は「一説では」「といわれます」を維持する
- 4枚の画像は、完成形・疑問を表す対比・理由となる動作・印象的な結果のように役割を変える
- image_promptは英語で、9:16、同じ画風、文字・字幕・ラベル・ロゴ・透かしなしを明記する
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

    video = data["video"]
    scenes = _normalize_scenes(video.get("scenes"))
    if scenes:
        video["scenes"] = scenes
        video["narration"] = [scene["narration"] for scene in scenes]
        video["subtitles"] = [scene["subtitle"] for scene in scenes]
        video["image_prompt"] = scenes[0]["image_prompt"]
    else:
        narration = [str(item).strip() for item in video.get("narration", []) if str(item).strip()]
        subtitles = [str(item).strip() for item in video.get("subtitles", []) if str(item).strip()]
        if not narration or not subtitles:
            raise ValueError("Video narration and subtitles are required")
        video["narration"] = narration[:5]
        video["subtitles"] = subtitles[:5]

    hooks = video.get("hook_candidates")
    video["hook_candidates"] = [str(item).strip() for item in hooks or [] if str(item).strip()][:3]

    image_prompt = str(video.get("image_prompt", "")).strip()
    if not image_prompt:
        # Backward compatibility for content generated before static videos
        # became the default.
        old_prompts = video.get("visual_prompts") or []
        if old_prompts and isinstance(old_prompts[0], dict):
            image_prompt = str(old_prompts[0].get("prompt", "")).strip()
    if not image_prompt:
        raise ValueError("A static video image prompt is required")
    if "no text" not in image_prompt.lower():
        image_prompt += " No text, no subtitles, no labels, no logo, no watermark."
    video["image_prompt"] = image_prompt

    prompts = video.get("visual_prompts")
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
    video["visual_prompts"] = normalized_prompts
    return data


def _normalize_scenes(raw_scenes: Any) -> list[dict]:
    if not isinstance(raw_scenes, list) or len(raw_scenes) < 3:
        return []
    allowed_motions = {"zoom_in", "zoom_out", "pan_left", "pan_right"}
    scenes = []
    for index, item in enumerate(raw_scenes[:4]):
        if not isinstance(item, dict):
            continue
        narration = str(item.get("narration", "")).strip()
        subtitle = str(item.get("subtitle", "")).strip()
        prompt = str(item.get("image_prompt", "")).strip()
        if not narration or not subtitle or not prompt:
            continue
        if "no text" not in prompt.lower():
            prompt += " No text, no subtitles, no labels, no logo, no watermark."
        try:
            duration = float(item.get("duration", 5))
        except (TypeError, ValueError):
            duration = 5.0
        motion = str(item.get("motion", "zoom_in")).strip()
        scenes.append({
            "duration": max(2.0, min(duration, 8.0)),
            "role": str(item.get("role", f"scene_{index + 1}")).strip(),
            "narration": narration,
            "subtitle": subtitle,
            "image_prompt": prompt,
            "motion": motion if motion in allowed_motions else "zoom_in",
        })
    if len(scenes) < 3:
        return []
    total = sum(scene["duration"] for scene in scenes)
    if total < 18.0 or total > 22.0:
        target = 20.0
        for scene in scenes:
            scene["duration"] = round(scene["duration"] * target / total, 2)
    return scenes


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
