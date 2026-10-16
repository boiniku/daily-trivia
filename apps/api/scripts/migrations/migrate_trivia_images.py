"""Add ordered galleries without discarding legacy single-photo references."""

from sqlalchemy import MetaData, Table, inspect, text

from database import engine


TABLES = ("trivia", "map_trivia", "trivia_candidates")


def migrate(bind=None):
    target = bind if bind is not None else engine
    inspector = inspect(target)
    for name in TABLES:
        if not inspector.has_table(name):
            continue
        columns = {column["name"] for column in inspector.get_columns(name)}
        with target.begin() as connection:
            guard = "IF NOT EXISTS " if target.dialect.name == "postgresql" else ""
            if "image_urls" not in columns:
                connection.execute(text(f"ALTER TABLE {name} ADD COLUMN {guard}image_urls JSON"))
            if "image_sources" not in columns:
                connection.execute(text(f"ALTER TABLE {name} ADD COLUMN {guard}image_sources JSON"))
            if name in {"trivia", "map_trivia"}:
                for column, kind in (("image_credit", "TEXT"), ("image_credit_metadata", "JSON")):
                    if column not in columns:
                        connection.execute(text(f"ALTER TABLE {name} ADD COLUMN {guard}{column} {kind}"))
            if "image_url" not in columns:
                continue
            table = Table(name, MetaData(), autoload_with=connection)
            rows = connection.execute(
                table.select().with_only_columns(table.c.id, table.c.image_url)
                .where(table.c.image_urls.is_(None))
            ).all()
            for row in rows:
                # Preserve existing references exactly. Validation belongs to
                # edits, so deployment never fails on a historical URL.
                cover = (row.image_url or "").strip()
                connection.execute(
                    table.update().where(table.c.id == row.id, table.c.image_urls.is_(None)).values(
                        image_urls=[cover] if cover else [], image_url=cover or None,
                    )
                )


if __name__ == "__main__":
    migrate()
