"""Shared, idempotent history writes for widget delivery and card swipes."""

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import Collection, CollectionItem


HISTORY_TITLE = "過去に見た雑学"


def lock_trivia_user(db: Session, user_id: str) -> None:
    """Serialize daily assignment and history writes until this transaction ends."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"daily-trivia-history:{user_id}"},
        )


def record_history_items(db: Session, user_id: str, trivia_ids: Iterable[int]) -> int:
    """Add each trivia once without committing or clearing the caller's RLS context."""
    ids = list(dict.fromkeys(trivia_ids))
    if not ids:
        return 0

    lock_trivia_user(db, user_id)
    folders = db.query(Collection).filter(
        Collection.user_id == user_id,
        Collection.title == HISTORY_TITLE,
    ).order_by(Collection.id).all()
    if not folders:
        folder = Collection(
            user_id=user_id, title=HISTORY_TITLE, icon="time-outline", is_locked=False,
        )
        db.add(folder)
        # SET LOCAL is transaction scoped; committing here would clear RLS.
        db.flush()
        folders = [folder]

    # Older app versions could create duplicate default folders. Do not add a
    # second copy if a trivia already lives in any of this user's history folders.
    existing = {row[0] for row in db.query(CollectionItem.trivia_id).filter(
        CollectionItem.collection_id.in_([folder.id for folder in folders]),
        CollectionItem.trivia_id.in_(ids),
    ).all()}
    missing = [trivia_id for trivia_id in ids if trivia_id not in existing]
    db.add_all([
        CollectionItem(collection_id=folders[0].id, trivia_id=trivia_id)
        for trivia_id in missing
    ])
    # Production sessions disable autoflush. Repeated calls in the same
    # transaction must see the just-created rows as well.
    db.flush()
    return len(missing)
