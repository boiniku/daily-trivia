import json
import os
import re
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from services.story_patterns import expected_roles, select_story_pattern, story_pattern_instruction


URL_PATTERN = re.compile(r"https?://\S+")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchBrief(StrictModel):
    subject: str
    common_misconception: str
    verified_fact: str
    explanation: str
    supporting_details: list[str]
    caveats: list[str]
    visual_anchors: list[str]
    sources: list[str]


class TextPost(StrictModel):
    text: str


class ThreadsPost(TextPost):
    topic_tag: str


class CaptionPost(StrictModel):
    caption: str
    hashtags: list[str]


class VideoScene(StrictModel):
    duration: float
    role: str
    narration: str
    subtitle: str
    image_prompt: str
    motion: str


class VisualPrompt(StrictModel):
    duration: int
    prompt: str


class VideoDraft(StrictModel):
    story_pattern: str
    hook_candidates: list[str]
    scenes: list[VideoScene]
    visual_prompts: list[VisualPrompt]


class SocialDraft(StrictModel):
    x: TextPost
    threads: ThreadsPost
    instagram: CaptionPost
    tiktok: CaptionPost
    video: VideoDraft


class SharedTextDraft(StrictModel):
    text: str
    answer: str
    alt_text: str


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


def build_research_prompt(trivia: Any) -> str:
    return f"""
次のDB雑学を出発点としてWeb検索し、短いSNS動画の脚本に使える事実メモを日本語で作成してください。
DBの記述を無条件に正しいとみなさず、検索結果と照合してください。
元の出典を優先し、可能なら公的機関、博物館、大学、学術資料、専門団体など信頼性の高い情報でも確認してください。
動画の主役は一つに絞り、subjectは冒頭でそのまま読める2〜15文字程度の具体的な名詞にしてください。
確認できなかった情報は追加せず、異説や断定できない点はcaveatsへ入れてください。
sourcesには実際に確認に使ったURLだけを入れてください。

タイトル: {trivia.title}
本文: {trivia.content}
解説: {trivia.explanation or ''}
カテゴリ: {trivia.category or 'その他'}
DBに登録された出典: {trivia.source or 'なし'}
""".strip()


