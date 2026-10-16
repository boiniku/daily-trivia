import os
import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Importing models initializes database.py; force its otherwise unused engines
# to SQLite even when this checkout has real connection settings in .env.
with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    from models import (
        Base, Collection, CollectionItem, DailyAssignment, MapTrivia,
        SocialContentJob, Trivia, TriviaCandidate, TriviaHee,
    )
    from services.admin_workflow import (
        create_manual_trivia, delete_normal_trivia, publish_candidate,
        update_map_trivia, update_normal_trivia, validate_trivia_values,
    )


class AdminWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.values = {
            "title": "東京タワーの色",
            "content": "東京タワーはインターナショナルオレンジと白で塗られています。",
            "explanation": "航空機から見分けやすくするためです。",
            "source": "https://example.com/tower",
            "category": "観光",
            "image_url": "https://images.example.com/trivia/tower.webp",
        }
        self.location = {
            "map_address": "東京都港区芝公園4-2-8 / 東京タワー",
            "map_prefecture": "東京都",
            "map_latitude": 35.658581,
            "map_longitude": 139.745433,
            "map_radius": 500,
            "map_hint": "大きな展望台が目印です。",
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def candidate(self, **overrides):
        values = {**self.values, **self.location, "status": "pending", **overrides}
        item = TriviaCandidate(**values)
        self.db.add(item)
        self.db.commit()
        return item

    def test_trims_fields_and_rejects_whitespace_only_required_fields(self):
        values = validate_trivia_values(title=" 題名 ", content=" 本文 ", category=" ", image_url=" ")
        self.assertEqual(values["title"], "題名")
        self.assertEqual(values["content"], "本文")
        self.assertEqual(values["category"], "その他")
        self.assertIsNone(values["image_url"])
        for field in ("title", "content"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "必須"):
                validate_trivia_values(**{**self.values, field: " \t\n"})

    def test_requires_publication_destination(self):
        with self.assertRaisesRegex(ValueError, "どちらか"):
            create_manual_trivia(self.db, add_to_normal=False, add_to_map=False, **self.values)
        self.assertEqual(self.db.query(Trivia).count(), 0)

    def test_map_location_validation_prevents_partial_normal_publication(self):
        for field in ("map_prefecture", "map_address"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                create_manual_trivia(
                    self.db, add_to_map=True,
                    **{**self.values, **self.location, field: " "},
                )
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)

    def test_coordinates_are_finite_numbers_in_range_and_preserve_zero(self):
        for field, invalid in (
            ("map_latitude", 90.1), ("map_latitude", float("nan")),
            ("map_longitude", float("inf")), ("map_longitude", -180.1),
            ("map_latitude", None), ("map_longitude", True),
        ):
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                validate_trivia_values(
                    add_to_map=True, **{**self.values, **self.location, field: invalid},
                )
        values = validate_trivia_values(
            add_to_map=True,
            **{**self.values, **self.location, "map_latitude": 0, "map_longitude": 0},
        )
        self.assertEqual(values["map_latitude"], 0)
        self.assertEqual(values["map_longitude"], 0)

    def test_map_radius_must_be_an_integer_in_ui_range(self):
        for radius in (0, 9, 5001, 10.5, "unknown", None, True):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                validate_trivia_values(
                    add_to_map=True, **{**self.values, **self.location, "map_radius": radius},
                )

    def test_both_destinations_share_image_and_commit_once(self):
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            result = create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location)
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(result.trivia.image_url, self.values["image_url"])
        self.assertEqual(result.map_trivia.image_url, self.values["image_url"])
        self.assertEqual(result.map_trivia.map_hint, self.location["map_hint"])

    def test_map_only_keeps_uploaded_image(self):
        result = create_manual_trivia(
            self.db, add_to_normal=False, add_to_map=True, **self.values, **self.location,
        )
        self.assertIsNone(result.trivia)
        self.assertEqual(result.map_trivia.image_url, self.values["image_url"])
        self.assertEqual(self.db.query(Trivia).count(), 0)

    def test_repeated_manual_registration_is_rejected_without_duplicates(self):
        create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location)
        with self.assertRaisesRegex(ValueError, "登録済み"):
            create_manual_trivia(
                self.db, add_to_map=True,
                **{**self.values, "title": " " + self.values["title"] + " "}, **self.location,
            )
        self.assertEqual(self.db.query(Trivia).count(), 1)
        self.assertEqual(self.db.query(MapTrivia).count(), 1)

    def test_map_duplicate_prevents_adding_normal_copy(self):
        create_manual_trivia(
            self.db, add_to_normal=False, add_to_map=True, **self.values, **self.location,
        )
        with self.assertRaisesRegex(ValueError, "雑学MAP"):
            create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location)
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 1)

    def test_fact_at_different_map_location_is_allowed(self):
        create_manual_trivia(
            self.db, add_to_normal=False, add_to_map=True, **self.values, **self.location,
        )
        create_manual_trivia(
            self.db, add_to_normal=False, add_to_map=True, **self.values,
            **{**self.location, "map_address": "別の地点", "map_latitude": 36},
        )
        self.assertEqual(self.db.query(MapTrivia).count(), 2)

    def test_map_insert_failure_rolls_back_normal_insert(self):
        def fail_insert(*_):
            raise RuntimeError("simulated map write failure")

        event.listen(MapTrivia, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                create_manual_trivia(self.db, add_to_map=True, **self.values, **self.location)
        finally:
            event.remove(MapTrivia, "before_insert", fail_insert)
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)
        create_manual_trivia(self.db, **self.values)
        self.assertEqual(self.db.query(Trivia).count(), 1)

    def test_publish_candidate_both_destinations_is_atomic(self):
        candidate = self.candidate()
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            result = publish_candidate(self.db, candidate.id, add_to_map=True)
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(candidate.status, "approved")
        self.assertEqual(candidate.published_trivia_id, result.trivia.id)
        self.assertEqual(result.map_trivia.map_address, self.location["map_address"])
        self.assertIsNotNone(candidate.reviewed_at)

    def test_candidate_map_only_retains_review_convention_and_cannot_publish_twice(self):
        candidate = self.candidate()
        publish_candidate(self.db, candidate.id, add_to_normal=False, add_to_map=True)
        self.assertEqual(candidate.status, "rejected")
        self.assertEqual(candidate.reviewed_by, "streamlit:map-published")
        self.assertIsNone(candidate.published_trivia_id)
        with self.assertRaisesRegex(ValueError, "既に確認済み"):
            publish_candidate(self.db, candidate.id, add_to_normal=False, add_to_map=True)
        self.assertEqual(self.db.query(MapTrivia).count(), 1)

    def test_candidate_insert_failure_restores_edits_and_review_state(self):
        candidate = self.candidate()
        original_title = candidate.title
        candidate_id = candidate.id

        def fail_insert(*_):
            raise RuntimeError("simulated map write failure")

        event.listen(MapTrivia, "before_insert", fail_insert)
        try:
            with self.assertRaises(RuntimeError):
                publish_candidate(self.db, candidate_id, add_to_map=True, title="編集後の題名")
        finally:
            event.remove(MapTrivia, "before_insert", fail_insert)
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)
        self.assertEqual(candidate.title, original_title)
        self.assertEqual(candidate.status, "pending")
        self.assertIsNone(candidate.reviewed_at)
        self.assertIsNone(candidate.published_trivia_id)

    def test_candidate_duplicate_prevents_map_and_review_changes(self):
        candidate = self.candidate()
        create_manual_trivia(self.db, **self.values)
        with self.assertRaises(ValueError):
            publish_candidate(self.db, candidate.id, add_to_map=True)
        self.assertEqual(candidate.status, "pending")
        self.assertEqual(self.db.query(MapTrivia).count(), 0)
        self.assertEqual(self.db.query(Trivia).count(), 1)

    def test_map_edit_keeps_source_image_hint_and_zero_coordinates(self):
        item = create_manual_trivia(
            self.db, add_to_normal=False, add_to_map=True, **self.values, **self.location,
        ).map_trivia
        updated = update_map_trivia(self.db, item.id, title="改訂した題名", map_latitude=0, map_longitude=0)
        self.assertEqual(updated.source, self.values["source"])
        self.assertEqual(updated.image_url, self.values["image_url"])
        self.assertEqual(updated.map_hint, self.location["map_hint"])
        self.assertEqual(updated.map_latitude, 0)
        self.assertEqual(updated.map_longitude, 0)
        with self.assertRaises(ValueError):
            update_map_trivia(self.db, item.id, map_address=" ")
        self.assertEqual(item.map_address, self.location["map_address"])

    def test_normal_text_edit_invalidates_embedding_without_resetting_other_fields(self):
        item = create_manual_trivia(self.db, **self.values).trivia
        item.embedding = [0.1, 0.2]
        self.db.commit()
        update_normal_trivia(self.db, item.id, content="改訂後の本文")
        self.assertIsNone(item.embedding)
        self.assertEqual(item.image_url, self.values["image_url"])
        with self.assertRaises(ValueError):
            update_normal_trivia(self.db, item.id, title=" ")
        self.assertEqual(item.title, self.values["title"])

    def test_delete_cleans_foreign_keys_and_preserves_candidate_review_history(self):
        candidate = self.candidate()
        trivia = publish_candidate(self.db, candidate.id).trivia
        trivia_id = trivia.id
        collection = Collection(user_id="test-user", title="お気に入り")
        self.db.add(collection)
        self.db.flush()
        self.db.add_all([
            DailyAssignment(user_id="test-user", date=date(2026, 10, 15), trivia_id=trivia_id),
            CollectionItem(collection_id=collection.id, trivia_id=trivia_id),
            TriviaHee(user_id="test-user", trivia_id=trivia_id, count=1),
        ])
        self.db.commit()
        delete_normal_trivia(self.db, trivia_id)
        for model in (Trivia, DailyAssignment, CollectionItem, TriviaHee):
            self.assertEqual(self.db.query(model).count(), 0)
        self.assertEqual(self.db.query(Collection).count(), 1)
        self.assertEqual(candidate.status, "approved")
        self.assertIsNotNone(candidate.reviewed_at)
        self.assertIsNone(candidate.published_trivia_id)

    def test_delete_refuses_social_dependencies_without_changing_data(self):
        trivia = create_manual_trivia(self.db, **self.values).trivia
        self.db.add(SocialContentJob(trivia_id=trivia.id, status="published", content_json={}))
        self.db.add(TriviaHee(user_id="test-user", trivia_id=trivia.id, count=1))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "SNS"):
            delete_normal_trivia(self.db, trivia.id)
        self.assertEqual(self.db.query(Trivia).count(), 1)
        self.assertEqual(self.db.query(SocialContentJob).count(), 1)
        self.assertEqual(self.db.query(TriviaHee).count(), 1)


if __name__ == "__main__":
    unittest.main()
