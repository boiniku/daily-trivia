import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, MapTrivia, MapTriviaUnlock
from routers.user import (
    LegacyMergeRequest,
    MergeRequest,
    delete_user,
    merge_legacy_guest_data,
    merge_verified_guest_data,
)
from services.map_trivia import archive_map_trivia
from scripts.migrations.migrate_map_trivia_unlocks import LEGACY_STATIC_SPOTS, migrate


class MapUnlockAccountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        db.add_all([
            MapTrivia(
                title=f"地点{i}",
                content="本文",
                explanation="説明",
                source="https://example.com",
                category="地域",
                map_address="住所",
                map_prefecture="東京都",
                map_latitude=35.0 + i,
                map_longitude=139.0,
                map_radius=300,
            )
            for i in range(2)
        ])
        db.commit()
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def test_apple_link_merges_unlocks_without_losing_earliest_timestamp(self):
        db = self.session_factory()
        map_ids = [row[0] for row in db.query(MapTrivia.id).order_by(MapTrivia.id)]
        early = datetime.datetime(2026, 1, 1)
        late = datetime.datetime(2026, 2, 1)
        db.add_all([
            MapTriviaUnlock(user_id="guest", map_trivia_id=map_ids[0], unlocked_at=early),
            MapTriviaUnlock(user_id="apple", map_trivia_id=map_ids[0], unlocked_at=late),
            MapTriviaUnlock(user_id="guest", map_trivia_id=map_ids[1], unlocked_at=early),
        ])
        db.commit()
        db.close()

        with (
            patch("database.SessionLocal", self.session_factory),
            patch("routers.user.firebase_auth.verify_id_token", return_value={
                "uid": "guest",
                "firebase": {"sign_in_provider": "anonymous"},
            }),
        ):
            merge_verified_guest_data(MergeRequest(guest_id_token="verified-guest-token"), auth_user_id="apple")

        db = self.session_factory()
        try:
            unlocks = db.query(MapTriviaUnlock).order_by(MapTriviaUnlock.map_trivia_id).all()
            self.assertEqual(len(unlocks), 2)
            self.assertTrue(all(item.user_id == "apple" for item in unlocks))
            self.assertEqual(unlocks[0].unlocked_at, early)
        finally:
            db.close()

    def test_archiving_keeps_both_collectible_and_unlock_ledger(self):
        db = self.session_factory()
        try:
            map_trivia = db.query(MapTrivia).first()
            db.add(MapTriviaUnlock(
                user_id="apple",
                map_trivia_id=map_trivia.id,
            ))
            db.commit()

            archive_map_trivia(db, map_trivia.id)

            self.assertFalse(db.query(MapTrivia).filter_by(id=map_trivia.id).one().is_active)
            self.assertEqual(db.query(MapTriviaUnlock).count(), 1)
            foreign_key = next(iter(MapTriviaUnlock.map_trivia_id.property.columns[0].foreign_keys))
            self.assertEqual(foreign_key.ondelete, "RESTRICT")
        finally:
            db.close()

    def test_merge_rejects_a_token_that_is_not_anonymous(self):
        with patch("routers.user.firebase_auth.verify_id_token", return_value={
            "uid": "another-apple-user",
            "firebase": {"sign_in_provider": "apple.com"},
        }):
            with self.assertRaisesRegex(Exception, "anonymous Firebase user"):
                merge_verified_guest_data(
                    MergeRequest(guest_id_token="not-a-guest-token"),
                    auth_user_id="apple",
                )

    def test_legacy_merge_remains_available_only_during_rollout_window(self):
        with (
            patch("database.SessionLocal", self.session_factory),
            patch.dict("os.environ", {"LEGACY_GUEST_MERGE_DEADLINE": "2099-01-01T00:00:00+00:00"}),
        ):
            result = merge_legacy_guest_data(
                LegacyMergeRequest(guest_user_id="guest"),
                auth_user_id="apple",
            )
            self.assertEqual(result["message"], "Merge successful")

        with patch.dict("os.environ", {"LEGACY_GUEST_MERGE_DEADLINE": "2020-01-01T00:00:00+00:00"}):
            with self.assertRaisesRegex(Exception, "expired"):
                merge_legacy_guest_data(
                    LegacyMergeRequest(guest_user_id="guest"),
                    auth_user_id="apple",
                )

    def test_explicit_account_deletion_removes_unlock_ledger(self):
        db = self.session_factory()
        map_id = db.query(MapTrivia.id).first()[0]
        db.add(MapTriviaUnlock(user_id="apple", map_trivia_id=map_id))
        db.commit()
        db.close()

        with patch("database.SessionLocal", self.session_factory):
            delete_user(user_id="apple")

        db = self.session_factory()
        try:
            self.assertEqual(db.query(MapTriviaUnlock).count(), 0)
        finally:
            db.close()

    def test_legacy_static_seed_is_complete_and_idempotent(self):
        with patch("scripts.migrations.migrate_map_trivia_unlocks.engine", self.engine):
            migrate()
            migrate()

        db = self.session_factory()
        try:
            seeded = db.query(MapTrivia).filter(MapTrivia.legacy_spot_id.isnot(None)).all()
            self.assertEqual(
                {item.legacy_spot_id for item in seeded},
                {item["legacy_spot_id"] for item in LEGACY_STATIC_SPOTS},
            )
            self.assertTrue(all(not item.is_active for item in seeded))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
