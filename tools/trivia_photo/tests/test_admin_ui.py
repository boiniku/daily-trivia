from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

import test_approval as fixtures


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit is an optional admin dependency")
class AdminUiTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        self.fixture = fixtures.ApprovalTests("test_adoption_still_waits_for_credit_display")
        self.fixture.setUp()
        self.workflow = self.fixture.workflow
        self.mock = patch("trivia_photo.admin_ui.create_workflow", return_value=self.workflow)
        self.mock.start()
        self.app = AppTest.from_string("from trivia_photo.admin_ui import render_photo_review\nrender_photo_review()", default_timeout=15)
        # AppTest's image element name differs across Streamlit releases.
        # Exercise the real image renderer and observe the supplied images.
        with patch("streamlit.image", wraps=st.image) as images:
            self.app.run()
        self.rendered_images = images.call_args_list

    def tearDown(self):
        self.mock.stop()
        self.fixture.tearDown()

    def click(self, label):
        buttons = [button for button in self.app.button if button.label == label]
        self.assertEqual(len(buttons), 1)
        buttons[0].click().run()
        self.assertEqual(len(self.app.exception), 0)

    def test_compare_hold_filter_and_reselection_reason(self):
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.rendered_images), 3)
        self.assertTrue(all(isinstance(call.args[0], bytes) and call.args[0] for call in self.rendered_images))
        self.assertFalse(any("写真を表示できません" in warning.value for warning in self.app.warning))
        self.click("保留")
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "held")
        self.app.selectbox(key="photo_status").set_value("保留").run()
        reason = next(box for box in self.app.selectbox if box.label == "選び直しの理由")
        reason.set_value("構図が合わない")
        note = next(box for box in self.app.text_input if box.label.startswith("補足"))
        note.input("近くから写した写真")
        self.click("理由を付けて選び直し")
        request = self.fixture.review.queue()[0]["request"]
        self.assertEqual(request["reason"], "構図が合わない：近くから写した写真")
        self.assertEqual(self.workflow.neon.writes, [])

    def test_stale_form_blocks_approval_until_explicit_reload(self):
        self.fixture.decide("held", reason="別の画面から保留")
        self.click("選択した写真を採用")
        self.assertTrue(any("画面を開いた後" in error.value for error in self.app.error))
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "held")
        self.click("最新の状態を読み直す")
        self.click("選択した写真を採用")
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "approved")
        self.assertEqual(self.workflow.neon.writes, [])

    def test_multiple_candidate_checkboxes_approve_all_photos_without_publishing(self):
        choices = [box for box in self.app.checkbox if box.label == "この写真を採用する"]
        self.assertEqual(len(choices), 3)
        self.assertTrue(choices[0].value)
        choices[1].check().run()
        next(box for box in self.app.checkbox if box.label == "写真と写っている対象の利用条件を確認した").check()
        self.click("選択した写真を採用")
        item = self.workflow.state.get(self.fixture.batch, 1)
        self.assertEqual(len(item["approved_photos"]), 2)
        self.assertEqual(item["status"], "approved")
        self.assertEqual(sum(box.value for box in self.app.checkbox if box.label == "この写真を採用する"), 2)
        self.assertEqual(self.workflow.neon.writes, [])
        self.assertEqual(self.workflow.storage.published, [])

    def enable_auto_publication(self):
        from streamlit.testing.v1 import AppTest
        self.app = AppTest.from_string(
            "from trivia_photo.admin_ui import render_photo_review\n"
            "render_photo_review(publish_on_approval=True, credits_ready=True)", default_timeout=15)
        self.app.run()

    def select_two_photos(self):
        choices = [box for box in self.app.checkbox if box.label == "この写真を採用する"]
        choices[1].check().run()
        next(box for box in self.app.checkbox if box.label == "写真と写っている対象の利用条件を確認した").check()

    def test_integrated_approval_publishes_all_photos_and_legacy_cover_automatically(self):
        self.enable_auto_publication()
        self.select_two_photos()
        self.click("選択した写真を採用して本番へ反映")
        item = self.workflow.state.get(self.fixture.batch, 1)
        self.assertEqual(item["status"], "published")
        self.assertEqual(len(item["published_photos"]), 2)
        self.assertEqual(len(self.workflow.neon.writes), 1)
        self.assertEqual(self.workflow.neon.rows[1]["image_url"], item["published_photos"][0]["url"])
        self.assertEqual(len(self.workflow.neon.rows[1]["image_urls"]), 2)
        self.app.run()
        self.assertEqual(len(self.workflow.neon.writes), 1)

    def test_failed_database_publication_keeps_approval_and_retries_from_the_screen(self):
        self.enable_auto_publication()
        self.select_two_photos()
        with patch.object(self.workflow.neon, "publish_gallery", side_effect=RuntimeError("DB offline")):
            self.click("選択した写真を採用して本番へ反映")
        item = self.workflow.state.get(self.fixture.batch, 1)
        self.assertEqual(item["status"], "approved")
        self.assertEqual(len(item["approved_photos"]), 2)
        self.assertTrue(any("DBへの反映に失敗" in error.value for error in self.app.error))
        self.assertEqual(self.workflow.neon.writes, [])
        self.click("採用済みの写真を本番へ反映")
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "published")
        self.assertEqual(len(self.workflow.neon.writes), 1)

    def test_auto_publication_does_not_publish_held_or_rejected_photos(self):
        self.enable_auto_publication()
        self.click("保留")
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "held")
        self.click("理由を付けて選び直し")
        self.assertEqual(self.workflow.state.get(self.fixture.batch, 1)["status"], "reselection_requested")
        self.assertEqual(self.workflow.neon.writes, [])
        self.assertEqual(self.workflow.storage.published, [])
