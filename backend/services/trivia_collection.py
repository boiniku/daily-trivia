import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate
from services.trivia_candidates import create_candidates, find_duplicate
from services.trivia_generation import TRIVIA_CATEGORIES


logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_DOMAINS: tuple[str, ...] = ()
DEFAULT_MAX_SEARCH_CALLS = 5
VALID_SEARCH_CONTEXT_SIZES = {"low", "medium", "high"}

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

SUBJECT_ALIASES = {
    "目": ("目", "眼", "眼球", "瞳", "視覚", "網膜", "角膜", "虹彩"),
}


class CollectedTrivia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_key: str
    title: str
    content: str
    explanation: str
    category: str
    source: str
    map_address: str = ""
    map_prefecture: str = ""
    map_latitude: float | None = None
    map_longitude: float | None = None
    map_radius: int | None = None
    map_hint: str = ""


class TriviaCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trivia: list[CollectedTrivia]


@dataclass(frozen=True)
class TriviaCollectionUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    web_search_calls: int = 0


def get_collection_usage(response) -> TriviaCollectionUsage:
    usage = getattr(response, "usage", None)
    output = getattr(response, "output", None) or []
    search_calls = sum(
        1
        for item in output
        if (
            getattr(item, "type", None)
            or (item.get("type") if isinstance(item, dict) else None)
        ) == "web_search_call"
    )
    return TriviaCollectionUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        web_search_calls=search_calls,
    )


def get_discovery_domains() -> list[str]:
    raw_domains = os.getenv("TRIVIA_DISCOVERY_DOMAINS")
    if raw_domains is None:
        return list(DEFAULT_DISCOVERY_DOMAINS)

    domains = []
    for value in raw_domains.split(","):
        domain = value.strip().lower()
        domain = re.sub(r"^https?://", "", domain).split("/", 1)[0]
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:100]


def get_max_search_calls() -> int:
    raw_value = os.getenv("TRIVIA_MAX_SEARCH_CALLS", "")
    try:
        value = int(raw_value)
    except ValueError:
        value = DEFAULT_MAX_SEARCH_CALLS
    return max(1, min(value or DEFAULT_MAX_SEARCH_CALLS, 10))


def get_search_context_size() -> str:
    value = os.getenv("TRIVIA_SEARCH_CONTEXT_SIZE", "medium").strip().lower()
    return value if value in VALID_SEARCH_CONTEXT_SIZES else "medium"


