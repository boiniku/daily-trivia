import os
import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status

from database import SessionLocal
from services.daily_trivia_collection import (
    notify_skipped_collection,
    prepare_daily_collection,
    run_daily_collection,
)


router = APIRouter()


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("DAILY_COLLECTION_SECRET", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Daily collection is not configured",
        )
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization",
        )


@router.post("/internal/daily-trivia-collection", status_code=status.HTTP_202_ACCEPTED)
def trigger_daily_collection(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    db = SessionLocal()
    try:
        run, should_start = prepare_daily_collection(db)
        response = {
            "run_id": run.id,
            "run_date": run.run_date.isoformat(),
            "status": run.status,
            "started": should_start,
        }
        if should_start:
            background_tasks.add_task(run_daily_collection, run.id)
        elif run.status == "skipped" and run.error:
            background_tasks.add_task(notify_skipped_collection, run.error)
        return response
    finally:
        db.close()
