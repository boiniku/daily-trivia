"""LINE map approvals share the atomic administration publication workflow."""

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    from models import Base, MapTrivia, Trivia, TriviaCandidate
    from routers import line_admin
    from routers.line_admin import _approve_candidate_from_line
    from services.line_bot import make_editor_token
    from services.trivia_candidates import CandidateError


class AdminLineApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def candidate(self, *, map_candidate=True, **overrides):
        values = dict(
            title="東京タワーの色", content="東京タワーの色には正式な名前があります。",
            explanation="航空機から目立つようにするためです。", category="地理", status="pending",
            image_url="https://images.example.test/trivia/tower.webp",
        )
        if map_candidate:
            values.update(
                map_prefecture="東京都", map_address="東京タワー / 東京都港区芝公園4-2-8",
                map_latitude=35.658581, map_longitude=139.745433, map_radius=500,
                map_hint="赤と白の塔を探そう",
            )
        item = TriviaCandidate(**{**values, **overrides})
        self.db.add(item)
        self.db.commit()
        return item

    def test_map_approval_commits_once_and_preserves_review_convention(self):
        candidate = self.candidate()
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            message = _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        self.assertEqual(commit.call_count, 1)
        self.assertIn("MAPに公開しました", message)
        self.assertEqual(candidate.status, "rejected")
        self.assertEqual(candidate.reviewed_by, "line:reviewer:map-published")
        self.assertIsNotNone(candidate.reviewed_at)
        self.assertEqual(self.db.query(Trivia).count(), 0)
        published = self.db.query(MapTrivia).one()
        self.assertEqual(published.image_url, candidate.image_url)
        self.assertEqual(published.map_hint, candidate.map_hint)

    def test_repeated_map_approval_reports_reviewed_candidate_without_duplicate(self):
        candidate = self.candidate()
        _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        with self.assertRaisesRegex(CandidateError, "既に確認済み"):
            _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        self.assertEqual(self.db.query(MapTrivia).count(), 1)
        self.assertEqual(self.db.query(Trivia).count(), 0)

    def test_rejected_map_candidate_cannot_be_published(self):
        candidate = self.candidate(status="rejected", reviewed_by="line:reviewer")
        with self.assertRaises(CandidateError):
            _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        self.assertEqual(self.db.query(MapTrivia).count(), 0)

    def test_map_write_failure_keeps_candidate_pending(self):
        candidate = self.candidate()

        def fail_insert(*_):
            raise RuntimeError("simulated map failure")

        event.listen(MapTrivia, "before_insert", fail_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        finally:
            event.remove(MapTrivia, "before_insert", fail_insert)
        self.assertEqual(candidate.status, "pending")
        self.assertIsNone(candidate.reviewed_at)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)

    def test_invalid_coordinates_are_reported_as_line_review_error(self):
        candidate = self.candidate(map_latitude=91)
        with self.assertRaisesRegex(CandidateError, "緯度"):
            _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        self.assertEqual(candidate.status, "pending")
        self.assertEqual(self.db.query(MapTrivia).count(), 0)

    def test_normal_approval_still_returns_existing_publication_on_repeat(self):
        candidate = self.candidate(map_candidate=False)
        first = _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        second = _approve_candidate_from_line(self.db, candidate.id, "reviewer")
        self.assertEqual(first, second)
        self.assertEqual(candidate.status, "approved")
        self.assertEqual(self.db.query(Trivia).count(), 1)
        self.assertEqual(self.db.query(MapTrivia).count(), 0)


class SignedAdminPublicationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.secret = patch.dict(os.environ, {"CANDIDATE_EDITOR_SECRET": "test-signed-admin-secret"})
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.session_patch = patch.object(line_admin, "SessionLocal", self.sessions)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        app = FastAPI()
        app.include_router(line_admin.router)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.payload = dict(
            title="東京タワーの色", content="東京タワーの色には正式な名前があります。",
            explanation="航空機から目立つようにするためです。", category="地理",
            source="https://example.test/tower", image_url="https://images.example.test/trivia/tower.webp",
            add_to_normal=True, add_to_map=True, publish=False,
            map_prefecture="東京都", map_address="東京タワー / 東京都港区芝公園4-2-8",
            map_latitude=35.658581, map_longitude=139.745433, map_radius=500,
            map_hint="赤と白の塔を探そう",
        )

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def seed_candidate(self):
        with self.sessions() as db:
            item = TriviaCandidate(title="元のタイトル", content="元の本文", category="その他", status="pending")
            db.add(item)
            db.commit()
            return item.id

    def post_new(self, **overrides):
        return self.client.post("/admin/candidates/new", json={
            **self.payload, "token": make_editor_token(0), **overrides,
        })

    def put_existing(self, candidate_id, **overrides):
        return self.client.put(f"/admin/candidates/{candidate_id}/edit", json={
            **self.payload, "token": make_editor_token(candidate_id), **overrides,
        })

    def assert_counts(self, *, normal=0, map_count=0, candidates=0):
        with self.sessions() as db:
            self.assertEqual(db.query(Trivia).count(), normal)
            self.assertEqual(db.query(MapTrivia).count(), map_count)
            self.assertEqual(db.query(TriviaCandidate).count(), candidates)

    def test_new_publish_false_still_publishes_both_without_creating_candidate(self):
        response = self.post_new()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")
        self.assertIsNotNone(response.json()["trivia_id"])
        self.assertIsNone(response.json()["map_spot_id"])
        self.assert_counts(normal=1, map_count=1)
        with self.sessions() as db:
            normal = db.query(Trivia).one()
            map_item = db.query(MapTrivia).one()
            self.assertEqual(normal.image_url, map_item.image_url)
            self.assertEqual(map_item.map_hint, self.payload["map_hint"])

    def test_existing_publish_false_publishes_both_with_review_history(self):
        candidate_id = self.seed_candidate()
        response = self.put_existing(candidate_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")
        self.assert_counts(normal=1, map_count=1, candidates=1)
        with self.sessions() as db:
            candidate = db.get(TriviaCandidate, candidate_id)
            self.assertEqual(candidate.status, "approved")
            self.assertEqual(candidate.published_trivia_id, response.json()["trivia_id"])
            self.assertEqual(candidate.reviewed_by, "mobile-editor")
            self.assertEqual(candidate.title, self.payload["title"])

    def test_new_map_write_failure_leaves_no_partial_normal_publication(self):
        def fail_insert(*_):
            raise RuntimeError("simulated map failure")

        event.listen(MapTrivia, "before_insert", fail_insert)
        try:
            self.assertEqual(self.post_new().status_code, 500)
        finally:
            event.remove(MapTrivia, "before_insert", fail_insert)
        self.assert_counts()

    def test_existing_map_write_failure_rolls_back_edits_review_and_publications(self):
        candidate_id = self.seed_candidate()

        def fail_insert(*_):
            raise RuntimeError("simulated map failure")

        event.listen(MapTrivia, "before_insert", fail_insert)
        try:
            self.assertEqual(self.put_existing(candidate_id).status_code, 500)
        finally:
            event.remove(MapTrivia, "before_insert", fail_insert)
        self.assert_counts(candidates=1)
        with self.sessions() as db:
            candidate = db.get(TriviaCandidate, candidate_id)
            self.assertEqual(candidate.status, "pending")
            self.assertEqual(candidate.title, "元のタイトル")
            self.assertEqual(candidate.content, "元の本文")
            self.assertIsNone(candidate.published_trivia_id)
            self.assertIsNone(candidate.reviewed_at)

    def test_invalid_map_values_return_400_without_partial_publications(self):
        candidate_id = self.seed_candidate()
        for field, value in (
            ("map_address", " "), ("map_prefecture", " "),
            ("map_latitude", 91), ("map_longitude", -181), ("map_radius", 0),
        ):
            with self.subTest(field=field, endpoint="new"):
                self.assertEqual(self.post_new(**{field: value}).status_code, 400)
            with self.subTest(field=field, endpoint="existing"):
                self.assertEqual(self.put_existing(candidate_id, **{field: value}).status_code, 400)
        self.assert_counts(candidates=1)

    def test_whitespace_required_fields_return_400_for_both_routes(self):
        candidate_id = self.seed_candidate()
        for field in ("title", "content"):
            with self.subTest(field=field):
                self.assertEqual(self.post_new(**{field: " \t"}).status_code, 400)
                self.assertEqual(self.put_existing(candidate_id, **{field: " \t"}).status_code, 400)
        self.assert_counts(candidates=1)

    def test_existing_map_only_publishes_once_and_keeps_legacy_response(self):
        candidate_id = self.seed_candidate()
        first = self.put_existing(candidate_id, add_to_normal=False)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), {"ok": True, "status": "approved", "trivia_id": None, "map_spot_id": None})
        repeated = self.put_existing(candidate_id, add_to_normal=False)
        self.assertEqual(repeated.status_code, 409)
        self.assert_counts(map_count=1, candidates=1)
        with self.sessions() as db:
            candidate = db.get(TriviaCandidate, candidate_id)
            self.assertEqual(candidate.status, "rejected")
            self.assertEqual(candidate.reviewed_by, "mobile-editor:map-published")

    def test_mismatched_tokens_are_rejected_before_writes(self):
        candidate_id = self.seed_candidate()
        self.assertEqual(self.post_new(token=make_editor_token(candidate_id)).status_code, 403)
        self.assertEqual(self.put_existing(candidate_id, token=make_editor_token(0)).status_code, 403)
        self.assert_counts(candidates=1)


if __name__ == "__main__":
    unittest.main()
