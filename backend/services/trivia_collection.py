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
    "記事では",
    "記事によれば",
    "記事に掲載",
    "よく紹介され",
)

GENERIC_TOPIC_PHRASES = (
    "雑学は多い",
    "由来を持つ語が多い",
    "言葉は多い",
    "事例が多い",
    "多数ある",
    "多数あります",
    "一部の食品名",
    "地域の歴史を反映",
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

【最重要: 雑学の題材】
- 雑学サイト、まとめサイト、記事、メディアそのものを題材にしない
- 「雑学サイトで紹介されている」「記事によると」など、情報源への言及をtitle、content、explanationに書かない
- サイトの特徴、使い方、分類、人気、魅力、クイズ、ランキングを雑学として出力しない
- 検索結果一覧やサイトのトップページではなく、具体的な事実を説明している個別記事を開いて内容を確認する
- 各項目は「何についての、どのような意外な事実か」を一文で明確に説明できる題材にする
- 1候補につき、具体的な対象1つと、検証可能な事実1つだけを扱う
- 複数の事例をまとめた総論、傾向の紹介、一覧記事の要約ではなく、その中から具体的な事実を1つ選ぶ
- 「多くあります」「さまざまです」「〜ことがあります」だけで終わる広すぎる主張は採用しない
- {count}件は対象と事実が互いに異なるものにし、同じ事実の言い換えや似たネタを含めない
- テーマ指定がない場合、特定ジャンルに偏らず、同じ動物、食品、人物、天体など同一対象から選ぶのは1件までにする
- テーマ指定がない場合、{count}件のうち可能な限り異なるカテゴリを選び、3件以上なら最低3カテゴリに分ける

【最重要: タイトル】
- 30文字以内で、タイトルだけで「何についての、どんな意外な事実か」が伝わるようにする
- 事実の結論を隠さず、具体的な対象、数字、比較、意外な特徴などを簡潔に入れる
- 「〜の雑学」「〜の豆知識」「〜について」「驚きの事実」のような中身のない表現は禁止
- 疑問形、過度な煽り、根拠のない断定、事実より大げさな表現は禁止

良いタイトルの例:
- バナナは植物学ではベリーの仲間
- タコは心臓を3つ持っている
- 宇宙空間では爆発音が伝わらない

悪いタイトルの例:
- バナナの分類について
- タコに関する驚きの雑学
- 宇宙空間の特徴

【本文と解説】
- contentは50〜80文字程度のです・ます調で、雑学の要点を一読で理解できる本文にする
- explanationは100〜150文字程度で、contentの繰り返しではなく、理由、仕組み、背景、条件や例外を補足する
- contentとexplanationに改行、前置き、感想、読者への呼びかけを入れない
- 「〜といわれています」だけで済ませず、記事で確認できる範囲で何が分かっているかを具体的に書く
- explanationも情報源を紹介する文章にせず、その事実自体の理由や背景だけを書く

【出典と正確性】
- sourceには、その具体的な事実を説明している個別記事ページのhttpまたはhttps URLを入れる
- URLが確認できない題材、検索結果の抜粋だけで判断した題材、記事に書かれていない内容は採用しない
- 数値、年代、固有名詞、因果関係は記事の内容と一致させる
- 条件や例外がある事実を、常に成り立つ事実のように書かない

【独自表現】
- 元記事のタイトルや文章をコピーしない
- 元記事から事実・題材・キーワードだけを抽出する
- タイトル、本文、解説は必ず独自の日本語表現で書き直す
- Markdownや引用記号を使わず、JSONだけを返す

【採用してはいけない題材の例】
- 雑学サイトには面白い知識が多い
- 家族で楽しめる雑学クイズの魅力
- 話題まとめサイトの使い方
- 雑学系サイトの分類と活用法
- 日常語には意外な語源を持つ言葉が多い
- 食品名には地域の歴史が反映されている

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

【除外リスト】
以下は公開済みまたは承認待ちです。タイトルの完全一致だけでなく、
同じ対象について同じ事実を述べる言い換え、似た切り口、実質的に同じネタも避けてください。
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
        topic_text = " ".join((data["title"], data["content"]))
        if any(phrase in topic_text for phrase in META_TOPIC_PHRASES):
            logger.warning("Discarded meta-site trivia candidate: %s", data["title"])
            continue
        if any(phrase in topic_text for phrase in GENERIC_TOPIC_PHRASES):
            logger.warning("Discarded overly broad trivia candidate: %s", data["title"])
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
    topic = topic.strip()
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
        input=build_collection_prompt(
            topic,
            count,
            existing_titles,
        ),
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
