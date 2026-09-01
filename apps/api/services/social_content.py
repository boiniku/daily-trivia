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
    original_claim: str
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


class YouTubePost(StrictModel):
    title: str
    description: str
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
    youtube: YouTubePost
    video: VideoDraft


class SharedTextDraft(StrictModel):
    headline_candidates: list[str]
    headline: str
    core_fact: str
    closing_point: str
    alt_text: str


class SharedTextReview(StrictModel):
    approved: bool
    issues: list[str]


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


def social_cta_reply() -> str:
    app_url = os.getenv(
        "APP_STORE_URL", "https://apps.apple.com/app/id6758872525"
    ).strip()
    return (
        "もっと「へぇ〜」となる雑学を知りたい人はこちら👇\n\n"
        "📱「毎日雑学」で、毎日ちょっと賢くなる。\n"
        "アプリをダウンロード👇\n"
        f"{app_url}"
    )


def build_research_prompt(trivia: Any) -> str:
    return f"""
次のDB雑学を出発点としてWeb検索し、短いSNS動画の脚本に使える事実メモを日本語で作成してください。
DBの内容は人間が精査済みなので、中心的な雑学を正として扱ってください。
最初に中心的な雑学をoriginal_claimへ一文で抜き出し、その面白さを変えずに最後まで主役として維持してください。
verified_factにはoriginal_claimの結論を、意味を変えずに初見向けの分かりやすい日本語で書いてください。
Web検索は元ネタを却下・別テーマへ置き換えるためではなく、初見の人にも伝わる補足、背景、理由、具体例を探すために使ってください。
まとめサイト、個人ブログ、Wikipediaを含め、関連情報が見つかる一般的なWebページを利用して構いません。
検索結果に別の面白い事実があっても、original_claimより主役にしてはいけません。
DBの内容と明確に矛盾する情報を見つけた場合だけcaveatsへ記録し、黙って別の雑学へ変更しないでください。
DBに登録された出典がある場合は検索時の手掛かりとして使ってください。
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
- YouTube Shortsのtitleは、対象名と意外な結論が分かる自然な日本語で60文字以内。ハッシュタグは入れない
- YouTube Shortsのdescriptionは、答えを伏せず、動画の要点を2〜4文で説明する。最後に「毎日雑学では、毎日3つの雑学をアプリとウィジェットで楽しめます。」を入れる
- YouTube Shortsのhashtagsは「Shorts」「雑学」「毎日雑学」を含む3〜5個にする
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
次の調査済み事実だけを根拠に、XとThreads投稿の材料を日本語で作ってください。
完成文の型・括弧・改行はコード側で固定するため、各フィールドには指定された一文だけを入れてください。

調査済み事実メモ:
{json.dumps(research, ensure_ascii=False, indent=2)}

条件:
- headline_candidates: 角度の異なる自然な見出しを3案作る。各案はsubjectを明記し、7〜23文字、括弧なしにする
- headline: headline_candidatesから、初見で意味が通り、元ネタの意外性が最も具体的に伝わる1案を完全一致で選ぶ
- 見出しは単語を無理に詰めたり助詞を省いたりしない。「衝撃の事実」「まさかの正体」のように内容を隠す煽りも禁止
- 良い見出しの例: 「昔の消しゴムはパンだった」「タコには心臓が3つある」。対象と意外な一点が一読で分かる
- コードが付ける【】を含め、1段落目全体が25文字以内になるようにする
- core_fact: DBの元ネタの結論を省略せず、30〜60文字の自然なです・ます調で説明する。見出しだけでは分からない前提や関係もここで補う
- closing_point: 読後にもう一段「へぇ〜」となる情報を30〜55文字で書く。理由、仕組み、背景、例外、身近な意味のうち、調査メモに根拠がある最適なものを選ぶ
- 雑学に理由が存在しない、または根拠が弱い場合は理由を作らず、比較・具体例・背景などで締める
- 3段階で新しい情報が一つずつ増える構成にし、同じ結論を言い換えて繰り返さない
- core_factとclosing_pointは自然なです・ます調の完成した文章にし、定型句を無理に付けない
- 推定や諸説がある内容は「〜と考えられています」「〜といわれています」と正確に弱める
- 全体はXの280ウェイトに収まる簡潔さにする
- ニュース見出し、教科書調、同じ事実の反復、問いかけ、ハッシュタグは禁止
- 「意外です」「秘密があります」「結論として」「説明すると」「〜ということです」は禁止
- 2段目と3段目は、直前の段落との関係が初見でも分かる文章にする。「この人」「この使い方」など説明不足の指示語や、紹介していない人物名を突然出さない
- 数字や固有名詞は、それが1段目の面白さを具体的に深める場合だけ使い、単独の年表や資料メモにしない
- alt_textは添付画像の説明として、subjectを含む20〜60文字の客観的な日本語にする
{feedback}
""".strip()


