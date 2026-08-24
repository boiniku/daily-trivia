from datetime import datetime
import difflib
import re
import unicodedata
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import Trivia, TriviaCandidate


VALID_CANDIDATE_STATUSES = {"pending", "approved", "rejected"}
NUMBER_TRANSLATION = str.maketrans(
    "０１２３４５６７８９一二三四五六七八九",
    "0123456789123456789",
)

SIMILARITY_REPLACEMENTS = (
    ("センチメートル", "cm"),
    ("センチ", "cm"),
    ("メートル", "m"),
    ("キログラム", "kg"),
    ("個", "つ"),
    ("匹", "頭"),
    ("エラ", "えら"),
    ("心ぞう", "心臓"),
)


class CandidateError(ValueError):
    pass


class DuplicateCandidateError(CandidateError):
    pass


def _optional_float(value):
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _normalize_for_similarity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    normalized = normalized.translate(NUMBER_TRANSLATION)
    for before, after in SIMILARITY_REPLACEMENTS:
        normalized = normalized.replace(before, after)
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _similarity(left: str, right: str) -> float:
    normalized_left = _normalize_for_similarity(left)
    normalized_right = _normalize_for_similarity(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _ngram_similarity(left: str, right: str, size: int = 2) -> float:
    normalized_left = _normalize_for_similarity(left)
    normalized_right = _normalize_for_similarity(right)
    if len(normalized_left) < size or len(normalized_right) < size:
        return 0.0
    left_ngrams = {
        normalized_left[index:index + size]
        for index in range(len(normalized_left) - size + 1)
    }
    right_ngrams = {
        normalized_right[index:index + size]
        for index in range(len(normalized_right) - size + 1)
    }
    return (
        2 * len(left_ngrams & right_ngrams)
        / (len(left_ngrams) + len(right_ngrams))
    )


def _contained_similarity(left: str, right: str) -> float:
    """Return how much of the shorter normalized text occurs in the longer one."""
    normalized_left = _normalize_for_similarity(left)
    normalized_right = _normalize_for_similarity(right)
    if not normalized_left or not normalized_right:
        return 0.0
    shorter, longer = sorted((normalized_left, normalized_right), key=len)
    if len(shorter) < 8:
        return 0.0
    if shorter in longer:
        return len(shorter) / len(longer)
    return 0.0


def _numeric_signals(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value or "").translate(NUMBER_TRANSLATION)
    return set(re.findall(r"\d+(?:\.\d+)?", normalized))


def duplicate_reason(
    *,
    title: str,
    content: str,
    source: str,
    explanation: str = "",
    other_title: str,
    other_content: str,
    other_source: str,
    other_explanation: str = "",
) -> Optional[str]:
    if _similarity(title, other_title) >= 0.68:
        return "タイトルが類似しています"
    if _similarity(content, other_content) >= 0.68:
        return "本文が類似しています"

    combined = f"{title} {content} {explanation}"
    other_combined = f"{other_title} {other_content} {other_explanation}"
    if _contained_similarity(combined, other_combined) >= 0.55:
        return "同じ説明を含んでいます"

    title_ngrams = _ngram_similarity(title, other_title)
    combined_ngrams = _ngram_similarity(combined, other_combined)
    if (
        title_ngrams >= 0.27
        and combined_ngrams >= 0.32
    ):
        return "同じ事実の言い換えに見えます"
    shared_numbers = _numeric_signals(combined) & _numeric_signals(other_combined)
    if shared_numbers and title_ngrams >= 0.22 and combined_ngrams >= 0.27:
        return "対象と数値が共通する同じ事実に見えます"
    return None


def find_duplicate(
    db: Session,
    *,
    title: str,
    content: str,
    explanation: str = "",
    source: str = "",
    exclude_candidate_id: Optional[int] = None,
    include_pending: bool = True,
) -> Optional[str]:
    for trivia in db.query(
        Trivia.id,
        Trivia.title,
        Trivia.content,
        Trivia.explanation,
        Trivia.source,
    ).all():
        reason = duplicate_reason(
            title=title,
            content=content,
            explanation=explanation,
            source=source,
            other_title=trivia.title,
            other_content=trivia.content,
            other_explanation=trivia.explanation,
            other_source=trivia.source,
        )
        if reason:
            return f"公開済み #{trivia.id}「{trivia.title}」と{reason}"

    if include_pending:
        query = db.query(
            TriviaCandidate.id,
            TriviaCandidate.title,
            TriviaCandidate.content,
            TriviaCandidate.explanation,
            TriviaCandidate.source,
        ).filter(TriviaCandidate.status == "pending")
        if exclude_candidate_id is not None:
            query = query.filter(TriviaCandidate.id != exclude_candidate_id)
        for candidate in query.all():
            reason = duplicate_reason(
                title=title,
                content=content,
                explanation=explanation,
                source=source,
                other_title=candidate.title,
                other_content=candidate.content,
                other_explanation=candidate.explanation,
                other_source=candidate.source,
            )
            if reason:
                return f"承認待ち #{candidate.id}「{candidate.title}」と{reason}"
    return None


def create_candidates(db: Session, items: Iterable[dict]) -> list[TriviaCandidate]:
    candidates = []
    for item in items:
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not title or not content:
            continue
        if find_duplicate(
            db,
            title=title,
            content=content,
            explanation=(item.get("explanation") or "").strip(),
            source=(item.get("source") or "").strip(),
        ):
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
    duplicate = find_duplicate(
        db,
        title=title,
        content=content,
        explanation=(item.get("explanation") or "").strip(),
        source=(item.get("source") or "").strip(),
    )
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
        map_address=(item.get("map_address") or "").strip() or None,
        map_prefecture=(item.get("map_prefecture") or "").strip() or None,
        map_latitude=_optional_float(item.get("map_latitude")),
        map_longitude=_optional_float(item.get("map_longitude")),
        map_radius=_optional_int(item.get("map_radius")),
        map_hint=(item.get("map_hint") or "").strip() or None,
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
    map_address: Optional[str] = None,
    map_prefecture: Optional[str] = None,
    map_latitude: Optional[float] = None,
    map_longitude: Optional[float] = None,
    map_radius: Optional[int] = None,
    map_hint: Optional[str] = None,
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
        explanation=explanation,
        source=source,
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
    candidate.map_address = (map_address or "").strip() or None
    candidate.map_prefecture = (map_prefecture or "").strip() or None
    candidate.map_latitude = _optional_float(map_latitude)
    candidate.map_longitude = _optional_float(map_longitude)
    candidate.map_radius = _optional_int(map_radius)
    candidate.map_hint = (map_hint or "").strip() or None
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
        explanation=candidate.explanation,
        source=candidate.source,
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