def build_social_prompt(
    trivia: Any,
    research: dict,
    quality_feedback: list[str] | None = None,
    *,
    story_pattern: str | None = None,
) -> str:
    story_pattern = story_pattern or select_story_pattern(research)
    feedback = ""
    if quality_feedback:
        feedback = "\n前回案の問題点。すべて修正してください:\n- " + "\n- ".join(quality_feedback)
    return f"""
あなたは短尺動画専門の構成作家です。次の調査済み事実メモを「事実の素材」として使い、
SNS投稿セットを日本語で新しく書いてください。
DBの元タイトル・本文・言い回しは参照せず、模倣もしないでください。
事実メモの文章を要約するのではなく、視聴者が続きを見たくなる順番へ再構成してください。
ただし、事実メモにない数値、固有名詞、因果関係を追加してはいけません。

調査済み事実メモ:
{json.dumps(research, ensure_ascii=False, indent=2)}

動画脚本の条件:
- {story_pattern_instruction(story_pattern)}
- 人気動画の固有表現はコピーせず、「冒頭で期待を作る→情報を小分けにする→回収する」という構造だけを使う
- 動画の主役はresearch.subject一つに絞る
- 語り手は「丁寧だけれど話がうまい友人」。敬語のです・ます調を最後まで保ち、講義・ニュース・論文の読み上げにはしない
- 面白さは大げさな煽りや冗談ではなく、「思い込みと事実の差」「頭に浮かぶ具体的な情景」「短い文のリズム」で作る
- 事実自体の驚きが弱い場合も誇張しない。supporting_detailsから、見た目、動き、身近な比較、次に対象を見た時の見え方を一つ選んで具体化する
- 各シーンは一つの役割だけを持たせる。前の文を言い換えて尺を埋めず、聞くたびに情報か見方が一段進むようにする
- revealの答えは最も短く気持ちよく言い切り、その直後の場面で理由や仕組みを具体的に説明する
- 「実は」「ところが」「つまり」は効果がある箇所で一つだけ使い、毎シーン同じ接続語や「〜です。」を機械的に繰り返さない
- 1シーンは原則1〜2文。声に出して一度読み、息継ぎしやすく、初見で意味を取り違えない自然な話し言葉にする
- 「結論として」「説明すると」「〜にあたる」「極めて」「〜ということです」「ご紹介します」「〜について解説します」などの硬い解説口調は禁止
- 内輪ノリ、ダジャレ、ネットスラング、子ども扱いする口調、馴れ馴れしいタメ口は禁止
- 書き始める前に、common_misconceptionとverified_factの差から「最も意外な一点」を内部で選ぶ
- hookはその意外な一点を具体的に匂わせ、映像なしでも意味が通る文章にする
- hookにはresearch.subjectを必ず明記し、ニュースの見出しではなく友人へ話す自然な口調にする
- hookでは勘違いとの対比までは見せてよいが、正体の専門用語・仕組み・理由はrevealまで伏せる
- 例: 「カニみそ、脳みそだと思っていませんか？」はよいが、冒頭で正体を肝膵臓と言い切らない
- 「意外です」「秘密です」「名前がかなり直球です」のように、中身を伏せただけの抽象表現は禁止
- 安全かつ事実に沿う場合は、「犬のアレ」「脳ではない」のような短く具体的な対比を使ってよい
- 冒頭を「これ」「それ」「あれ」など、映像を見ないと対象が分からない言葉から始めない
- hookでは答えを説明し切らず、questionで知識の空白を作り、revealで答えを明かす
- ナレーションは順に25、32、57、50文字以内を目安にし、7秒の場面へ説明を詰め込まない
- 字幕は1シーン22文字以内。ナレーション全文を字幕にしない
- 断定できない内容は「一説では」「といわれます」を維持する
- payoffは新しい理解を短く言い直して締める。「誰かに出題」「フォローして」「知っていましたか」だけで終えない
- hook_candidatesは角度の異なる3案にし、すべてにresearch.subjectと具体的な意外性を入れる
- 3案から「具体性・意外性・続きが気になる」の3条件が最も強い案をhookのnarrationに使う
- 4枚の画像は、対象・勘違い・正体や仕組み・印象的な結果のように役割を変える
- image_promptは英語で、9:16、同じ画風、文字・字幕・ラベル・ロゴ・透かしなしを明記する
- visual_promptsはSeedance用に2本、各8秒で作る

投稿の条件:
- Xはハッシュタグ込みで日本語120文字程度、280ウェイト以内。引き、結論、理由まで完結させる
- ThreadsはXと完全に同じ本文にする。問いかけたまま答えを伏せて終わらない
- InstagramとTikTokのhashtagsは各2〜4個にする
{feedback}
""".strip()


def build_shared_text_prompt(
    trivia: Any,
    research: dict,
    quality_feedback: list[str] | None = None,
) -> str:
    feedback = ""
    if quality_feedback:
        feedback = "\n前回案の問題点。すべて修正してください:\n- " + "\n- ".join(quality_feedback)
    return f"""
あなたは、短い文章だけで雑学を面白く伝えるSNS編集者です。
次の調査済み事実だけを根拠に、XとThreadsの両方へそのまま投稿する共通本文を日本語で作ってください。
DB本文の言い換えではなく、初見の人が一読で「何が意外で、答えは何で、なぜそうなるか」まで理解できる順番へ再構成してください。

調査済み事実メモ:
{json.dumps(research, ensure_ascii=False, indent=2)}

条件:
- 丁寧なです・ます調を保つが、ニュース見出しや教科書ではなく、話がうまい友人の自然な文章にする
- 全体をおよそ70〜130文字、Xの280ウェイト以内に収める
- 1文目はsubjectを明記し、思い込みとのズレや具体的な違和感で続きを読みたくさせる
- 2文目までにverified_factの結論を明言する。問いかけたまま答えを伏せて終わらない
- 最後はexplanationまたはsupporting_detailsから理由、仕組み、身近な意味のどれか一つを具体的に伝える
- 「意外です」「秘密があります」だけの抽象的な煽り、過剰な驚き、ダジャレ、ネットスラングは禁止
- 「結論として」「説明すると」「〜ということです」のような硬い解説口調は禁止
- 末尾を「知っていましたか？」などの問いかけだけにせず、読み手が人へ話せる知識を残す
- 事実を2〜3文で完結させ、同じ内容を言い換えて繰り返さない
- ハッシュタグは末尾に「#雑学」一つだけ付ける
- answerには、投稿内でそのまま使った結論の一文を句読点込みで完全一致させる
- alt_textは添付画像の説明として、subjectを含む20〜60文字の客観的な日本語にする
{feedback}
""".strip()


