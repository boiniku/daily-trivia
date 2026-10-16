"""既存管理画面の実ファイルを実行し、DB・AI・移行はモックで隔離する。"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import test_approval as fixtures


APP = Path(os.environ["DAILY_TRIVIA_API_ROOT"]) if os.environ.get("DAILY_TRIVIA_API_ROOT") else Path(__file__).resolve().parents[2] / "毎日雑学" / "apps" / "api"
AVAILABLE = all(importlib.util.find_spec(name) for name in ("streamlit", "sqlalchemy", "openai"))


@unittest.skipUnless(AVAILABLE and (APP / "admin_dashboard.py").is_file(), "Optional sibling Streamlit admin environment")
class AdminIntegrationTests(unittest.TestCase):
    def test_existing_admin_approval_publishes_gallery_then_returns_to_editing(self):
        from streamlit.testing.v1 import AppTest
        fixture = fixtures.ApprovalTests("test_adoption_still_waits_for_credit_display")
        fixture.setUp()
        sys.path.insert(0, str(APP))
        try:
            query = MagicMock()
            for method in ("filter", "order_by", "offset", "limit"):
                getattr(query, method).return_value = query
            query.all.return_value = []
            query.count.return_value = 0
            session = MagicMock()
            session.__enter__.return_value = session
            session.query.return_value = query
            with patch("database.SessionLocal", return_value=session), \
                 patch("scripts.migrations.migrate_trivia_candidates.migrate") as migration, \
                 patch("openai.OpenAI") as client, \
                 patch("trivia_photo.admin_ui.create_workflow", return_value=fixture.workflow) as photo_workflow:
                app = AppTest.from_file(str(APP / "admin_dashboard.py"), default_timeout=20)
                app.session_state["admin_authenticated"] = True
                app.session_state["admin_section"] = "🛠️ 管理・編集"
                app.session_state["manage_operation"] = "写真の確認"
                app.run()
                self.assertEqual(len(app.exception), 0)
                self.assertTrue(any(h.value == "写真の確認" for h in app.subheader))
                self.assertTrue(any(b.label == "選択した写真を採用して本番へ反映" for b in app.button))
                from database import DATABASE_URL
                self.assertTrue(photo_workflow.call_args.kwargs.get("database_url") == DATABASE_URL)
                choices = [box for box in app.checkbox if box.label == "この写真を採用する"]
                self.assertEqual(len(choices), 3)
                choices[1].check().run()
                next(box for box in app.checkbox if box.label == "写真と写っている対象の利用条件を確認した").check()
                next(button for button in app.button if button.label == "選択した写真を採用して本番へ反映").click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(fixture.state.get(fixture.batch, 1)["approved_photos"]), 2)
                self.assertEqual(fixture.state.get(fixture.batch, 1)["status"], "published")
                app.radio(key="manage_operation").set_value("本文・写真の編集").run()
                self.assertEqual(len(app.exception), 0)
                self.assertTrue(any(t.label.startswith("🔍 検索") for t in app.text_input))
                self.assertFalse(any(b.label == "選択した写真を採用して本番へ反映" for b in app.button))
                session.commit.assert_not_called()
                client.return_value.chat.completions.create.assert_not_called()
                self.assertTrue(migration.called)  # 実処理はモック。
                self.assertEqual(len(fixture.neon.writes), 1)
                self.assertEqual(len(fixture.neon.rows[1]["image_urls"]), 2)
        finally:
            sys.path.remove(str(APP))
            fixture.tearDown()
