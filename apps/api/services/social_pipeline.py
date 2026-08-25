import os
from datetime import datetime
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import SocialContentJob, SocialPublishJob, SocialVideoJob, Trivia
from services.kling import KlingClient, download_kling_video
from services.seedance import SeedanceClient
from services.social_content import generate_social_content
from services.social_publishers import (
    InstagramReelPublisher,
    ThreadsTextPublisher,
    TikTokVideoPublisher,
    XTextPublisher,
)
from services.social_storage import upload_social_asset
from services.static_video import (
    compose_static_video,
    download_image,
    generate_narration_audio,
    generate_social_image,
    load_background_music,
    load_intro_video,
    load_promo_video,
)


TEXT_PLATFORMS = ("x", "threads")
VIDEO_PLATFORMS = ("instagram", "tiktok")
STATIC_RENDER_VERSION = 3


def _video_prompt_json(video_content: dict) -> dict:
    scenes = video_content.get("scenes", [])
    hero_index = next(
        (index for index, scene in enumerate(scenes) if scene.get("role") == "reveal"),
        min(2, max(0, len(scenes) - 1)),
    )
    return {
        "image_prompt": video_content.get("image_prompt", ""),
        "image_prompts": [
            scene["image_prompt"] for scene in video_content.get("scenes", [])
        ],
        "image_urls": [],
        "visual_prompts": video_content.get("visual_prompts", []),
        "kling_scene_index": hero_index,
        "kling_duration": 5,
    }


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
    if video_mode not in {"static", "seedance", "kling"}:
        raise ValueError("video_mode must be 'static', 'seedance', or 'kling'")
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
            else (
                os.getenv("KLING_MODEL", "kling-3.0").strip()
                if video_mode == "kling"
                else os.getenv("SOCIAL_IMAGE_MODEL", "gpt-image-1-mini").strip()
            )
        ),
        status="pending",
        prompt_json=_video_prompt_json(video_content),
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


def regenerate_content_job(
    db: Session,
    content_job_id: int,
    *,
    generator: Callable = generate_social_content,
) -> SocialContentJob:
    """Replace an unapproved draft without creating paid image assets."""
    job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
    if job.status != "review" or job.approved_at:
        raise ValueError("Only an unapproved review job can be regenerated")
    if any(video.final_video_url or video.thumbnail_url for video in job.video_jobs):
        raise ValueError("A job with generated media cannot be regenerated")
    if any(item.status == "published" for item in job.publish_jobs):
        raise ValueError("A published job cannot be regenerated")

    content = generator(job.trivia)
    job.content_json = content
    video_content = content["video"]
    for video in job.video_jobs:
        video.status = "pending"
        video.error = None
        video.prompt_json = _video_prompt_json(video_content)
        video.provider_task_ids = []
        video.source_video_urls = []
        video.duration_seconds = None
    for publish_job in job.publish_jobs:
        publish_job.status = (
            "waiting_approval" if publish_job.content_type == "text" else "waiting_video"
        )
        publish_job.attempt_count = 0
        publish_job.last_error = None
    db.commit()
    db.refresh(job)
    return job


def approve_content_job(db: Session, content_job_id: int) -> SocialContentJob:
    job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
    if job.status == "approved":
        return job
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


def reject_content_job(db: Session, content_job_id: int) -> SocialContentJob:
    job = db.query(SocialContentJob).filter_by(id=content_job_id).one()
    if any(item.status == "published" for item in job.publish_jobs):
        raise ValueError("A published content job cannot be rejected")
    job.status = "rejected"
    for publish_job in job.publish_jobs:
        if publish_job.status != "published":
            publish_job.status = "cancelled"
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