def shared_text_quality_issues(data: dict, research: dict) -> list[str]:
    text = str(data.get("text", "")).strip()
    answer = str(data.get("answer", "")).strip()
    alt_text = str(data.get("alt_text", "")).strip()
    subject = str(research.get("subject", "")).strip()
    issues = []
    if subject and subject not in text:
        issues.append(f"本文に対象名「{subject}」を明記してください")
    if not answer or answer not in text:
        issues.append("answerの結論文を本文内に完全一致で入れ、答えを明言してください")
    plain_text = re.sub(r"\s*#\S+\s*$", "", text).strip()
    if plain_text.endswith(("？", "?")):
        issues.append("問いかけで終わらず、答えや意味まで言い切ってください")
    if len(_spoken_text(plain_text)) < 45:
        issues.append("本文を短くしすぎず、答えに加えて理由または意味まで説明してください")
    if x_weighted_length(text) > 280:
        issues.append("本文をXの280ウェイト以内にしてください")
    if sum(plain_text.count(mark) for mark in ("。", "！", "？")) < 2:
        issues.append("2〜3文で、引き・答え・理由が読み分けられる文章にしてください")
    if any(phrase in text for phrase in ("意外です", "秘密があります", "結論として", "説明すると")):
        issues.append("抽象的な煽りや硬い解説口調を避け、具体的な事実を自然に説明してください")
    if subject and subject not in alt_text:
        issues.append(f"alt_textに対象名「{subject}」を入れてください")
    if not 20 <= len(alt_text) <= 60:
        issues.append("alt_textを20〜60文字にしてください")
    return issues


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
    # X and Threads intentionally share one fully self-contained explanation.
    data["threads"]["text"] = data["x"]["text"]

    video = data["video"]
    pattern = str(video.get("story_pattern", "classic_reveal")).strip()
    video["story_pattern"] = pattern if pattern in {
        "classic_reveal", "misconception_reversal", "quiz_reveal", "origin_story", "mechanism"
    } else "classic_reveal"
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
    for index, item in enumerate(raw_scenes[:6]):
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


def script_quality_issues(data: dict, subject: str) -> list[str]:
    video = data.get("video") if isinstance(data, dict) else None
    scenes = video.get("scenes") if isinstance(video, dict) else None
    if not isinstance(scenes, list) or not 4 <= len(scenes) <= 6:
        return ["動画は4〜6シーンにしてください"]

    issues = []
    pattern_name = str(video.get("story_pattern", "classic_reveal"))
    roles = expected_roles(pattern_name)
    if len(scenes) != len(roles):
        issues.append(f"story_pattern={pattern_name}は{len(roles)}シーンにしてください")
    for index, (scene, role) in enumerate(zip(scenes, roles)):
        if scene.get("role") != role:
            issues.append(f"シーン{index + 1}のroleは{role}にしてください")
        narration = str(scene.get("narration", "")).strip()
        subtitle = str(scene.get("subtitle", "")).strip()
        duration = float(scene.get("duration", 5) or 5)
        max_narration = int(duration * 7) + 8
        if len(_spoken_text(narration)) > max_narration:
            issues.append(
                f"シーン{index + 1}のナレーションを{max_narration}文字程度まで短くしてください"
            )
        if len(subtitle) > 22:
            issues.append(f"シーン{index + 1}の字幕を22文字以内にしてください")

    hook = str(scenes[0].get("narration", "")).strip()
    if subject and subject not in hook:
        issues.append(f"冒頭のナレーションに対象名「{subject}」を明記してください")
    if re.match(r"^(これ|それ|あれ)(?:[、。！？!?はをがって]|$)", hook):
        issues.append("冒頭を「これ・それ・あれ」から始めず、対象名を明記してください")
    weak_hook_phrases = (
        "意外です",
        "秘密です",
        "かなり直球です",
        "驚きです",
        "知っていますか",
    )
    if any(phrase in hook for phrase in weak_hook_phrases):
        issues.append(
            "冒頭は抽象的な煽りを避け、勘違いと事実の差が伝わる具体的な言葉にしてください"
        )

    hooks = [str(item).strip() for item in video.get("hook_candidates", [])]
    if len(hooks) != 3 or any(subject and subject not in hook_item for hook_item in hooks):
        issues.append(f"冒頭候補を3案作り、すべてに対象名「{subject}」を明記してください")
    elif len(set(hooks)) != 3:
        issues.append("冒頭候補3案は、言い換えではなく異なる角度で作ってください")

    payoff = str(scenes[-1].get("narration", ""))
    if any(phrase in payoff for phrase in ("誰かに出題", "フォローして", "知っていましたか？")):
        issues.append("最後は一般的な行動誘導ではなく、雑学の意味を短く言い直してください")
    all_narration = " ".join(str(scene.get("narration", "")) for scene in scenes)
    stiff_phrases = (
        "結論として",
        "説明すると",
        "にあたる部分です",
        "極めて",
        "ということです",
        "ご紹介します",
        "について解説します",
    )
    used_stiff_phrases = [phrase for phrase in stiff_phrases if phrase in all_narration]
    if used_stiff_phrases:
        issues.append(
            "硬い解説口調を避け、です・ます調の自然な会話へ直してください: "
            + "、".join(used_stiff_phrases)
        )
    return issues


