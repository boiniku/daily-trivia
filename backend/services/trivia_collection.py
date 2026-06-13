import json
import logging
import os
import re

from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate
from services.trivia_generation import TRIVIA_CATEGORIES


logger = logging.getLogger(__name__)

META_TOPIC_PHRASES = (
    "雑学サイト",
    "まとめサイト",
    "雑学まとめ",
    "豆知識サイト",
    "サイトで紹介",
    "サイトによると",
    "サイトの分類",
    "サイトの活用",
    "サイトの使い方",
    "記事で紹介",
    "よく紹介され",
)


class CollectedTrivia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    content: str
    explanation: str
    category: str
    source: str


class TriviaCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trivia: list[CollectedTrivia]


def get_discovery_domains() -> list[str]:
    raw_domains = os.getenv("TRIVIA_DISCOVERY_DOMAINS", "")
    domains = []
    for value in raw_domains.split(","):
        domain = value.strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/", 1)[0]
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:100]


def build_collection_prompt(
    topic: str,
    count: int,
    exclusion_titles: list[str],
) -> str:
    subject = f"「{topic}」に関する" if topic else "ジャンルを限定しない"
    categories = ", ".join(TRIVIA_CATEGORIES)
    exclusions = "\n".join(f"- {title}" for title in exclusion_titles[-300:])
    return f"""
Web検索を1回だけ行い、日本語の雑学・豆知識・話のネタをまとめたWebサイトの記事から、
{subject}具体的な事実を{count}件見つけ、それぞれを独立した雑学として書いてください。

Webサイトは題材を探すための情報源にすぎません。出力対象は、記事内で紹介されている
生物、人体、自然、科学、歴史、文化、生活、食べ物などに関する具体的な事実です。
学術論文、大学、官公庁、企業の公式解説よりも、雑学・豆知識を扱う日本語の記事を
探索先として優先してください。

重要:
- 雑学サイト、まとめサイト、記事、メディアそのものを題材にしない
- 「雑学サイトで紹介されている」「記事によると」など、情報源への言及をtitle、content、explanationに書かない
- サイトの特徴、使い方、分類、人気、魅力、クイズ、ランキングを雑学として出力しない
- 検索結果一覧やサイトのトップページではなく、具体的な事実を説明している個別記事を開いて内容を確認する
- 各項目は「何についての、どのような意外な事実か」を一文で明確に説明できる題材にする
- 元記事のタイトルや文章をコピーしない
- 元記事から事実・題材・キーワードだけを抽出する
- タイトル、本文、解説は必ず独自の日本語表現で書き直す
- titleは30文字以内、contentは50〜80文字、explanationは100〜150文字程度に収める
- 各項目は異なる題材にする
- 既存タイトルと同じ題材を避ける
- sourceには、その具体的な事実を説明している個別記事ページのURLを入れる
- 検索結果に確認できない内容は作らない
- Markdownや引用記号を使わず、JSONだけを返す

良い題材の例:
- ウォンバットのフンが立方体になる
- タコの心臓は3つある
- ハチミツは適切に保存すると非常に腐りにくい

悪い題材の例:
- 雑学サイトには面白い知識が多い
- 家族で楽しめる雑学クイズの魅力
- 話題まとめサイトの使い方
- 雑学系サイトの分類と活用法

出力形式:
{{
  "trivia": [
    {{
      "title": "独自に作成した30文字以内のタイトル",
      "content": "独自に作成した50〜80文字程度の本文",
      "explanation": "独自に作成した100〜150文字程度の解説",
      "category": "{categories}のいずれか",
      "source": "題材を発見した記事のURL"
    }}
  ]
}}

既存または承認待ちのタイトル:
{exclusions}
"""


def parse_collection_output(output_text: str) -> list[dict]:
    text = (output_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Web収集結果をJSONとして読み取れませんでした") from exc
        data = json.loads(text[start:end + 1])

    items = data.get("trivia", [])
    if not isinstance(items, list):
        return []
    return [
        item for item in items
        if isinstance(item, dict)
        and (item.get("title") or "").strip()
        and (item.get("content") or "").strip()
        and (item.get("source") or "").strip().startswith(("http://", "https://"))
    ]


def validate_collected_items(items: list[CollectedTrivia]) -> list[dict]:
    valid_items = []
    for item in items:
        data = item.model_dump()
        combined_text = " ".join(
            (data["title"], data["content"], data["explanation"])
        )
        if any(phrase in combined_text for phrase in META_TOPIC_PHRASES):
            logger.warning("Discarded meta-site trivia candidate: %s", data["title"])
            continue
        if data["category"] not in TRIVIA_CATEGORIES:
            data["category"] = "その他"
        if (
            data["title"].strip()
            and data["content"].strip()
            and data["source"].strip().startswith(("http://", "https://"))
        ):
            valid_items.append(data)
    return valid_items


def get_incomplete_reason(response) -> str:
    status = getattr(response, "status", None)
    if status != "incomplete":
        return ""
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    if not reason and isinstance(details, dict):
        reason = details.get("reason")
    if reason == "max_output_tokens":
        return "収集結果が長すぎて途中で切れました。件数を減らして再実行してください"
    return f"収集処理が完了しませんでした: {reason or 'unknown'}"


def collect_trivia(db: Session, topic: str, count: int) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    count = max(1, min(count, 10))
    existing_titles = [
        row[0]
        for row in db.query(Trivia.title).all()
        + db.query(TriviaCandidate.title).filter(TriviaCandidate.status == "pending").all()
        if row[0]
    ]
    tool = {
        "type": "web_search",
        "search_context_size": "low",
        "user_location": {
            "type": "approximate",
            "country": "JP",
            "timezone": "Asia/Tokyo",
        },
    }
    domains = get_discovery_domains()
    if domains:
        tool["filters"] = {"allowed_domains": domains}

    response = OpenAI(api_key=api_key).responses.parse(
        model=os.getenv(
            "TRIVIA_COLLECTION_MODEL",
            os.getenv("TRIVIA_GENERATION_MODEL", "gpt-5-mini"),
        ),
        tools=[tool],
        tool_choice="required",
        max_tool_calls=1,
        max_output_tokens=16000,
        reasoning={"effort": "low"},
        text_format=TriviaCollectionResult,
        input=build_collection_prompt(topic.strip(), count, existing_titles),
    )
    incomplete_reason = get_incomplete_reason(response)
    if incomplete_reason:
        raise RuntimeError(incomplete_reason)
    if not (response.output_text or "").strip():
        raise RuntimeError("Web収集結果が空でした。もう一度実行してください")
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        logger.error(
            "Web collection parse failed: status=%s output=%r",
            getattr(response, "status", None),
            (response.output_text or "")[:1000],
        )
        raise RuntimeError(
            "Web収集結果を構造化できませんでした。件数を減らして再実行してください"
        )
    return validate_collected_items(parsed.trivia)[:count]
