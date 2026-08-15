import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate
from services.trivia_candidates import create_candidates, find_duplicate
from services.trivia_generation import TRIVIA_CATEGORIES


logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_DOMAINS: tuple[str, ...] = ()
DEFAULT_MAX_SEARCH_CALLS = 5
DEFAULT_COLLECTION_ATTEMPTS = 3
RECENT_FACT_EXCLUSION_LIMIT = 100
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


class MapTriviaQualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int
    is_trivia: bool
    is_hyperlocal: bool
    answers_why_and_how: bool
    jargon_is_clear: bool
    onsite_payoff_is_specific: bool
    trivia_score: int = Field(ge=0, le=5)
    hyperlocal_score: int = Field(ge=0, le=5)
    why_how_score: int = Field(ge=0, le=5)
    clarity_score: int = Field(ge=0, le=5)
    rejection_reason: str


class MapTriviaQualityReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[MapTriviaQualityAssessment]


@dataclass(frozen=True)
class TriviaCollectionUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    web_search_calls: int = 0


@dataclass
class TriviaCollectionDiagnostics:
    attempts: int = 0
    generated: int = 0
    complete_map: int = 0
    quality_accepted: int = 0
    duplicates: int = 0
    final_candidates: int = 0


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


def get_collection_attempts() -> int:
    raw_value = os.getenv("TRIVIA_COLLECTION_ATTEMPTS", "")
    try:
        value = int(raw_value)
    except ValueError:
        value = DEFAULT_COLLECTION_ATTEMPTS
    return max(1, min(value or DEFAULT_COLLECTION_ATTEMPTS, 3))


