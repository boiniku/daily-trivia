"""Public photo galleries preserve legacy covers and per-photo attribution."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    import main
    from models import Base, MapTrivia, Trivia
    from scripts.migrations.migrate_trivia_images import migrate


class PhotoGalleryApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            item = Trivia(title="写真テスト", content="本文", explanation="解説", source="本文の出典", category="科学",
                          image_url="old.jpg", image_urls=["first.jpg", "second.jpg"],
                          image_sources={"second.jpg": "写真提供：博物館"})
            spot = MapTrivia(title="写真MAP", content="本文", explanation="解説", source="本文の出典", category="地理",
                             image_url="map.jpg", image_urls=["map.jpg"], image_sources={"map.jpg": "https://museum.test/photo"},
                             map_address="東京都", map_prefecture="東京都", map_latitude=35, map_longitude=139)
            db.add_all([item, spot])
            db.commit()
            self.trivia_id = item.id
        def database():
            with self.sessions() as db:
                yield db
        self.overrides = dict(main.app.dependency_overrides)
        main.app.dependency_overrides[main.get_db] = database
        main.app.dependency_overrides[main.get_optional_user_id] = lambda: None
        self.patches = [patch.object(main, "TRIVIA_IMAGE_R2_BASE_URL", "https://images.test"),
                        patch.object(main, "AppSessionLocal", self.sessions)]
        for mocked in self.patches:
            mocked.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(self.overrides)
        for mocked in reversed(self.patches):
            mocked.stop()
        self.engine.dispose()

    def test_today_widget_and_details_return_the_whole_gallery_and_photo_sources(self):
        for path in ("/trivia/today", "/trivia/widget", f"/trivia/{self.trivia_id}"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                item = data[0] if isinstance(data, list) else data
                self.assertEqual(item["image_urls"], ["https://images.test/first.jpg", "https://images.test/second.jpg"])
                self.assertEqual(item["image_url"], item["image_urls"][0])
                self.assertEqual(item["image_sources"], {"https://images.test/second.jpg": "写真提供：博物館"})
                self.assertEqual(item["source"], "本文の出典")

    def test_map_keeps_110_payload_while_new_clients_receive_photos(self):
        item = self.client.get("/trivia/map").json()[0]
        self.assertEqual(item["image_sources"], {"https://images.test/map.jpg": "https://museum.test/photo"})
        old = self.client.get("/trivia/map", headers={"X-Daily-Trivia-App-Version": "1.1.0"}).json()[0]
        self.assertNotIn("image_urls", old)
        self.assertNotIn("image_sources", old)

    def test_collection_response_carries_attribution_and_explicit_photo_removal(self):
        values = dict(id=1, title="題名", content="本文", explanation="解説", source="本文の出典", category="科学",
                      image_url="first.jpg", image_urls=["first.jpg"], image_sources={"first.jpg": "撮影：山田太郎"}, user_hee_count=3)
        item = main.CollectionItemSchema.model_validate(values)
        self.assertEqual(item.image_sources, {"https://images.test/first.jpg": "撮影：山田太郎"})
        self.assertEqual(item.user_hee_count, 3)
        cleared = main.CollectionItemSchema.model_validate(dict(values, image_urls=[]))
        self.assertEqual(cleared.image_sources, {})
        self.assertIsNone(cleared.image_url)


class PhotoGalleryMigrationTests(unittest.TestCase):
    def test_legacy_migration_is_additive_and_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as db:
                for table in ("trivia", "map_trivia", "trivia_candidates"):
                    db.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, image_url VARCHAR)"))
                    db.execute(text(f"INSERT INTO {table} VALUES (1, 'photo.jpg')"))
            migrate(engine)
            migrate(engine)
            for table in ("trivia", "map_trivia", "trivia_candidates"):
                self.assertTrue({"image_url", "image_urls", "image_sources"} <= {column["name"] for column in inspect(engine).get_columns(table)})
            self.assertTrue({"image_credit", "image_credit_metadata"} <= {column["name"] for column in inspect(engine).get_columns("trivia")})
            with engine.connect() as db:
                self.assertEqual(db.execute(text("SELECT image_url FROM trivia WHERE id=1")).scalar_one(), "photo.jpg")
        finally:
            engine.dispose()
