import html
import json
import os
import time
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database import SessionLocal
from models import SocialContentJob, Trivia, TriviaCandidate
from services.line_bot import (
    SOCIAL_TEXT_REVIEW_MESSAGE_VERSION,
    candidate_carousel_message,
    is_allowed_user,
    mark_line_sent,
    new_candidate_message,
    push_message,
    push_social_text_review,
    read_editor_token,
    read_social_editor_token,
    reply_message,
    verify_signature,
)
from services.social_pipeline import (
    approve_content_job,
    configured_text_platforms,
    configured_video_platforms,
    process_due_video_jobs,
    publish_due_text_jobs,
    reject_content_job,
    video_publishing_is_manual,
)
from services.trivia_candidates import (
    CandidateError,
    approve_candidate,
    create_candidate,
    create_candidates,
    reject_candidate,
)
from services.image_storage import upload_trivia_image
from services.admin_workflow import create_manual_trivia, publish_candidate
from services.trivia_collection import TriviaCollectionDiagnostics, collect_trivia_candidates
from services.trivia_generation import TRIVIA_CATEGORIES, generate_trivia
from services.social_content import x_weighted_length


router = APIRouter()


class CandidateUpdateRequest(BaseModel):
    token: str
    title: str
    content: str
    explanation: str = ""
    source: str = ""
    category: str = "その他"
    image_url: str = ""
    image_urls: list[str] | None = None
    image_sources: dict[str, str] | None = None
    publish: bool = False
    add_to_normal: bool = True
    add_to_map: bool = False
    map_spot_id: str = ""
    map_address: str = ""
    map_prefecture: str = ""
    map_latitude: float = 35.6812
    map_longitude: float = 139.7671
    map_radius: int = 1200
    map_hint: str = ""


def _request_image_values(request: CandidateUpdateRequest) -> dict:
    """Omitted image fields must not replace an existing candidate's gallery."""
    values = {}
    if request.image_sources is not None:
        values["image_sources"] = request.image_sources
    if request.image_urls is not None:
        values["image_urls"] = request.image_urls
    elif "image_url" in request.model_fields_set:
        values["image_url"] = request.image_url
    return values


class SocialTextUpdateRequest(BaseModel):
    token: str
    text: str


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
        try:
            result = publish_candidate(
                db, candidate_id, add_to_normal=False, add_to_map=True,
                reviewed_by=f"line:{user_id}",
            )
        except CandidateError:
            raise
        except ValueError as exc:
            # The webhook reports CandidateError to the reviewer in LINE.
            raise CandidateError(str(exc)) from exc
        return f"MAPに公開しました: {result.map_trivia.title}"
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
        push_message(user_id, [
            _text_message(f"{len(candidates)}件生成しました。左右にスワイプして確認してください。"),
            candidate_carousel_message(candidates),
        ])
        for candidate in candidates:
            mark_line_sent(candidate)
        db.commit()
    except Exception as exc:
        push_message(user_id, [_text_message(f"生成中にエラーが発生しました: {exc}")])
    finally:
        db.close()


