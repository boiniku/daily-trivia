"""Allow independent text and video content jobs for the same trivia."""

from sqlalchemy import inspect, text

from database import engine


def migrate() -> None:
    inspector = inspect(engine)
    if "social_content_jobs" not in inspector.get_table_names():
        return

    unique_constraints = inspector.get_unique_constraints("social_content_jobs")
    trivia_constraints = [
        item["name"]
        for item in unique_constraints
        if item.get("name") and item.get("column_names") == ["trivia_id"]
    ]
    unique_indexes = [
        item
        for item in inspector.get_indexes("social_content_jobs")
        if item.get("name")
        and item.get("unique")
        and item.get("column_names") == ["trivia_id"]
    ]

    if not trivia_constraints and not unique_indexes:
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            "Removing the social_content_jobs trivia_id uniqueness constraint "
            "is only supported automatically on PostgreSQL"
        )

    preparer = engine.dialect.identifier_preparer
    table_name = preparer.quote("social_content_jobs")
    with engine.begin() as connection:
        for constraint_name in trivia_constraints:
            quoted_constraint = preparer.quote(constraint_name)
            connection.execute(text(
                f"ALTER TABLE {table_name} DROP CONSTRAINT {quoted_constraint}"
            ))
        for index in unique_indexes:
            # PostgreSQL reports an index owned by a unique constraint with
            # duplicates_constraint. Dropping the constraint already removes it.
            if index.get("duplicates_constraint"):
                continue
            quoted_index = preparer.quote(index["name"])
            connection.execute(text(f"DROP INDEX IF EXISTS {quoted_index}"))

        # Preserve lookup performance after replacing the old unique index.
        index_name = preparer.quote("ix_social_content_jobs_trivia_id")
        connection.execute(text(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} ({preparer.quote('trivia_id')})"
        ))


if __name__ == "__main__":
    migrate()
