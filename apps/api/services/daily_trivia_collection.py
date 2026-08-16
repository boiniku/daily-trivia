import os
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import SessionLocal
from models import DailyTriviaCollectionRun, TriviaCandidate
from services.line_bot import (
    candidate_carousel_message,
    get_admin_user_ids,
    mark_line_sent,
    push_message,
)
from services.trivia_collection import TriviaCollectionUsage, collect_trivia_candidates


JST = ZoneInfo("Asia/Tokyo")


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def estimate_collection_cost_usd(usage: TriviaCollectionUsage) -> float:
    input_rate = _float_env("OPENAI_INPUT_USD_PER_MILLION", 0.25)
    output_rate = _float_env("OPENAI_OUTPUT_USD_PER_MILLION", 2.0)
    search_rate = _float_env("OPENAI_WEB_SEARCH_USD_PER_1000", 10.0)
    return round(
        usage.input_tokens * input_rate / 1_000_000
        + usage.output_tokens * output_rate / 1_000_000
        + usage.web_search_calls * search_rate / 1_000,
        6,
    )


def prepare_daily_collection(
    db: Session,
    *,
    now: datetime | None = None,
) -> tuple[DailyTriviaCollectionRun, bool]:
    run_date = (now or datetime.now(JST)).astimezone(JST).date()
    existing = (
        db.query(DailyTriviaCollectionRun)
        .filter(DailyTriviaCollectionRun.run_date == run_date)
        .first()
    )
    if existing:
        return existing, False

    requested_count = min(_positive_int_env("DAILY_COLLECTION_COUNT", 10), 10)
    pending_limit = _positive_int_env("DAILY_COLLECTION_MAX_PENDING", 30)
    monthly_budget_usd = _float_env("DAILY_COLLECTION_MONTHLY_BUDGET_USD", 6.0)
    month_start = run_date.replace(day=1)
    monthly_estimated_cost = float(
        db.query(func.coalesce(func.sum(DailyTriviaCollectionRun.estimated_cost_usd), 0.0))
        .filter(DailyTriviaCollectionRun.run_date >= month_start)
        .scalar()
        or 0.0
    )
    pending_count = (
        db.query(TriviaCandidate)
        .filter(TriviaCandidate.status == "pending")
        .count()
    )
    if monthly_budget_usd and monthly_estimated_cost >= monthly_budget_usd:
        status = "skipped"
        error = (
            f"今月のAI概算費用が${monthly_estimated_cost:.2f}となり、"
            f"上限${monthly_budget_usd:.2f}に達したため収集を停止しました。"
        )
    elif pending_count >= pending_limit:
        status = "skipped"
        error = f"承認待ちが上限の{pending_limit}件以上あるため収集を停止しました。"
    else:
        status = "running"
        error = None
    run = DailyTriviaCollectionRun(
        run_date=run_date,
        status=status,
        requested_count=requested_count,
        error=error,
        completed_at=datetime.utcnow() if status == "skipped" else None,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(DailyTriviaCollectionRun)
            .filter(DailyTriviaCollectionRun.run_date == run_date)
            .one()
        )
        return existing, False
    db.refresh(run)
    return run, status == "running"


def _send_to_admins(messages: list[dict]) -> None:
    user_ids = get_admin_user_ids()
    if not user_ids:
        raise RuntimeError("LINE_ADMIN_USER_IDS is not configured")
    for user_id in user_ids:
        push_message(user_id, messages)


def notify_skipped_collection(message: str) -> None:
    _send_to_admins([{"type": "text", "text": message[:5000]}])


def run_daily_collection(run_id: int) -> None:
    db = SessionLocal()
    usage = TriviaCollectionUsage()
    try:
        run = db.query(DailyTriviaCollectionRun).filter_by(id=run_id).one()
        if run.status != "running":
            return

        def record_usage(value: TriviaCollectionUsage) -> None:
            nonlocal usage
            usage = value

        candidates = collect_trivia_candidates(
            db,
            topic="",
            count=run.requested_count,
            usage_callback=record_usage,
        )
        if candidates:
            summary = {
                "type": "text",
                "text": (
                    f"本日の雑学候補を{len(candidates)}件収集しました。"
                    "左右にスワイプして、公開・編集・却下を選んでください。"
                ),
            }
            _send_to_admins([summary, candidate_carousel_message(candidates)])
            for candidate in candidates:
                mark_line_sent(candidate)
        else:
            _send_to_admins([{
                "type": "text",
                "text": "本日の自動収集では、重複または品質基準を除くと新しい候補がありませんでした。",
            }])

        run.collected_count = len(candidates)
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.web_search_calls = usage.web_search_calls
        run.estimated_cost_usd = estimate_collection_cost_usd(usage)
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.query(DailyTriviaCollectionRun).filter_by(id=run_id).first()
        if run:
            run.status = "failed"
            run.input_tokens = usage.input_tokens
            run.output_tokens = usage.output_tokens
            run.web_search_calls = usage.web_search_calls
            run.estimated_cost_usd = estimate_collection_cost_usd(usage)
            run.error = str(exc)[:2000]
            run.completed_at = datetime.utcnow()
            db.commit()
        try:
            _send_to_admins([{
                "type": "text",
                "text": f"本日の雑学自動収集に失敗しました: {str(exc)[:1000]}",
            }])
        except Exception:
            pass
    finally:
        db.close()
