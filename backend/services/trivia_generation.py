import json
import os
import random

from openai import OpenAI
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate


TRIVIA_CATEGORIES = [
    "歴史", "地理", "科学", "宇宙・天体", "生物", "人体・医学",
    "生活", "食べ物", "芸術・文化", "デザイン", "エンタメ",
    "スポーツ", "IT・テクノロジー", "心理学", "言語・言葉", "その他",
]


def build_generation_prompt(
    topic: str,
    count: int,
    exclusion: str,
    selected_categories: list[str] | None = None,
) -> str:
    topic = topic.strip()
    if selected_categories:
        category_plan = "、".join(selected_categories)
        topic_instruction = (
            f"次の{count}カテゴリから、それぞれ1件ずつ雑学を作成してください: "
            f"{category_plan}。各項目のcategoryは指定されたカテゴリにしてください。"
        )
    else:
        topic_instruction = f"「{topic}」に関する雑学を{count}件作成してください。"

    categories = ", ".join(TRIVIA_CATEGORIES)
    return f"""
{topic_instruction}
正確で意外性のある日本語の内容にしてください。
出力は {{"trivia": [...]}} のJSONオブジェクトだけにしてください。

各要素:
- title: 30文字以内。内容と意外性が伝わるタイトル
- content: です・ます調、50〜80文字程度
- explanation: 根拠や背景を100〜150文字程度
- category: 次から1つ選択: {categories}
- source: 根拠を確認できるhttpまたはhttpsのURL
- map_address: 雑学MAPに置ける具体的な住所や施設名。場所に関係しない雑学なら空文字
- map_prefecture: 都道府県。場所に関係しない雑学なら空文字
- map_latitude: 緯度。場所に関係しない雑学なら null
- map_longitude: 経度。場所に関係しない雑学なら null
- map_radius: 解放半径メートル。場所に関係しない雑学なら null。通常は500
- map_hint: 空文字

URLを提示できない事実は生成しないでください。同じ事実の言い換えは禁止です。
地名、建物、史跡、駅、観光地、地域文化など場所に紐づく雑学では、雑学MAP用の情報もできるだけ正確に入れてください。
指定されたカテゴリ同士で、題材や内容が重ならないようにしてください。
既存または承認待ちのタイトル:
{exclusion}
"""


def generate_trivia(db: Session, topic: str, count: int) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    count = max(1, min(count, 10))
    topic = topic.strip()
    is_random = topic.lower() in {"", "ランダム", "おまかせ", "お任せ", "random"}
    selected_categories = None
    if is_random:
        available_categories = [
            category for category in TRIVIA_CATEGORIES
            if category != "その他"
        ]
        selected_categories = random.sample(available_categories, count)
    existing_titles = [
        row[0]
        for row in db.query(Trivia.title).all()
        + db.query(TriviaCandidate.title).filter(TriviaCandidate.status == "pending").all()
        if row[0]
    ]
    exclusion = "\n".join(f"- {title}" for title in existing_titles[-300:])
    prompt = build_generation_prompt(
        topic,
        count,
        exclusion,
        selected_categories=selected_categories,
    )
    response = OpenAI(api_key=api_key).chat.completions.create(
        model=os.getenv("TRIVIA_GENERATION_MODEL", "gpt-5-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You create accurate Japanese trivia for a mobile app. "
                    "Return JSON only and always provide a reliable source URL."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    items = data.get("trivia", [])
    return [item for item in items if isinstance(item, dict)]
