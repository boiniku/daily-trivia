from datetime import datetime
import difflib
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate


VALID_CANDIDATE_STATUSES = {"pending", "approved", "rejected"}


class CandidateError(ValueError):
    pass


class DuplicateCandidateError(CandidateError):
    pass


def _normalize_for_similarity(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").lower(), flags=re.UNICODE)


def _similarity(left: str, right: str) -> float:
    normalized_left = _normalize_for_similarity(left)
    normalized_right = _normalize_for_similarity(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def find_duplicate(
    db: Session,
    *,
    title: str,
    content: str,
    exclude_candidate_id: Optional[int] = None,
    include_pending: bool = True,
) -> Optional[str]:
    for trivia in db.query(Trivia.id, Trivia.title, Trivia.content).all():
        if _similarity(title, trivia.title) >= 0.72:
            return f"公開済み #{trivia.id}「{trivia.title}」とタイトルが類似しています"
        if _similarity(content, trivia.content) >= 0.78:
            return f"公開済み #{trivia.id}「{trivia.title}」と本文が類似しています"

    if include_pending:
        query = db.query(
            TriviaCandidate.id,
            TriviaCandidate.title,
            TriviaCandidate.content,
        ).filter(TriviaCandidate.status == "pending")
        if exclude_candidate_id is not None:
            query = query.filter(TriviaCandidate.id != exclude_candidate_id)
        for candidate in query.all():
            if _similarity(title, candidate.title) >= 0.72:
                return f"承認待ち #{candidate.id}「{candidate.title}」とタイトルが類似しています"
            if _similarity(content, candidate.content) >= 0.78:
                return f"承認待ち #{candidate.id}「{candidate.title}」と本文が類似しています"
    return None


def create_candidates(db: Session, items: Iterable[dict]) -> list[TriviaCandidate]:
    candidates = []
    for item in items:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not title or not content:
            continue
        if find_duplicate(db, title=title, content=content):
            continue
        candidates.append(_add_candidate(db, item))
    db.commit()
    for candidate in candidates:
        db.refresh(candidate)
    return candidates


def create_candidate(db: Session, item: dict) -> TriviaCandidate:
    title = (item.get("title") or "").strip()
    content = (item.get("content") or "").strip()
    if not title or not content:
        raise CandidateError("Title and content are required")
    duplicate = find_duplicate(db, title=title, content=content)
    if duplicate:
        raise DuplicateCandidateError(duplicate)
    candidate = _add_candidate(db, item)
    db.commit()
    db.refresh(candidate)
    return candidate


def _add_candidate(db: Session, item: dict) -> TriviaCandidate:
    candidate = TriviaCandidate(
        title=(item.get("title") or "").strip(),
        content=(item.get("content") or "").strip(),
        explanation=(item.get("explanation") or "").strip(),
        source=(item.get("source") or "").strip(),
        category=(item.get("category") or "その他").strip(),
        image_url=(item.get("image_url") or "").strip() or None,
        status="pending",
    )
    db.add(candidate)
    db.flush()
    return candidate


def update_candidate(
    db: Session,
    candidate_id: int,
    *,
    title: str,
    content: str,
    explanation: str,
    source: str,
    category: str,
    image_url: Optional[str] = None,
) -> TriviaCandidate:
    candidate = db.query(TriviaCandidate).filter(TriviaCandidate.id == candidate_id).first()
    if not candidate:
        raise CandidateError("Candidate not found")
    if candidate.status != "pending":
        raise CandidateError("Only pending candidates can be edited")
    if not title.strip() or not content.strip():
        raise CandidateError("Title and content are required")
    duplicate = find_duplicate(
        db,
        title=title,
        content=content,
        exclude_candidate_id=candidate_id,
    )
    if duplicate:
        raise DuplicateCandidateError(duplicate)

    candidate.title = title.strip()
    candidate.content = content.strip()
    candidate.explanation = explanation.strip()
    candidate.source = source.strip()
    candidate.category = category.strip() or "その他"
    candidate.image_url = (image_url or "").strip() or None
    db.commit()
    db.refresh(candidate)
    return candidate


def approve_candidate(db: Session, candidate_id: int, reviewed_by: str) -> Trivia:
    candidate = (
        db.query(TriviaCandidate)
        .filter(TriviaCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if not candidate:
        raise CandidateError("Candidate not found")
    if candidate.status == "approved" and candidate.published_trivia_id:
        trivia = db.query(Trivia).filter(Trivia.id == candidate.published_trivia_id).first()
        if trivia:
            return trivia
    if candidate.status != "pending":
        raise CandidateError(f"Candidate is already {candidate.status}")
    duplicate = find_duplicate(
        db,
        title=candidate.title,
        content=candidate.content,
        exclude_candidate_id=candidate.id,
        include_pending=False,
    )
    if duplicate:
        raise DuplicateCandidateError(duplicate)

    trivia = Trivia(
        title=candidate.title,
        content=candidate.content,
        explanation=candidate.explanation,
        source=candidate.source,
        category=candidate.category,
        image_url=candidate.image_url,
        embedding=candidate.embedding,
    )
    db.add(trivia)
    db.flush()

    candidate.status = "approved"
    candidate.reviewed_at = datetime.utcnow()
    candidate.reviewed_by = reviewed_by
    candidate.published_trivia_id = trivia.id
    db.commit()
    db.refresh(trivia)
    return trivia


def reject_candidate(db: Session, candidate_id: int, reviewed_by: str) -> TriviaCandidate:
    candidate = (
        db.query(TriviaCandidate)
        .filter(TriviaCandidate.id == candidate_id)
        .with_for_update()
        .first()
    )
    if not candidate:
        raise CandidateError("Candidate not found")
    if candidate.status == "rejected":
        return candidate
    if candidate.status != "pending":
        raise CandidateError(f"Candidate is already {candidate.status}")

    candidate.status = "rejected"
    candidate.reviewed_at = datetime.utcnow()
    candidate.reviewed_by = reviewed_by
    db.commit()
    db.refresh(candidate)
    return candidate