def build_map_collection_focus(output_count: int) -> str:
    return f"""
【地図用収集モード: 場所にまつわる面白い雑学】
今回は日本国内の雑学MAPへ登録する候補だけを集める。
特定の場所と強く結びつき、読んだ人が「この場所にそんなものがあるの？」「実際に探したい」と思えるものを選ぶ。
「発祥の地」「日本初」という肩書だけを大量に集めず、それ自体より面白い二段目がある場合だけ採用する。

【最重要: 全国の人にも面白さが伝わるローカル雑学】
- ニッチさは目的ではなく、面白い事実を発見するための手段とする。「地元の人しか知らない」だけでは採用理由にしない
- 「誰でも知っている物・習慣・常識」→「予想と違う具体的な事実」→「腑に落ちる理由」の順で理解でき、その日のうちに誰かへ一文で話したくなる候補を優先する
- 地元資料でしか見つからない事実でも、地域史や専門分野の前提知識がないと意外性が伝わらないものは採用しない
- 観光名所そのものの歴史、規模、見どころを紹介する観光案内ではなく、その場所の一部分、痕跡、仕組み、用途の変化、地元で続く習慣など、普通の観光ページでは主役にならない具体的な一点を扱う
- 「有名な場所にある、あまり知られていない具体物」または「何気ない場所に隠れた意外な経緯」を優先する。その地点にある具体物や経緯を資料で確認できれば、似た仕組みが他地域にも存在することだけを理由に除外しない
- 全国向け観光サイトの概要だけで候補を完成させない。自治体史・市史・町史、図書館や博物館の郷土資料、文化財調査報告書、施設の技術資料、地域新聞、地元団体の一次資料を追加で探す
- 検索では、場所名だけでなく「市史」「町史」「郷土資料」「調査報告書」「広報」「設計」「改修」「痕跡」「由来」などを組み合わせ、地元資料にしか出にくい情報を発見する
- 地元で有名な話をそのまま採用するのではなく、資料で裏付けられ、初見の人にも面白さが伝わるものだけを選ぶ

優先する面白さの型:
1. 普通に見える物に、変な形、傷、向き、数、配置が残り、それに意外だが納得できる理由がある
2. 一見無駄に見える構造や決まりが、災害、地形、当時の技術、生活上の切実な事情から生まれた
3. 現在の道、建物、公園、店などが、想像しにくい過去の用途に今も引っ張られている
4. 地元では普通の習慣や呼び方が、地域外の人には意外で、成立した理由まで説明できる
5. 有名な場所に、ほとんどの人が見落とす具体物や仕掛けがある
6. 失敗、苦肉の策、偶然、対立、勘違い、転用が、現在見える形や習慣を生んだ
7. 一段目より二段目が面白い: 「古い」「日本初」ではなく、なぜその形になったか、今も何が残るかを調べると驚きが増える

候補ごとに出力前に確認すること:
1. 最初の一文だけで、専門知識のない人が「え、そうなの？」と思えるか
2. 何が一般的な予想と違うのか、一読で分かるか
3. 理由や仕組みを知ることで、最初の驚きがきちんと回収されるか
4. 物、形、数字、行動、場所などを頭に描けるか
5. 読者が30秒以内、一文で友人へ言い換えられるか
6. 現地で対象を見たとき、それまでと見え方が変わるか

【必須の深掘り】
- 面白い事実を見つけたら、そこで止めず、「なぜそうなったか」「当時何が起きたか」「現在も残るか」「現地で具体的に何が見えるか」を追加検索する
- 二段目・三段目で面白さが増した情報はexplanationへ入れる。弱い関連情報を無理に足して長くしない
- explanationは、情報を箇条書きのように並べず、「成立した背景や原因→転機となった具体的な出来事→現在の姿や現地で確認できる痕跡」が一続きで分かる構成にする
- 年代、人物、数量、構造、用途の変化は、驚きや理由の理解に必要なものだけを具体的に入れる。種類数を満たすために情報を足さない
- 「なぜそうなったのか」と「どのように実現・変化・保存されたのか」のうち、面白さの核心を最もよく説明する問いへ十分に答える。両方が面白さに必要な場合だけ両方を説明する
- 「〜のため造られた」「〜として使われた」で止めず、その必要が生じた事情と、形・材料・工程・制度・人の工夫のどれが結果を生んだかまで説明する
- 事実の存在は確認できても、理由や仕組みを資料で確認できない候補は、推測で埋めず採用しない
- 現存、営業、公開、移設、改修の状況を、できるだけ新しい公式情報で確認する。現在見られないものを見られるように書かない

【専門用語の説明】
- 専門用語、昔の制度名、建築・土木用語、地域固有の呼び名は、初出の同じ文で「つまり何か」「何の役割か」を平易な言葉で説明する
- 用語の言い換えだけで済ませず、その用語が今回の雑学の原因や仕組みにどう関係するかまで書く
- 用語を知らない中学生が、説明を読んで現地の対象を頭に描けない場合は書き直す。説明に多くの文字が必要なら、より平易な表現へ置き換える

【現地体験】
- map_hintには、現地でできることを25〜80文字程度で具体的に書く。例のような対象をそのまま使わず、「どの建物のどの部分を見る」「何を数える」「何と見比べる」まで分かる文章にする
- 「説明板を読める」「歴史を感じられる」のような抽象表現だけでは採用しない。説明板より対象物そのものを観察できる候補を優先する
- 公道や公開区域から安全に確認できるものを選ぶ。私有地への立入り、危険行為、文化財への接触を促さない
- 有料、公開時間限定、予約制、通常非公開など重要な条件が公式情報で確認できる場合はmap_hintに簡潔に入れる

【採用しないもの】
- 「発祥」「日本初」「跡地」「石碑がある」だけで終わり、現地体験や深掘りの面白さがない
- 寺社、城、駅、橋、建物などの創建年、規模、建築様式、一般的な歴史、定番の見どころを要約しただけの観光案内
- 「歴史ある」「地域に愛される」「貴重な文化財」のような評価語を外すと、具体的な驚きが残らない
- 地名の由来や伝説を紹介するだけで、なぜその形・仕組み・習慣・痕跡が生まれたかを説明できない
- 地元では知られていても、初見の人には何が意外なのか分からず、地域史の前提説明ばかり長くなる
- 詳しく正しいが、30秒で誰かへ話したくなる一文へ縮められない郷土史の解説
- 場所を示す固有名詞を外すと、全国どこでも成立する一般論しか残らない。ただし、同種の仕組みが他地域にもあるだけなら不採用理由にしない
- 観光サイトの概要を言い換えただけの有名すぎる話
- 現地に何も残らず、場所そのものにも訪れる理由がない
- 都市伝説、伝承だけの話、個人ブログやまとめサイトしか根拠がない話
- 魅力的でも中心事実、人物、年代、由来を信頼できる資料で確認できない話
- 虚偽や観光案内で数を埋めてはいけないが、一項目が満点でないだけの候補を自己判断で捨てない。最低品質を満たす候補を比較し、可能な限り{output_count}件出力する

【ファクトチェックと出典】
- 国、自治体、博物館、文化財機関、施設・企業公式、大学、新聞社、専門資料の順に優先する
- 可能な限り2件以上の独立した資料で、中心事実、年代、人物、現存状況、場所を照合する
- sourceには、照合した中で中心事実と現存状況を最も直接説明する、最も信頼性の高い個別ページ1件を入れる
- 検索結果の抜粋、トップページ、URLが確認できない資料はsourceにしない

【位置情報】
- map_address、map_prefecture、map_latitude、map_longitude、map_radius、map_hintを全件必ず入れる
- map_addressは「対象物・施設名 / 具体的な住所」とし、ユーザーが現地へ向かえる情報にする
- 座標は施設全体の代表点より、傷、石碑、店舗、遺構、モニュメントなど雑学の対象物そのものへ可能な限り近づける
- 公式案内図、文化財資料、施設情報、信頼できる地図で位置を確認する。座標を推測しない。対象位置に自信がなければ候補自体を出力しない
- map_radiusは、対象点が明確なら100m、建物や小規模施設なら200〜300m、広い公園・城跡なら500〜800mを目安にする

【内部評価】
候補を広く調査してから、「予想とのズレ」「前提知識なしで伝わるか」「理由を知った納得感」「具体的に想像できるか」「一文で話したくなるか」「場所との強い結びつき」「信頼性」を各0〜5点で評価する。「場所との強い結びつき」は全国唯一かではなく、その地点の具体物・出来事・習慣として確認できるかで評価する。
「予想とのズレ」「前提知識なしで伝わるか」「場所との強い結びつき」「信頼性」が2点以上の候補から、総合点の高いものを優先する。2点は最低品質、3点は明確な合格とする。現地体験や説明の一項目がやや弱くても、他の面白さが十分に強ければ除外しない。
{output_count}件は場所、地域、面白さの型が偏りすぎないようにする。
"""


