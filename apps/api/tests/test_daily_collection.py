import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, DailyTriviaCollectionRun, TriviaCandidate
from routers.daily_collection import _authorize
from services import daily_trivia_collection
from services.daily_trivia_collection import (
    estimate_collection_cost_usd,
    prepare_daily_collection,
    run_daily_collection,
)
from services.trivia_candidates import create_candidates
from services.trivia_collection import TriviaCollectionUsage


JST = ZoneInfo("Asia/Tokyo")


class DailyCollectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_prepare_is_idempotent_for_jst_date(self):
        now = datetime(2026, 8, 14, 9, 0, tzinfo=JST)
        first, first_started = prepare_daily_collection(self.db, now=now)
        second, second_started = prepare_daily_collection(self.db, now=now)
        self.assertTrue(first_started)
        self.assertFalse(second_started)
        self.assertEqual(first.id, second.id)

    def test_prepare_stops_at_pending_limit(self):
        self.db.add(TriviaCandidate(title="未承認", content="本文", status="pending"))
        self.db.commit()
        with patch.dict(os.environ, {"DAILY_COLLECTION_MAX_PENDING": "1"}):
            run, should_start = prepare_daily_collection(
                self.db,
                now=datetime(2026, 8, 14, 9, 0, tzinfo=JST),
            )
        self.assertFalse(should_start)
        self.assertEqual(run.status, "skipped")

    def test_estimated_cost_uses_configurable_rates(self):
        usage = TriviaCollectionUsage(1_000_000, 1_000_000, 1000)
        self.assertEqual(estimate_collection_cost_usd(usage), 12.25)

    def test_run_sends_one_carousel_and_records_usage(self):
        run = DailyTriviaCollectionRun(
            run_date=datetime(2026, 8, 14, tzinfo=JST).date(),
            status="running",
            requested_count=2,
        )
        self.db.add(run)
        self.db.commit()

        def fake_collect(db, topic, count, map_mode=False, usage_callback=None):
            usage_callback(TriviaCollectionUsage(1000, 500, 3))
            return create_candidates(db, [
                {"title": "タコの心臓は3つ", "content": "タコは3つの心臓を持ちます。", "category": "生物"},
                {"title": "金星の一日は一年より長い", "content": "金星は自転が非常に遅い惑星です。", "category": "宇宙・天体"},
            ])

        sent = []
        with patch.object(daily_trivia_collection, "SessionLocal", self.session_factory), \
             patch.object(daily_trivia_collection, "collect_trivia_candidates", fake_collect), \
             patch.object(daily_trivia_collection, "get_admin_user_ids", return_value=["admin"]), \
             patch.object(daily_trivia_collection, "push_message", side_effect=lambda user, messages: sent.append((user, messages))), \
             patch.dict(os.environ, {
                 "PUBLIC_BASE_URL": "https://example.com",
                 "CANDIDATE_EDITOR_SECRET": "test-editor-secret",
             }):
            run_daily_collection(run.id)

        verify = self.session_factory()
        try:
            saved_run = verify.query(DailyTriviaCollectionRun).filter_by(id=run.id).one()
            self.assertEqual(saved_run.status, "completed")
            self.assertEqual(saved_run.collected_count, 2)
            self.assertEqual(saved_run.web_search_calls, 3)
        finally:
            verify.close()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1][1]["contents"]["type"], "carousel")

    def test_endpoint_authorization(self):
        with patch.dict(os.environ, {"DAILY_COLLECTION_SECRET": "correct-secret"}):
            _authorize("Bearer correct-secret")
            with self.assertRaises(HTTPException):
                _authorize("Bearer wrong-secret")


if __name__ == "__main__":
    unittest.main()