def build_collection_prompt(
    topic: str,
    count: int,
    exclusion_titles: list[str],
    output_count: int | None = None,
    max_search_calls: int = DEFAULT_MAX_SEARCH_CALLS,
    map_mode: bool = False,
    existing_facts: list[str] | None = None,
) -> str:
    output_count = output_count or count
    subject = f"「{topic}」に関する" if topic else "ジャンルを限定しない"
    categories = ", ".join(TRIVIA_CATEGORIES)
    exclusions = "\n".join(f"- {title}" for title in exclusion_titles)
    fact_exclusions = "\n".join(f"- {fact}" for fact in (existing_facts or []))
    map_focus = ""
    if map_mode:
        map_focus = f"""
【地図用収集モード】
- 今回は雑学MAPへ登録する候補だけを集める
- 地名、建物、史跡、駅、橋、公園、神社仏閣、城跡、観光地、地域文化、特定の店や施設など、現地に行ける具体的な場所に紐づく雑学だけを採用する
- 場所に紐づかない生物・科学・言葉・食べ物などの一般雑学は、どれだけ面白くても採用しない
- map_address、map_prefecture、map_latitude、map_longitude、map_radiusは全件必ず入れる
- map_addressは施設名だけでなく、可能なら住所や「施設名 / 住所」の形にする
- map_latitude/map_longitudeは代表地点の座標を数値で入れる。分からない地点は採用しない
- {output_count}件は都道府県、施設、史跡、地域文化などが互いに偏りすぎないようにする
"""
    return f"""
Web検索を最大{max_search_calls}回まで行い、Web上の個別ページから、
{subject}具体的な事実を{output_count}件見つけ、それぞれを独立した雑学として書いてください。
最初の検索だけで決めず、必要に応じて検索語や切り口を変えて複数回探してください。
十分に良い候補が集まった時点で検索を止め、回数を使い切る必要はありません。

【必須の検索手順】
- モデルの内部知識だけで題材、理由、例外、因果関係を作らない。出力する全候補について必ずWeb検索結果の個別ページを開く
- まず雑学・豆知識サイトなどから意外な起点となる事実を探す
- 起点となる事実を見つけたら「なぜそうなったのか」「例外はあるか」「一見矛盾する事例はないか」「名称・商標・制度・歴史とどう繋がるか」のうち、最も面白くなる問いを1つ立て、その答えを追加検索する
- 例: 「宅急便は商標」で止めず、「それなら『魔女の宅急便』でなぜ使えるのか」を検索する。検索ページで理由まで確認できた場合だけ候補にする
- 検索で直接確認できなかった推測や、一般知識から補った説明は出力しない
- 検索結果のスニペットだけで判断せず、最終的な主張を直接説明する個別ページを確認する
- 1段目の事実だけよりも、2段目の理由・例外・意外な繋がりまで確認できた候補を優先する

題材発見には雑学サイトも使えます。深掘りと検証には、企業・団体の公式ページ、官公庁、
大学・研究機関、博物館、専門メディアなど、その主張を直接確認できる情報源を優先してください。
出力対象は、生物、人体、自然、科学、歴史、文化、生活、食べ物などに関する具体的な事実です。
日常会話で誰かに話したくなる意外性と分かりやすさを重視してください。

【最重要: 雑学の題材】
- 雑学サイト、まとめサイト、記事、メディアそのものを題材にしない
- 「雑学サイトで紹介されている」「記事によると」など、情報源への言及をtitle、content、explanationに書かない
- サイトの特徴、使い方、分類、人気、魅力、クイズ、ランキングを雑学として出力しない
- 検索結果一覧やサイトのトップページではなく、具体的な事実を説明している個別記事を開いて内容を確認する
- 各項目は「何についての、どのような意外な事実か」を一文で明確に説明できる題材にする
- 1候補につき、具体的な対象1つと、検証可能な事実1つだけを扱う
- 複数の事例をまとめた総論、傾向の紹介、一覧記事の要約ではなく、その中から具体的な事実を1つ選ぶ
- 「多くあります」「さまざまです」「〜ことがあります」だけで終わる広すぎる主張は採用しない
- {output_count}件は対象と事実が互いに異なるものにし、同じ事実の言い換えや似たネタを含めない
- テーマ指定がない場合、特定ジャンルに偏らず、同じ動物、食品、人物、天体など同一対象から選ぶのは1件までにする
- テーマ指定がない場合、{output_count}件のうち可能な限り異なるカテゴリを選び、3件以上なら最低3カテゴリに分ける
- subject_keyには中心対象を短い一般名詞で1つだけ入れる。例: 目、タコ、金星、ハチミツ、江戸時代
- 目・視覚・瞳・眼球のように実質同じ対象は、同じsubject_key「目」に統一する
{map_focus}

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
- explanationは100〜180文字程度で、contentの繰り返しではなく、追加検索で確認した理由、仕組み、背景、条件、例外、一見矛盾する事例との繋がりを補足する
- 深掘りで面白さが増す題材では、contentに起点となる意外な事実、explanationに「なぜ／どうして可能か」の答えを書く
- contentとexplanationに改行、前置き、感想、読者への呼びかけを入れない
- 「〜といわれています」だけで済ませず、記事で確認できる範囲で何が分かっているかを具体的に書く
- explanationも情報源を紹介する文章にせず、その事実自体の理由や背景だけを書く

【出典と正確性】
- sourceには、最終的な深掘り内容を直接説明している個別ページのhttpまたはhttps URLを入れる
- 公式ページ、官公庁、大学・研究機関、博物館、信頼できる専門メディアがあれば優先する
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
      "subject_key": "中心対象を表す短い一般名詞",
      "title": "独自に作成した30文字以内のタイトル",
      "content": "独自に作成した50〜80文字程度の本文",
      "explanation": "追加検索した理由や意外な繋がりを含む100〜180文字程度の解説",
      "category": "{categories}のいずれか",
      "source": "題材を発見した記事のURL",
      "map_address": "雑学MAPに置ける具体的な住所や施設名。場所に関係しない雑学なら空文字",
      "map_prefecture": "都道府県。場所に関係しない雑学なら空文字",
      "map_latitude": 35.6812,
      "map_longitude": 139.7671,
      "map_radius": 300,
      "map_hint": ""
    }}
  ]
}}

【雑学MAP用情報】
- 地名、建物、史跡、駅、観光地、地域文化など場所に紐づく雑学では、map_address/map_prefecture/map_latitude/map_longitude/map_radiusをできるだけ入れる
- 場所に関係しない雑学では、map_address/map_prefecture/map_hintは空文字、map_latitude/map_longitude/map_radiusはnullにする
- map_addressはユーザーが現地へ向かえる具体的な施設名や住所にする
- 緯度経度はその地点の代表座標にする
- map_radiusは通常300、広い公園や城跡などは500〜800にする
{"- 地図用収集モードでは、場所情報が欠ける候補は出力しない" if map_mode else ""}

【除外リスト】
以下はデータベースにある公開済みまたは承認待ちの雑学です。新しい候補を考える前に必ず照合してください。
タイトルの完全一致だけでなく、
同じ対象について同じ事実を述べる言い換え、似た切り口、実質的に同じネタも避けてください。
{exclusions}

【既存雑学の本文要約（直近最大300件）】
タイトルが違っても、以下と中心事実が同じ候補は出力しないでください。
{fact_exclusions}
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
        if not is_valid_collected_item(item):
            continue
        data = item.model_dump()
        if data["category"] not in TRIVIA_CATEGORIES:
            data["category"] = "その他"
        data.pop("subject_key", None)
        if (
            data["title"].strip()
            and data["content"].strip()
            and data["source"].strip().startswith(("http://", "https://"))
        ):
            valid_items.append(data)
    return valid_items


def has_complete_map_fields(item: CollectedTrivia) -> bool:
    return bool(
        item.map_address.strip()
        and item.map_prefecture.strip()
        and item.map_latitude is not None
        and item.map_longitude is not None
        and item.map_radius is not None
    )


def is_valid_collected_item(item: CollectedTrivia) -> bool:
    topic_text = " ".join((item.title, item.content))
    if any(phrase in topic_text for phrase in META_TOPIC_PHRASES):
        logger.warning("Discarded meta-site trivia candidate: %s", item.title)
        return False
    if any(phrase in topic_text for phrase in GENERIC_TOPIC_PHRASES):
        logger.warning("Discarded overly broad trivia candidate: %s", item.title)
        return False
    return (
        bool(item.title.strip())
        and bool(item.content.strip())
        and item.source.strip().startswith(("http://", "https://"))
    )


def remove_existing_duplicates(
    db: Session,
    items: list[CollectedTrivia],
) -> tuple[list[CollectedTrivia], list[str]]:
    novel_items = []
    duplicate_titles = []
    for item in items:
        if not is_valid_collected_item(item):
            continue
        duplicate = find_duplicate(
            db,
            title=item.title,
            content=item.content,
            source=item.source,
        )
        if duplicate:
            logger.info("Discarded collected duplicate %r: %s", item.title, duplicate)
            duplicate_titles.append(item.title)
            continue
        novel_items.append(item)
    return novel_items, duplicate_titles


def select_diverse_items(
    items: list[CollectedTrivia],
    count: int,
) -> list[CollectedTrivia]:
    selected = []
    used_subjects = set()
    category_counts = {}

    # First pass: maximize category variety.
    for item in items:
        subject = normalize_subject_key(item.subject_key)
        if (
            not subject
            or subject in used_subjects
            or category_counts.get(item.category, 0) >= 1
        ):
            continue
        selected.append(item)
        used_subjects.add(subject)
        category_counts[item.category] = category_counts.get(item.category, 0) + 1
        if len(selected) == count:
            return selected

    # Second pass: allow a second item per category, but never the same subject.
    for item in items:
        subject = normalize_subject_key(item.subject_key)
        if (
            not subject
            or subject in used_subjects
            or item in selected
            or category_counts.get(item.category, 0) >= 2
        ):
            continue
        selected.append(item)
        used_subjects.add(subject)
        category_counts[item.category] = category_counts.get(item.category, 0) + 1
        if len(selected) == count:
            break
    return selected


def normalize_subject_key(value: str) -> str:
    normalized = re.sub(r"[\W_]+", "", (value or "").lower())
    for canonical, aliases in SUBJECT_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return canonical
    return normalized


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


def collect_trivia(
    db: Session,
    topic: str,
    count: int,
    map_mode: bool = False,
    usage_callback: Callable[[TriviaCollectionUsage], None] | None = None,
) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    count = max(1, min(count, 10))
    topic = topic.strip()
    output_count = min(10, count * 2) if not topic else count
    existing_rows = (
        db.query(Trivia.title, Trivia.content).order_by(Trivia.id.asc()).all()
        + db.query(TriviaCandidate.title, TriviaCandidate.content)
        .filter(TriviaCandidate.status == "pending")
        .order_by(TriviaCandidate.id.asc())
        .all()
    )
    existing_titles = [row[0] for row in existing_rows if row[0]]
    existing_facts = [
        f"{title}: {re.sub(r'\\s+', ' ', content or '').strip()[:160]}"
        for title, content in existing_rows[-300:]
        if title
    ]
    tool = {
        "type": "web_search",
        "search_context_size": get_search_context_size(),
        "user_location": {
            "type": "approximate",
            "country": "JP",
            "timezone": "Asia/Tokyo",
        },
    }
    domains = get_discovery_domains()
    if domains:
        tool["filters"] = {"allowed_domains": domains}

    max_search_calls = get_max_search_calls()
    response = OpenAI(api_key=api_key).responses.parse(
        model=os.getenv(
            "TRIVIA_COLLECTION_MODEL",
            os.getenv("TRIVIA_GENERATION_MODEL", "gpt-5-mini"),
        ),
        tools=[tool],
        tool_choice="required",
        max_tool_calls=max_search_calls,
        max_output_tokens=16000,
        reasoning={"effort": "low"},
        text_format=TriviaCollectionResult,
        input=build_collection_prompt(
            topic,
            count,
            existing_titles,
            output_count=output_count,
            max_search_calls=max_search_calls,
            map_mode=map_mode,
            existing_facts=existing_facts,
        ),
    )
    if usage_callback:
        usage_callback(get_collection_usage(response))
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

    source_items = parsed.trivia
    if map_mode:
        source_items = [item for item in source_items if has_complete_map_fields(item)]
    novel_items, _ = remove_existing_duplicates(db, source_items)
    if not topic:
        novel_items = select_diverse_items(novel_items, count)
    return validate_collected_items(novel_items)[:count]


def collect_trivia_candidates(
    db: Session,
    topic: str,
    count: int,
    map_mode: bool = False,
    usage_callback: Callable[[TriviaCollectionUsage], None] | None = None,
) -> list[TriviaCandidate]:
    """Run the shared web collection workflow and persist its review candidates."""
    items = collect_trivia(
        db,
        topic=topic,
        count=count,
        map_mode=map_mode,
        usage_callback=usage_callback,
    )
    return create_candidates(db, items)