def _spoken_text(text: str) -> str:
    return re.sub(r"[\s、。！？!?『』「」・…]", "", text)


def _response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    output = getattr(response, "output", None) or []
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "web_search_calls": sum(
            1
            for item in output
            if (getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None))
            == "web_search_call"
        ),
    }


def _web_source_urls(response: Any) -> list[str]:
    urls = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )
        if item_type != "web_search_call":
            continue
        action = getattr(item, "action", None) or (
            item.get("action") if isinstance(item, dict) else None
        )
        sources = getattr(action, "sources", None) or (
            action.get("sources", []) if isinstance(action, dict) else []
        )
        for source in sources:
            url = getattr(source, "url", None) or (
                source.get("url") if isinstance(source, dict) else None
            )
            if url and str(url).startswith(("http://", "https://")) and url not in urls:
                urls.append(str(url))
    return urls[:8]


def _parsed_response(response: Any, label: str) -> BaseModel:
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        detail = getattr(response, "incomplete_details", None)
        raise RuntimeError(f"{label} did not return structured output: {detail or 'unknown'}")
    return parsed


def _max_research_calls() -> int:
    try:
        value = int(os.getenv("SOCIAL_RESEARCH_MAX_SEARCH_CALLS", "1"))
    except ValueError:
        value = 1
    return max(1, min(value, 2))


def _estimated_generation_cost(usage: dict[str, int]) -> float:
    input_rate = float(os.getenv("SOCIAL_INPUT_USD_PER_MILLION", "0.20"))
    output_rate = float(os.getenv("SOCIAL_OUTPUT_USD_PER_MILLION", "1.20"))
    search_rate = float(os.getenv("SOCIAL_WEB_SEARCH_USD_PER_1000", "10.0"))
    return round(
        usage["input_tokens"] * input_rate / 1_000_000
        + usage["output_tokens"] * output_rate / 1_000_000
        + usage["web_search_calls"] * search_rate / 1_000,
        6,
    )


