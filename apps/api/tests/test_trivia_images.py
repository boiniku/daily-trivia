import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    import main
    from models import Base, MapTrivia, Trivia, TriviaCandidate
    from scripts.migrations.migrate_trivia_images import migrate
    from services.admin_workflow import (
        create_manual_trivia, publish_candidate, update_map_trivia, update_normal_trivia,
    )
    from services.map_trivia import create_map_trivia_from_candidate
    from services.trivia_candidates import approve_candidate, create_candidate, update_candidate
    from services.trivia_images import MAX_TRIVIA_IMAGES, normalize_trivia_images, read_trivia_images


class TriviaImageNormalizationTests(unittest.TestCase):
    def test_legacy_fallback_and_authoritative_empty_gallery(self):
        self.assertEqual(normalize_trivia_images(None, " old/a.jpg "), ["old/a.jpg"])
        self.assertEqual(normalize_trivia_images([], "old/a.jpg"), [])
        self.assertEqual(normalize_trivia_images(), [])

    def test_trims_deduplicates_and_preserves_order(self):
        self.assertEqual(
            normalize_trivia_images([" b.jpg ", "a.jpg", "", "b.jpg", "https://example.test/a.jpg"]),
            ["b.jpg", "a.jpg", "https://example.test/a.jpg"],
        )

    def test_rejects_invalid_shapes_references_and_image_limit(self):
        invalid = [
            "one.jpg", ("a.jpg",), [None], [123], ["javascript:alert(1)"],
            ["https://"], ["../secret"], ["//example.test/a.jpg"], ["a\n.jpg"],
            [f"{index}.jpg" for index in range(MAX_TRIVIA_IMAGES + 1)],
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_trivia_images(value)

    def test_reads_skip_invalid_photos_individually_and_keep_authoritative_empty_list(self):
        self.assertEqual(read_trivia_images(["one.jpg", "https://", None, "../bad", "two.jpg"]),
                         ["one.jpg", "two.jpg"])
        self.assertEqual(read_trivia_images([], "stale.jpg"), [])
        self.assertEqual(read_trivia_images(None, "https://"), [])


class TriviaImageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.values = dict(title="地層の重なり", content="岩石の層には過去の環境が記録されています。",
                           explanation="堆積が長年かけて積み重なるためです。", source="出典", category="地理")
        self.location = dict(map_address="東京都の地層", map_prefecture="東京都", map_latitude=35,
                             map_longitude=139, map_radius=300)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def candidate(self):
        return create_candidate(self.db, {**self.values, **self.location, "image_urls": ["one.jpg", "two.jpg"]})

    def test_create_and_atomic_publication_share_complete_gallery(self):
        result = create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location,
                                      image_urls=["one.jpg", "two.jpg"], image_url="ignored.jpg")
        for item in (result.trivia, result.map_trivia):
            self.assertEqual(item.image_urls, ["one.jpg", "two.jpg"])
            self.assertEqual(item.image_url, "one.jpg")

    def test_photo_sources_survive_publication_reordering_and_text_edits(self):
        sources = {"one.jpg": "https://museum.test/original", "two.jpg": "撮影：山田太郎"}
        candidate = create_candidate(self.db, {**self.values, **self.location,
            "image_urls": ["one.jpg", "two.jpg"], "image_sources": sources})
        copied = create_map_trivia_from_candidate(self.db, candidate)
        self.assertEqual(copied.image_sources, sources)
        update_candidate(self.db, candidate.id, **self.values, **self.location, image_urls=["two.jpg", "one.jpg"])
        self.assertEqual(candidate.image_sources, sources)
        result = publish_candidate(self.db, candidate.id, add_to_map=True,
                                   map_address="別の場所", map_latitude=36)
        for item, update in ((result.trivia, update_normal_trivia), (result.map_trivia, update_map_trivia)):
            self.assertEqual(item.image_sources, sources)
            update(self.db, item.id, content="本文だけを更新します。")
            self.assertEqual(item.image_sources, sources)
            update(self.db, item.id, image_urls=["two.jpg"])
            self.assertEqual(item.image_sources, {"two.jpg": "撮影：山田太郎"})
            update(self.db, item.id, image_sources={})
            self.assertEqual(item.image_sources, {})

    def test_photo_sources_approval_and_clear_do_not_copy_trivia_source(self):
        candidate = create_candidate(self.db, {**self.values,
            "image_urls": ["one.jpg"], "image_sources": {"one.jpg": "写真提供：博物館"}})
        item = approve_candidate(self.db, candidate.id, "test")
        self.assertEqual(item.image_sources, {"one.jpg": "写真提供：博物館"})
        update_normal_trivia(self.db, item.id, image_urls=[])
        self.assertEqual(item.image_sources, {})
        self.assertEqual(item.source, self.values["source"])
        self.assertEqual(create_manual_trivia(self.db,
            title="出典未登録の写真", content="本文", source="本文の参考資料", image_url="other.jpg").trivia.image_sources, {})

    def test_atomic_publication_of_candidate_keeps_all_photos_on_text_edit(self):
        candidate = self.candidate()
        result = publish_candidate(self.db, candidate.id, add_to_map=True, source="更新した出典")
        for item in (candidate, result.trivia, result.map_trivia):
            self.assertEqual(item.image_urls, ["one.jpg", "two.jpg"])
            self.assertEqual(item.image_url, "one.jpg")

    def test_approval_and_map_copy_keep_all_candidate_photos(self):
        candidate = self.candidate()
        map_item = create_map_trivia_from_candidate(self.db, candidate)
        item = approve_candidate(self.db, candidate.id, "test")
        self.assertEqual(map_item.image_urls, ["one.jpg", "two.jpg"])
        self.assertEqual(item.image_urls, ["one.jpg", "two.jpg"])
        self.assertEqual(item.image_url, "one.jpg")

    def test_candidate_text_edit_and_legacy_cover_edit_keep_extra_photos(self):
        candidate = self.candidate()
        update_candidate(self.db, candidate.id, **self.values)
        self.assertEqual(candidate.image_urls, ["one.jpg", "two.jpg"])
        update_candidate(self.db, candidate.id, **self.values, image_url="cover.jpg")
        self.assertEqual(candidate.image_urls, ["cover.jpg", "two.jpg"])
        update_candidate(self.db, candidate.id, **self.values, image_urls=[])
        self.assertEqual(candidate.image_urls, [])
        self.assertIsNone(candidate.image_url)

    def test_normal_and_map_edits_preserve_reorder_and_clear(self):
        result = create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location,
                                      image_urls=["one.jpg", "two.jpg"])
        for item, update in ((result.trivia, update_normal_trivia), (result.map_trivia, update_map_trivia)):
            with self.subTest(model=type(item).__name__):
                update(self.db, item.id, source="新出典")
                self.assertEqual(item.image_urls, ["one.jpg", "two.jpg"])
                update(self.db, item.id, image_url="cover.jpg")
                self.assertEqual(item.image_urls, ["cover.jpg", "two.jpg"])
                update(self.db, item.id, image_urls=["two.jpg", "cover.jpg"])
                self.assertEqual(item.image_url, "two.jpg")
                update(self.db, item.id, image_url="")
                self.assertEqual(item.image_urls, [])
                self.assertIsNone(item.image_url)

    def test_gallery_validation_prevents_partial_publication(self):
        candidate = self.candidate()
        with self.assertRaises(ValueError):
            publish_candidate(self.db, candidate.id, add_to_map=True, image_urls=["https://"])
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)
        self.assertEqual(candidate.status, "pending")

    def test_old_client_can_replace_or_clear_a_malformed_legacy_cover(self):
        item = Trivia(**self.values, image_url="https://", image_urls=["https://", "extra.jpg"])
        self.db.add(item)
        self.db.commit()
        update_normal_trivia(self.db, item.id, image_url="fixed.jpg")
        self.assertEqual(item.image_urls, ["fixed.jpg", "extra.jpg"])
        item.image_urls = ["https://", "extra.jpg"]
        item.image_url = "https://"
        self.db.commit()
        update_normal_trivia(self.db, item.id, image_url="")
        self.assertEqual(item.image_urls, [])
        self.assertIsNone(item.image_url)


