import json
import os

from openai import OpenAI
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate


TRIVIA_CATEGORIES = [
    "歴史", "地理", "科学", "宇宙・天体", "生物", "人体・医学",
    "生活", "食べ物", "芸術・文化", "デザイン", "エンタメ",
    "スポーツ", "IT・テクノロジー", "心理学", "言語・言葉", "その他",
]


def generate_trivia(db: Session, topic: str, count: int) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    count = max(1, min(count, 10))
    topic = topic.strip()
    is_random = topic.lower() in {"", "ランダム", "おまかせ", "お任せ", "random"}
    topic_instruction = (
        "歴史、科学、生物、食べ物、宇宙、文化など、幅広いジャンルから"
        "互いにジャンルの異なる雑学"
        if is_random
        else f"「{topic}」に関する雑学"
    )
    existing_titles = [
        row[0]
        for row in db.query(Trivia.title).all()
        + db.query(TriviaCandidate.title).filter(TriviaCandidate.status == "pending").all()
        if row[0]
    ]
    exclusion = "\n".join(f"- {title}" for title in existing_titles[-300:])
    categories = ", ".join(TRIVIA_CATEGORIES)
    prompt = f"""
{topic_instruction}を{count}件作成してください。
出力は {{"trivia": [...]}} のJSONオブジェクトだけにしてください。

各要素:
- title: 30文字以内。内容と意外性が伝わるタイトル
- content: です・ます調、50〜80文字程度
- explanation: 根拠や背景を100〜150文字程度
- category: 次から1つ選択: {categories}
- source: 根拠を確認できるhttpまたはhttpsのURL

URLを提示できない事実は生成しないでください。同じ事実の言い換えは禁止です。
ランダム指定の場合は、可能な限り各件を異なるカテゴリにしてください。
既存または承認待ちのタイトル:
{exclusion}
"""
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