def submit_kling_job(
    db: Session,
    video_job_id: int,
    client: KlingClient | None = None,
    *,
    image_generator: Callable = generate_social_image,
    uploader: Callable = upload_social_asset,
) -> SocialVideoJob:
    """Create one silent 720p Kling clip, capped to five submitted videos/month."""
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "kling":
        raise ValueError("This video job is not a Kling job")
    if video_job.provider_task_ids:
        return video_job
    _enforce_kling_monthly_limit(db, video_job)

    prompt_data = dict(video_job.prompt_json or {})
    prompts = prompt_data.get("image_prompts") or []
    if not prompts:
        raise ValueError("Kling video job has no first-frame prompt")
    scene_index = max(0, min(int(prompt_data.get("kling_scene_index", 2)), len(prompts) - 1))
    first_frame_url = str(prompt_data.get("kling_first_frame_url") or "").strip()
    try:
        if not first_frame_url:
            generated = image_generator(prompts[scene_index])
            first_frame_url = uploader(
                generated, "image/png", "png", prefix="images/kling-first-frames"
            )
            prompt_data["kling_first_frame_url"] = first_frame_url
            video_job.prompt_json = prompt_data
            video_job.thumbnail_url = first_frame_url
            # Save the paid image before making the separately billed video request.
            db.commit()

        client = client or KlingClient()
        task = client.create_image_video(
            _kling_motion_prompt(video_job),
            first_frame_url,
            duration=int(os.getenv("KLING_DURATION_SECONDS", str(prompt_data.get("kling_duration", 5)))),
            resolution="720p",
            audio=False,
            multi_shot=False,
            model=video_job.model or "kling-3.0",
            external_task_id=f"daily-trivia-{video_job.id}",
        )
        video_job.provider_task_ids = [task.id]
        video_job.status = "generating"
        video_job.error = None
    except Exception as exc:
        video_job.status = "submission_failed"
        video_job.error = str(exc)[:2000]
        db.commit()
        raise
    db.commit()
    db.refresh(video_job)
    return video_job


def poll_kling_job(
    db: Session,
    video_job_id: int,
    client: KlingClient | None = None,
    *,
    downloader: Callable = download_kling_video,
    uploader: Callable = upload_social_asset,
) -> SocialVideoJob:
    """Poll Kling and immediately archive its temporary result in R2."""
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "kling":
        raise ValueError("This video job is not a Kling job")
    if video_job.status == "clips_ready" and video_job.source_video_urls:
        return video_job
    if not video_job.provider_task_ids:
        raise ValueError("Kling video job has not been submitted")
    client = client or KlingClient()
    task = client.get_task(str(video_job.provider_task_ids[0]))
    if task.status == "failed":
        video_job.status = "failed"
        video_job.error = (task.error or "Kling task failed")[:2000]
    elif task.status == "succeeded" and task.video_url:
        video_bytes = downloader(task.video_url)
        archived_url = uploader(video_bytes, "video/mp4", "mp4", prefix="clips/kling")
        video_job.source_video_urls = [archived_url]
        video_job.duration_seconds = task.duration or float(
            video_job.prompt_json.get("kling_duration", 5)
        )
        video_job.status = "clips_ready"
        video_job.error = None
    else:
        video_job.status = "generating"
    db.commit()
    db.refresh(video_job)
    return video_job


def submit_video_job(db: Session, video_job_id: int) -> SocialVideoJob:
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider == "kling":
        return submit_kling_job(db, video_job_id)
    return submit_seedance_job(db, video_job_id)


def poll_video_job(db: Session, video_job_id: int) -> SocialVideoJob:
    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider == "kling":
        return poll_kling_job(db, video_job_id)
    return poll_seedance_job(db, video_job_id)


def _kling_motion_prompt(video_job: SocialVideoJob) -> str:
    prompt_data = video_job.prompt_json or {}
    visual_prompts = prompt_data.get("visual_prompts") or []
    source = ""
    if visual_prompts and isinstance(visual_prompts[0], dict):
        source = str(visual_prompts[0].get("prompt") or "").strip()
    return (
        "One continuous vertical documentary shot based strictly on the provided first frame. "
        "Preserve the subject, anatomy, materials, colors, lighting, and composition. "
        "Use a slow cinematic camera push-in, subtle parallax, and only physically natural motion. "
        "Do not introduce, remove, transform, duplicate, or distort any object. "
        f"Creative direction: {source} "
        "No cuts, no text, no captions, no labels, no logos, no watermark."
    )[:3072]


def _enforce_kling_monthly_limit(db: Session, current_job: SocialVideoJob) -> None:
    try:
        limit = int(os.getenv("KLING_MONTHLY_VIDEO_LIMIT", "5"))
    except ValueError:
        limit = 5
    limit = max(1, min(limit, 31))
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    next_month = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1)
    submitted = (
        db.query(SocialVideoJob)
        .filter(
            SocialVideoJob.provider == "kling",
            SocialVideoJob.id != current_job.id,
            SocialVideoJob.created_at >= month_start,
            SocialVideoJob.created_at < next_month,
        )
        .all()
    )
    used = sum(1 for item in submitted if item.provider_task_ids)
    if used >= limit:
        raise ValueError(f"Kling monthly video limit reached ({used}/{limit})")