def _collect_and_push(user_id: str, topic: str, count: int, map_mode: bool = False) -> None:
    db = SessionLocal()
    diagnostics = TriviaCollectionDiagnostics()

    def record_diagnostics(value: TriviaCollectionDiagnostics) -> None:
        nonlocal diagnostics
        diagnostics = value

    try:
        candidates = collect_trivia_candidates(
            db,
            topic,
            count,
            map_mode=map_mode,
            diagnostics_callback=record_diagnostics,
        )
        if not candidates:
            if map_mode:
                detail = (
                    f"試行: {diagnostics.attempts}回 / 生成: {diagnostics.generated}件\n"
                    f"位置情報通過: {diagnostics.complete_map}件 / "
                    f"品質通過: {diagnostics.quality_accepted}件 / "
                    f"重複除外: {diagnostics.duplicates}件"
                )
                if diagnostics.generated == 0:
                    reason = "生成段階で候補が作られていません。"
                elif diagnostics.complete_map == 0:
                    reason = "住所・座標などの位置情報が揃わず、全候補が除外されました。"
                elif diagnostics.quality_accepted == 0:
                    reason = "位置情報は揃いましたが、全候補が品質審査で除外されました。"
                elif diagnostics.duplicates >= diagnostics.quality_accepted:
                    reason = "品質審査を通過した候補が、既存候補との重複で除外されました。"
                else:
                    reason = "候補が最終保存条件を満たしませんでした。"
                message = f"地図収集で候補が残りませんでした。\n{detail}\n{reason}"
            else:
                message = "重複または品質基準を除くと、収集できる候補がありませんでした。"
            push_message(
                user_id,
                [_text_message(message)],
            )
            return
        push_message(user_id, [
            _text_message(
                f"Webから{len(candidates)}件の{'地図用' if map_mode else ''}題材を収集しました。確認してください。"
            ),
            candidate_carousel_message(candidates),
        ])
        for candidate in candidates:
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
        push_message(user_id, [
            _text_message(f"承認待ちを{len(candidates)}件送ります。左右にスワイプして確認してください。"),
            candidate_carousel_message(candidates),
        ])
        for candidate in candidates:
            mark_line_sent(candidate)
        db.commit()
    finally:
        db.close()


def _social_publish_status_text(job: SocialContentJob) -> str:
    labels = {"x": "X", "instagram": "Instagram", "tiktok": "TikTok"}
    rows = [
        f"{labels.get(item.platform, item.platform)}: {item.status}"
        for item in job.publish_jobs
        if item.platform != "threads"
    ]
    return "投稿処理の状況\n" + "\n".join(rows)


def _publish_social_after_approval(content_job_id: int, user_id: str) -> None:
    db = SessionLocal()
    try:
        publish_due_text_jobs(db)
        enabled_video = configured_video_platforms()
        poll_count = max(1, min(int(os.getenv("SOCIAL_VIDEO_PUBLISH_POLL_COUNT", "5")), 10))
        poll_seconds = max(15, min(int(os.getenv("SOCIAL_VIDEO_PUBLISH_POLL_SECONDS", "60")), 60))
        for index in range(poll_count):
            process_due_video_jobs(db, content_job_id=content_job_id)
            db.expire_all()
            job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
            pending = any(
                item.platform in enabled_video and item.status == "publishing"
                for item in job.publish_jobs
            )
            if not pending or index == poll_count - 1:
                break
            time.sleep(poll_seconds)
        db.expire_all()
        job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
        push_message(user_id, [_text_message(_social_publish_status_text(job))])
    except Exception as exc:
        push_message(user_id, [_text_message(f"投稿処理でエラーが発生しました: {exc}")])
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
            if action in {"social_approve", "social_reject"}:
                raw_content_id = values.get("content_job_id", [""])[0]
                if not raw_content_id.isdigit():
                    reply_message(reply_token, [_text_message("動画ジョブIDを確認できませんでした。")])
                    continue
                db = SessionLocal()
                try:
                    content_job_id = int(raw_content_id)
                    if action == "social_approve":
                        existing = db.query(SocialContentJob).filter_by(id=content_job_id).one()
                        if existing.status == "approved":
                            kind = "動画" if existing.video_jobs else "投稿案"
                            reply_message(reply_token, [_text_message(f"この{kind}はすでに承認済みです。")])
                            continue
                        job = approve_content_job(db, content_job_id)
                        if job.video_jobs and video_publishing_is_manual():
                            reply_message(
                                reply_token,
                                [_text_message(
                                    "確認済みにしました。LINEの動画URLと投稿文を使って、"
                                    "Instagram・TikTok・YouTube Shortsへ手動で投稿してください。"
                                )],
                            )
                            continue
                        configured = configured_text_platforms() | configured_video_platforms()
                        enabled = {
                            item.platform for item in job.publish_jobs
                            if item.platform in configured
                        }
                        if enabled:
                            names = ", ".join(sorted(enabled))
                            reply_message(
                                reply_token,
                                [_text_message(f"承認しました。投稿を開始します: {names}")],
                            )
                            background_tasks.add_task(
                                _publish_social_after_approval,
                                job.id,
                                user_id,
                            )
                        else:
                            reply_message(
                                reply_token,
                                [_text_message(
                                    "承認しました。ただし投稿先がまだ有効化されていないため、投稿待ちにしています。"
                                )],
                            )
                    else:
                        job = reject_content_job(db, content_job_id)
                        reply_message(
                            reply_token,
                            [_text_message(f"今回は投稿しません: {job.trivia.title}")],
                        )
                except Exception as exc:
                    reply_message(reply_token, [_text_message(str(exc))])
                finally:
                    db.close()
                continue
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


