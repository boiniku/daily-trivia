import os
from datetime import datetime
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import SocialContentJob, SocialPublishJob, SocialVideoJob, Trivia
from services.seedance import SeedanceClient
from services.social_content import generate_social_content
from services.social_publishers import ThreadsTextPublisher, XTextPublisher
from services.social_storage import upload_social_asset
from services.static_video import (
    compose_static_video,
    download_image,
    generate_narration_audio,
    generate_social_image,
)


TEXT_PLATFORMS = ("x", "threads")
VIDEO_PLATFORMS = ("instagram", "tiktok")


def select_unused_trivia(db: Session) -> Trivia | None:
    used_ids = db.query(SocialContentJob.trivia_id)
    return (
        db.query(Trivia)
        .filter(~Trivia.id.in_(used_ids))
        .order_by(Trivia.hee_count.desc(), Trivia.id.asc())
        .first()
    )


def create_content_job(
    db: Session,
    trivia_id: int | None = None,
    *,
    scheduled_at: datetime | None = None,
    generator: Callable = generate_social_content,
    video_mode: str = "static",
) -> SocialContentJob:
    if video_mode not in {"static", "seedance"}:
        raise ValueError("video_mode must be 'static' or 'seedance'")
    trivia = db.query(Trivia).filter(Trivia.id == trivia_id).first() if trivia_id else select_unused_trivia(db)
    if trivia is None:
        raise ValueError("No unused trivia is available")
    existing = db.query(SocialContentJob).filter_by(trivia_id=trivia.id).first()
    if existing:
        return existing

    content = generator(trivia)
    job = SocialContentJob(
        trivia_id=trivia.id,
        status="review",
        content_json=content,
        scheduled_at=scheduled_at,
    )
    db.add(job)
    db.flush()
    video_content = content["video"]
    video = SocialVideoJob(
        content_job_id=job.id,
        provider=video_mode,
        model=(
            os.getenv("SEEDANCE_MODEL", "").strip()
            if video_mode == "seedance"
            else os.getenv("SOCIAL_IMAGE_MODEL", "gpt-image-1-mini").strip()
        ),
        status="pending",
        prompt_json={
            "image_prompt": video_content.get("image_prompt", ""),
            "visual_prompts": video_content.get("visual_prompts", []),
        },
    )
    db.add(video)
    for platform in TEXT_PLATFORMS:
        db.add(SocialPublishJob(
            content_job_id=job.id,
            platform=platform,
            content_type="text",
            status="waiting_approval",
            scheduled_at=scheduled_at,
        ))
    for platform in VIDEO_PLATFORMS:
        db.add(SocialPublishJob(
            content_job_id=job.id,
            platform=platform,
            content_type="video",
            status="waiting_video",
            scheduled_at=scheduled_at,
        ))
    db.commit()
    db.refresh(job)
    return job


def approve_content_job(db: Session, content_job_id: int) -> SocialContentJob:
    job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
    job.status = "approved"
    job.approved_at = datetime.utcnow()
    for publish_job in job.publish_jobs:
        if publish_job.content_type == "text" and publish_job.status == "waiting_approval":
            publish_job.status = "queued"
        elif publish_job.content_type == "video" and publish_job.status == "waiting_video":
            if any(video.status == "ready" for video in job.video_jobs):
                publish_job.status = "queued"
    db.commit()
    db.refresh(job)
    return job


def submit_seedance_job(
    db: Session,
    video_job_id: int,
    client: SeedanceClient | None = None,
) -> SocialVideoJob:
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "seedance":
        raise ValueError("This video job is not a Seedance job")
    prompts = video_job.prompt_json.get("visual_prompts", [])
    task_ids = list(video_job.provider_task_ids or [])
    if task_ids and len(task_ids) >= len(prompts):
        return video_job
    client = client or SeedanceClient()
    if not prompts:
        raise ValueError("Video job has no visual prompts")
    try:
        for item in prompts[len(task_ids):]:
            task = client.create_video(
                item["prompt"],
                duration=item.get("duration", 8),
                ratio="9:16",
                generate_audio=False,
                model=video_job.model,
            )
            task_ids.append(task.id)
            # Persist each external task immediately so a partial failure can
            # resume without paying for duplicate Seedance generations.
            video_job.provider_task_ids = list(task_ids)
            video_job.status = "generating"
            video_job.error = None
            db.commit()
    except Exception as exc:
        video_job.status = "submission_failed"
        video_job.error = str(exc)[:2000]
        db.commit()
        raise
    db.refresh(video_job)
    return video_job


