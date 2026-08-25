import argparse
import json
from datetime import datetime

from database import SessionLocal
from models import SocialContentJob, SocialVideoJob
from services.social_pipeline import (
    approve_content_job,
    create_content_job,
    poll_video_job,
    publish_due_text_jobs,
    render_static_video_job,
    submit_video_job,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and publish Daily Trivia social content")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--trivia-id", type=int)
    prepare.add_argument("--scheduled-at", help="UTC ISO-8601 datetime")
    prepare.add_argument("--video-mode", choices=("static", "seedance", "kling"), default="static")
    approve = commands.add_parser("approve")
    approve.add_argument("content_job_id", type=int)
    submit = commands.add_parser("submit-video")
    submit.add_argument("video_job_id", type=int)
    poll = commands.add_parser("poll-video")
    poll.add_argument("video_job_id", type=int)
    render = commands.add_parser("render-static")
    render.add_argument("video_job_id", type=int)
    commands.add_parser("publish-text")
    commands.add_parser("status")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "prepare":
            scheduled_at = datetime.fromisoformat(args.scheduled_at) if args.scheduled_at else None
            item = create_content_job(
                db, args.trivia_id, scheduled_at=scheduled_at, video_mode=args.video_mode
            )
            output = {"content_job_id": item.id, "status": item.status}
        elif args.command == "approve":
            item = approve_content_job(db, args.content_job_id)
            output = {"content_job_id": item.id, "status": item.status}
        elif args.command == "submit-video":
            item = submit_video_job(db, args.video_job_id)
            output = {"video_job_id": item.id, "status": item.status, "task_ids": item.provider_task_ids}
        elif args.command == "poll-video":
            item = poll_video_job(db, args.video_job_id)
            output = {"video_job_id": item.id, "status": item.status, "urls": item.source_video_urls}
        elif args.command == "render-static":
            item = render_static_video_job(db, args.video_job_id)
            output = {
                "video_job_id": item.id,
                "status": item.status,
                "final_video_url": item.final_video_url,
            }
        elif args.command == "publish-text":
            items = publish_due_text_jobs(db)
            output = {"published_job_ids": [item.id for item in items]}
        else:
            output = {
                "content_jobs": db.query(SocialContentJob).count(),
                "video_jobs": db.query(SocialVideoJob).count(),
            }
        print(json.dumps(output, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