def build_map_quality_review_prompt(items: list[CollectedTrivia]) -> str:
    candidates = [
        {
            "candidate_index": index,
            "title": item.title,
            "content": item.content,
            "explanation": item.explanation,
            "map_hint": item.map_hint,
        }
        for index, item in enumerate(items)
    ]
    return f"""
あなたは雑学MAPの最終品質審査者です。候補を好意的に補完せず、書かれている文章だけで厳しく判定してください。

雑学として合格する条件:
- 専門知識のない読者にも身近な入口があり、一般的な予想を少し裏切る、具体的で検証可能な事実が中心にある
- 観光名所の概要ではなく、その地点固有の小さな痕跡、仕組み、工夫、用途変化、習慣などを扱う。ニッチであること自体は加点しない
- explanationが「なぜそうなったか」「どのように実現・変化・保存されたか」のうち、面白さの核心となる問いへ具体的に答え、最初の驚きを回収する
- 物、形、数字、行動、場所を具体的に想像でき、読者が30秒以内、一文で友人へ言い換えられる
- 専門用語は初見の中学生にも意味と役割が分かる
- map_hintが、現地のどこで何を見れば事実を確かめられるか具体的に示す

次は不合格:
- 創建年、改名、世界遺産・文化財登録、受賞、規模、日本一、長い伝統を紹介するだけ
- 有名な人物・祭り・工芸・城・寺社・施設の一般的な歴史や見どころ
- 地元資料にしか載っていないというだけで、初見の人にとっての意外性や面白さがない
- 詳しく正しいが、中心となる驚きを一文で言えない郷土史・技術史の解説
- 「資料にある」「公式が紹介」「展示で見られる」を根拠として述べ、原因や仕組みを説明していない
- 「〜のため造られた」「〜として使われた」で止まり、必要が生じた事情や実現方法がない
- 専門用語を別の専門用語で言い換えただけ
- 現地体験が「展示を見る」「景色を見る」「歴史を感じる」だけ

is_triviaは「予想とのズレがあり、一文で人に話したくなるか」、is_hyperlocalは「その地点の具体物・出来事・習慣として本文と資料で結びついているか」、answers_why_and_howは「面白さの核心となる理由または仕組みを十分に説明したか」で判定してください。
is_hyperlocalは全国唯一という意味ではありません。同じ種類の構造や習慣が他地域にも存在していても、その地点にある具体的な対象や経緯を確認できるなら、それだけでfalseにしないでください。
jargon_is_clear、onsite_payoff_is_specificを含め、候補文だけで実質的に満たしている場合にtrueにしてください。
trivia_scoreは意外性と話したくなる度合い、hyperlocal_scoreは場所固有性、why_how_scoreは驚きを回収する説明、clarity_scoreは前提知識なしで具体的に想像できる度合いとして採点してください。
各スコアは0〜5点で付け、2点を最低品質、3点を明確な合格、4点を優れた候補、5点を非常に優れた候補とします。boolは判定理由を示す補助情報であり、一つのfalseだけで総合的に面白い候補を不合格にしないでください。
候補ごとにcandidate_indexを保ち、全候補を1回ずつ評価してください。

候補:
{json.dumps(candidates, ensure_ascii=False, indent=2)}
"""


