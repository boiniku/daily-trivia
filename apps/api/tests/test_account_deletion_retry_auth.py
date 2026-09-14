import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import AccountLifecycle
from auth import get_deletion_user_id


class DeletionRetryAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        AccountLifecycle.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials='signed-token')

    def tearDown(self):
        self.engine.dispose()

    def test_valid_signature_can_retry_only_a_previously_deleted_account(self):
        with self.sessions() as db:
            db.add(AccountLifecycle(user_id='deleted-user', status='deleted'))
            db.commit()
        with patch('database.SessionLocal', self.sessions), patch('auth.auth.verify_id_token', side_effect=[
            ValueError('Firebase user no longer exists'), {'uid': 'deleted-user'},
        ]):
            self.assertEqual(get_deletion_user_id(self.credentials), 'deleted-user')

    def test_revoked_token_cannot_initiate_a_new_deletion(self):
        with self.sessions() as db:
            db.add(AccountLifecycle(user_id='active-user', status='active'))
            db.commit()
        with patch('database.SessionLocal', self.sessions), patch('auth.auth.verify_id_token', side_effect=[
            ValueError('revoked'), {'uid': 'active-user'},
        ]):
            with self.assertRaises(HTTPException) as error:
                get_deletion_user_id(self.credentials)
            self.assertEqual(error.exception.status_code, 401)
