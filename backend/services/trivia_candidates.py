from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate


VALID_CANDIDATE_STATUSES = {"pending", "approved", "rejected"}


class CandidateError(ValueError):
    pass


def create_candidates(db: Session, items: Iterable[dict]) -> list[TriviaCandidate]:
    candidates = []
    for item in items:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not title or not content:
            continue
        candidate = TriviaCandidate(
            title=title,
            content=content,
            explanation=(item.get("explanation") or "").strip(),
            source=(item.get("source") or "").strip(),
            category=(item.get("category") or "その他").strip(),
            image_url=(item.get("image_url") or "").strip() or None,
            status="pending",
        )
        db.add(candidate)
        candidates.append(candidate)
    db.commit()
    for candidate in candidates:
        db.refresh(candidate)
    return candidates


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
