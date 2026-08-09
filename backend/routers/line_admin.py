import html
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database import SessionLocal
from models import Trivia, TriviaCandidate
from services.line_bot import (
    candidate_flex_message,
    is_allowed_user,
    mark_line_sent,
    new_candidate_message,
    push_message,
    read_editor_token,
    reply_message,
    verify_signature,
)
from services.trivia_candidates import (
    CandidateError,
    approve_candidate,
    create_candidate,
    create_candidates,
    reject_candidate,
    update_candidate,
)
from services.image_storage import upload_trivia_image
from services.map_trivia import create_map_trivia, create_map_trivia_from_candidate
from services.trivia_collection import collect_trivia
from services.trivia_generation import TRIVIA_CATEGORIES, generate_trivia


router = APIRouter()


class CandidateUpdateRequest(BaseModel):
    token: str
    title: str
    content: str
    explanation: str = ""
    source: str = ""
    category: str = "その他"
    image_url: str = ""
    publish: bool = False
    add_to_normal: bool = True
    add_to_map: bool = False
    map_spot_id: str = ""
    map_address: str = ""
    map_prefecture: str = ""
    map_latitude: float = 35.6812
    map_longitude: float = 139.7671
    map_radius: int = 300
    map_hint: str = ""


def _text_message(text: str) -> dict:
    return {"type": "text", "text": text[:5000]}


def _candidate_has_complete_map(candidate: TriviaCandidate) -> bool:
    return bool(
        candidate.map_address
        and candidate.map_prefecture
        and candidate.map_latitude is not None
        and candidate.map_longitude is not None
        and candidate.map_radius is not None
    )

def _approve_candidate_from_line(db, candidate_id: int, user_id: str) -> str:
    candidate = db.query(TriviaCandidate).filter(TriviaCandidate.id == candidate_id).first()
    if not candidate:
        raise CandidateError("Candidate not found")
    if _candidate_has_complete_map(candidate):
        create_map_trivia_from_candidate(db, candidate)
        reject_candidate(db, candidate_id, f"line:{user_id}:map-published")
        return f"MAPに公開しました: {candidate.title}"
    trivia = approve_candidate(db, candidate_id, f"line:{user_id}")
    return f"公開しました: #{trivia.id} {trivia.title}"


def _validate_map_request(request: CandidateUpdateRequest) -> None:
    if not request.add_to_map:
        return
    if not request.map_prefecture.strip():
        raise HTTPException(status_code=400, detail="雑学MAPには都道府県が必要です。")
    if not request.map_address.strip():
        raise HTTPException(status_code=400, detail="雑学MAPには住所・施設名が必要です。")


def _validate_publish_target(request: CandidateUpdateRequest) -> None:
    if not request.add_to_normal and not request.add_to_map:
        raise HTTPException(status_code=400, detail="通常の雑学、雑学MAPのどちらかは選択してください。")


def _create_normal_trivia(
    db,
    *,
    title: str,
    content: str,
    explanation: str,
    source: str,
    category: str,
    image_url: str,
):
    trivia = Trivia(
        title=title.strip(),
        content=content.strip(),
        explanation=(explanation or "").strip(),
        source=(source or "").strip(),
        category=(category or "その他").strip(),
        image_url=(image_url or "").strip() or None,
    )
    db.add(trivia)
    db.commit()
    db.refresh(trivia)
    return trivia


def _parse_generate_command(text: str) -> tuple[str, int] | None:
    normalized = text.strip()
    prefix = next((value for value in ("生成", "作成") if normalized.startswith(value)), None)
    if not prefix:
        return None
    parts = normalized[len(prefix):].strip().split()
    count = 3
    if parts and parts[-1].isdigit():
        count = max(1, min(int(parts.pop()), 10))
    topic = " ".join(parts).strip()
    if topic.lower() in {"", "ランダム", "おまかせ", "お任せ", "random"}:
        topic = ""
    return topic, count


