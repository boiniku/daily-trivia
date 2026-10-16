"""Real Streamlit reruns for the read-only R2 browser, without external I/O."""

import unittest
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest


BROWSER_APP = """
import streamlit as st
from services.admin_images import render_r2_image_browser

render_r2_image_browser(
    st,
    key="test",
    client_factory=lambda: st.session_state["test_client"],
    bucket="test-bucket",
    base_url=st.session_state.get("test_base_url", "https://images.example.test"),
    default_prefix="pending/",
    target_key="image_url",
)
with st.form("image_form"):
    image_url = st.text_input("Image URL / R2 key", key="image_url")
    if st.form_submit_button("Save"):
        st.session_state["saved_image_url"] = image_url
"""


class R2BrowserAppTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.list_objects_v2.return_value = {
            "Contents": [{"Key": "pending/a b.webp", "Size": 1024}, {"Key": "pending/second.jpg", "Size": 2048}],
            "IsTruncated": False,
        }
        self.client.generate_presigned_url.side_effect = lambda operation, Params, ExpiresIn: (
            f"https://private.example.test/{Params['Key']}?signature=temporary"
        )
        self.app = AppTest.from_string(BROWSER_APP, default_timeout=10)
        self.app.session_state["test_client"] = self.client

    def run_app(self):
        self.app.run()
        self.assertFalse(list(self.app.exception), [error.message for error in self.app.exception])
        return self.app

    def click(self, key):
        self.app.button(key=key).click()
        return self.run_app()

    def assert_read_only(self):
        self.client.put_object.assert_not_called()
        self.client.delete_object.assert_not_called()
        self.client.get_object.assert_not_called()

    def test_explicit_load_then_select_reselect_clear_and_form_save(self):
        self.run_app()
        self.client.list_objects_v2.assert_not_called()
        self.client.generate_presigned_url.assert_not_called()
        self.assertEqual(self.app.button(key="test:r2_browser:load").proto.form_id, "")
        self.assertEqual(self.app.text_input(key="image_url").proto.form_id, "image_form")

        self.click("test:r2_browser:load")
        self.client.list_objects_v2.assert_called_once_with(Bucket="test-bucket", Prefix="pending/", MaxKeys=12)
        self.click("test:r2_browser:choose:0")
        self.assertEqual(self.app.text_input(key="image_url").value, "https://images.example.test/pending/a%20b.webp")
        self.app.button(key="FormSubmitter:image_form-Save").click()
        self.run_app()
        self.assertEqual(self.app.session_state["saved_image_url"], "https://images.example.test/pending/a%20b.webp")

        self.click("test:r2_browser:choose:1")
        self.assertEqual(self.app.text_input(key="image_url").value, "https://images.example.test/pending/second.jpg")
        self.click("test:r2_browser:clear")
        self.assertEqual(self.app.text_input(key="image_url").value, "")
        self.app.button(key="FormSubmitter:image_form-Save").click()
        self.run_app()
        self.assertEqual(self.app.session_state["saved_image_url"], "")
        self.assertEqual(self.client.list_objects_v2.call_count, 1)
        self.assert_read_only()

    def test_signed_preview_never_replaces_persisted_object_key(self):
        self.app.session_state["test_base_url"] = ""
        self.run_app()
        self.click("test:r2_browser:load")
        self.assertEqual(self.client.generate_presigned_url.call_count, 2)
        self.click("test:r2_browser:choose:0")
        self.assertEqual(self.app.text_input(key="image_url").value, "pending/a b.webp")
        self.app.button(key="FormSubmitter:image_form-Save").click()
        self.run_app()
        self.assertEqual(self.app.session_state["saved_image_url"], "pending/a b.webp")
        self.assertEqual(self.client.generate_presigned_url.call_count, 2)
        self.assert_read_only()

    def test_pagination_fetches_only_on_next_and_caches_previous_pages(self):
        self.client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": f"pending/{index}.webp", "Size": 100} for index in range(12)],
                "IsTruncated": True,
                "NextContinuationToken": "next-page-token",
            },
            {"Contents": [{"Key": "pending/final.webp", "Size": 100}], "IsTruncated": False},
        ]
        self.run_app()
        self.click("test:r2_browser:load")
        self.assertTrue(self.app.button(key="test:r2_browser:previous").disabled)
        self.click("test:r2_browser:next")
        self.assertEqual(self.client.list_objects_v2.call_count, 2)
        self.assertEqual(self.client.list_objects_v2.call_args.kwargs["ContinuationToken"], "next-page-token")
        self.assertTrue(self.app.button(key="test:r2_browser:next").disabled)
        self.click("test:r2_browser:choose:0")
        self.assertEqual(self.app.text_input(key="image_url").value, "https://images.example.test/pending/final.webp")
        self.click("test:r2_browser:previous")
        self.assertTrue(self.app.button(key="test:r2_browser:previous").disabled)
        self.click("test:r2_browser:choose:0")
        self.assertEqual(self.app.text_input(key="image_url").value, "https://images.example.test/pending/0.webp")
        self.click("test:r2_browser:next")
        self.assertEqual(self.client.list_objects_v2.call_count, 2)
        self.assert_read_only()

    def test_changing_prefix_and_search_waits_for_explicit_reload(self):
        self.run_app()
        self.click("test:r2_browser:load")
        self.app.text_input(key="test:r2_browser:prefix").set_value("other/")
        self.app.text_input(key="test:r2_browser:search").set_value("tower")
        self.run_app()
        self.assertEqual(self.client.list_objects_v2.call_count, 1)
        self.assertFalse([button for button in self.app.button if button.label == "この画像を使う"])
        self.client.list_objects_v2.return_value = {
            "Contents": [{"Key": "other/tower.jpg", "Size": 100}], "IsTruncated": False,
        }
        self.click("test:r2_browser:load")
        self.assertEqual(self.client.list_objects_v2.call_count, 2)
        self.assertEqual(self.client.list_objects_v2.call_args.kwargs["Prefix"], "other/")
        self.click("test:r2_browser:choose:0")
        self.assertEqual(self.app.text_input(key="image_url").value, "https://images.example.test/other/tower.jpg")
        self.assert_read_only()


if __name__ == "__main__":
    unittest.main()
