"""Exercise real PostgreSQL parameter inference in an isolated, disposable schema.

Set TEST_POSTGRES_DATABASE_URL to a test database. No application tables in the
public schema are read or changed. Both supported PostgreSQL drivers are tested.
"""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from models import MapTrivia, Trivia
from scripts.migrations import migrate_map_trivia_unlocks
from scripts.migrations.migrate_trivia_images import migrate as migrate_images


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DATABASE_URL"), "PostgreSQL test URL not configured")
class PostgresStartupMigrationTests(unittest.TestCase):
    def test_migrations_preserve_data_and_can_run_twice_with_both_drivers(self):
        url = make_url(os.environ["TEST_POSTGRES_DATABASE_URL"])
        # Neon transaction pooling rejects search_path startup options. Use the
        # direct endpoint of the same branch for this isolated-schema fixture.
        if (url.host or "").endswith(".neon.tech"):
            url = url.set(host=url.host.replace("-pooler.", "."))
        for driver in ("psycopg", "psycopg2"):
            with self.subTest(driver=driver):
                schema = "test_photo_startup_" + uuid4().hex
                target_url = url.set(drivername="postgresql+" + driver)
                admin = create_engine(target_url, poolclass=NullPool)
                engine = create_engine(target_url, poolclass=NullPool,
                                       connect_args={"options": "-csearch_path=" + schema})
                created = False
                try:
                    with admin.begin() as db:
                        db.execute(text(f'CREATE SCHEMA "{schema}"'))
                    created = True
                    Trivia.__table__.create(engine)
                    MapTrivia.__table__.create(engine)
                    with engine.begin() as db:
                        db.execute(text("INSERT INTO trivia (title, content, image_url) "
                                        "VALUES ('keep title', 'keep content', 'cover.webp')"))
                    with patch.object(migrate_map_trivia_unlocks, "engine", engine):
                        migrate_map_trivia_unlocks.migrate()
                        migrate_map_trivia_unlocks.migrate()
                    migrate_images(engine)
                    migrate_images(engine)
                    with engine.connect() as db:
                        rows = db.execute(text("SELECT legacy_spot_id, is_active FROM map_trivia")).all()
                        self.assertEqual({row.legacy_spot_id for row in rows},
                                         {spot["legacy_spot_id"] for spot in migrate_map_trivia_unlocks.LEGACY_STATIC_SPOTS})
                        self.assertEqual(len(rows), len(migrate_map_trivia_unlocks.LEGACY_STATIC_SPOTS))
                        self.assertTrue(all(not row.is_active for row in rows))
                        saved = db.execute(text("SELECT title, content, image_url, image_urls FROM trivia")).one()
                        self.assertEqual(tuple(saved), ("keep title", "keep content", "cover.webp", ["cover.webp"]))
                finally:
                    engine.dispose()
                    if created:
                        # Only this test's randomly named schema is removed.
                        with admin.begin() as db:
                            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                    admin.dispose()


if __name__ == "__main__":
    unittest.main()