def review_map_trivia_quality(
    client,
    model: str,
    items: list[CollectedTrivia],
) -> tuple[list[CollectedTrivia], TriviaCollectionUsage]:
    if not items:
        return [], TriviaCollectionUsage()

    response = client.responses.parse(
        model=model,
        max_output_tokens=5000,
        reasoning={"effort": "medium"},
        text_format=MapTriviaQualityReviewResult,
        input=build_map_quality_review_prompt(items),
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        logger.warning("Map trivia quality review returned no structured result")
        return [], get_collection_usage(response)

    accepted_indices = set()
    for assessment in parsed.assessments:
        score_total = (
            assessment.trivia_score
            + assessment.hyperlocal_score
            + assessment.why_how_score
            + assessment.clarity_score
        )
        passed = (
            assessment.trivia_score >= 2
            and assessment.hyperlocal_score >= 2
            and assessment.why_how_score >= 2
            and assessment.clarity_score >= 2
            and score_total >= 10
        )
        if passed and 0 <= assessment.candidate_index < len(items):
            accepted_indices.add(assessment.candidate_index)
        else:
            logger.info(
                "Rejected map trivia candidate %s: %s",
                assessment.candidate_index,
                assessment.rejection_reason,
            )

    return (
        [item for index, item in enumerate(items) if index in accepted_indices],
        get_collection_usage(response),
    )


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
    map_focus = build_map_collection_focus(output_count) if map_mode else ""
    if map_mode:
        content_rule = (
            "- contentは70〜110文字程度のです・ます調で、場所と中心事実の結びつきが"
            "一読で分かる本文にする"
        )
        explanation_rule = (
            "- explanationは180〜300文字程度、3〜4文で、contentの言い換えではなく、検索で確認した"
            "背景や原因、具体的な出来事、現在の状態と現地の痕跡を因果関係または時系列でつなげる"
        )
        content_example = "場所との結びつきが一読で分かる70〜110文字程度の本文"
        explanation_example = "背景、具体的な出来事、現在の痕跡をつないだ180〜300文字、3〜4文の解説"
    else:
        content_rule = "- contentは45〜75文字程度のです・ます調で、専門知識のない中学生が雑学の要点を一読で理解できる本文にする"
        explanation_rule = (
            "- explanationは80〜140文字程度、最大2文で、contentの繰り返しではなく、追加検索で確認した"
            "理由、仕組み、背景、条件、例外、一見矛盾する事例との繋がりを平易に補足する"
        )
        content_example = "中学生が一読で分かる45〜75文字程度の本文"
        explanation_example = "理由や意外な繋がりを平易に説明する80〜140文字、最大2文の解説"
    return f"""
Web検索を最大{max_search_calls}回まで行い、Web上の個別ページから、
{subject}具体的な事実を{output_count}件見つけ、それぞれを独立した雑学として書いてください。
最初の検索だけで決めず、必要に応じて検索語や切り口を変えて複数回探してください。
除外リストと重なる題材が見つかった場合は、そこで終了せず、対象・カテゴリ・検索語を変えて未掲載の題材を探してください。
除外リストを新しい候補の発想元にせず、Web検索で別の対象から候補を発見してください。
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
ジャンル自体を目的にせず、日常会話で誰かに話したくなる面白さと分かりやすさを最優先してください。

【面白さの優先順位】
「能力がすごい」「非常に珍しい」というだけでなく、知った人の予想が裏切られ、
自然に「なぜ？」「それならこれは？」と次の会話が生まれる候補を優先してください。
生物、人体、法律、商標、歴史、科学などは固定枠にせず、次の面白さを探す分野として横断してください。

優先する面白さの型:
1. 常識逆転型: 多くの人が自然に思い込むことと、実際の事実が逆になっている
2. 疑問深掘り型: 最初の事実から生まれる「なぜ／それなら／例外は」に、さらに面白い答えがある
3. 身近な由来型: 普段使う物、言葉、商品名、形、習慣、決まりに、歴史的事情、設計理由、制度、偶然が残っている
4. 意外な接続型: 関係なさそうな二つの物事が、歴史、制度、科学、言葉などを通してつながる
5. 例外・矛盾型: 一般的なルールの意外な例外や、矛盾して見える事実が理由を知ると両立する
6. 想像超越型: 数字が普通の予想を大きく超え、身近な比較によって異常な規模を直感的に実感できる

【候補の内部選考】
- 見つけた候補をすぐ採用せず、「予想とのギャップ」「次の疑問」「深掘りした答えの面白さ」「身近さ・話しやすさ」「出典の信頼性」を各0〜5点で内部評価する
- 合計18点未満の候補は出力しない
- 「深掘りした答え」または「予想を超える規模を実感できる面白さ」が4点未満の候補は出力しない
- 人に30秒で話したとき、事実と理由または比較が一続きで伝わる候補を選ぶ
- 「実は」「驚くことに」などの煽りを外すと面白くなくなる候補は採用しない

【読みやすさと題材の身近さ】
- 想定読者は専門知識のない中学生。1回読めば内容を理解でき、そのまま友達へ話せる日本語にする
- テーマ指定がない場合、候補のおよそ7割は、日用品、食べ物、言葉、体、動物、学校、街、乗り物など身近な対象から選ぶ
- 珍しい生物、人物名、現象名、法律名など、名前を知らないことが前提の題材は全体の3割以内にする
- 珍しい対象を扱う場合も、名前を覚えないと面白さが伝わらない候補は避け、身近な言葉で驚きが分かるタイトルにする
- 中学校の教科書を超える専門用語は原則使わない。必要な専門語は1候補につき最大1つとし、その場で短く意味を説明する
- 固有名詞、年代、カタカナ語を並べない。面白さに不要な研究者名、学名、物質名、制度名は省く
- 「生理的意義」「免疫寛容」「イオン供給」「分子レベル」のような説明なしでは分からない表現を避ける
- 一文では一つのことだけを伝え、長い括弧書きや三つ以上の情報の列挙をしない
- 専門用語を三つ以上使わないと説明できない題材は、内容が正しくても採用しない
- 研究の現状や専門的な補足より、「何が意外か」「なぜそうなるか」を平易に説明する

【数字を使う雑学】
- 「最大」「最速」「最古」「非常に多い」という記録だけでは採用しない
- ただし、数字が一般的な予想を大きく超え、身近な比較で規模を実感できる場合は積極的に採用する
- 数字を出す場合は、身近な物・人間・建物・時間・距離などとの正確な比較、予想との大きな差、またはその規模になる面白い理由を最低1つ入れる
- 単位を変えただけの誇張や、出典にない比較を作らない。比較計算は正確に行う

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

良いタイトルの型:
- 「一般的な予想」と「実際」の違いが具体的に分かる
- 身近な名前・形・習慣と、その意外な由来が一文でつながる
- 数字と比較対象が入り、規模を直感的に想像できる
- ルールと意外な例外が一文で分かる

悪いタイトルの例:
- バナナの分類について
- タコに関する驚きの雑学
- 宇宙空間の特徴

【本文と解説】
{content_rule}
{explanation_rule}
- 深掘りで面白さが増す題材では、contentに起点となる意外な事実、explanationに「なぜ／どうして可能か」の答えを書く
- contentとexplanationに改行、前置き、感想、読者への呼びかけを入れない
- 「〜といわれています」だけで済ませず、記事で確認できる範囲で何が分かっているかを具体的に書く
- explanationも情報源を紹介する文章にせず、その事実自体の理由や背景だけを書く
- 書き終えたら「中学生が知らない言葉を説明なしで使っていないか」「一度で言い換えられるか」を確認し、難しければ書き直す

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
- 世界最大・最速・最古という記録だけで、身近な比較や面白い理由がないもの
- 専門知識がないと意外性が伝わらず、30秒で説明できないもの
- 有名な定番雑学を、深掘りや新しい繋がりなしで言い直したもの

出力形式:
{{
  "trivia": [
    {{
      "subject_key": "中心対象を表す短い一般名詞",
      "title": "独自に作成した30文字以内のタイトル",
      "content": "{content_example}",
      "explanation": "{explanation_example}",
      "category": "{categories}のいずれか",
      "source": "題材を発見した記事のURL",
      "map_address": "雑学MAPに置ける具体的な住所や施設名。場所に関係しない雑学なら空文字",
      "map_prefecture": "都道府県。場所に関係しない雑学なら空文字",
      "map_latitude": 35.6812,
      "map_longitude": 139.7671,
      "map_radius": 300,
      "map_hint": "現地で何を、どこで、どう探したり体験したりできるか"
    }}
  ]
}}

【雑学MAP用情報】
- 地名、建物、史跡、駅、観光地、地域文化など場所に紐づく雑学では、map_address/map_prefecture/map_latitude/map_longitude/map_radius/map_hintをできるだけ入れる
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

【既存雑学の本文要約（直近最大100件）】
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
        and item.map_hint.strip()
        and item.map_latitude is not None
        and item.map_longitude is not None
        and item.map_radius is not None
        and 50 <= item.map_radius <= 1000
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
            return selected

    # Diversity is a preference, not a reason to discard otherwise valid facts.
    # Structured model output can occasionally omit subject_key or concentrate on
    # one category; fill the remaining slots after the diverse choices.
    for item in items:
        if item in selected:
            continue
        selected.append(item)
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
    diagnostics_callback: Callable[[TriviaCollectionDiagnostics], None] | None = None,
) -> list[dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    count = max(1, min(count, 10))
    topic = topic.strip()
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
        for title, content in existing_rows[-RECENT_FACT_EXCLUSION_LIMIT:]
        if title
    ]
    search_context_size = "high" if map_mode else get_search_context_size()
    tool = {
        "type": "web_search",
        "search_context_size": search_context_size,
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
    if map_mode:
        max_search_calls = max(max_search_calls, 8)
    client = OpenAI(api_key=api_key)
    model = os.getenv(
        "TRIVIA_COLLECTION_MODEL",
        os.getenv("TRIVIA_GENERATION_MODEL", "gpt-5-mini"),
    )
    collected_items: list[CollectedTrivia] = []
    attempted_titles: list[str] = []
    seen_exact_items: set[tuple[str, str]] = set()
    total_usage = TriviaCollectionUsage()
    diagnostics = TriviaCollectionDiagnostics()

    def publish_diagnostics() -> None:
        if diagnostics_callback:
            diagnostics_callback(TriviaCollectionDiagnostics(**vars(diagnostics)))

    for attempt in range(get_collection_attempts()):
        eligible_items = (
            select_diverse_items(collected_items, count)
            if not topic
            else collected_items
        )
        remaining = count - len(eligible_items)
        if remaining <= 0:
            break
        diagnostics.attempts += 1
        # Give the quality review enough alternatives even for a one-item request.
        output_count = min(10, max(3, remaining * 2))
        response = client.responses.parse(
            model=model,
            tools=[tool],
            tool_choice="required",
            max_tool_calls=max_search_calls,
            max_output_tokens=16000,
            reasoning={"effort": "medium" if map_mode else "low"},
            text_format=TriviaCollectionResult,
            input=build_collection_prompt(
                topic,
                remaining,
                existing_titles + attempted_titles,
                output_count=output_count,
                max_search_calls=max_search_calls,
                map_mode=map_mode,
                existing_facts=existing_facts,
            ),
        )
        usage = get_collection_usage(response)
        total_usage = TriviaCollectionUsage(
            input_tokens=total_usage.input_tokens + usage.input_tokens,
            output_tokens=total_usage.output_tokens + usage.output_tokens,
            web_search_calls=total_usage.web_search_calls + usage.web_search_calls,
        )
        if usage_callback:
            usage_callback(total_usage)

        incomplete_reason = get_incomplete_reason(response)
        if incomplete_reason:
            raise RuntimeError(incomplete_reason)
        if not (response.output_text or "").strip():
            logger.warning("Web collection attempt %s returned no output", attempt + 1)
            publish_diagnostics()
            continue
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            logger.error(
                "Web collection parse failed: status=%s output=%r",
                getattr(response, "status", None),
                (response.output_text or "")[:1000],
            )
            publish_diagnostics()
            continue

        source_items = parsed.trivia
        generated_count = len(source_items)
        diagnostics.generated += generated_count
        complete_map_count = generated_count
        quality_accepted_count = generated_count
        attempted_titles.extend(
            item.title.strip() for item in source_items if item.title.strip()
        )
        if map_mode:
            source_items = [item for item in source_items if has_complete_map_fields(item)]
            complete_map_count = len(source_items)
            diagnostics.complete_map += complete_map_count
            source_items, review_usage = review_map_trivia_quality(
                client,
                model,
                source_items,
            )
            quality_accepted_count = len(source_items)
            diagnostics.quality_accepted += quality_accepted_count
            total_usage = TriviaCollectionUsage(
                input_tokens=total_usage.input_tokens + review_usage.input_tokens,
                output_tokens=total_usage.output_tokens + review_usage.output_tokens,
                web_search_calls=total_usage.web_search_calls + review_usage.web_search_calls,
            )
            if usage_callback:
                usage_callback(total_usage)
        novel_items, duplicate_titles = remove_existing_duplicates(db, source_items)
        diagnostics.duplicates += len(duplicate_titles)
        logger.info(
            "Web collection attempt %s: generated=%s complete_map=%s "
            "quality_accepted=%s duplicates=%s novel=%s",
            attempt + 1,
            generated_count,
            complete_map_count,
            quality_accepted_count,
            len(duplicate_titles),
            len(novel_items),
        )
        for item in novel_items:
            exact_key = (
                re.sub(r"[\W_]+", "", item.title.lower()),
                re.sub(r"[\W_]+", "", item.content.lower()),
            )
            if exact_key in seen_exact_items:
                continue
            seen_exact_items.add(exact_key)
            collected_items.append(item)
        diagnostics.final_candidates = len(collected_items)
        publish_diagnostics()

    if not topic:
        collected_items = select_diverse_items(collected_items, count)
    final_items = validate_collected_items(collected_items)[:count]
    diagnostics.final_candidates = len(final_items)
    publish_diagnostics()
    return final_items


def collect_trivia_candidates(
    db: Session,
    topic: str,
    count: int,
    map_mode: bool = False,
    usage_callback: Callable[[TriviaCollectionUsage], None] | None = None,
    diagnostics_callback: Callable[[TriviaCollectionDiagnostics], None] | None = None,
) -> list[TriviaCandidate]:
    """Run the shared web collection workflow and persist its review candidates."""
    items = collect_trivia(
        db,
        topic=topic,
        count=count,
        map_mode=map_mode,
        usage_callback=usage_callback,
        diagnostics_callback=diagnostics_callback,
    )
    return create_candidates(db, items)
