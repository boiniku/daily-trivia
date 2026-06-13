import html
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database import SessionLocal
from models import TriviaCandidate
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


def _text_message(text: str) -> dict:
    return {"type": "text", "text": text[:5000]}


def _parse_generate_command(text: str) -> tuple[str, int] | None:
    normalized = text.strip()
    prefix = next((value for value in ("生成", "作成") if normalized.startswith(value)), None)
    if not prefix:
        return None
    parts = normalized[len(prefix):].strip().split()
    count = 3
    if parts and parts[-1].isdigit():
        count = max(1, min(int(parts.pop()), 10))
    return " ".join(parts) or "ランダム", count


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
            command = _parse_generate_command(message_text)
            if command:
                topic, count = command
                reply_message(reply_token, [_text_message(f"「{topic}」の雑学を{count}件生成します。")])
                background_tasks.add_task(_generate_and_push, user_id, topic, count)
            elif message_text in {"候補", "承認待ち", "一覧"}:
                reply_message(reply_token, [_text_message("承認待ちの候補を確認します。")])
                background_tasks.add_task(_push_pending_candidates, user_id)
            elif message_text in {"新規", "手入力", "登録"}:
                reply_message(reply_token, [new_candidate_message()])
            else:
                reply_message(
                    reply_token,
                    [_text_message(
                        "使い方:\n"
                        "・生成 宇宙 3\n"
                        "・候補\n"
                        "・新規\n"
                        "生成件数は最大10件です。"
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
                    trivia = approve_candidate(db, int(raw_id), f"line:{user_id}")
                    reply_message(reply_token, [_text_message(f"公開しました: #{trivia.id} {trivia.title}")])
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
def new_candidate_editor(token: str):
    _validate_editor_token(0, token)
    candidate = SimpleNamespace(
        id=0,
        title="",
        content="",
        explanation="",
        source="",
        category="その他",
        image_url="",
    )
    return HTMLResponse(_editor_html(candidate, token, is_new=True))


@router.post("/admin/candidates/new")
def save_new_candidate(request: CandidateUpdateRequest):
    _validate_editor_token(0, request.token)
    db = SessionLocal()
    try:
        candidate = create_candidate(db, {
            "title": request.title,
            "content": request.content,
            "explanation": request.explanation,
            "source": request.source,
            "category": request.category,
            "image_url": request.image_url,
        })
        trivia_id = None
        if request.publish:
            trivia_id = approve_candidate(db, candidate.id, "mobile-editor")
            trivia_id = trivia_id.id
        return {
            "ok": True,
            "candidate_id": candidate.id,
            "status": "approved" if trivia_id else candidate.status,
            "trivia_id": trivia_id,
        }
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
        )
        trivia_id = None
        if request.publish:
            trivia_id = approve_candidate(db, candidate_id, "mobile-editor").id
        return {"ok": True, "status": "approved" if trivia_id else candidate.status, "trivia_id": trivia_id}
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        db.close()


def _validate_editor_token(candidate_id: int, token: str) -> None:
    try:
        token_candidate_id = read_editor_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if token_candidate_id != candidate_id:
        raise HTTPException(status_code=403, detail="Token does not match candidate")


def _editor_html(candidate: TriviaCandidate, token: str, is_new: bool) -> str:
    options = "".join(
        f'<option value="{html.escape(category)}"'
        f'{" selected" if category == candidate.category else ""}>{html.escape(category)}</option>'
        for category in TRIVIA_CATEGORIES
    )
    value = lambda raw: html.escape(raw or "")
    heading = "新しい雑学を登録" if is_new else f"雑学候補 #{candidate.id}"
    method = "POST" if is_new else "PUT"
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
<div class="actions"><button class="save" onclick="submitCandidate(false)">下書き保存</button>
<button class="publish" onclick="submitCandidate(true)">保存して公開</button></div><div id="message"></div>
</div></main><script>
const editorToken={json.dumps(token)};
document.getElementById("image_file").addEventListener("change",event=>{{
 const file=event.target.files[0],preview=document.getElementById("image_preview");
 if(!file){{preview.style.display="none";return}}
 preview.src=URL.createObjectURL(file);preview.style.display="block";
}});
async function submitCandidate(publish){{
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
 const response=await fetch(window.location.pathname,{{method:"{method}",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{
 token:editorToken,title:document.getElementById("title").value,content:document.getElementById("content").value,
 explanation:document.getElementById("explanation").value,category:document.getElementById("category").value,
 source:document.getElementById("source").value,image_url:imageUrl,publish}})}});
 const data=await response.json();message.textContent=response.ok?(publish?"公開しました。LINEへ戻ってください。":"下書きを保存しました。"):(data.detail||"保存できませんでした。");
}}
</script></body></html>"""
