"""Exercise old collection rows against the new API without a production DB.

SQLite tests suppress only PostgreSQL's session-setting statement; these do not
test RLS, advisory locks or the native Firebase upgrade behavior.
"""
import datetime
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from models import Base, Collection, CollectionItem, Trivia
from main import get_collections
from routers.user import _merge_guest_data


class LocalSession(Session):
    def execute(self, statement, *args, **kwargs):
        if str(statement).startswith('SET LOCAL app.current_user_id'):
            return None
        return super().execute(statement, *args, **kwargs)


class CollectionUpgradeRetentionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, class_=LocalSession, autoflush=False, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([Trivia(id=i, title=f'Test {i}', content='test') for i in range(1, 5)])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def add_folder(self, uid, title, trivia_ids):
        with self.sessions() as db:
            folder = Collection(user_id=uid, title=title, is_locked=title == 'お気に入り')
            db.add(folder)
            db.flush()
            for trivia_id in trivia_ids:
                db.add(CollectionItem(collection_id=folder.id, trivia_id=trivia_id,
                                      saved_at=datetime.datetime(2025, 1, trivia_id)))
            db.commit()
            return folder.id

    def snapshot(self, uid):
        with self.sessions() as db:
            return sorted((c.title, i.trivia_id, i.saved_at) for c, i in db.query(Collection, CollectionItem).join(
                CollectionItem, Collection.id == CollectionItem.collection_id).filter(Collection.user_id == uid))

    def test_normal_update_reads_preserve_each_accounts_ids_and_saved_dates(self):
        for uid in ('anonymous', 'apple'):
            for title in ('お気に入り', '過去に見た雑学', '自分のコレクション'):
                self.add_folder(uid, title, [1, 2])
        before = {uid: self.snapshot(uid) for uid in ('anonymous', 'apple')}
        with patch('main.AppSessionLocal', self.sessions):
            for uid in before:
                get_collections(user_id=uid)
                get_collections(user_id=uid)
        for uid in before:
            self.assertEqual(self.snapshot(uid), before[uid])

    def test_duplicate_folder_cleanup_preserves_all_unique_items_and_dates(self):
        for title in ('お気に入り', '過去に見た雑学', '自分のコレクション'):
            self.add_folder('apple', title, [1, 2])
            self.add_folder('apple', title, [2, 3])
            self.add_folder('apple', title, [4])
        expected = sorted(set(self.snapshot('apple')))
        with patch('main.AppSessionLocal', self.sessions):
            first = get_collections(user_id='apple')
            get_collections(user_id='apple')
        self.assertEqual(self.snapshot('apple'), expected)
        self.assertTrue(all(folder.count == 4 for folder in first))
        with self.sessions() as db:
            self.assertEqual(db.query(CollectionItem).filter(CollectionItem.collection_id.is_(None)).count(), 0)

    def test_guest_to_apple_union_keeps_favorites_history_and_custom_items(self):
        for title in ('お気に入り', '過去に見た雑学', '自分のコレクション'):
            self.add_folder('guest', title, [1, 2])
            self.add_folder('apple', title, [2, 3])
        self.add_folder('unrelated', 'お気に入り', [4])
        unrelated_before = self.snapshot('unrelated')
        expected = sorted(set(self.snapshot('guest') + self.snapshot('apple')))
        with patch('database.SessionLocal', self.sessions):
            _merge_guest_data('guest', 'apple')
            _merge_guest_data('guest', 'apple')
        self.assertEqual(self.snapshot('apple'), expected)
        self.assertEqual(self.snapshot('unrelated'), unrelated_before)

    def test_failed_merge_rolls_back_both_users_collections(self):
        self.add_folder('guest', 'お気に入り', [1, 2])
        self.add_folder('apple', 'お気に入り', [2, 3])
        before = {uid: self.snapshot(uid) for uid in ('guest', 'apple')}
        with patch('database.SessionLocal', self.sessions), patch.object(LocalSession, 'commit', side_effect=RuntimeError('DB unavailable')):
            with self.assertRaises(Exception):
                _merge_guest_data('guest', 'apple')
        for uid in before:
            self.assertEqual(self.snapshot(uid), before[uid])
