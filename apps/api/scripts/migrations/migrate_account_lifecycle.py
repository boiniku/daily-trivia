"""Add durable merge intents and prevent late writes after account deletion."""
from sqlalchemy import text
from database import engine
from models import AccountLifecycle


def migrate():
    AccountLifecycle.__table__.create(engine, checkfirst=True)
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        # All application writers (including old clients) take the same lock as
        # delete/merge. SECURITY DEFINER only exposes this yes/no write check.
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION public.check_account_data_write()
            RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = pg_catalog, public AS $$
            DECLARE account_id text;
            BEGIN
                IF TG_TABLE_NAME = 'collection_items' THEN
                    SELECT user_id INTO account_id FROM public.collections WHERE id = NEW.collection_id;
                ELSE
                    account_id := NEW.user_id;
                END IF;
                IF account_id IS NOT NULL THEN
                    PERFORM pg_advisory_xact_lock(('x' || substr(md5(account_id), 1, 16))::bit(64)::bigint);
                    IF EXISTS (SELECT 1 FROM public.account_lifecycle
                               WHERE user_id = account_id AND status <> 'active') THEN
                        RAISE EXCEPTION 'Account data is deleted or transferred' USING ERRCODE = '42501';
                    END IF;
                END IF;
                RETURN NEW;
            END $$;
        """))
        for table in ("map_trivia_unlocks", "daily_assignments", "trivia_hees", "collections", "collection_items"):
            # Names are a fixed source-code allowlist, not user input.
            connection.execute(text(f"DROP TRIGGER IF EXISTS account_data_write_guard ON public.{table}"))
            connection.execute(text(f"""CREATE TRIGGER account_data_write_guard
                BEFORE INSERT OR UPDATE ON public.{table}
                FOR EACH ROW EXECUTE FUNCTION public.check_account_data_write()"""))


if __name__ == "__main__":
    migrate()
