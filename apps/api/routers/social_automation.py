import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from database import SessionLocal
from models import SocialContentJob, SocialPublishJob, SocialVideoJob
from services.social_pipeline import (
    STATIC_RENDER_VERSION,
    approve_content_job,
    create_daily_text_job,
    create_content_job,
    poll_video_job,
    publish_due_text_jobs,
    process_due_video_jobs,
    regenerate_content_job,
    render_static_video_job,
    submit_video_job,
)
from services.line_bot import (
    SOCIAL_TEXT_REVIEW_MESSAGE_VERSION,
    push_social_review,
    push_social_text_review,
)
from services.aivis_tts import generate_aivis_narration
from services.social_storage import upload_social_asset


router = APIRouter(prefix="/internal/social", tags=["social-automation"])


class PrepareRequest(BaseModel):
    trivia_id: int | None = None
    scheduled_at: datetime | None = None
    video_mode: str = "static"


class VoicePreviewRequest(BaseModel):
    styles: list[str] = Field(default_factory=list, max_length=3)


def _authorize(
    authorization: str | None,
    *,
    allow_scheduler_secret: bool = False,
) -> None:
    expected_values = [os.getenv("SOCIAL_AUTOMATION_SECRET", "").strip()]
    if allow_scheduler_secret:
        expected_values.append(os.getenv("DAILY_COLLECTION_SECRET", "").strip())
    expected_values = [value for value in expected_values if value]
    if not expected_values:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Social automation is not configured",
        )
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not any(
        secrets.compare_digest(supplied, expected) for expected in expected_values
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization")


def _send_line_review_if_needed(db, job: SocialVideoJob) -> None:
    review_meta = dict((job.prompt_json or {}).get("line_review") or {})
    if review_meta.get("video_url") == job.final_video_url and review_meta.get("sent_at"):
        return
    try:
        recipients = push_social_review(job.content_job, job)
        review_meta = {
            "video_url": job.final_video_url,
            "sent_at": datetime.utcnow().isoformat(),
            "recipient_count": recipients,
        }
    except Exception as exc:
        review_meta = {"video_url": job.final_video_url, "error": str(exc)[:500]}
    job.prompt_json = {**(job.prompt_json or {}), "line_review": review_meta}
    db.commit()
    db.refresh(job)


def _send_line_text_review_if_needed(db, job: SocialContentJob) -> dict:
    content = dict(job.content_json or {})
    automation = dict(content.get("automation") or {})
    review_meta = dict(automation.get("line_review") or {})
    image_url = str((content.get("shared_image") or {}).get("url") or "")
    if (
        review_meta.get("image_url") == image_url
        and review_meta.get("sent_at")
        and review_meta.get("message_version") == SOCIAL_TEXT_REVIEW_MESSAGE_VERSION
    ):
        return review_meta
    try:
        recipients = push_social_text_review(job)
        review_meta = {
            "image_url": image_url,
            "sent_at": datetime.utcnow().isoformat(),
            "recipient_count": recipients,
            "message_version": SOCIAL_TEXT_REVIEW_MESSAGE_VERSION,
        }
    except Exception as exc:
        review_meta = {"image_url": image_url, "error": str(exc)[:500]}
    automation["line_review"] = review_meta
    content["automation"] = automation
    job.content_json = content
    db.commit()
    db.refresh(job)
    return review_meta


@router.post("/prepare", status_code=status.HTTP_201_CREATED)
def prepare_social_content(
    request: PrepareRequest,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = create_content_job(
            db,
            request.trivia_id,
            scheduled_at=request.scheduled_at,
            video_mode=request.video_mode,
        )
        return _content_job_response(job)
    finally:
        db.close()


@router.post("/run-due")
def run_due_social_content(
    authorization: str | None = Header(default=None),
):
    """Create at most one static video per interval and send it to LINE for review."""
    _authorize(authorization, allow_scheduler_secret=True)
    db = SessionLocal()
    try:
        # Recover safely after a Render restart: only already-approved jobs are processed.
        publish_due_text_jobs(db)
        process_due_video_jobs(db)
        pending_review = (
            db.query(SocialContentJob)
            .filter(
                SocialContentJob.status == "review",
                SocialContentJob.video_jobs.any(),
            )
            .order_by(SocialContentJob.created_at.desc())
            .first()
        )
        if pending_review:
            video_job = next((item for item in pending_review.video_jobs if item.provider == "static"), None)
            if video_job and video_job.status == "ready":
                render_meta = (video_job.prompt_json or {}).get("render_meta") or {}
                if render_meta.get("pipeline_version") != STATIC_RENDER_VERSION:
                    video_job = render_static_video_job(db, video_job.id, force=True)
                    _send_line_review_if_needed(db, video_job)
                    return {
                        "status": "review",
                        "reason": "outdated_video_rerendered",
                        "content_job_id": pending_review.id,
                        "video_job": _video_job_response(video_job),
                    }
                _send_line_review_if_needed(db, video_job)
                return {
                    "status": "skipped",
                    "reason": "awaiting_line_review",
                    "content_job_id": pending_review.id,
                    "line_review": (video_job.prompt_json or {}).get("line_review"),
                }
            if video_job and video_job.status == "rendering":
                return {"status": "skipped", "reason": "rendering", "content_job_id": pending_review.id}
            if video_job:
                video_job = render_static_video_job(db, video_job.id)
                _send_line_review_if_needed(db, video_job)
                return {
                    "status": "review",
                    "content_job_id": pending_review.id,
                    "video_job": _video_job_response(video_job),
                }

        interval_days = max(1, min(int(os.getenv("SOCIAL_GENERATION_INTERVAL_DAYS", "4")), 31))
        latest = (
            db.query(SocialContentJob)
            .filter(SocialContentJob.video_jobs.any())
            .order_by(SocialContentJob.created_at.desc())
            .first()
        )
        if latest and latest.created_at > datetime.utcnow() - timedelta(days=interval_days):
            return {
                "status": "skipped",
                "reason": "interval_not_elapsed",
                "content_job_id": latest.id,
                "next_at": (latest.created_at + timedelta(days=interval_days)).isoformat(),
            }
        content_job = create_content_job(db, video_mode="static")
        video_job = render_static_video_job(db, content_job.video_jobs[0].id)
        _send_line_review_if_needed(db, video_job)
        return {
            "status": "review",
            "content_job_id": content_job.id,
            "video_job": _video_job_response(video_job),
        }
    finally:
        db.close()


@router.post("/run-due-text")
def run_due_social_text(
    force: bool = False,
    authorization: str | None = Header(default=None),
):
    """Create and publish at most one shared X/Threads image post per day."""
    _authorize(authorization, allow_scheduler_secret=True)
    db = SessionLocal()
    try:
        # Resume a previously queued post first, without creating a duplicate.
        resumed = publish_due_text_jobs(db)
        pending_review = (
            db.query(SocialContentJob)
            .filter(
                SocialContentJob.status == "review",
                ~SocialContentJob.video_jobs.any(),
            )
            .order_by(SocialContentJob.created_at.asc())
            .first()
        )
        if pending_review:
            automation = (pending_review.content_json or {}).get("automation") or {}
            if int(automation.get("format_version") or 0) < 7:
                pending_review = regenerate_content_job(db, pending_review.id)
            line_review = _send_line_text_review_if_needed(db, pending_review)
            return {
                "status": "review",
                "reason": "awaiting_line_review",
                "content_job_id": pending_review.id,
                "line_review": line_review,
                "published_job_ids": [item.id for item in resumed],
                "publish_jobs": [
                    _publish_job_response(item) for item in pending_review.publish_jobs
                ],
            }
        latest = (
            db.query(SocialContentJob)
            .filter(
                ~SocialContentJob.video_jobs.any(),
                SocialContentJob.status != "rejected",
            )
            .order_by(SocialContentJob.created_at.desc())
            .first()
        )
        interval_hours = max(1, min(int(os.getenv("SOCIAL_TEXT_INTERVAL_HOURS", "24")), 168))
        if (
            not force
            and latest
            and latest.created_at > datetime.utcnow() - timedelta(hours=interval_hours)
        ):
            db.refresh(latest)
            return {
                "status": "published" if resumed else "skipped",
                "reason": "interval_not_elapsed",
                "content_job_id": latest.id,
                "next_at": (latest.created_at + timedelta(hours=interval_hours)).isoformat(),
                "published_job_ids": [item.id for item in resumed],
                "publish_jobs": [_publish_job_response(item) for item in latest.publish_jobs],
            }
        job = create_daily_text_job(db)
        line_review = _send_line_text_review_if_needed(db, job)
        db.refresh(job)
        return {
            "status": "review",
            "content_job": _content_job_response(job),
            "line_review": line_review,
            "published_job_ids": [],
            "publish_jobs": [_publish_job_response(item) for item in job.publish_jobs],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Social text generation failed: {type(exc).__name__}: {str(exc)[:1200]}",
        ) from exc
    finally:
        db.close()


@router.post("/content/{content_job_id}/approve")
def approve_social_content(
    content_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = approve_content_job(db, content_job_id)
        return _content_job_response(job)
    finally:
        db.close()


@router.post("/content/{content_job_id}/regenerate")
def regenerate_social_content(
    content_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = regenerate_content_job(db, content_job_id)
        return _content_job_response(job)
    finally:
        db.close()


@router.post("/content/{content_job_id}/voice-previews", status_code=status.HTTP_201_CREATED)
def create_voice_previews(
    content_job_id: int,
    request: VoicePreviewRequest,
    authorization: str | None = Header(default=None),
):
    """Generate only narration samples, so a voice can be chosen before paid images."""
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = db.query(SocialContentJob).filter_by(id=content_job_id).one_or_none()
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content job not found")
        video = (job.content_json or {}).get("video") or {}
        narration = [str(item).strip() for item in video.get("narration", []) if str(item).strip()]
        if not narration:
            raise HTTPException(status_code=422, detail="Content job has no narration")
        # A preview must remain cheap even if malformed content reaches the database.
        preview_lines = narration[:2]
        preview_text = "".join(preview_lines)[:180]
        preview_lines = [preview_text]
        styles = [str(item).strip() for item in request.styles if str(item).strip()]
        if not styles:
            styles = [os.getenv("AIVIS_STYLE_NAME", "").strip()]

        previews = []
        for selected_style in styles[:3]:
            try:
                audio = generate_aivis_narration(
                    preview_lines,
                    style_name=selected_style or None,
                )
                url = upload_social_asset(
                    audio,
                    "audio/mpeg",
                    "mp3",
                    prefix="voice-previews",
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc)[:500],
                ) from exc
            previews.append({
                "provider": "aivis",
                "style": selected_style or "default",
                "audio_url": url,
                "character_count": len(preview_text),
            })
        return {"content_job_id": job.id, "previews": previews}
    finally:
        db.close()


@router.post("/video/{video_job_id}/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_social_video(
    video_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = submit_video_job(db, video_job_id)
        return _video_job_response(job)
    finally:
        db.close()


@router.post("/video/{video_job_id}/render-static", status_code=status.HTTP_202_ACCEPTED)
def render_static_social_video(
    video_job_id: int,
    force: bool = False,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = render_static_video_job(db, video_job_id, force=force)
        _send_line_review_if_needed(db, job)
        return _video_job_response(job)
    finally:
        db.close()


@router.post("/video/{video_job_id}/poll")
def poll_social_video(
    video_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = poll_video_job(db, video_job_id)
        return _video_job_response(job)
    finally:
        db.close()


@router.post("/publish-text")
def publish_social_text(
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        jobs = publish_due_text_jobs(db)
        return {"published_job_ids": [job.id for job in jobs]}
    finally:
        db.close()


@router.post("/publish-video")
def publish_social_video(
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        jobs = process_due_video_jobs(db)
        return {"processed_job_ids": [job.id for job in jobs]}
    finally:
        db.close()


@router.get("/jobs")
def list_social_jobs(
    limit: int = 20,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        jobs = (
            db.query(SocialContentJob)
            .order_by(SocialContentJob.id.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [_content_job_response(job) for job in jobs]
    finally:
        db.close()


def _content_job_response(job: SocialContentJob) -> dict:
    return {
        "id": job.id,
        "trivia_id": job.trivia_id,
        "status": job.status,
        "scheduled_at": job.scheduled_at,
        "approved_at": job.approved_at,
        "content": job.content_json,
        "video_jobs": [_video_job_response(item) for item in job.video_jobs],
        "publish_jobs": [_publish_job_response(item) for item in job.publish_jobs],
    }


def _video_job_response(job: SocialVideoJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "provider": job.provider,
        "model": job.model,
        "provider_task_ids": job.provider_task_ids,
        "source_video_urls": job.source_video_urls,
        "final_video_url": job.final_video_url,
        "thumbnail_url": job.thumbnail_url,
        "duration_seconds": job.duration_seconds,
        "error": job.error,
        "render_meta": (job.prompt_json or {}).get("render_meta"),
        "line_review": (job.prompt_json or {}).get("line_review"),
    }


def _publish_job_response(job: SocialPublishJob) -> dict:
    return {
        "id": job.id,
        "platform": job.platform,
        "content_type": job.content_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "remote_post_id": job.remote_post_id,
        "remote_post_url": job.remote_post_url,
        "last_error": job.last_error,
    }