def _extract_map_mode(value: str) -> tuple[str, bool]:
    normalized = value.replace("（", "(").replace("）", ")")
    map_mode = False
    for marker in ("(地図用)", "(map用)", "(MAP用)", "地図用", "map用", "MAP用"):
        if marker in normalized:
            normalized = normalized.replace(marker, " ")
            map_mode = True
    return normalized.strip(), map_mode


def _parse_collect_command(text: str) -> tuple[str, int, bool] | None:
    normalized = text.strip()
    map_prefix = next(
        (
            prefix
            for prefix in ("地図収集", "MAP収集", "map収集", "マップ収集")
            if normalized.startswith(prefix)
        ),
        None,
    )
    if map_prefix:
        remainder = normalized[len(map_prefix):].strip()
        map_mode = True
    elif normalized.startswith("収集"):
        remainder, map_mode = _extract_map_mode(normalized[len("収集"):].strip())
    else:
        return None
    parts = remainder.split()
    count = 3
    if parts and parts[-1].isdigit():
        count = max(1, min(int(parts.pop()), 10))
    topic = " ".join(parts).strip()
    if topic.lower() in {"", "ランダム", "おまかせ", "お任せ", "random"}:
        topic = ""
    return topic, count, map_mode


def _generate_and_push(user_id: str, topic: str, count: int) -> None:
    db = SessionLocal()
    try:
        candidates = create_candidates(db, generate_trivia(db, topic, count))
        if not candidates:
            push_message(user_id, [_text_message("候補を生成できませんでした。もう一度試してください。")])
            return
        push_message(user_id, [_text_message(f"{len(candidates)}件生成しました。確認してください。")])
        for candidate in candidates:
            push_message(user_id, [candidate_flex_message(candidate)])
            mark_line_sent(candidate)
            db.commit()
    except Exception as exc:
        push_message(user_id, [_text_message(f"生成中にエラーが発生しました: {exc}")])
    finally:
        db.close()


def _collect_and_push(user_id: str, topic: str, count: int, map_mode: bool = False) -> None:
    db = SessionLocal()
    try:
        candidates = create_candidates(db, collect_trivia(db, topic, count, map_mode=map_mode))
        if not candidates:
            push_message(
                user_id,
                [_text_message("重複を除くと収集できる候補がありませんでした。")],
            )
            return
        push_message(
            user_id,
            [_text_message(
                f"Webから{len(candidates)}件の{'地図用' if map_mode else ''}題材を収集しました。確認してください。"
            )],
        )
        for candidate in candidates:
            push_message(user_id, [candidate_flex_message(candidate)])
            mark_line_sent(candidate)
            db.commit()
    except Exception as exc:
        push_message(user_id, [_text_message(f"収集中にエラーが発生しました: {exc}")])
    finally:
        db.close()


def _push_pending_candidates(user_id: str) -> None:
    db = SessionLocal()
    try:
        candidates = (
            db.query(TriviaCandidate)
            .filter(TriviaCandidate.status == "pending")
            .order_by(TriviaCandidate.created_at.asc())
            .limit(10)
            .all()
        )
        if not candidates:
            push_message(user_id, [_text_message("承認待ちの候補はありません。")])
            return
        push_message(user_id, [_text_message(f"承認待ちを{len(candidates)}件送ります。")])
        for candidate in candidates:
            push_message(user_id, [candidate_flex_message(candidate)])
            mark_line_sent(candidate)
        db.commit()
    finally:
        db.close()