@router.get("/admin/social/{content_job_id}/edit", response_class=HTMLResponse)
def social_text_editor(content_job_id: int, token: str):
    _validate_social_editor_token(content_job_id, token)
    db = SessionLocal()
    try:
        job = _editable_social_text_job(db, content_job_id)
        text = str(((job.content_json or {}).get("x") or {}).get("text") or "")
        return HTMLResponse(_social_text_editor_html(job, token, text))
    finally:
        db.close()


@router.put("/admin/social/{content_job_id}/edit")
def save_social_text(content_job_id: int, request: SocialTextUpdateRequest):
    _validate_social_editor_token(content_job_id, request.token)
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="投稿文を入力してください。")
    if x_weighted_length(text) > 280:
        raise HTTPException(status_code=400, detail="投稿文をXの280ウェイト以内にしてください。")
    db = SessionLocal()
    try:
        job = _editable_social_text_job(db, content_job_id)
        content = dict(job.content_json or {})
        x_content = dict(content.get("x") or {})
        x_content["text"] = text
        content["x"] = x_content
        automation = dict(content.get("automation") or {})
        automation.pop("line_review", None)
        automation["line_edited_at"] = datetime.utcnow().isoformat()
        content["automation"] = automation
        job.content_json = content
        db.commit()
        db.refresh(job)

        notification_error = None
        try:
            recipients = push_social_text_review(job)
            review_meta = {
                "image_url": str((content.get("shared_image") or {}).get("url") or ""),
                "sent_at": datetime.utcnow().isoformat(),
                "recipient_count": recipients,
                "message_version": SOCIAL_TEXT_REVIEW_MESSAGE_VERSION,
            }
        except Exception as exc:
            notification_error = str(exc)[:500]
            review_meta = {"error": notification_error}
        content = dict(job.content_json or {})
        automation = dict(content.get("automation") or {})
        automation["line_review"] = review_meta
        content["automation"] = automation
        job.content_json = content
        db.commit()
        return {
            "ok": True,
            "status": "review",
            "notification_sent": notification_error is None,
            "notification_error": notification_error,
        }
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
        image_urls=[],
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
        result = create_manual_trivia(
            db,
            add_to_normal=request.add_to_normal,
            add_to_map=request.add_to_map,
            title=request.title,
            content=request.content,
            explanation=request.explanation,
            source=request.source,
            category=request.category,
            **_request_image_values(request),
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
            "trivia_id": result.trivia.id if result.trivia else None,
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
        result = publish_candidate(
            db,
            candidate_id,
            add_to_normal=request.add_to_normal,
            add_to_map=request.add_to_map,
            reviewed_by="mobile-editor",
            title=request.title,
            content=request.content,
            explanation=request.explanation,
            source=request.source,
            category=request.category,
            **_request_image_values(request),
            map_address=request.map_address,
            map_prefecture=request.map_prefecture,
            map_latitude=request.map_latitude if request.add_to_map else None,
            map_longitude=request.map_longitude if request.add_to_map else None,
            map_radius=request.map_radius if request.add_to_map else None,
            map_hint=request.map_hint,
        )
        return {
            "ok": True,
            "status": "approved",
            "trivia_id": result.trivia.id if result.trivia else None,
            "map_spot_id": None,
        }
    except CandidateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        db.close()


def _validate_social_editor_token(content_job_id: int, token: str) -> None:
    try:
        token_content_job_id = read_social_editor_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if token_content_job_id != content_job_id:
        raise HTTPException(status_code=403, detail="Token does not match social content")


def _editable_social_text_job(db, content_job_id: int) -> SocialContentJob:
    job = db.query(SocialContentJob).filter_by(id=content_job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="投稿案が見つかりません。")
    if job.video_jobs:
        raise HTTPException(status_code=400, detail="この画面では動画投稿文を編集できません。")
    if job.status != "review":
        raise HTTPException(status_code=409, detail="承認待ちの投稿案だけ編集できます。")
    return job


def _validate_editor_token(candidate_id: int, token: str) -> None:
    try:
        token_candidate_id = read_editor_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if token_candidate_id != candidate_id:
        raise HTTPException(status_code=403, detail="Token does not match candidate")


def _social_text_editor_html(content_job: SocialContentJob, token: str, text: str) -> str:
    title = html.escape(content_job.trivia.title or f"投稿案 #{content_job.id}")
    return f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>X投稿文を編集</title>
<style>
body{{margin:0;background:#f4f6f8;color:#17212b;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:680px;margin:auto;padding:20px 16px 48px}}.card{{background:white;padding:20px;border-radius:16px;box-shadow:0 4px 18px #00000012}}
h1{{font-size:22px;margin:0 0 8px}}.subject{{color:#667085;margin-bottom:18px}}
textarea{{width:100%;min-height:260px;box-sizing:border-box;padding:14px;border:1px solid #cbd3da;border-radius:10px;font-size:17px;line-height:1.6;resize:vertical}}
.counter{{margin-top:8px;color:#667085;font-size:14px}}button{{width:100%;margin-top:20px;border:0;border-radius:11px;padding:14px;background:#1db446;color:white;font-size:16px;font-weight:700}}
#message{{margin-top:14px;min-height:24px;font-weight:700;white-space:pre-wrap}}
</style></head><body><main><div class="card">
<h1>X投稿文を編集</h1><div class="subject">{title}</div>
<textarea id="text" maxlength="5000">{html.escape(text)}</textarea>
<div class="counter" id="counter"></div>
<button onclick="saveText()">保存してLINEへ再送</button><div id="message"></div>
</div></main><script>
const editorToken={json.dumps(token)};
const textArea=document.getElementById("text"),counter=document.getElementById("counter"),message=document.getElementById("message");
function updateCounter(){{counter.textContent=`${{[...textArea.value].length}}文字（Xでは全角文字などを2ウェイトで数える場合があります）`;}}
textArea.addEventListener("input",updateCounter);updateCounter();
async function saveText(){{
 message.textContent="保存中...";
 const response=await fetch(window.location.pathname,{{method:"PUT",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{token:editorToken,text:textArea.value}})}});
 const data=await response.json();
 if(!response.ok){{message.textContent=data.detail||"保存できませんでした。";return}}
 message.textContent=data.notification_sent?"保存しました。更新後の承認カードをLINEへ送りました。":"保存しました。LINE再送に失敗したため、次回の自動処理で再送します。";
}}
</script></body></html>"""


def _editor_html(candidate: TriviaCandidate, token: str, is_new: bool, map_mode: bool = False) -> str:
    options = "".join(
        f'<option value="{html.escape(category)}"'
        f'{" selected" if category == candidate.category else ""}>{html.escape(category)}</option>'
        for category in TRIVIA_CATEGORIES
    )
    value = lambda raw: html.escape(raw or "")
    image_urls = getattr(candidate, "image_urls", None)
    if image_urls is None:
        image_urls = [candidate.image_url] if candidate.image_url else []
    image_urls_value = value("\n".join(image_urls))
    image_sources_value = html.escape(json.dumps(getattr(candidate, "image_sources", None) or {}, ensure_ascii=False))
    image_base_url = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
    heading = "新しい地図用雑学を登録" if is_new and map_mode else ("新しい雑学を登録" if is_new else f"雑学候補 #{candidate.id}")
    method = "POST" if is_new else "PUT"
    map_address_value = value(getattr(candidate, "map_address", "") or "")
    map_prefecture_value = value(getattr(candidate, "map_prefecture", "") or "")
    map_hint_value = value(getattr(candidate, "map_hint", "") or "")
    map_latitude_value = getattr(candidate, "map_latitude", None) or 35.6812
    map_longitude_value = getattr(candidate, "map_longitude", None) or 139.7671
    map_radius_value = getattr(candidate, "map_radius", None) or 1200
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
        if getattr(candidate, "map_hint", None):
            map_summary_parts.append(f"現地ポイント: {getattr(candidate, 'map_hint')}")
        map_summary = html.escape(" / ".join(str(part) for part in map_summary_parts if part))
    return rf"""<!doctype html>
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
.help{{color:#667085;font-size:13px;line-height:1.6;margin-top:6px}}.gallery{{display:grid;gap:12px;margin-top:12px}}
.photo{{margin:0;padding:12px;border:1px solid #d7dee5;border-radius:12px;overflow:hidden}}
.photo img{{display:block;max-height:260px;width:100%;object-fit:contain;border-radius:8px;background:#f4f6f8}}
.photo figcaption{{margin-top:8px;font-size:14px;overflow-wrap:anywhere}}.photo-actions{{display:flex;gap:8px;margin-top:8px}}
.photo-actions button{{flex:1;padding:10px;background:#e8edf1;font-size:14px}}button:disabled{{opacity:.45}}#image_urls{{min-height:100px}}
#message{{margin-top:14px;min-height:24px;font-weight:700}}
</style></head><body><main><div class="card">
<h1>{heading}</h1>
<label>タイトル<input id="title" value="{value(candidate.title)}"></label>
<label>本文<textarea id="content">{value(candidate.content)}</textarea></label>
<label>解説<textarea id="explanation">{value(candidate.explanation)}</textarea></label>
<label>カテゴリ<select id="category">{options}</select></label>
<label>出典URL<input id="source" type="url" value="{value(candidate.source)}"></label>
<label>写真URL / R2キー（1行に1枚）<textarea id="image_urls">{image_urls_value}</textarea></label>
<textarea id="image_sources" hidden>{image_sources_value}</textarea>
<div class="help">写真は10枚まで登録できます。1枚目を表紙として、アプリにはこの順番で表示します。下のボタンで順番の変更・削除ができます。</div>
<label>スマホから写真を追加<input id="image_file" type="file" accept="image/*" multiple></label>
<div class="help">複数の写真を選択できます。1枚12MBまで。写真の削除はこの雑学から外す操作です。</div>
<div id="image_count" class="help" aria-live="polite"></div><div id="image_gallery" class="gallery"></div>
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
<label>現地ポイント<textarea id="map_hint" placeholder="現地で探す場所や見どころ、公開条件など">{map_hint_value}</textarea></label>
<label>MAP ID（空欄なら自動生成）<input id="map_spot_id" placeholder="tokyo_001"></label>
</div>
<div class="actions"><button class="publish" onclick="submitCandidate()">登録する</button></div><div id="message"></div>
</div></main><script>
const editorToken={json.dumps(token)};
const imageBaseUrl={json.dumps(image_base_url)};
const imageUrlInput=document.getElementById("image_urls"),imageFileInput=document.getElementById("image_file");
const savedImageSources=JSON.parse(document.getElementById("image_sources").value);
let gallery=[],submitting=false;
function urlLines(){{return [...new Set(imageUrlInput.value.split(/\r?\n/).map(value=>value.trim()).filter(Boolean))];}}
function syncImageUrls(){{imageUrlInput.value=gallery.filter(item=>item.url).map(item=>item.url).join("\n");}}
function previewUrl(reference){{
 if(/^https?:\/\//i.test(reference))return reference;
 if(!imageBaseUrl||/^\w+:/.test(reference)||reference.startsWith("//"))return "";
 return imageBaseUrl+"/"+reference.replace(/^\/+/,"").split("/").map(encodeURIComponent).join("/");
}}
function moveImage(index,direction){{
 if(submitting)return;
 const target=index+direction;
 if(target<0||target>=gallery.length)return;
 [gallery[index],gallery[target]]=[gallery[target],gallery[index]];syncImageUrls();renderGallery();
}}
function removeImage(index){{
 if(submitting)return;
 const item=gallery.splice(index,1)[0];if(item.preview)URL.revokeObjectURL(item.preview);
 syncImageUrls();renderGallery();
}}
function renderGallery(){{
 const container=document.getElementById("image_gallery");container.replaceChildren();
 document.getElementById("image_count").textContent=`${{gallery.length}} / 10枚`;
 gallery.forEach((item,index)=>{{
  const figure=document.createElement("figure");figure.className="photo";
  const preview=item.preview||previewUrl(item.url),caption=document.createElement("figcaption");
  if(preview){{const image=document.createElement("img");image.src=preview;image.alt=`写真 ${{index+1}}`;figure.append(image);}}
  caption.textContent=`${{index+1}}枚目${{index===0?"（表紙）":""}}・${{item.file?item.file.name+"（アップロード待ち）":item.url}}`;
  figure.append(caption);
  const sourceLabel=document.createElement("label"),sourceInput=document.createElement("input");
  sourceLabel.textContent="写真の出典";sourceInput.type="text";sourceInput.value=item.source||"";
  sourceInput.placeholder="出典URL または 撮影者・提供元";sourceInput.disabled=submitting;
  sourceInput.oninput=()=>{{item.source=sourceInput.value;}};sourceLabel.append(sourceInput);figure.append(sourceLabel);
  const actions=document.createElement("div");actions.className="photo-actions";
  [["前へ",()=>moveImage(index,-1),index===0],["次へ",()=>moveImage(index,1),index===gallery.length-1],["削除",()=>removeImage(index),false]].forEach(([label,action,disabled])=>{{
   const button=document.createElement("button");button.type="button";button.textContent=label;
   button.setAttribute("aria-label",`写真${{index+1}}を${{label}}`);button.disabled=submitting||disabled;button.onclick=action;actions.append(button);
  }});figure.append(actions);container.append(figure);
 }});
}}
function readImageUrls(){{
 const pending=gallery.filter(item=>item.file),previous=gallery;
 gallery=urlLines().map(url=>previous.find(item=>item.url===url)||{{url,source:savedImageSources[url]||""}}).concat(pending);renderGallery();
}}
imageUrlInput.addEventListener("input",readImageUrls);readImageUrls();
imageFileInput.addEventListener("change",event=>{{
 const message=document.getElementById("message"),knownKeys=new Set(gallery.map(item=>item.fileKey));
 const files=[...event.target.files].filter(file=>{{const key=[file.name,file.size,file.lastModified].join(":");if(knownKeys.has(key))return false;knownKeys.add(key);return true;}});
 imageFileInput.value="";
 if(gallery.length+files.length>10){{message.textContent="写真は合計10枚までです。枚数を減らして選び直してください。";return}}
 if(files.some(file=>!file.type.startsWith("image/")||file.size===0||file.size>12*1024*1024)){{message.textContent="写真は1枚12MB以下の画像ファイルを選択してください。";return}}
 files.forEach(file=>gallery.push({{file,preview:URL.createObjectURL(file),fileKey:[file.name,file.size,file.lastModified].join(":")}}));
 message.textContent="";renderGallery();
}});
function validateImageReferences(){{
 for(const item of gallery){{
  if(!item.url)continue;
  const reference=item.url;
  if(/[\x00-\x1f\\]/.test(reference)||reference.startsWith("//"))return false;
  if(/^[a-z][a-z0-9+.-]*:/i.test(reference)){{
   try{{const parsed=new URL(reference);if(!["http:","https:"].includes(parsed.protocol)||!parsed.hostname||parsed.username||parsed.password)return false;}}catch{{return false;}}
  }}else if(reference.split("/").some(part=>part==="."||part===".."))return false;
 }}return true;
}}
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
async function submitCandidate(){{
 if(submitting)return;
 const message=document.getElementById("message");
 const addToMap=document.getElementById("add_to_map").checked;
 const addToNormal=document.getElementById("add_to_normal").checked;
 if(!document.getElementById("title").value.trim()||!document.getElementById("content").value.trim()){{message.textContent="タイトルと本文は必須です。";return}}
 if(!addToNormal&&!addToMap){{message.textContent="通常の雑学、雑学MAPのどちらかは選択してください。";return}}
 if(addToMap&&!document.getElementById("map_prefecture").value.trim()){{message.textContent="雑学MAPには都道府県が必要です。";return}}
 if(addToMap&&!document.getElementById("map_address").value.trim()){{message.textContent="雑学MAPには住所・施設名が必要です。";return}}
 if(gallery.length>10){{message.textContent="写真は合計10枚までです。";return}}
 if(!validateImageReferences()){{message.textContent="写真URL / R2キーの形式を確認してください。";return}}
 const latitude=Number(document.getElementById("map_latitude").value),longitude=Number(document.getElementById("map_longitude").value),radius=Number(document.getElementById("map_radius").value);
 if(addToMap&&(!Number.isFinite(latitude)||Math.abs(latitude)>90||!Number.isFinite(longitude)||Math.abs(longitude)>180||!Number.isInteger(radius)||radius<10||radius>5000)){{message.textContent="緯度・経度・解放半径（10〜5000m）を確認してください。";return}}
 submitting=true;document.querySelectorAll("input,textarea,select,button").forEach(element=>element.disabled=true);renderGallery();
 try{{
 for(const item of gallery){{
  if(!item.file)continue;
  message.textContent="写真をアップロード中...";
  const formData=new FormData();formData.append("token",editorToken);formData.append("image",item.file);
  const uploadResponse=await fetch("/admin/candidates/image",{{method:"POST",body:formData}});
  const uploadData=await uploadResponse.json();
  if(!uploadResponse.ok||!uploadData.image_url)throw new Error(uploadData.detail||"写真をアップロードできませんでした。");
  item.url=uploadData.image_url;delete item.file;URL.revokeObjectURL(item.preview);delete item.preview;
  syncImageUrls();renderGallery();
 }}
 const imageUrls=gallery.map(item=>item.url);syncImageUrls();message.textContent="保存中...";
 const response=await fetch(window.location.pathname,{{method:"{method}",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{
 token:editorToken,title:document.getElementById("title").value,content:document.getElementById("content").value,
 explanation:document.getElementById("explanation").value,category:document.getElementById("category").value,add_to_normal:addToNormal,
 source:document.getElementById("source").value,image_urls:imageUrls,
 image_sources:Object.fromEntries(gallery.filter(item=>item.source?.trim()).map(item=>[item.url,item.source.trim()])),publish:true,add_to_map:addToMap,
 map_spot_id:document.getElementById("map_spot_id").value,
 map_address:document.getElementById("map_address").value,
 map_prefecture:document.getElementById("map_prefecture").value,
 map_latitude:latitude,
 map_longitude:longitude,
 map_radius:radius,
 map_hint:document.getElementById("map_hint").value}})}});
 const data=await response.json();
 if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"入力内容を確認してください。");
 message.textContent="登録しました。LINEへ戻ってください。";
 }}catch(error){{message.textContent=(error.message||"保存できませんでした。")+" 入力内容とアップロード済みの写真は残っています。確認して再試行してください。";}}
 finally{{submitting=false;document.querySelectorAll("input,textarea,select,button").forEach(element=>element.disabled=false);renderGallery();}}
}}
</script></body></html>"""
