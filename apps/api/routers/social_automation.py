import os
import secrets
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from database import SessionLocal
from models import SocialContentJob, SocialPublishJob, SocialVideoJob
from services.social_pipeline import (
    approve_content_job,
    create_content_job,
    poll_seedance_job,
    publish_due_text_jobs,
    regenerate_content_job,
    render_static_video_job,
    submit_seedance_job,
)


router = APIRouter(prefix="/internal/social", tags=["social-automation"])


class PrepareRequest(BaseModel):
    trivia_id: int | None = None
    scheduled_at: datetime | None = None
    video_mode: str = "static"


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("SOCIAL_AUTOMATION_SECRET", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Social automation is not configured",
        )
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization")


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


@router.post("/video/{video_job_id}/submit", status_code=status.HTTP_202_ACCEPTED)
def submit_social_video(
    video_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = submit_seedance_job(db, video_job_id)
        return _video_job_response(job)
    finally:
        db.close()


@router.post("/video/{video_job_id}/render-static", status_code=status.HTTP_202_ACCEPTED)
def render_static_social_video(
    video_job_id: int,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        job = render_static_video_job(db, video_job_id)
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
        job = poll_seedance_job(db, video_job_id)
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