@router.post("/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    if not verify_signature(body, request.headers.get("x-line-signature", "")):
        raise HTTPException(status_code=400, detail="Invalid LINE signature")

    payload = json.loads(body)
    for event in payload.get("events", []):
        user_id = event.get("source", {}).get("userId", "")
        reply_token = event.get("replyToken")
        if not is_allowed_user(user_id):
            if reply_token:
                reply_message(
                    reply_token,
                    [_text_message(
                        "このBotの管理操作は許可されていません。"
                        f"\n管理者設定用LINEユーザーID: {user_id}"
                    )],
                )
            continue

        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            message_text = event["message"].get("text", "").strip()
            collect_command = _parse_collect_command(message_text)
            generate_command = _parse_generate_command(message_text)
            if collect_command:
                topic, count, map_mode = collect_command
                subject = f"「{topic}」" if topic else "幅広いジャンル"
                reply_message(
                    reply_token,
                    [_text_message(
                        f"{subject}の{'地図用' if map_mode else ''}題材をWebから{count}件収集します。"
                        "検索料金が発生します。"
                    )],
                )
                background_tasks.add_task(_collect_and_push, user_id, topic, count, map_mode)
            elif generate_command:
                topic, count = generate_command
                subject = f"「{topic}」" if topic else "幅広いジャンル"
                reply_message(reply_token, [_text_message(f"{subject}の雑学を{count}件生成します。")])
                background_tasks.add_task(_generate_and_push, user_id, topic, count)
            elif message_text in {"候補", "承認待ち", "一覧"}:
                reply_message(reply_token, [_text_message("承認待ちの候補を確認します。")])
                background_tasks.add_task(_push_pending_candidates, user_id)
            elif message_text in {"新規", "手入力", "登録"}:
                reply_message(reply_token, [new_candidate_message()])
            elif message_text in {"新規 地図用", "新規(地図用)", "新規（地図用）", "手入力 地図用", "登録 地図用"}:
                reply_message(reply_token, [new_candidate_message(map_mode=True)])
            elif message_text in {"ヘルプ", "help", "HELP", "使い方"}:
                reply_message(
                    reply_token,
                    [_text_message(
                        "使い方:\n"
                        "・新規: 通常雑学の手入力フォームを開く\n"
                        "・新規(地図用): 雑学MAP用フォームを開く\n"
                        "・生成 宇宙 3: AIで通常候補を作る\n"
                        "・収集 食べ物 5: Webから通常候補を集める\n"
                        "・地図収集: 住所・座標つきのMAP候補をおまかせで集める\n"
                        "・地図収集 京都 5: 京都のMAP候補を5件集める\n"
                        "・候補: 承認待ちを表示\n"
                        "生成件数は最大10件です。\n"
                        "MAP情報がある候補の公開ボタンは雑学MAPへ登録します。\n"
                        "フォームでは通常雑学だけ/MAPだけ/両方を選べます。"
                    )],
                )
            else:
                reply_message(
                    reply_token,
                    [_text_message(
                        "コマンドを確認できませんでした。\n"
                        "「ヘルプ」と送ると使い方を表示します。\n"
                        "よく使う登録コマンド:\n"
                        "・新規\n"
                        "・新規(地図用)"
                    )],
                )

        elif event.get("type") == "postback":
            values = parse_qs(event.get("postback", {}).get("data", ""))
            action = values.get("action", [""])[0]
            raw_id = values.get("candidate_id", [""])[0]
            if not raw_id.isdigit():
                reply_message(reply_token, [_text_message("候補IDを確認できませんでした。")])
                continue
            db = SessionLocal()
            try:
                if action == "approve":
                    reply_message(
                        reply_token,
                        [_text_message(_approve_candidate_from_line(db, int(raw_id), user_id))],
                    )
                elif action == "reject":
                    candidate = reject_candidate(db, int(raw_id), f"line:{user_id}")
                    reply_message(reply_token, [_text_message(f"却下しました: {candidate.title}")])
                else:
                    reply_message(reply_token, [_text_message("不明な操作です。")])
            except CandidateError as exc:
                reply_message(reply_token, [_text_message(str(exc))])
            finally:
                db.close()
    return {"ok": True}


@router.get("/admin/candidates/{candidate_id}/edit", response_class=HTMLResponse)
def candidate_editor(candidate_id: int, token: str):
    _validate_editor_token(candidate_id, token)
    db = SessionLocal()
    try:
        candidate = db.query(TriviaCandidate).filter(TriviaCandidate.id == candidate_id).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return HTMLResponse(_editor_html(candidate, token, is_new=False))
    finally:
        db.close()


@router.get("/admin/candidates/new", response_class=HTMLResponse)
def new_candidate_editor(token: str, map: str = ""):
    _validate_editor_token(0, token)
    candidate = SimpleNamespace(
        id=0,
        title="",
        content="",
        explanation="",
        source="",
        category="その他",
        image_url="",
        map_address="",
        map_prefecture="",
        map_latitude=None,
        map_longitude=None,
        map_radius=None,
        map_hint="",
    )
    return HTMLResponse(_editor_html(candidate, token, is_new=True, map_mode=map in {"1", "true", "yes"}))


@router.post("/admin/candidates/new")
def save_new_candidate(request: CandidateUpdateRequest):
    _validate_editor_token(0, request.token)
    _validate_publish_target(request)
    _validate_map_request(request)
    db = SessionLocal()
    try:
        trivia_id = None
        if request.add_to_normal:
            trivia = _create_normal_trivia(
                db,
                title=request.title,
                content=request.content,
                explanation=request.explanation,
                source=request.source,
                category=request.category,
                image_url=request.image_url,
            )
            trivia_id = trivia.id
        if request.add_to_map:
            create_map_trivia(
                db,
                title=request.title,
                content=request.content,
                explanation=request.explanation,
                source=request.source,
                category=request.category,
                image_url=request.image_url,
                map_address=request.map_address,
                map_prefecture=request.map_prefecture,
                map_latitude=request.map_latitude,
                map_longitude=request.map_longitude,
                map_radius=request.map_radius,
                map_hint=request.map_hint,
            )
        return {
            "ok": True,
            "status": "approved",
            "trivia_id": trivia_id,
            "map_spot_id": None,
        }
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        db.close()


@router.post("/admin/candidates/image")
async def upload_candidate_image(
    token: str = Form(...),
    image: UploadFile = File(...),
):
    try:
        read_editor_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    try:
        image_url = upload_trivia_image(
            await image.read(),
            image.content_type or "",
            image.filename or "image",
        )
        return {"ok": True, "image_url": image_url}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.put("/admin/candidates/{candidate_id}/edit")
def save_candidate(candidate_id: int, request: CandidateUpdateRequest):
    _validate_editor_token(candidate_id, request.token)
    _validate_publish_target(request)
    _validate_map_request(request)
    db = SessionLocal()
    try:
        candidate = update_candidate(
            db,
            candidate_id,
            title=request.title,
            content=request.content,
            explanation=request.explanation,
            source=request.source,
            category=request.category,
            image_url=request.image_url,
            map_address=request.map_address,
            map_prefecture=request.map_prefecture,
            map_latitude=request.map_latitude if request.add_to_map else None,
            map_longitude=request.map_longitude if request.add_to_map else None,
            map_radius=request.map_radius if request.add_to_map else None,
            map_hint=request.map_hint,
        )
        trivia_id = None
        if request.add_to_normal:
            trivia = approve_candidate(db, candidate_id, "mobile-editor")
            trivia_id = trivia.id
        if request.add_to_map:
            create_map_trivia_from_candidate(db, candidate)
            if not request.add_to_normal:
                reject_candidate(db, candidate_id, "mobile-editor:map-published")
        return {"ok": True, "status": "approved", "trivia_id": trivia_id, "map_spot_id": None}
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        db.close()


def _validate_editor_token(candidate_id: int, token: str) -> None:
    try:
        token_candidate_id = read_editor_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if token_candidate_id != candidate_id:
        raise HTTPException(status_code=403, detail="Token does not match candidate")


def _editor_html(candidate: TriviaCandidate, token: str, is_new: bool, map_mode: bool = False) -> str:
    options = "".join(
        f'<option value="{html.escape(category)}"'
        f'{" selected" if category == candidate.category else ""}>{html.escape(category)}</option>'
        for category in TRIVIA_CATEGORIES
    )
    value = lambda raw: html.escape(raw or "")
    heading = "新しい地図用雑学を登録" if is_new and map_mode else ("新しい雑学を登録" if is_new else f"雑学候補 #{candidate.id}")
    method = "POST" if is_new else "PUT"
    map_address_value = value(getattr(candidate, "map_address", "") or "")
    map_prefecture_value = value(getattr(candidate, "map_prefecture", "") or "")
    map_latitude_value = getattr(candidate, "map_latitude", None) or 35.6812
    map_longitude_value = getattr(candidate, "map_longitude", None) or 139.7671
    map_radius_value = getattr(candidate, "map_radius", None) or 300
    has_map_values = any([
        getattr(candidate, "map_address", None),
        getattr(candidate, "map_prefecture", None),
        getattr(candidate, "map_latitude", None) is not None,
        getattr(candidate, "map_longitude", None) is not None,
        getattr(candidate, "map_radius", None) is not None,
    ])
    map_checked = " checked" if map_mode or has_map_values else ""
    map_display = "block" if map_checked else "none"
    normal_checked = "" if map_mode or has_map_values else " checked"
    map_summary = ""
    if has_map_values:
        map_summary_parts = [
            getattr(candidate, "map_prefecture", None),
            getattr(candidate, "map_address", None),
        ]
        if getattr(candidate, "map_latitude", None) is not None and getattr(candidate, "map_longitude", None) is not None:
            map_summary_parts.append(f"{float(getattr(candidate, 'map_latitude')):.6f}, {float(getattr(candidate, 'map_longitude')):.6f}")
        map_summary = html.escape(" / ".join(str(part) for part in map_summary_parts if part))
    return f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>雑学を編集</title>
<style>
body{{margin:0;background:#f4f6f8;color:#17212b;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:680px;margin:auto;padding:20px 16px 48px}}.card{{background:white;padding:20px;border-radius:16px;box-shadow:0 4px 18px #00000012}}
h1{{font-size:22px;margin:0 0 18px}}label{{display:block;font-weight:700;margin-top:16px}}
input,textarea,select{{width:100%;box-sizing:border-box;margin-top:7px;padding:12px;border:1px solid #cbd3da;border-radius:10px;font-size:16px}}
textarea{{min-height:110px;resize:vertical}}.actions{{display:grid;gap:10px;margin-top:22px}}
button{{border:0;border-radius:11px;padding:14px;font-size:16px;font-weight:700}}.save{{background:#e8edf1}}.publish{{background:#1db446;color:white}}
.check{{display:flex;gap:10px;align-items:center;margin-top:18px}}.check input{{width:auto;margin:0}}
.mapbox{{display:{map_display};margin-top:12px;padding:14px;border:1px solid #d7dee5;border-radius:12px;background:#fbfcfd}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.smallbtn{{margin-top:10px;background:#e8edf1;width:100%}}
#message{{margin-top:14px;min-height:24px;font-weight:700}}
</style></head><body><main><div class="card">
<h1>{heading}</h1>
<label>タイトル<input id="title" value="{value(candidate.title)}"></label>
<label>本文<textarea id="content">{value(candidate.content)}</textarea></label>
<label>解説<textarea id="explanation">{value(candidate.explanation)}</textarea></label>
<label>カテゴリ<select id="category">{options}</select></label>
<label>出典URL<input id="source" type="url" value="{value(candidate.source)}"></label>
<label>画像URL / R2キー<input id="image_url" value="{value(candidate.image_url)}"></label>
<label>スマホから画像を選択<input id="image_file" type="file" accept="image/*"></label>
<img id="image_preview" alt="" style="display:none;width:100%;margin-top:12px;border-radius:10px">
<label class="check"><input id="add_to_normal" type="checkbox"{normal_checked}>通常の雑学に追加</label>
<label class="check"><input id="add_to_map" type="checkbox"{map_checked} onchange="toggleMap()">雑学MAPに追加</label>
{f'<div class="mapbox" style="display:block"><strong>収集済みMAP情報</strong><br>{map_summary}</div>' if map_summary else ''}
<div id="map_section" class="mapbox">
<label>都道府県<input id="map_prefecture" placeholder="東京都" value="{map_prefecture_value}"></label>
<div class="grid2">
<label>緯度<input id="map_latitude" inputmode="decimal" value="{float(map_latitude_value):.6f}"></label>
<label>経度<input id="map_longitude" inputmode="decimal" value="{float(map_longitude_value):.6f}"></label>
</div>
<button class="smallbtn" onclick="fillCurrentLocation()">現在地を自動入力</button>
<label>住所・施設名<input id="map_address" value="{map_address_value}" placeholder="東京都港区芝公園4-2-8 / 東京タワー"></label>
<label>解放半径（m）<input id="map_radius" inputmode="numeric" value="{int(map_radius_value)}"></label>
<label>MAP ID（空欄なら自動生成）<input id="map_spot_id" placeholder="tokyo_001"></label>
</div>
<div class="actions"><button class="publish" onclick="submitCandidate()">登録する</button></div><div id="message"></div>
</div></main><script>
const editorToken={json.dumps(token)};
function toggleMap(){{
 document.getElementById("map_section").style.display=document.getElementById("add_to_map").checked?"block":"none";
}}
function fillCurrentLocation(){{
 const message=document.getElementById("message");
 if(!navigator.geolocation){{message.textContent="この端末では現在地を取得できません。";return}}
 message.textContent="現在地を取得中...";
 navigator.geolocation.getCurrentPosition(position=>{{
  document.getElementById("map_latitude").value=position.coords.latitude.toFixed(6);
  document.getElementById("map_longitude").value=position.coords.longitude.toFixed(6);
  message.textContent="現在地を入力しました。都道府県も確認してください。";
 }},()=>{{message.textContent="現在地を取得できませんでした。位置情報の許可を確認してください。";}},{{enableHighAccuracy:true,timeout:10000}});
}}
document.getElementById("image_file").addEventListener("change",event=>{{
 const file=event.target.files[0],preview=document.getElementById("image_preview");
 if(!file){{preview.style.display="none";return}}
 preview.src=URL.createObjectURL(file);preview.style.display="block";
}});
async function submitCandidate(){{
 const message=document.getElementById("message");message.textContent="保存中...";
 let imageUrl=document.getElementById("image_url").value;
 const imageFile=document.getElementById("image_file").files[0];
 if(imageFile){{
  message.textContent="画像をアップロード中...";
  const formData=new FormData();formData.append("token",editorToken);formData.append("image",imageFile);
  const uploadResponse=await fetch("/admin/candidates/image",{{method:"POST",body:formData}});
  const uploadData=await uploadResponse.json();
  if(!uploadResponse.ok){{message.textContent=uploadData.detail||"画像をアップロードできませんでした。";return}}
  imageUrl=uploadData.image_url;document.getElementById("image_url").value=imageUrl;
 }}
 message.textContent="保存中...";
 const addToMap=document.getElementById("add_to_map").checked;
 const addToNormal=document.getElementById("add_to_normal").checked;
 if(!addToNormal&&!addToMap){{message.textContent="通常の雑学、雑学MAPのどちらかは選択してください。";return}}
 if(addToMap&&!document.getElementById("map_prefecture").value.trim()){{message.textContent="雑学MAPには都道府県が必要です。";return}}
 if(addToMap&&!document.getElementById("map_address").value.trim()){{message.textContent="雑学MAPには住所・施設名が必要です。";return}}
 const response=await fetch(window.location.pathname,{{method:"{method}",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{
 token:editorToken,title:document.getElementById("title").value,content:document.getElementById("content").value,
 explanation:document.getElementById("explanation").value,category:document.getElementById("category").value,add_to_normal:addToNormal,
 source:document.getElementById("source").value,image_url:imageUrl,publish:true,add_to_map:addToMap,
 map_spot_id:document.getElementById("map_spot_id").value,
 map_address:document.getElementById("map_address").value,
 map_prefecture:document.getElementById("map_prefecture").value,
 map_latitude:Number(document.getElementById("map_latitude").value),
 map_longitude:Number(document.getElementById("map_longitude").value),
 map_radius:Number(document.getElementById("map_radius").value),
 map_hint:""}})}});
 const data=await response.json();message.textContent=response.ok?"登録しました。LINEへ戻ってください。":(data.detail||"保存できませんでした。");
}}
</script></body></html>"""
