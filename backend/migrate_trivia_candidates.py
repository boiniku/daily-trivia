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

TRIVIA_COLUMNS = {
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

    existing = {column["name"] for column in inspector.get_columns("trivia_candidates")}
    trivia_existing = {column["name"] for column in inspector.get_columns("trivia")}
    with engine.begin() as conn:
        for name, sql_type in COLUMNS.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE trivia_candidates ADD COLUMN {name} {sql_type}"))
                print(f"Added trivia_candidates.{name}")
        for name, sql_type in TRIVIA_COLUMNS.items():
            if name not in trivia_existing:
                conn.execute(text(f"ALTER TABLE trivia ADD COLUMN {name} {sql_type}"))
                print(f"Added trivia.{name}")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_trivia_candidates_published_trivia_id "
            "ON trivia_candidates (published_trivia_id) "
            "WHERE published_trivia_id IS NOT NULL"
        ))


if __name__ == "__main__":
    migrate()