def poll_seedance_job(
    db: Session,
    video_job_id: int,
    client: SeedanceClient | None = None,
) -> SocialVideoJob:
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "seedance":
        raise ValueError("This video job is not a Seedance job")
    client = client or SeedanceClient()
    results = [client.get_task(task_id) for task_id in video_job.provider_task_ids]
    failed = [item for item in results if item.status in {"failed", "error", "cancelled"}]
    if failed:
        video_job.status = "failed"
        video_job.error = f"Seedance tasks failed: {', '.join(item.id for item in failed)}"
    elif results and all(
        item.status in {"succeeded", "success", "completed"} and item.video_url
        for item in results
    ):
        video_job.source_video_urls = [item.video_url for item in results]
        video_job.status = "clips_ready"
    else:
        video_job.status = "generating"
    db.commit()
    db.refresh(video_job)
    return video_job


def render_static_video_job(
    db: Session,
    video_job_id: int,
    *,
    image_generator: Callable = generate_social_image,
    image_downloader: Callable = download_image,
    narration_generator: Callable = generate_narration_audio,
    composer: Callable = compose_static_video,
    uploader: Callable = upload_social_asset,
) -> SocialVideoJob:
    """Render the low-cost automatic video lane and archive it in R2."""
    import tempfile
    from pathlib import Path

    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "static":
        raise ValueError("This video job is not a static video job")
    if video_job.status == "ready" and video_job.final_video_url:
        return video_job

    video_job.status = "rendering"
    video_job.error = None
    db.commit()
    try:
        content_job = video_job.content_job
        video_content = content_job.content_json["video"]
        if content_job.trivia.image_url:
            image_data = image_downloader(content_job.trivia.image_url)
            video_job.thumbnail_url = content_job.trivia.image_url
        else:
            image_data = image_generator(video_job.prompt_json["image_prompt"])
            video_job.thumbnail_url = uploader(
                image_data, "image/png", "png", prefix="images"
            )

        audio_data = None
        if os.getenv("SOCIAL_TTS_ENABLED", "true").lower() == "true":
            audio_data = narration_generator(video_content["narration"])

        with tempfile.TemporaryDirectory(prefix="daily-trivia-output-") as temp_dir:
            output_path = Path(temp_dir) / f"social-video-{video_job.id}.mp4"
            duration = composer(
                image_data,
                content_job.trivia.title,
                video_content["subtitles"],
                output_path,
                audio_data=audio_data,
                narration=video_content["narration"],
            )
            video_job.final_video_url = uploader(
                output_path.read_bytes(), "video/mp4", "mp4", prefix="videos"
            )
        video_job.duration_seconds = duration
        video_job.status = "ready"
        if content_job.status == "approved":
            for publish_job in content_job.publish_jobs:
                if publish_job.content_type == "video" and publish_job.status == "waiting_video":
                    publish_job.status = "queued"
    except Exception as exc:
        video_job.status = "failed"
        video_job.error = str(exc)[:2000]
        db.commit()
        raise
    db.commit()
    db.refresh(video_job)
    return video_job


def configured_text_platforms() -> set[str]:
    enabled = set()
    if os.getenv("SOCIAL_X_PUBLISH_ENABLED", "false").lower() == "true":
        enabled.add("x")
    if os.getenv("SOCIAL_THREADS_PUBLISH_ENABLED", "false").lower() == "true":
        enabled.add("threads")
    return enabled


def publish_due_text_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    enabled_platforms: set[str] | None = None,
    publishers: dict | None = None,
) -> list[SocialPublishJob]:
    now = now or datetime.utcnow()
    enabled = configured_text_platforms() if enabled_platforms is None else enabled_platforms
    if not enabled:
        return []
    publishers = publishers or {}
    jobs = (
        db.query(SocialPublishJob)
        .join(SocialContentJob)
        .filter(
            SocialContentJob.status == "approved",
            SocialPublishJob.status.in_(["queued", "retry"]),
            SocialPublishJob.platform.in_(enabled),
            SocialPublishJob.content_type == "text",
            or_(SocialPublishJob.scheduled_at.is_(None), SocialPublishJob.scheduled_at <= now),
        )
        .order_by(SocialPublishJob.id.asc())
        .all()
    )
    completed = []
    for job in jobs:
        job.status = "publishing"
        job.attempt_count += 1
        db.commit()
        try:
            content = job.content_job.content_json[job.platform]
            if job.platform == "x":
                publisher = publishers.get("x") or XTextPublisher()
                result = publisher.publish(content["text"])
            elif job.platform == "threads":
                publisher = publishers.get("threads") or ThreadsTextPublisher()
                result = publisher.publish(content["text"], content.get("topic_tag"))
            else:
                continue
            job.status = "published"
            job.remote_post_id = result.remote_post_id
            job.remote_post_url = result.remote_post_url
            job.published_at = datetime.utcnow()
            job.last_error = None
            completed.append(job)
        except Exception as exc:
            job.status = "retry" if job.attempt_count < 3 else "failed"
            job.last_error = str(exc)[:2000]
        db.commit()
    return completed