def generate_social_content(trivia: Any, client: OpenAI | None = None) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if client is None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=api_key)
    model = os.getenv("SOCIAL_CONTENT_MODEL", "gpt-5.6-luna").strip()
    research_response = client.responses.parse(
        model=model,
        tools=[{
            "type": "web_search",
            "search_context_size": os.getenv("SOCIAL_RESEARCH_SEARCH_CONTEXT_SIZE", "low"),
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        }],
        tool_choice="required",
        max_tool_calls=_max_research_calls(),
        include=["web_search_call.action.sources"],
        reasoning={"effort": "low"},
        max_output_tokens=3000,
        text_format=ResearchBrief,
        input=build_research_prompt(trivia),
    )
    research = _parsed_response(research_response, "Social research").model_dump()
    sources = _web_source_urls(research_response)
    if not sources:
        sources = [str(item).strip() for item in research.get("sources", [])]
    research["sources"] = [item for item in sources if item.startswith(("http://", "https://"))][:8]
    if not research["sources"]:
        raise RuntimeError("Social research returned no source URLs")

    story_pattern = select_story_pattern(research)
    script_response = client.responses.parse(
        model=model,
        reasoning={"effort": "low"},
        max_output_tokens=5000,
        text_format=SocialDraft,
        input=build_social_prompt(trivia, research, story_pattern=story_pattern),
    )
    draft = _parsed_response(script_response, "Social script").model_dump()
    draft = normalize_social_content(draft)
    issues = script_quality_issues(draft, research["subject"])
    responses = [research_response, script_response]
    repaired = False
    if issues:
        repair_response = client.responses.parse(
            model=model,
            reasoning={"effort": "low"},
            max_output_tokens=5000,
            text_format=SocialDraft,
            input=build_social_prompt(
                trivia, research, issues, story_pattern=story_pattern
            ),
        )
        draft = normalize_social_content(
            _parsed_response(repair_response, "Social script repair").model_dump()
        )
        responses.append(repair_response)
        repaired = True
        remaining = script_quality_issues(draft, research["subject"])
        if remaining:
            raise RuntimeError("Social script quality check failed: " + "; ".join(remaining))

    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_calls": 0}
    for response in responses:
        item_usage = _response_usage(response)
        for key in usage:
            usage[key] += item_usage[key]
    draft["research"] = research
    draft["generation_meta"] = {
        "model": model,
        **usage,
        "repaired": repaired,
        "estimated_cost_usd": _estimated_generation_cost(usage),
    }
    return draft


def generate_shared_text_content(trivia: Any, client: OpenAI | None = None) -> dict:
    """Research and write one complete daily post shared by X and Threads."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if client is None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        client = OpenAI(api_key=api_key)
    model = os.getenv("SOCIAL_CONTENT_MODEL", "gpt-5.6-luna").strip()
    research_response = client.responses.parse(
        model=model,
        tools=[{
            "type": "web_search",
            "search_context_size": os.getenv("SOCIAL_RESEARCH_SEARCH_CONTEXT_SIZE", "low"),
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        }],
        tool_choice="required",
        max_tool_calls=_max_research_calls(),
        include=["web_search_call.action.sources"],
        reasoning={"effort": "low"},
        max_output_tokens=3000,
        text_format=ResearchBrief,
        input=build_research_prompt(trivia),
    )
    research = _parsed_response(research_response, "Social text research").model_dump()
    sources = _web_source_urls(research_response)
    if not sources:
        sources = [str(item).strip() for item in research.get("sources", [])]
    research["sources"] = [item for item in sources if item.startswith(("http://", "https://"))][:8]
    if not research["sources"]:
        raise RuntimeError("Social text research returned no source URLs")

    responses = [research_response]
    text_response = client.responses.parse(
        model=model,
        reasoning={"effort": "low"},
        max_output_tokens=1200,
        text_format=SharedTextDraft,
        input=build_shared_text_prompt(trivia, research),
    )
    draft = _parsed_response(text_response, "Social shared text").model_dump()
    responses.append(text_response)
    issues = shared_text_quality_issues(draft, research)
    repaired = False
    if issues:
        repair_response = client.responses.parse(
            model=model,
            reasoning={"effort": "low"},
            max_output_tokens=1200,
            text_format=SharedTextDraft,
            input=build_shared_text_prompt(trivia, research, issues),
        )
        draft = _parsed_response(repair_response, "Social shared text repair").model_dump()
        responses.append(repair_response)
        repaired = True
        remaining = shared_text_quality_issues(draft, research)
        if remaining:
            raise RuntimeError("Social shared text quality check failed: " + "; ".join(remaining))

    text = trim_for_x(draft["text"])
    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_calls": 0}
    for response in responses:
        item_usage = _response_usage(response)
        for key in usage:
            usage[key] += item_usage[key]
    return {
        "automation": {"mode": "daily_text"},
        "x": {"text": text},
        "threads": {"text": text, "topic_tag": "雑学"},
        "shared_image": {
            "url": str(getattr(trivia, "image_url", "") or "").strip(),
            "alt_text": draft["alt_text"],
        },
        "post_meta": {"answer": draft["answer"]},
        "research": research,
        "generation_meta": {
            "model": model,
            **usage,
            "repaired": repaired,
            "estimated_cost_usd": _estimated_generation_cost(usage),
        },
    }
