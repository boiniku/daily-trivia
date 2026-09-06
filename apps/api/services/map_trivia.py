from sqlalchemy.orm import Session

from models import MapTrivia, TriviaCandidate


def create_map_trivia(
    db: Session,
    *,
    title: str,
    content: str,
    explanation: str,
    source: str,
    category: str,
    image_url: str | None,
    map_address: str,
    map_prefecture: str,
    map_latitude: float,
    map_longitude: float,
    map_radius: int = 1200,
    map_hint: str = "",
) -> MapTrivia:
    item = MapTrivia(
        title=title.strip(),
        content=content.strip(),
        explanation=(explanation or "").strip(),
        source=(source or "").strip(),
        category=(category or "その他").strip(),
        image_url=(image_url or "").strip() or None,
        map_address=map_address.strip(),
        map_prefecture=map_prefecture.strip(),
        map_latitude=float(map_latitude),
        map_longitude=float(map_longitude),
        map_radius=int(map_radius or 1200),
        map_hint=(map_hint or "").strip() or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_map_trivia_from_candidate(db: Session, candidate: TriviaCandidate) -> MapTrivia:
    return create_map_trivia(
        db,
        title=candidate.title or "",
        content=candidate.content or "",
        explanation=candidate.explanation or "",
        source=candidate.source or "",
        category=candidate.category or "その他",
        image_url=candidate.image_url,
        map_address=candidate.map_address or "",
        map_prefecture=candidate.map_prefecture or "",
        map_latitude=float(candidate.map_latitude),
        map_longitude=float(candidate.map_longitude),
        map_radius=int(candidate.map_radius or 1200),
        map_hint=candidate.map_hint or "",
    )
