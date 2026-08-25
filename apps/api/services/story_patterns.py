import re


STORY_PATTERNS = {
    "classic_reveal": {
        "roles": ("hook", "question", "reveal", "payoff"),
        "durations": (2.5, 3.5, 7.0, 6.0),
        "direction": "対象を明記した引き→疑問を深める→答え→意味を言い直す",
    },
    "misconception_reversal": {
        "roles": ("hook", "misconception", "reveal", "reason", "payoff"),
        "durations": (2.5, 3.0, 4.0, 6.0, 4.0),
        "direction": "よくある勘違いを具体的に示す→一度信じさせる→短く反転→理由→新しい見方",
    },
    "quiz_reveal": {
        "roles": ("hook", "choices", "tension", "reveal", "payoff"),
        "durations": (2.5, 3.5, 3.0, 6.0, 4.0),
        "direction": "答えられそうな具体的な問い→短い選択肢→考える余白→答えと根拠→記憶用の一言",
    },
    "origin_story": {
        "roles": ("hook", "assumption", "origin", "context", "payoff"),
        "durations": (2.5, 3.0, 5.0, 5.5, 4.0),
        "direction": "身近な名前を提示→普通の推測→本当の由来→背景→次に見た時の見方",
    },
    "mechanism": {
        "roles": ("hook", "question", "mechanism", "consequence", "payoff"),
        "durations": (2.5, 3.0, 6.0, 5.0, 4.0),
        "direction": "目に見える現象→なぜかを問う→仕組み→その結果→一文で腹落ち",
    },
}


def select_story_pattern(research: dict) -> str:
    text = " ".join(
        str(research.get(key, ""))
        for key in ("subject", "verified_fact", "explanation", "supporting_details")
    )
    misconception = str(research.get("common_misconception", "")).strip()
    if re.search(r"由来|語源|名前|呼ばれ", text):
        return "origin_story"
    if misconception and misconception not in {"なし", "特になし", "不明"}:
        return "misconception_reversal"
    if re.search(r"なぜ|ため|仕組み|働き|機能|構造", text):
        return "mechanism"
    if re.search(r"\d|[一二三四五六七八九十百千万]+(?:つ|個|本|回|倍|％|パーセント)", text):
        return "quiz_reveal"
    return "classic_reveal"


def story_pattern_instruction(pattern_name: str) -> str:
    pattern = STORY_PATTERNS.get(pattern_name, STORY_PATTERNS["classic_reveal"])
    roles = "、".join(pattern["roles"])
    durations = "、".join(f"{value:g}秒" for value in pattern["durations"])
    return f"story_patternは{pattern_name}。roleは順に{roles}、時間は順に{durations}。構成は「{pattern['direction']}」。"


def expected_roles(pattern_name: str) -> tuple[str, ...]:
    return STORY_PATTERNS.get(pattern_name, STORY_PATTERNS["classic_reveal"])["roles"]
