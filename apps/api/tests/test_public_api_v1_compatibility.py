import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from main import MapTriviaUnlockRequest, get_app_version, get_map_trivia, get_todays_trivia, health_check, record_map_trivia_unlocks
from models import Base, MapTrivia, MapTriviaUnlock, Trivia


class PublicApiV1CompatibilityTests(unittest.TestCase):
    """Protect fields used by the currently distributed 1.0.5 iOS client."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        db.add(
            Trivia(
                title="互換テスト",
                content="旧アプリでも読める",
                explanation="既存フィールドを維持する",
                source="https://example.com/source",
                category="テスト",
                hee_count=3,
            )
        )
        db.add(
            MapTrivia(
                title="姫町テスト",
                content="地図の互換テスト",
                explanation="説明",
                source="https://example.com/map-source",
                category="地域",
                map_address="岐阜県多治見市姫町",
                map_prefecture="岐阜県",
                map_latitude=35.390926,
                map_longitude=137.06683,
                map_radius=300,
                map_hint="姫町の中心付近",
            )
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def test_version_and_health_only_add_fields(self):
        self.assertTrue(
            {
                "minimum_supported_version",
                "latest_version",
                "app_store_url",
            }.issubset(get_app_version())
        )
        self.assertTrue({"status", "environment"}.issubset(health_check()))
        self.assertTrue({
            "map_unlock_backup_v2",
            "verified_guest_merge",
            "archived_map_collectibles",
        }.issubset(health_check()["capabilities"]))

    def test_map_contract_keeps_legacy_camel_case_fields(self):
        db = self.session_factory()
        try:
            payload = get_map_trivia(db=db)[0]
        finally:
            db.close()

        self.assertTrue(
            {
                "id",
                "title",
                "description",
                "latitude",
                "longitude",
                "unlockRadiusMeters",
                "isUnlocked",
                "unlockedAt",
            }.issubset(payload)
        )
        self.assertTrue(payload["id"].startswith("map_"))
        self.assertEqual(payload["unlockCount"], 0)

    def test_distributed_1_1_0_uses_pre_count_map_read_path(self):
        request = Request({
            "type": "http",
            "headers": [(b"x-daily-trivia-app-version", b"1.1.0")],
        })
        db = self.session_factory()
        try:
            payload = get_map_trivia(db=db, request=request)[0]
        finally:
            db.close()

        self.assertTrue(payload["id"].startswith("map_"))
        self.assertNotIn("unlockCount", payload)

    def test_map_unlock_count_is_idempotent_per_user(self):
        db = self.session_factory()
        try:
            spot_id = f"map_{db.query(MapTrivia.id).scalar()}"
            request = MapTriviaUnlockRequest(spot_ids=[spot_id, spot_id])
            first = record_map_trivia_unlocks(request, user_id="user-a", db=db)
            second = record_map_trivia_unlocks(request, user_id="user-a", db=db)
            third = record_map_trivia_unlocks(request, user_id="user-b", db=db)

            self.assertEqual(first["unlockCounts"][spot_id], 1)
            self.assertEqual(second["unlockCounts"][spot_id], 1)
            self.assertEqual(third["unlockCounts"][spot_id], 2)
            self.assertEqual(db.query(MapTriviaUnlock).count(), 2)
            self.assertEqual(get_map_trivia(db=db)[0]["unlockCount"], 2)
            self.assertEqual(first["unlockedRecords"][0]["id"], spot_id)
        finally:
            db.close()

    def test_empty_sync_returns_server_ledger_for_local_recovery(self):
        db = self.session_factory()
        try:
            map_trivia_id = db.query(MapTrivia.id).scalar()
            db.add(MapTriviaUnlock(user_id="recover-user", map_trivia_id=map_trivia_id))
            db.commit()

            payload = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(spot_ids=[]),
                user_id="recover-user",
                db=db,
            )

            self.assertEqual(payload["unlockCounts"], {})
            self.assertEqual(payload["unlockedRecords"][0]["id"], f"map_{map_trivia_id}")
        finally:
            db.close()

    def test_sync_preserves_original_unlock_time_and_returns_explicit_utc(self):
        db = self.session_factory()
        try:
            spot_id = f"map_{db.query(MapTrivia.id).scalar()}"
            original = "2024-01-02T03:04:05Z"
            payload = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(records=[{
                    "id": spot_id,
                    "unlockedAt": original,
                }]),
                user_id="apple-user",
                db=db,
            )

            self.assertEqual(payload["unlockedRecords"][0]["unlockedAt"], original)
            self.assertEqual(
                db.query(MapTriviaUnlock).one().unlocked_at,
                datetime.datetime(2024, 1, 2, 3, 4, 5),
            )
        finally:
            db.close()

    def test_fixed_legacy_spot_id_maps_to_archived_collectible(self):
        db = self.session_factory()
        try:
            legacy = MapTrivia(
                title="東京タワーの色の雑学",
                content="旧固定スポット",
                explanation="説明",
                source="",
                category="地域",
                map_address="東京タワー",
                map_prefecture="東京都",
                map_latitude=35.6586,
                map_longitude=139.7454,
                map_radius=300,
                is_active=False,
                legacy_spot_id="tokyo_001",
            )
            db.add(legacy)
            db.commit()

            payload = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(
                    records=[{"id": "tokyo_001", "unlockedAt": "2024-01-01T00:00:00Z"}],
                ),
                user_id="legacy-user",
                db=db,
            )

            self.assertEqual(payload["spotIdAliases"], {"tokyo_001": f"map_{legacy.id}"})
            collected = get_map_trivia(db=db, user_id="legacy-user")
            restored = next(item for item in collected if item["id"] == f"map_{legacy.id}")
            self.assertTrue(restored["isArchived"])
        finally:
            db.close()

    def test_update_sync_restores_each_identity_without_cross_user_leakage(self):
        db = self.session_factory()
        try:
            spot_id = f"map_{db.query(MapTrivia.id).scalar()}"

            for user_id in ("anonymous-user", "apple-user"):
                record_map_trivia_unlocks(
                    MapTriviaUnlockRequest(spot_ids=[spot_id]),
                    user_id=user_id,
                    db=db,
                )
                restored = record_map_trivia_unlocks(
                    MapTriviaUnlockRequest(spot_ids=[]),
                    user_id=user_id,
                    db=db,
                )
                self.assertEqual(
                    [item["id"] for item in restored["unlockedRecords"]],
                    [spot_id],
                )

            unrelated = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(spot_ids=[]),
                user_id="different-user",
                db=db,
            )
            self.assertEqual(unrelated["unlockedRecords"], [])
            self.assertEqual(db.query(MapTriviaUnlock).count(), 2)
        finally:
            db.close()

    def test_archived_map_trivia_remains_visible_to_its_collector(self):
        db = self.session_factory()
        try:
            map_trivia = db.query(MapTrivia).one()
            map_trivia.is_active = False
            db.add(MapTriviaUnlock(
                user_id="apple-user",
                map_trivia_id=map_trivia.id,
            ))
            db.commit()

            self.assertEqual(get_map_trivia(db=db, user_id=None), [])
            collected = get_map_trivia(db=db, user_id="apple-user")
            self.assertEqual(len(collected), 1)
            self.assertTrue(collected[0]["isArchived"])
        finally:
            db.close()

    def test_legacy_trivia_spot_id_is_mapped_without_discarding_it(self):
        db = self.session_factory()
        try:
            legacy_trivia = Trivia(
                title="旧ID引き継ぎテスト",
                content="旧地図IDで解放済み",
                explanation="旧形式から移行する",
                source="https://example.com/legacy-map-source",
                category="地域",
            )
            current_map = MapTrivia(
                title="旧ID引き継ぎテスト",
                content="旧地図IDで解放済み",
                explanation="旧形式から移行する",
                source="https://example.com/legacy-map-source",
                category="地域",
                map_address="東京都千代田区",
                map_prefecture="東京都",
                map_latitude=35.6812,
                map_longitude=139.7671,
                map_radius=300,
            )
            db.add_all([legacy_trivia, current_map])
            db.commit()
            legacy_id = f"trivia_{legacy_trivia.id}"
            current_id = f"map_{current_map.id}"

            payload = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(spot_ids=[legacy_id]),
                user_id="legacy-user",
                db=db,
            )

            self.assertEqual(payload["spotIdAliases"], {legacy_id: current_id})
            self.assertEqual(payload["unlockCounts"][current_id], 1)
            unlock = db.query(MapTriviaUnlock).one()
            self.assertEqual(unlock.map_trivia_id, current_map.id)
        finally:
            db.close()

    def test_legacy_trivia_spot_id_is_not_guessed_when_match_is_ambiguous(self):
        db = self.session_factory()
        try:
            legacy_trivia = Trivia(
                title="重複タイトル",
                content="同一本文",
                explanation="説明",
                source="https://example.com/ambiguous",
                category="地域",
            )
            duplicate_maps = [
                MapTrivia(
                    title="重複タイトル",
                    content="同一本文",
                    explanation="説明",
                    source="https://example.com/ambiguous",
                    category="地域",
                    map_address=f"候補{i}",
                    map_prefecture="東京都",
                    map_latitude=35.0 + i,
                    map_longitude=139.0,
                    map_radius=300,
                )
                for i in range(2)
            ]
            db.add_all([legacy_trivia, *duplicate_maps])
            db.commit()
            legacy_id = f"trivia_{legacy_trivia.id}"

            payload = record_map_trivia_unlocks(
                MapTriviaUnlockRequest(spot_ids=[legacy_id]),
                user_id="legacy-user",
                db=db,
            )

            self.assertEqual(payload["spotIdAliases"], {})
            self.assertEqual(payload["unlockCounts"], {})
            self.assertEqual(db.query(MapTriviaUnlock).count(), 0)
        finally:
            db.close()

    def test_today_contract_still_accepts_anonymous_legacy_request(self):
        with patch("main.AppSessionLocal", self.session_factory):
            payload = get_todays_trivia(
                user_id=None,
                category=None,
                limit=3,
                date="2026-08-17",
                include_assignments=True,
                token_user_id=None,
            )

        item = payload[0]
        for field in ("id", "title", "content", "explanation", "source", "category", "hee_count", "date"):
            self.assertTrue(hasattr(item, field), field)


if __name__ == "__main__":
    unittest.main()
