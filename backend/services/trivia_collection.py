import json
import os
import re

from openai import OpenAI
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate
from services.trivia_generation import TRIVIA_CATEGORIES


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
Web検索を1回だけ行い、日本語の雑学・豆知識・話のネタをまとめたWebサイトから、
{subject}雑学の題材を{count}件集めてください。

目的は題材の発見です。学術論文、大学、官公庁、企業の公式解説よりも、
雑学まとめ、豆知識まとめ、話のネタ、面白い知識を扱う日本語メディアの記事を優先してください。

重要:
- 元記事のタイトルや文章をコピーしない
- 元記事から事実・題材・キーワードだけを抽出する
- タイトル、本文、解説は必ず独自の日本語表現で書き直す
- 各項目は異なる題材にする
- 既存タイトルと同じ題材を避ける
- sourceには、その題材を見つけた記事ページのURLを入れる
- 検索結果に確認できない内容は作らない
- Markdownや引用記号を使わず、JSONだけを返す

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

    response = OpenAI(api_key=api_key).responses.create(
        model=os.getenv(
            "TRIVIA_COLLECTION_MODEL",
            os.getenv("TRIVIA_GENERATION_MODEL", "gpt-5-mini"),
        ),
        tools=[tool],
        tool_choice="required",
        max_tool_calls=1,
        max_output_tokens=5000,
        input=build_collection_prompt(topic.strip(), count, existing_titles),
    )
    return parse_collection_output(response.output_text)[:count]