def render_static_video_job(
    db: Session,
    video_job_id: int,
    *,
    image_generator: Callable = generate_social_image,
    image_downloader: Callable = download_image,
    narration_generator: Callable = generate_narration_audio,
    background_music_loader: Callable = load_background_music,
    promo_video_loader: Callable = load_promo_video,
    intro_video_loader: Callable = load_intro_video,
    composer: Callable = compose_static_video,
    uploader: Callable = upload_social_asset,
    force: bool = False,
) -> SocialVideoJob:
    """Render the low-cost automatic video lane and archive it in R2."""
    import tempfile
    from pathlib import Path

    video_job = db.query(SocialVideoJob).filter_by(id=video_job_id).one()
    if video_job.provider != "static":
        raise ValueError("This video job is not a static video job")
    if video_job.status == "ready" and video_job.final_video_url and not force:
        return video_job

    video_job.status = "rendering"
    video_job.error = None
    db.commit()
    try:
        content_job = video_job.content_job
        video_content = content_job.content_json["video"]
        scenes = list(video_content.get("scenes") or [])
        narration = list(video_content["narration"])
        subtitles = list(video_content["subtitles"])
        promo_video_data = promo_video_loader()
        intro_video_data = intro_video_loader()
        cta_narration = os.getenv(
            "SOCIAL_BRAND_CTA_NARRATION",
            "毎日3つの雑学を、ウィジェットで。毎日雑学。",
        ).strip()
        cta_subtitle = os.getenv(
            "SOCIAL_BRAND_CTA_SUBTITLE", "続きは「毎日雑学」で"
        ).strip()
        if promo_video_data and cta_narration:
            narration.append(cta_narration)
        elif cta_narration and cta_subtitle:
            narration.append(cta_narration)
            subtitles.append(cta_subtitle)
            scenes.append({
                "duration": 2.5,
                "role": "cta",
                "narration": cta_narration,
                "subtitle": cta_subtitle,
                "motion": "zoom_in",
            })
        prompts = video_job.prompt_json.get("image_prompts") or []
        if not prompts:
            prompts = [video_job.prompt_json["image_prompt"]]
        image_urls = list(video_job.prompt_json.get("image_urls") or [])
        if not image_urls:
            reusable_image_url = video_job.thumbnail_url or content_job.trivia.image_url
            if reusable_image_url:
                image_urls.append(reusable_image_url)
                video_job.thumbnail_url = reusable_image_url

        image_items = []
        for index, prompt in enumerate(prompts):
            if index < len(image_urls):
                image_items.append(image_downloader(image_urls[index]))
                continue
            generated = image_generator(prompt)
            generated_url = uploader(generated, "image/png", "png", prefix="images")
            image_urls.append(generated_url)
            image_items.append(generated)
            video_job.prompt_json = {**video_job.prompt_json, "image_urls": image_urls}
            if not video_job.thumbnail_url:
                video_job.thumbnail_url = generated_url
            # Preserve each paid image if a later API call or FFmpeg run fails.
            db.commit()
        if image_urls and not video_job.thumbnail_url:
            video_job.thumbnail_url = image_urls[0]

        image_data = image_items if len(image_items) > 1 else image_items[0]

        audio_data = None
        if os.getenv("SOCIAL_TTS_ENABLED", "true").lower() == "true":
            audio_data = narration_generator(narration)
        background_music_data = background_music_loader()
        video_job.prompt_json = {
            **(video_job.prompt_json or {}),
            "render_meta": {
                "pipeline_version": STATIC_RENDER_VERSION,
                "tts_provider": os.getenv("SOCIAL_TTS_PROVIDER", "openai"),
                "tts_style": os.getenv("AIVIS_SELECTED_STYLE", "Surprise"),
                "bgm": "DOVA-SYNDROME Escort" if background_music_data else None,
            },
        }

        with tempfile.TemporaryDirectory(prefix="daily-trivia-output-") as temp_dir:
            output_path = Path(temp_dir) / f"social-video-{video_job.id}.mp4"
            duration = composer(
                image_data,
                content_job.trivia.title,
                subtitles,
                output_path,
                audio_data=audio_data,
                narration=narration,
                scenes=scenes,
                background_music_data=background_music_data,
                promo_video_data=promo_video_data,
                promo_duration=5.0,
                intro_video_data=intro_video_data,
                intro_duration=1.0,
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


def configured_video_platforms() -> set[str]:
    enabled = set()
    if os.getenv("SOCIAL_INSTAGRAM_PUBLISH_ENABLED", "false").lower() == "true":
        enabled.add("instagram")
    if os.getenv("SOCIAL_TIKTOK_PUBLISH_ENABLED", "false").lower() == "true":
        enabled.add("tiktok")
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


def process_due_video_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    content_job_id: int | None = None,
    enabled_platforms: set[str] | None = None,
    publishers: dict | None = None,
) -> list[SocialPublishJob]:
    """Submit or advance approved asynchronous Reel/TikTok publishing jobs."""
    now = now or datetime.utcnow()
    enabled = configured_video_platforms() if enabled_platforms is None else enabled_platforms
    if not enabled:
        return []
    publishers = publishers or {}
    query = (
        db.query(SocialPublishJob)
        .join(SocialContentJob)
        .filter(
            SocialContentJob.status == "approved",
            SocialPublishJob.status.in_(["queued", "publishing", "retry"]),
            SocialPublishJob.platform.in_(enabled),
            SocialPublishJob.content_type == "video",
            or_(SocialPublishJob.scheduled_at.is_(None), SocialPublishJob.scheduled_at <= now),
        )
    )
    if content_job_id is not None:
        query = query.filter(SocialPublishJob.content_job_id == content_job_id)
    jobs = query.order_by(SocialPublishJob.id.asc()).all()
    changed = []
    for job in jobs:
        video = next(
            (item for item in job.content_job.video_jobs if item.status == "ready" and item.final_video_url),
            None,
        )
        if video is None:
            continue
        try:
            content = job.content_job.content_json[job.platform]
            caption = str(content.get("caption") or "").strip()
            hashtags = [str(item).strip().lstrip("#") for item in content.get("hashtags", [])]
            suffix = " ".join(f"#{item}" for item in hashtags if item and f"#{item}" not in caption)
            full_caption = " ".join(item for item in (caption, suffix) if item).strip()
            if job.platform == "instagram":
                publisher = publishers.get("instagram") or InstagramReelPublisher()
                if not job.remote_post_id:
                    result = publisher.submit(video.final_video_url, full_caption)
                    job.remote_post_id = result.remote_post_id
                    job.status = "publishing"
                    job.attempt_count += 1
                else:
                    remote_status = publisher.status(job.remote_post_id)
                    if remote_status == "FINISHED":
                        result = publisher.publish(job.remote_post_id)
                        job.remote_post_id = result.remote_post_id
                        job.status = "published"
                        job.published_at = datetime.utcnow()
                    elif remote_status in {"ERROR", "EXPIRED"}:
                        raise RuntimeError(f"Instagram container status is {remote_status}")
            elif job.platform == "tiktok":
                publisher = publishers.get("tiktok") or TikTokVideoPublisher()
                if not job.remote_post_id:
                    result = publisher.submit(video.final_video_url, full_caption)
                    job.remote_post_id = result.remote_post_id
                    job.status = "publishing"
                    job.attempt_count += 1
                else:
                    remote_status, post_id = publisher.status(job.remote_post_id)
                    if remote_status == "PUBLISH_COMPLETE":
                        job.remote_post_id = post_id or job.remote_post_id
                        username = os.getenv("TIKTOK_USERNAME", "").strip().lstrip("@")
                        if username and post_id:
                            job.remote_post_url = f"https://www.tiktok.com/@{username}/video/{post_id}"
                        job.status = "published"
                        job.published_at = datetime.utcnow()
                    elif remote_status == "FAILED":
                        raise RuntimeError("TikTok publish status is FAILED")
            job.last_error = None
            changed.append(job)
        except Exception as exc:
            # If an external id exists, retry by polling it rather than submitting a duplicate.
            job.status = "publishing" if job.remote_post_id else ("retry" if job.attempt_count < 3 else "failed")
            job.last_error = str(exc)[:2000]
        db.commit()
    return changed