class TriviaImageMigrationTests(unittest.TestCase):
    def test_old_schema_backfills_all_models_and_repeated_migration_preserves_gallery(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                for name in ("trivia", "map_trivia", "trivia_candidates"):
                    connection.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, image_url VARCHAR)"))
                    connection.execute(text(f"INSERT INTO {name} VALUES (1, ' old/cover.jpg '), (2, NULL)"))
            migrate(engine)
            with engine.begin() as connection:
                for name in ("trivia", "map_trivia", "trivia_candidates"):
                    self.assertIn("image_urls", {column["name"] for column in inspect(connection).get_columns(name)})
                    self.assertIn("image_sources", {column["name"] for column in inspect(connection).get_columns(name)})
                    if name in {"trivia", "map_trivia"}:
                        for column in ("image_credit", "image_credit_metadata"):
                            self.assertIn(column, {c["name"] for c in inspect(connection).get_columns(name)})
                    self.assertIsNone(connection.execute(text(f"SELECT image_sources FROM {name} WHERE id=1")).scalar_one())
                    rows = connection.execute(text(f"SELECT image_url, image_urls FROM {name} ORDER BY id")).all()
                    self.assertEqual(rows[0].image_url, "old/cover.jpg")
                    self.assertEqual(json.loads(rows[0].image_urls), ["old/cover.jpg"])
                    self.assertEqual(json.loads(rows[1].image_urls), [])
                    connection.execute(text(f"UPDATE {name} SET image_urls=:gallery WHERE id=1"),
                                       {"gallery": json.dumps(["old/cover.jpg", "extra.jpg"])})
                    connection.execute(text(f"UPDATE {name} SET image_sources=:sources WHERE id=1"),
                                       {"sources": json.dumps({"old/cover.jpg": "写真提供：博物館"})})
            migrate(engine)
            with engine.connect() as connection:
                for name in ("trivia", "map_trivia", "trivia_candidates"):
                    gallery = connection.execute(text(f"SELECT image_urls FROM {name} WHERE id=1")).scalar_one()
                    self.assertEqual(json.loads(gallery), ["old/cover.jpg", "extra.jpg"])
                    sources = connection.execute(text(f"SELECT image_sources FROM {name} WHERE id=1")).scalar_one()
                    self.assertEqual(json.loads(sources), {"old/cover.jpg": "写真提供：博物館"})
        finally:
            engine.dispose()

    def test_missing_tables_are_safe(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            migrate(engine)
            self.assertEqual(inspect(engine).get_table_names(), [])
        finally:
            engine.dispose()

    def test_deployment_migration_entrypoint_adds_gallery_before_orm_reads(self):
        from scripts.migrations import migrate_trivia_candidates
        engine = create_engine("sqlite:///:memory:")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                for name in ("trivia", "map_trivia", "trivia_candidates"):
                    connection.execute(text(f"ALTER TABLE {name} DROP COLUMN image_urls"))
            with patch.object(migrate_trivia_candidates, "engine", engine):
                migrate_trivia_candidates.migrate()
                migrate_trivia_candidates.migrate()
            for name in ("trivia", "map_trivia", "trivia_candidates"):
                self.assertIn("image_urls", {column["name"] for column in inspect(engine).get_columns(name)})
        finally:
            engine.dispose()


class TriviaImageApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        db = self.factory()
        item = Trivia(title="写真つき雑学", content="本文", explanation="解説", source="出典", category="科学",
                      image_url="stale.jpg", image_urls=["one.jpg", "https://external.test/two.jpg"],
                      image_sources={"one.jpg": "https://museum.test/original", "https://external.test/two.jpg": "撮影：山田太郎"})
        spot = MapTrivia(title="地図の写真", content="本文", explanation="解説", source="出典", category="地理",
                         image_url="stale.jpg", image_urls=["map/one.jpg", "map/two.jpg"], map_address="住所",
                         map_prefecture="東京都", map_latitude=35, map_longitude=139, map_radius=300,
                         image_sources={"map/two.jpg": "写真提供：観光協会"})
        db.add_all([item, spot])
        db.commit()
        self.trivia_id = item.id
        db.close()
        self.base_patch = patch.object(main, "TRIVIA_IMAGE_R2_BASE_URL", "https://images.test")
        self.base_patch.start()
        self.session_patch = patch.object(main, "AppSessionLocal", self.factory)
        self.session_patch.start()
        def get_db():
            db = self.factory()
            try:
                yield db
            finally:
                db.close()
        self.previous_overrides = dict(main.app.dependency_overrides)
        main.app.dependency_overrides[main.get_db] = get_db
        main.app.dependency_overrides[main.get_optional_user_id] = lambda: None
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(self.previous_overrides)
        self.session_patch.stop()
        self.base_patch.stop()
        self.engine.dispose()

    def test_today_widget_and_detail_serialize_gallery_and_synchronized_cover(self):
        for path in ("/trivia/today", "/trivia/widget", f"/trivia/{self.trivia_id}"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                item = response.json()[0] if isinstance(response.json(), list) else response.json()
                self.assertEqual(item["image_urls"], ["https://images.test/one.jpg", "https://external.test/two.jpg"])
                self.assertEqual(item["image_url"], "https://images.test/one.jpg")
                self.assertEqual(item["image_sources"], {"https://images.test/one.jpg": "https://museum.test/original",
                    "https://external.test/two.jpg": "撮影：山田太郎"})

    def test_map_adds_gallery_without_changing_110_compatibility_payload(self):
        item = self.client.get("/trivia/map").json()[0]
        self.assertEqual(item["image_urls"], ["https://images.test/map/one.jpg", "https://images.test/map/two.jpg"])
        self.assertEqual(item["image_url"], item["image_urls"][0])
        self.assertEqual(item["image_sources"], {"https://images.test/map/two.jpg": "写真提供：観光協会"})
        legacy = self.client.get("/trivia/map", headers={"X-Daily-Trivia-App-Version": "1.1.0"}).json()[0]
        self.assertNotIn("image_urls", legacy)
        self.assertNotIn("image_url", legacy)
        self.assertNotIn("image_sources", legacy)

    def test_collection_schema_normalizes_legacy_cover_and_preserves_hee_count(self):
        item = main.CollectionItemSchema.model_validate(dict(
            id=1, title="題名", content="本文", explanation="解説", source="出典", category="科学",
            image_url="old.jpg", user_hee_count=4,
        ))
        self.assertEqual(item.image_urls, ["https://images.test/old.jpg"])
        self.assertEqual(item.user_hee_count, 4)

    def test_explicit_empty_gallery_clears_stale_legacy_cover(self):
        item = main.TriviaSchema.model_validate(dict(
            id=1, title="題名", content="本文", explanation="解説", source="出典", category="科学",
            image_url="old.jpg", image_urls=[],
        ))
        self.assertEqual(item.image_urls, [])
        self.assertIsNone(item.image_url)

    def test_inline_legacy_image_remains_readable_after_backfill(self):
        for image_urls in (None, ["data:image/png;base64,example"]):
            item = main.public_trivia_image_values(image_urls, "data:image/png;base64,example")
            self.assertEqual(item["image_urls"], ["data:image/png;base64,example"])

    def test_valid_uppercase_url_scheme_does_not_become_an_r2_key(self):
        item = main.public_trivia_image_values(["HTTPS://images.external.test/one.jpg"])
        self.assertEqual(item["image_url"], "HTTPS://images.external.test/one.jpg")

    def test_bad_historical_cover_does_not_break_today_widget_detail_or_map(self):
        db = self.factory()
        item = db.get(Trivia, self.trivia_id)
        item.image_urls = ["https://", "two.jpg"]
        item.image_url = "https://"
        spot = db.query(MapTrivia).one()
        spot.image_urls = None
        spot.image_url = "javascript:bad"
        db.commit()
        db.close()
        for path in ("/trivia/today", "/trivia/widget", f"/trivia/{self.trivia_id}", "/trivia/map"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                item = response.json()[0] if isinstance(response.json(), list) else response.json()
                expected = [] if path == "/trivia/map" else ["https://images.test/two.jpg"]
                self.assertEqual(item["image_urls"], expected)


if __name__ == "__main__":
    unittest.main()