def build_shared_text_review_prompt(trivia: Any, research: dict, draft: dict) -> str:
    return f"""
あなたはSNS雑学投稿の厳しい編集責任者です。投稿案を公開してよいか判定してください。

元のDB雑学:
- タイトル: {trivia.title}
- 本文: {trivia.content}
- 解説: {trivia.explanation or ''}

調査結果:
{json.dumps(research, ensure_ascii=False, indent=2)}

投稿案:
{draft.get('text', '')}

次をすべて満たす場合だけapproved=trueにしてください:
- 元のDB雑学の中心的な面白さを維持し、関連する別テーマへ変えていない
- 1段目だけで対象と具体的な意外性が分かり、日本語として自然な見出しになっている
- 1段目は括弧を含め25文字以内で、助詞を不自然に省略していない
- 2段目で元の雑学の結論を省略せず説明し、3段目がさらに理解や驚きを一段進める
- 各段落の関係が自然で、話題が飛ばない
- 人物名、専門語、数字、指示語が説明なしに突然現れず、初見の読者が一度で意味を理解できる
- 調査メモの箇条書きを並べた文章ではなく、人に話したくなる自然な日本語になっている
- DBの元ネタとWeb検索で追加した補足を混同せず、検索で得た補足に留保がある場合は消していない

approved=falseの場合、issuesへ修正内容を具体的に最大5件入れてください。
""".strip()


def compose_shared_text(data: dict) -> dict:
    def sentence(value: str) -> str:
        cleaned = str(value or "").strip().strip("【】")
        cleaned = cleaned.rstrip("。！？!?")
        return cleaned + "。"

    headline = str(data.get("headline", "")).strip().strip("【】").rstrip("。！!？?")
    core_fact = sentence(data.get("core_fact", ""))
    closing_point = sentence(data.get("closing_point", ""))
    text = f"【{headline}】\n\n{core_fact}\n\n{closing_point}"
    return {
        **data,
        "text": text,
        "answer": core_fact,
    }


def shared_text_quality_issues(data: dict, research: dict) -> list[str]:
    text = str(data.get("text", "")).strip()
    answer = str(data.get("answer", "")).strip()
    alt_text = str(data.get("alt_text", "")).strip()
    headline = str(data.get("headline", "")).strip().strip("【】")
    candidates = [str(item).strip().strip("【】") for item in data.get("headline_candidates", [])]
    subject = str(research.get("subject", "")).strip()
    issues = []
    if subject and subject not in text:
        issues.append(f"本文に対象名「{subject}」を明記してください")
    if not answer or answer not in text:
        issues.append("core_factの結論を本文内に入れ、答えを明言してください")
    if len(candidates) != 3 or len(set(candidates)) != 3:
        issues.append("意味と角度の異なる見出し候補を3案作ってください")
    if headline not in candidates:
        issues.append("headlineはheadline_candidatesの1案と完全一致させてください")
    plain_text = text.strip()
    paragraphs = plain_text.split("\n\n")
    if len(paragraphs) != 3:
        issues.append("本文を空行で区切った3段落にしてください")
    else:
        if not (paragraphs[0].startswith("【") and paragraphs[0].endswith("】")):
            issues.append("1段落目を【短い見出し】の形にしてください")
        if len(paragraphs[0]) > 25:
            issues.append("1段落目を括弧込み25文字以内の、具体的で引きのある見出しにしてください")
        if len(paragraphs[0]) < 9:
            issues.append("1段落目を短くしすぎず、対象と具体的な意外性が分かる見出しにしてください")
        if subject and subject not in paragraphs[0]:
            issues.append(f"見出しに対象名「{subject}」を明記してください")
        if len(set(paragraphs)) != 3:
            issues.append("3段階で別々の情報を伝え、同じ内容を繰り返さないでください")
    if plain_text.endswith(("？", "?")):
        issues.append("問いかけで終わらず、答えや意味まで言い切ってください")
    if len(_spoken_text(plain_text)) < 45:
        issues.append("本文を短くしすぎず、答えに加えて理由または意味まで説明してください")
    if x_weighted_length(text) > 280:
        issues.append("本文をXの280ウェイト以内にしてください")
    if "#" in text:
        issues.append("本文にハッシュタグを入れないでください")
    if any(phrase in text for phrase in (
        "意外です", "秘密があります", "結論として", "説明すると",
        "衝撃の事実", "驚きの事実", "まさかの正体",
    )):
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

    youtube = data.get("youtube")
    if not isinstance(youtube, dict):
        # Keep older jobs usable after YouTube handoff metadata is introduced.
        youtube = {
            "title": str(data["x"]["text"]).split("。", 1)[0],
            "description": str(data["x"]["text"]),
            "hashtags": ["Shorts", "雑学", "毎日雑学"],
        }
        data["youtube"] = youtube
    youtube["title"] = str(youtube.get("title", "")).strip().lstrip("#")[:60]
    if not youtube["title"]:
        raise ValueError("YouTube title is empty")
    youtube["description"] = str(youtube.get("description", "")).strip()[:5000]
    if not youtube["description"]:
        raise ValueError("YouTube description is empty")
    raw_youtube_hashtags = youtube.get("hashtags")
    if not isinstance(raw_youtube_hashtags, list):
        raw_youtube_hashtags = []
    youtube_hashtags = []
    for item in [*raw_youtube_hashtags, "Shorts", "雑学", "毎日雑学"]:
        value = re.sub(r"\s+", "", str(item).strip().lstrip("#"))
        if value and value not in youtube_hashtags:
            youtube_hashtags.append(value)
    youtube["hashtags"] = youtube_hashtags[:5]

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


