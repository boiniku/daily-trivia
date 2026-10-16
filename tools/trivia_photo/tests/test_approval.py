from __future__ import annotations

import copy
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import test_workflow as fixtures
from trivia_photo.approval import PhotoReview, review_token
from trivia_photo.cloud_state import CloudState
from trivia_photo.config import Settings
from trivia_photo.workflow import Workflow


class VariantCommons(fixtures.FakeCommons):
    def __init__(self):
        super().__init__()
        self.variant = 0
        self.files = {}
        for index, color in enumerate(["red", "blue", "green"]):
            stream = BytesIO()
            Image.new("RGB", (800, 600), color).save(stream, "JPEG")
            self.files[f"https://upload.wikimedia.org/{index}.jpg"] = stream.getvalue()

    def search(self, query):
        self.calls += 1
        result = []
        for index in range(3):
            metadata = copy.deepcopy(self.metadata)
            metadata["source_url"] = f"https://commons.wikimedia.org/wiki/File:Photo{index + self.variant}.jpg"
            result.append({"page_id": 100 + index + self.variant, "file_title": f"File:Photo{index}.jpg",
                           "download_url": f"https://upload.wikimedia.org/{index}.jpg", "metadata": metadata})
        return result

    def download(self, url):
        return self.files[url]


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = fixtures.FakeStorage()
        self.state = CloudState(self.storage, Path(self.temp.name))
        self.neon, self.commons = fixtures.FakeNeon(), VariantCommons()
        self.settings = Settings(data_dir=self.state.root)
        self.workflow = Workflow(self.settings, self.state, self.neon, self.commons, self.storage)
        self.review = PhotoReview(self.workflow)
        self.batch = self.workflow.collect(1)["batch"]
        fixtures.stage_fixture(self.workflow, self.batch, 1)

    def tearDown(self):
        self.temp.cleanup()

    def decide(self, action, **kwargs):
        item = self.state.get(self.batch, 1)
        self.review.decide(self.batch, 1, action, review_token(item), **kwargs)

    def test_alternate_adoption_uses_r2_without_search_local_images_or_neon_write(self):
        before = self.commons.calls, len(self.storage.objects)
        with self.assertRaisesRegex(ValueError, "追加の利用条件"):
            self.decide("approved", option=1)
        with patch.object(Path, "write_bytes", side_effect=AssertionError("ローカル画像禁止")):
            self.decide("approved", option=1, rights_confirmed=True)
        item = self.state.get(self.batch, 1)
        self.assertEqual(item["selected"]["page_id"], 101)
        self.assertTrue(item["metadata"]["is_reference"])
        self.assertEqual(item["status"], "approved")
        self.assertEqual(before, (self.commons.calls, len(self.storage.objects)))
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])
        self.assertFalse(list(self.state.root.rglob("*.webp")))

    def test_multiple_photos_are_approved_together_and_survive_reloading_r2_state(self):
        before = len(self.storage.objects)
        with self.assertRaisesRegex(ValueError, "追加の利用条件"):
            self.decide("approved", options=[0, 1])
        self.assertNotIn("approved_photos", self.state.get(self.batch, 1))
        self.decide("approved", options=[0, 1], rights_confirmed=True)
        with tempfile.TemporaryDirectory() as fresh:
            item = CloudState(self.storage, Path(fresh)).get(self.batch, 1)
        self.assertEqual(item["status"], "approved")
        self.assertEqual([photo["selected"]["page_id"] for photo in item["approved_photos"]], [100, 101])
        self.assertEqual(len(item["review"]["photos"]), 2)
        self.assertEqual(item["selected"]["page_id"], 100)
        self.assertNotEqual(item["approved_photos"][0]["metadata"]["source_url"], item["approved_photos"][1]["metadata"]["source_url"])
        self.assertEqual(len(self.storage.objects), before)
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])

    def test_empty_duplicate_or_invalid_multiple_selection_cannot_change_approval(self):
        before = self.state.get(self.batch, 1)
        for options in ([], [0, 0], [0, 99], [0, True]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.decide("approved", options=options, rights_confirmed=True)
            self.assertEqual(self.state.get(self.batch, 1), before)

    def test_all_approved_photos_publish_in_one_gallery_write(self):
        self.decide("approved", options=[0, 1], rights_confirmed=True)
        self.assertEqual(self.workflow.publish(self.batch, apply=True)[0]["status"], "waiting_for_credit_display")
        self.assertEqual(self.storage.published, [])
        result = self.workflow.publish(self.batch, apply=True, credits_ready=True)[0]
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(result["urls"]), 2)
        self.assertEqual(len(self.neon.writes), 1)
        self.assertEqual(self.neon.rows[1]["image_urls"], result["urls"])
        item = self.state.get(self.batch, 1)
        self.assertEqual(len(item["published_photos"]), 2)
        self.assertEqual(item["published_url"], result["urls"][0])
        self.workflow.publish(self.batch, apply=True, credits_ready=True)
        self.assertEqual(len(self.neon.writes), 1)

    def test_invalid_second_photo_prevents_any_copy_or_database_write(self):
        self.decide("approved", options=[0, 1], rights_confirmed=True)
        original = self.commons.refresh_metadata
        def refreshed(candidate):
            result = original(candidate)
            if candidate["page_id"] == 101:
                result["license"] = "Changed license"
            return result
        with patch.object(self.commons, "refresh_metadata", side_effect=refreshed):
            result = self.workflow.publish(self.batch, apply=True, credits_ready=True)[0]
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.storage.published, [])
        self.assertEqual(self.neon.writes, [])

    def test_gallery_database_failure_can_retry_without_losing_selected_photos(self):
        self.decide("approved", options=[0, 1], rights_confirmed=True)
        with patch.object(self.neon, "publish_gallery", side_effect=RuntimeError("database unavailable")):
            result = self.workflow.publish(self.batch, apply=True, credits_ready=True)[0]
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(len(self.state.get(self.batch, 1)["approved_photos"]), 2)
        result = self.workflow.publish(self.batch, apply=True, credits_ready=True)[0]
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(self.neon.writes), 1)
        self.assertEqual(len(self.neon.rows[1]["image_urls"]), 2)

    def test_reason_queue_and_rejection_survive_empty_local_directory(self):
        self.decide("reselection_requested", reason="構図が合わない：もっと近くから")
        with tempfile.TemporaryDirectory() as fresh:
            state = CloudState(self.storage, Path(fresh))
            review = PhotoReview(Workflow(self.settings, state, self.neon, self.commons, self.storage))
            self.assertEqual(review.queue()[0]["request"]["reason"], "構図が合わない：もっと近くから")
            self.assertEqual(review.rejections(1)[0]["photo"]["page_id"], 100)
            self.assertEqual(review.rejections(2), [])

    def test_rejected_image_is_excluded_even_in_another_batch_with_changed_page_id(self):
        rejected_sha = self.state.get(self.batch, 1)["asset"]["sha256"]
        self.decide("reselection_requested", reason="別の写真がよい")
        batch = self.state.create_batch([self.neon.rows[1]])
        self.commons.variant = 10
        self.workflow.search(batch, 1, fixtures.plan())
        candidates = self.state.get(batch, 1)["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertNotIn(rejected_sha, [c["asset"]["sha256"] for c in candidates])

    def test_stale_screen_cannot_approve_after_hold_or_reselection(self):
        old = review_token(self.state.get(self.batch, 1))
        self.decide("held", reason="後で確認")
        with self.assertRaisesRegex(ValueError, "画面を開いた後"):
            self.review.decide(self.batch, 1, "approved", old)
        self.assertEqual(self.state.get(self.batch, 1)["status"], "held")
        self.assertEqual(self.workflow.publish(self.batch), [])

    def test_rejected_candidate_cannot_be_approved_via_ui_or_cli(self):
        self.decide("reselection_requested", reason="対象が違う")
        with self.assertRaisesRegex(ValueError, "却下済み"):
            self.decide("approved")
        self.workflow.decision(self.batch, 1, False)
        with self.assertRaisesRegex(ValueError, "却下済み"):
            self.workflow.decision(self.batch, 1, True)

    def test_refresh_preserves_rejection_history_and_request_for_codex(self):
        self.decide("reselection_requested", reason="構図が合わない")
        self.workflow.search(self.batch, 1, fixtures.plan(), refresh=True)
        item = self.state.get(self.batch, 1)
        self.assertEqual(len(item["candidates"]), 2)
        self.assertEqual(item["reselection_request"]["reason"], "構図が合わない")
        self.assertEqual(item["review_history"][0]["photo"]["page_id"], 100)
        self.workflow.select(self.batch, 1, fixtures.choice(item))
        self.assertNotIn("reselection_request", self.state.get(self.batch, 1))
        self.assertEqual(self.review.queue(), [])

    def test_legacy_rejection_is_preserved_before_refresh(self):
        item = self.state.get(self.batch, 1)
        item["review"] = {"decision": "rejected", "checked_at": "old"}
        self.state.save(item, "rejected")
        self.workflow.search(self.batch, 1, fixtures.plan(), refresh=True)
        self.assertEqual(self.review.rejections(1)[0]["photo"]["page_id"], 100)
        self.assertEqual(len(self.state.get(self.batch, 1)["candidates"]), 2)

    def test_published_photo_cannot_be_held(self):
        item = self.state.get(self.batch, 1)
        self.state.save(item, "published")
        with self.assertRaisesRegex(ValueError, "反映済み"):
            self.decide("held")

    def test_adoption_still_waits_for_credit_display(self):
        self.decide("approved")
        result = self.workflow.publish(self.batch, apply=True)
        self.assertEqual(result[0]["status"], "waiting_for_credit_display")
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])

    def test_legacy_rejection_survives_reframing(self):
        item = self.state.get(self.batch, 1)
        item["asset"] = item["asset"]["source"]
        item["review"] = {"decision": "rejected", "checked_at": "old"}
        self.state.save(item, "rejected")
        self.workflow.reformat(self.batch)
        self.assertEqual(self.review.rejections(1)[0]["photo"]["page_id"], 100)
        with self.assertRaisesRegex(ValueError, "却下済み"):
            self.decide("approved")

    def test_legacy_unformatted_candidates_do_not_appear_as_comparable_alternatives(self):
        item = self.state.get(self.batch, 1)
        item["candidates"][1]["asset"].pop("format_signature")
        choices = self.review.options(item)
        self.assertEqual([c["page_id"] for c in choices], [100, 102])
