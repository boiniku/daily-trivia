import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import get_app_version, get_map_trivia, get_todays_trivia, health_check
from models import Base, MapTrivia, Trivia


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