def _max_text_research_calls() -> int:
    try:
        value = int(os.getenv("SOCIAL_TEXT_RESEARCH_MAX_SEARCH_CALLS", "2"))
    except ValueError:
        value = 2
    return max(1, min(value, 3))


def _estimated_generation_cost(
    usage: dict[str, int],
    *,
    input_rate: float | None = None,
    output_rate: float | None = None,
) -> float:
    input_rate = input_rate or float(os.getenv("SOCIAL_INPUT_USD_PER_MILLION", "0.20"))
    output_rate = output_rate or float(os.getenv("SOCIAL_OUTPUT_USD_PER_MILLION", "1.20"))
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
    model = os.getenv("SOCIAL_TEXT_MODEL", "gpt-5.6-terra").strip()
    research_response = client.responses.parse(
        model=model,
        tools=[{
            "type": "web_search",
            "search_context_size": os.getenv(
                "SOCIAL_TEXT_RESEARCH_SEARCH_CONTEXT_SIZE", "medium"
            ),
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        }],
        tool_choice="required",
        max_tool_calls=_max_text_research_calls(),
        include=["web_search_call.action.sources"],
        reasoning={"effort": "medium"},
        max_output_tokens=6000,
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
        reasoning={"effort": "medium"},
        max_output_tokens=3000,
        text_format=SharedTextDraft,
        input=build_shared_text_prompt(trivia, research),
    )
    draft = compose_shared_text(
        _parsed_response(text_response, "Social shared text").model_dump()
    )
    responses.append(text_response)
    issues = shared_text_quality_issues(draft, research)
    review_response = client.responses.parse(
        model=model,
        reasoning={"effort": "medium"},
        max_output_tokens=2000,
        text_format=SharedTextReview,
        input=build_shared_text_review_prompt(trivia, research, draft),
    )
    review = _parsed_response(review_response, "Social shared text review").model_dump()
    responses.append(review_response)
    if not review.get("approved"):
        issues.extend(str(item) for item in review.get("issues", []) if str(item).strip())
    repaired = False
    if issues:
        repair_response = client.responses.parse(
            model=model,
            reasoning={"effort": "medium"},
            max_output_tokens=3000,
            text_format=SharedTextDraft,
            input=build_shared_text_prompt(trivia, research, issues),
        )
        draft = compose_shared_text(
            _parsed_response(repair_response, "Social shared text repair").model_dump()
        )
        responses.append(repair_response)
        repaired = True
        remaining = shared_text_quality_issues(draft, research)
        final_review_response = client.responses.parse(
            model=model,
            reasoning={"effort": "medium"},
            max_output_tokens=2000,
            text_format=SharedTextReview,
            input=build_shared_text_review_prompt(trivia, research, draft),
        )
        final_review = _parsed_response(
            final_review_response, "Social shared text final review"
        ).model_dump()
        responses.append(final_review_response)
        if not final_review.get("approved"):
            remaining.extend(
                str(item)
                for item in final_review.get("issues", [])
                if str(item).strip()
            )
        if remaining:
            raise RuntimeError("Social shared text quality check failed: " + "; ".join(remaining))

    text = draft["text"]
    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_calls": 0}
    for response in responses:
        item_usage = _response_usage(response)
        for key in usage:
            usage[key] += item_usage[key]
    return {
        "automation": {"mode": "daily_text", "format_version": 7},
        "x": {"text": text, "reply_text": social_cta_reply()},
        "threads": {"text": text, "reply_text": social_cta_reply(), "topic_tag": "雑学"},
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
            "estimated_cost_usd": _estimated_generation_cost(
                usage,
                input_rate=float(os.getenv("SOCIAL_TEXT_INPUT_USD_PER_MILLION", "2.0")),
                output_rate=float(os.getenv("SOCIAL_TEXT_OUTPUT_USD_PER_MILLION", "12.0")),
            ),
        },
    }
