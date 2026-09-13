"""Create the private map trivia unlock ledger used by authenticated API routes."""

from sqlalchemy import inspect, text

from database import engine
from models import MapTriviaUnlock


def migrate() -> None:
    map_columns = {
        column["name"] for column in inspect(engine).get_columns("map_trivia")
    }
    if "is_active" not in map_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE map_trivia "
                "ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"
            ))

    if "map_trivia_unlocks" not in inspect(engine).get_table_names():
        MapTriviaUnlock.__table__.create(engine)

    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        # A map entry may be archived but must never cascade-delete a
        # collector's ledger. RESTRICT also catches accidental hard deletes.
        connection.execute(text("""
            DO $$
            DECLARE fk_name text;
                    delete_action "char";
            BEGIN
                SELECT conname, confdeltype INTO fk_name, delete_action
                FROM pg_constraint
                WHERE conrelid = 'map_trivia_unlocks'::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) LIKE '%map_trivia_id%';
                IF fk_name IS NULL OR delete_action <> 'r' THEN
                    IF fk_name IS NOT NULL THEN
                        EXECUTE format(
                            'ALTER TABLE map_trivia_unlocks DROP CONSTRAINT %I',
                            fk_name
                        );
                    END IF;
                    ALTER TABLE map_trivia_unlocks
                        ADD CONSTRAINT map_trivia_unlocks_map_trivia_id_fkey
                        FOREIGN KEY (map_trivia_id) REFERENCES map_trivia(id)
                        ON DELETE RESTRICT;
                END IF;
            END $$;
        """))

        app_user_exists = connection.execute(text(
            "SELECT 1 FROM pg_roles WHERE rolname = 'app_user'"
        )).scalar()
        # Some isolated staging databases use only the owner connection. The
        # table stays private there because no application role has a grant.
        if not app_user_exists:
            return

        connection.execute(text(
            "GRANT SELECT, INSERT ON map_trivia_unlocks TO app_user"
        ))
        connection.execute(text(
            "GRANT USAGE, SELECT ON SEQUENCE map_trivia_unlocks_id_seq TO app_user"
        ))
        connection.execute(text(
            "ALTER TABLE map_trivia_unlocks ENABLE ROW LEVEL SECURITY"
        ))
        connection.execute(text(
            "DROP POLICY IF EXISTS map_trivia_unlocks_select_own ON map_trivia_unlocks"
        ))
        connection.execute(text(
            "CREATE POLICY map_trivia_unlocks_select_own ON map_trivia_unlocks "
            "FOR SELECT TO app_user USING "
            "(user_id = current_setting('app.current_user_id', true))"
        ))
        connection.execute(text(
            "DROP POLICY IF EXISTS map_trivia_unlocks_insert_own ON map_trivia_unlocks"
        ))
        connection.execute(text(
            "CREATE POLICY map_trivia_unlocks_insert_own ON map_trivia_unlocks "
            "FOR INSERT TO app_user WITH CHECK "
            "(user_id = current_setting('app.current_user_id', true))"
        ))


if __name__ == "__main__":
    migrate()
