import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth import verify_token
from main import cleanup_old_assignments


class CleanupAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()  # Never run production startup migrations in tests.
        self.app.delete('/admin/cleanup-assignments')(cleanup_old_assignments)
        self.client = TestClient(self.app)

    def test_unauthenticated_and_non_admin_requests_never_open_database(self):
        with patch('database.SessionLocal') as sessions:
            self.assertIn(self.client.delete('/admin/cleanup-assignments').status_code, (401, 403))
            self.app.dependency_overrides[verify_token] = lambda: {'uid': 'ordinary-user'}
            self.assertEqual(self.client.delete('/admin/cleanup-assignments').status_code, 403)
            sessions.assert_not_called()

    def test_admin_cannot_request_zero_negative_or_unbounded_days(self):
        self.app.dependency_overrides[verify_token] = lambda: {'uid': 'admin', 'admin': True}
        with patch('database.SessionLocal') as sessions:
            for days in (0, -1, 36501):
                self.assertEqual(self.client.delete(f'/admin/cleanup-assignments?days={days}').status_code, 422)
            sessions.assert_not_called()
