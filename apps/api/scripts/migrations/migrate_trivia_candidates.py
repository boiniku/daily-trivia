from sqlalchemy import inspect, text

from database import engine

COLUMNS = {
    "image_url": "VARCHAR",
    "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "reviewed_at": "TIMESTAMP",
    "reviewed_by": "VARCHAR",
    "published_trivia_id": "INTEGER REFERENCES trivia(id)",
    "line_sent_at": "TIMESTAMP",
    "map_address": "VARCHAR",
    "map_prefecture": "VARCHAR",
    "map_latitude": "FLOAT",
    "map_longitude": "FLOAT",
    "map_radius": "INTEGER",
    "map_hint": "VARCHAR",
}

def migrate():
    inspector = inspect(engine)
    if not inspector.has_table("trivia_candidates") or not inspector.has_table("trivia"):
        from models import Base
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
    if not inspector.has_table("map_trivia"):
        from models import MapTrivia
        MapTrivia.__table__.create(bind=engine)
        inspector = inspect(engine)
    if not inspector.has_table("daily_trivia_collection_runs"):
        from models import DailyTriviaCollectionRun
        DailyTriviaCollectionRun.__table__.create(bind=engine)
        inspector = inspect(engine)
    from models import SocialContentJob, SocialPublishJob, SocialVideoJob
    for model in (SocialContentJob, SocialVideoJob, SocialPublishJob):
        if not inspector.has_table(model.__tablename__):
            model.__table__.create(bind=engine)
            inspector = inspect(engine)

    existing = {column["name"] for column in inspector.get_columns("trivia_candidates")}
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE trivia_candidates ADD COLUMN {name} {sql_type}"))
                print(f"Added trivia_candidates.{name}")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_trivia_candidates_published_trivia_id "
            "ON trivia_candidates (published_trivia_id) "
            "WHERE published_trivia_id IS NOT NULL"
        ))
        if engine.dialect.name == "postgresql":
            conn.execute(text(
                "ALTER TABLE map_trivia "
                "ALTER COLUMN map_radius SET DEFAULT 1200"
            ))
        trivia_columns = {column["name"] for column in inspector.get_columns("trivia")}
        if {"map_address", "map_prefecture", "map_latitude", "map_longitude"} <= trivia_columns:
            conn.execute(text("""
                INSERT INTO map_trivia (
                    title, content, explanation, source, category, image_url,
                    map_address, map_prefecture, map_latitude, map_longitude, map_radius, map_hint
                )
                SELECT
                    t.title, t.content, t.explanation, t.source, t.category, t.image_url,
                    t.map_address, t.map_prefecture, t.map_latitude, t.map_longitude, COALESCE(t.map_radius, 1200), t.map_hint
                FROM trivia t
                WHERE t.map_address IS NOT NULL
                  AND t.map_prefecture IS NOT NULL
                  AND t.map_latitude IS NOT NULL
                  AND t.map_longitude IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM map_trivia m
                      WHERE m.title = t.title
                        AND m.map_address = t.map_address
                        AND m.map_latitude = t.map_latitude
                        AND m.map_longitude = t.map_longitude
                  )
            """))

    # PostgreSQL's standard full-text parser does not segment Japanese well.
    # Trigram indexes accelerate the substring search used by collection history.
    if engine.dialect.name == "postgresql":
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                for column in ("title", "content", "explanation", "category"):
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_trivia_{column}_trgm "
                        f"ON trivia USING gin ({column} gin_trgm_ops)"
                    ))
        except Exception as exc:
            # Search remains correct without these optional performance indexes.
            print(f"Warning: could not create trivia search indexes: {exc}")


if __name__ == "__main__":
    migrate()
