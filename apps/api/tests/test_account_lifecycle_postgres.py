"""Opt-in real PostgreSQL tests; NEVER use DATABASE_URL or an existing app DB.

Set TEST_ACCOUNT_DATABASE_URL to a disposable local DB named daily_trivia_test_*.
Tests install the production trigger and create uniquely named fixture users.
"""
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
from models import Base, AccountLifecycle, DailyAssignment
from services.account_lifecycle import lock_accounts
from scripts.migrations.migrate_account_lifecycle import migrate

TEST_URL = os.getenv('TEST_ACCOUNT_DATABASE_URL')


@unittest.skipUnless(TEST_URL, 'Disposable local PostgreSQL is not configured')
class AccountLifecyclePostgresTests(unittest.TestCase):
    def setUp(self):
        url = make_url(TEST_URL)
        if url.host not in ('localhost', '127.0.0.1', '::1') or not (url.database or '').startswith('daily_trivia_test_'):
            raise RuntimeError('Refusing to run outside a disposable local daily_trivia_test_* database')
        self.engine = create_engine(url, connect_args={'options': '-c statement_timeout=5000'})
        Base.metadata.create_all(self.engine)
        with patch('scripts.migrations.migrate_account_lifecycle.engine', self.engine):
            migrate()
            migrate()  # DDL must be safe to repeat on every startup.
        self.sessions = sessionmaker(bind=self.engine)
        self.uid = 'test-' + uuid.uuid4().hex
        with self.sessions() as db:
            db.add(AccountLifecycle(user_id=self.uid, status='active'))
            db.commit()

    def tearDown(self):
        if hasattr(self, 'uid'):
            with self.sessions() as db:
                db.query(DailyAssignment).filter_by(user_id=self.uid).delete()
                db.query(AccountLifecycle).filter_by(user_id=self.uid).delete()
                db.commit()
        if hasattr(self, 'engine'):
            self.engine.dispose()

    def assert_waiting_for_account_lock(self, pid):
        deadline = time.monotonic() + 2
        with self.engine.connect() as connection:
            while time.monotonic() < deadline:
                waiting = connection.execute(text("""SELECT EXISTS (
                    SELECT 1 FROM pg_locks WHERE pid = :pid
                    AND locktype = 'advisory' AND NOT granted)"""), {'pid': pid}).scalar()
                if waiting:
                    return
                time.sleep(0.01)
        self.fail('Concurrent operation never waited for the account lock')

    def test_trigger_rejects_insert_started_while_deletion_is_uncommitted(self):
        started = threading.Event()
        worker_pid = []
        def late_insert():
            with self.sessions() as db:
                worker_pid.append(db.execute(text('SELECT pg_backend_pid()')).scalar())
                started.set()
                db.add(DailyAssignment(user_id=self.uid))
                db.commit()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.sessions() as db:
                lock_accounts(db, self.uid)
                db.get(AccountLifecycle, self.uid).status = 'deleted'
                db.flush()
                future = executor.submit(late_insert)
                self.assertTrue(started.wait(2))
                self.assert_waiting_for_account_lock(worker_pid[0])
                db.commit()
            with self.assertRaises(DBAPIError):
                future.result(timeout=10)
        with self.sessions() as db:
            self.assertEqual(db.query(DailyAssignment).filter_by(user_id=self.uid).count(), 0)

    def test_deletion_waits_for_an_earlier_writer_then_removes_its_record(self):
        started = threading.Event()
        worker_pid = []
        def deletion():
            with self.sessions() as db:
                worker_pid.append(db.execute(text('SELECT pg_backend_pid()')).scalar())
                started.set()
                lock_accounts(db, self.uid)
                db.get(AccountLifecycle, self.uid).status = 'deleted'
                db.query(DailyAssignment).filter_by(user_id=self.uid).delete()
                db.commit()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.sessions() as db:
                db.add(DailyAssignment(user_id=self.uid))
                db.flush()  # Actual trigger holds the account lock until commit.
                future = executor.submit(deletion)
                self.assertTrue(started.wait(2))
                self.assert_waiting_for_account_lock(worker_pid[0])
                db.commit()
            future.result(timeout=10)
        with self.sessions() as db:
            self.assertEqual(db.query(DailyAssignment).filter_by(user_id=self.uid).count(), 0)
