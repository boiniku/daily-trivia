import datetime
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, MapTrivia, MapTriviaUnlock, AccountLifecycle, Collection, CollectionItem, Trivia
from routers.user import (
    LegacyMergeRequest,
    MergeRequest,
    delete_user,
    merge_legacy_guest_data,
    merge_verified_guest_data,
    PrepareMergeRequest, prepare_guest_merge, finish_pending_merges,
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
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False)
        self.firebase_account = patch('routers.user.firebase_auth.get_user', return_value=SimpleNamespace(
            provider_data=[SimpleNamespace(provider_id='apple.com', uid='apple-subject')],
        ))
        self.firebase_account.start()
        self.addCleanup(self.firebase_account.stop)
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

    def test_legacy_merge_never_accepts_an_unverified_source_uid(self):
        with (
            patch("database.SessionLocal", self.session_factory),
            patch.dict("os.environ", {"LEGACY_GUEST_MERGE_DEADLINE": "2099-01-01T00:00:00+00:00"}),
        ):
            with self.assertRaises(HTTPException) as error:
                merge_legacy_guest_data(LegacyMergeRequest(guest_user_id="victim-apple"), auth_user_id="attacker")
            self.assertEqual(error.exception.status_code, 410)

        with patch.dict("os.environ", {"LEGACY_GUEST_MERGE_DEADLINE": "2020-01-01T00:00:00+00:00"}):
            with self.assertRaisesRegex(Exception, "Verified migration required"):
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

        with patch("database.SessionLocal", self.session_factory), patch('routers.user.firebase_auth.delete_user') as firebase_delete:
            delete_user(user_id="apple")
            firebase_delete.assert_called_once_with('apple')

        db = self.session_factory()
        try:
            self.assertEqual(db.query(MapTriviaUnlock).count(), 0)
        finally:
            db.close()

    def test_prepared_migration_survives_expired_source_token_and_response_loss(self):
        with patch('database.SessionLocal', self.session_factory):
            prepare_guest_merge(PrepareMergeRequest(apple_subject='apple-subject'), claims={
                'uid': 'guest', 'firebase': {'sign_in_provider': 'anonymous'},
            })
            with self.session_factory() as db:
                db.add(MapTriviaUnlock(user_id='guest', map_trivia_id=1))
                db.commit()
            # No guest ID token is required after the intent was saved.
            first = finish_pending_merges(auth_user_id='apple')
            self.assertEqual(first, finish_pending_merges(auth_user_id='apple'))
            with self.session_factory() as db:
                self.assertEqual(db.query(MapTriviaUnlock).one().user_id, 'apple')
                self.assertEqual(db.get(AccountLifecycle, 'guest').merged_into, 'apple')

    def test_intent_cannot_be_redeemed_by_another_apple_subject(self):
        with patch('database.SessionLocal', self.session_factory):
            prepare_guest_merge(PrepareMergeRequest(apple_subject='victim-subject'), claims={
                'uid': 'guest', 'firebase': {'sign_in_provider': 'anonymous'},
            })
            self.assertEqual(finish_pending_merges(auth_user_id='attacker'), {'merged_guest_ids': []})
            with self.session_factory() as db:
                self.assertEqual(db.get(AccountLifecycle, 'guest').status, 'active')

    def test_verified_guest_token_cannot_be_replayed_into_a_second_account(self):
        with patch('database.SessionLocal', self.session_factory), patch('routers.user.firebase_auth.verify_id_token', return_value={
            'uid': 'guest', 'firebase': {'sign_in_provider': 'anonymous'},
        }):
            request = MergeRequest(guest_id_token='proof')
            merge_verified_guest_data(request, auth_user_id='apple')
            with self.assertRaises(HTTPException) as error:
                merge_verified_guest_data(request, auth_user_id='second-apple')
            self.assertEqual(error.exception.status_code, 409)

    def test_deletion_blocks_late_uploads_even_when_firebase_delete_fails(self):
        from main import record_map_trivia_unlocks, MapTriviaUnlockRequest
        with patch('database.SessionLocal', self.session_factory), patch('routers.user.firebase_auth.delete_user', side_effect=RuntimeError('offline')):
            with self.assertRaises(HTTPException):
                delete_user(user_id='apple')
        with self.session_factory() as db:
            self.assertEqual(db.get(AccountLifecycle, 'apple').status, 'deleted')
            with self.assertRaises(HTTPException) as error:
                record_map_trivia_unlocks(MapTriviaUnlockRequest(spot_ids=['map_1']), user_id='apple', db=db)
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(db.query(MapTriviaUnlock).count(), 0)
        # Retry after a partial failure must still call Firebase and succeed.
        with patch('database.SessionLocal', self.session_factory), patch('routers.user.firebase_auth.delete_user'):
            delete_user(user_id='apple')

    def test_collection_items_survive_merge_with_production_autoflush_setting(self):
        with self.session_factory() as db:
            trivia = Trivia(title='saved', content='body')
            source = Collection(user_id='guest', title='History')
            target = Collection(user_id='apple', title='過去に見た雑学')
            db.add_all([trivia, source, target])
            db.flush()
            target_id = target.id
            db.add(CollectionItem(collection_id=source.id, trivia_id=trivia.id))
            db.commit()
        with patch('database.SessionLocal', self.session_factory), patch('routers.user.firebase_auth.verify_id_token', return_value={
            'uid': 'guest', 'firebase': {'sign_in_provider': 'anonymous'},
        }):
            merge_verified_guest_data(MergeRequest(guest_id_token='proof'), auth_user_id='apple')
        with self.session_factory() as db:
            self.assertEqual(db.query(CollectionItem).one().collection_id, target_id)

    def test_durable_alias_is_not_reassigned_to_a_new_same_text_spot(self):
        from main import record_map_trivia_unlocks, MapTriviaUnlockRequest
        with self.session_factory() as db:
            original = Trivia(title='original', content='original body')
            db.add(original)
            db.flush()
            source_id = original.id
            durable, duplicate = db.query(MapTrivia).order_by(MapTrivia.id).all()
            durable.legacy_trivia_id = source_id
            durable.title, durable.content = 'edited', 'edited body'
            duplicate.title, duplicate.content = original.title, original.content
            durable_id = durable.id
            db.commit()
            result = record_map_trivia_unlocks(MapTriviaUnlockRequest(spot_ids=[f'trivia_{source_id}']), user_id='apple', db=db)
            self.assertEqual(result['spotIdAliases'][f'trivia_{source_id}'], f'map_{durable_id}')
            self.assertEqual(db.query(MapTriviaUnlock).one().map_trivia_id, durable_id)

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
