import base64
import hashlib
import hmac
import os
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, Trivia, TriviaCandidate
from routers import line_admin
from services.line_bot import make_editor_token, read_editor_token, verify_signature
from services.trivia_candidates import (
    CandidateError,
    DuplicateCandidateError,
    approve_candidate,
    create_candidate,
    create_candidates,
    reject_candidate,
    update_candidate,
)


class TriviaWorkflowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_candidate_schema_contains_workflow_columns(self):
        columns = {
            column["name"]
            for column in inspect(self.db.get_bind()).get_columns("trivia_candidates")
        }
        self.assertTrue({
            "image_url",
            "updated_at",
            "reviewed_at",
            "reviewed_by",
            "published_trivia_id",
            "line_sent_at",
        }.issubset(columns))

    def test_candidate_can_be_edited_and_approved_once(self):
        candidate = create_candidates(self.db, [{
            "title": "元タイトル",
            "content": "元本文",
            "explanation": "元解説",
            "source": "https://example.com",
            "category": "科学",
        }])[0]

        update_candidate(
            self.db,
            candidate.id,
            title="編集後タイトル",
            content="編集後本文",
            explanation="編集後解説",
            source="https://example.com/source",
            category="宇宙・天体",
        )
        first = approve_candidate(self.db, candidate.id, "test")
        second = approve_candidate(self.db, candidate.id, "test-again")

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(Trivia).count(), 1)
        self.assertEqual(first.title, "編集後タイトル")

    def test_rejected_candidate_cannot_be_approved(self):
        candidate = create_candidates(self.db, [{
            "title": "却下候補",
            "content": "本文",
            "category": "その他",
        }])[0]
        reject_candidate(self.db, candidate.id, "test")

        with self.assertRaises(CandidateError):
            approve_candidate(self.db, candidate.id, "test")
        self.assertEqual(self.db.query(Trivia).count(), 0)
        refreshed = self.db.query(TriviaCandidate).filter_by(id=candidate.id).one()
        self.assertEqual(refreshed.status, "rejected")
        self.assertIsNone(refreshed.published_trivia_id)

    def test_manual_candidate_rejects_similar_published_trivia(self):
        self.db.add(Trivia(
            title="タコには心臓が3つある",
            content="タコは全身用とエラ用を合わせて3つの心臓を持っています。",
            explanation="",
            source="",
            category="生物",
        ))
        self.db.commit()

        with self.assertRaises(DuplicateCandidateError):
            create_candidate(self.db, {
                "title": "タコの心臓は3つある",
                "content": "タコには役割の違う心臓が合計3つあります。",
                "category": "生物",
            })

    def test_generated_candidates_filter_duplicates(self):
        existing = create_candidate(self.db, {
            "title": "ハチミツは腐りにくい",
            "content": "糖度が高いハチミツは非常に腐りにくい食品です。",
            "category": "食べ物",
        })
        created = create_candidates(self.db, [
            {
                "title": "ハチミツは腐りにくい",
                "content": "糖度が高いハチミツは非常に腐りにくい食品です。",
                "category": "食べ物",
            },
            {
                "title": "金星の1日は1年より長い",
                "content": "金星は自転が遅く、1日の長さが公転周期よりも長くなります。",
                "category": "宇宙・天体",
            },
        ])

        self.assertEqual(len(created), 1)
        self.assertNotEqual(created[0].id, existing.id)


class LineSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET"),
            "CANDIDATE_EDITOR_SECRET": os.environ.get("CANDIDATE_EDITOR_SECRET"),
        }
        os.environ["LINE_CHANNEL_SECRET"] = "line-secret"
        os.environ["CANDIDATE_EDITOR_SECRET"] = "editor-secret"

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_line_signature_verification(self):
        body = b'{"events":[]}'
        digest = hmac.new(b"line-secret", body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")

        self.assertTrue(verify_signature(body, signature))
        self.assertFalse(verify_signature(body + b"x", signature))

    def test_editor_token_rejects_tampering(self):
        token = make_editor_token(42)
        self.assertEqual(read_editor_token(token), 42)

        with self.assertRaises(ValueError):
            read_editor_token(token[:-1] + ("A" if token[-1] != "A" else "B"))

    def test_editor_token_expires(self):
        token = make_editor_token(42, expires_in=-1)
        time.sleep(0.01)
        with self.assertRaises(ValueError):
            read_editor_token(token)


class MobileEditorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        self.previous_secret = os.environ.get("CANDIDATE_EDITOR_SECRET")
        os.environ["CANDIDATE_EDITOR_SECRET"] = "editor-integration-secret"

        app = FastAPI()
        app.include_router(line_admin.router)
        self.client = TestClient(app)
        self.session_patch = patch.object(
            line_admin,
            "SessionLocal",
            self.session_factory,
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.db.close()
        self.engine.dispose()
        if self.previous_secret is None:
            os.environ.pop("CANDIDATE_EDITOR_SECRET", None)
        else:
            os.environ["CANDIDATE_EDITOR_SECRET"] = self.previous_secret

    def _create_candidate(self, suffix: str) -> TriviaCandidate:
        return create_candidate(self.db, {
            "title": f"編集テスト{suffix}",
            "content": f"編集画面の統合テスト本文{suffix}",
            "category": "その他",
        })

    def test_existing_candidate_can_load_save_and_publish(self):
        candidate = self._create_candidate("A")
        token = make_editor_token(candidate.id)
        path = f"/admin/candidates/{candidate.id}/edit"

        page = self.client.get(path, params={"token": token})
        self.assertEqual(page.status_code, 200)

        saved = self.client.put(path, json={
            "token": token,
            "title": "編集後タイトルA",
            "content": "編集後の本文として保存しますA",
            "explanation": "編集後解説",
            "category": "科学",
            "source": "",
            "image_url": "",
            "publish": False,
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["status"], "pending")

        published = self.client.put(path, json={
            "token": token,
            "title": "編集後タイトルA",
            "content": "編集後の本文として保存しますA",
            "explanation": "編集後解説",
            "category": "科学",
            "source": "",
            "image_url": "",
            "publish": True,
        })
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.json()["status"], "approved")

        verify_db = self.session_factory()
        try:
            refreshed = verify_db.query(TriviaCandidate).filter_by(id=candidate.id).one()
            self.assertEqual(refreshed.status, "approved")
            self.assertIsNotNone(refreshed.published_trivia_id)
            self.assertEqual(verify_db.query(Trivia).count(), 1)
        finally:
            verify_db.close()

    def test_new_candidate_can_save_as_draft(self):
        token = make_editor_token(0)
        page = self.client.get("/admin/candidates/new", params={"token": token})
        self.assertEqual(page.status_code, 200)

        response = self.client.post("/admin/candidates/new", json={
            "token": token,
            "title": "スマホ手入力テスト",
            "content": "スマホから新しく入力した雑学の本文です。",
            "explanation": "",
            "category": "その他",
            "source": "",
            "image_url": "",
            "publish": False,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")

    def test_image_upload_returns_uploaded_url(self):
        token = make_editor_token(0)
        with patch.object(
            line_admin,
            "upload_trivia_image",
            return_value="https://images.example/trivia/test.webp",
        ):
            response = self.client.post(
                "/admin/candidates/image",
                data={"token": token},
                files={"image": ("test.jpg", b"image-bytes", "image/jpeg")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["image_url"],
            "https://images.example/trivia/test.webp",
        )


if __name__ == "__main__":
    unittest.main()
