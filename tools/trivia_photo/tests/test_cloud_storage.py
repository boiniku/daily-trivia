from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import test_workflow as fixtures
from trivia_photo.cloud_state import CloudState
from trivia_photo.config import Settings
from trivia_photo.inspection import inspect_image
from trivia_photo.migration import migrate_local
from trivia_photo.review import render
from trivia_photo.state import State
from trivia_photo.storage import R2
from trivia_photo.workflow import Workflow


class CloudWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = fixtures.FakeStorage()
        self.state = CloudState(self.storage, Path(self.temp.name))
        self.settings = Settings(database_url="postgresql://user:password@project.neon.tech/neondb", data_dir=self.state.root)
        self.neon, self.commons = fixtures.FakeNeon(), fixtures.FakeCommons()
        self.workflow = Workflow(self.settings, self.state, self.neon, self.commons, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self):
        batch = self.workflow.collect(1)["batch"]
        fixtures.stage_fixture(self.workflow, batch, 1)
        return batch

    def test_photo_and_state_are_remote_without_local_image_writes(self):
        with patch.object(Path, "write_bytes", side_effect=AssertionError("画像をディスクへ書かない")):
            batch = self.collect()
            self.workflow.decision(batch, 1, False)
        self.assertFalse((self.state.root / "state.sqlite3").exists())
        self.assertFalse(list(self.state.root.rglob("*.webp")))
        self.assertEqual(self.state.get(batch, 1)["status"], "rejected")
        self.assertEqual(self.neon.writes, [])

    def test_different_empty_work_folder_can_resume_review_and_deduplicate(self):
        batch = self.collect()
        self.workflow.decision(batch, 1, False)
        with tempfile.TemporaryDirectory() as other:
            state = CloudState(self.storage, Path(other))
            workflow = Workflow(self.settings, state, self.neon, self.commons, self.storage)
            self.assertEqual(state.resolve_batch("latest"), batch)
            self.assertEqual(state.get(batch, 1)["status"], "rejected")
            self.assertEqual(state.attempted_ids(), [1])
            self.assertEqual(state.attempted_ids(retry=True), [])
            self.assertIn("CC BY 4.0", render(workflow, batch, offline=True))
            self.assertTrue(workflow.asset_bytes(state.get(batch, 1)["asset"]))
            result = workflow.collect(1)
            self.assertEqual(result["tasks"][0]["id"], 2)

    def test_inspection_returns_image_in_memory_with_original_hash(self):
        batch = self.collect()
        before = set(self.state.root.rglob("*"))
        result = inspect_image(self.workflow, batch, 1)
        encoded = result["image_url"].split(",", 1)[1]
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            self.assertAlmostEqual(image.width / image.height, 16 / 9, places=2)
        self.assertEqual(result["sha256"], self.state.get(batch, 1)["asset"]["sha256"])
        self.assertEqual(before, set(self.state.root.rglob("*")))

    def test_stale_item_cannot_overwrite_remote_rejection(self):
        batch = self.collect()
        stale = self.state.get(batch, 1)
        self.workflow.decision(batch, 1, False)
        with self.assertRaisesRegex(ValueError, "別の処理"):
            self.state.save(stale, "approved")
        self.assertEqual(self.state.get(batch, 1)["status"], "rejected")

    def test_conditional_write_protects_document(self):
        batch = self.collect()
        document, etag = self.storage.get_json(self.state.key(batch))
        self.workflow.decision(batch, 1, False)
        with self.assertRaisesRegex(ValueError, "別の処理"):
            self.storage.put_json(self.state.key(batch), document, etag)

    def test_migration_preserves_rejection_and_cleans_only_verified_local_image(self):
        with tempfile.TemporaryDirectory() as old:
            legacy = State(Path(old))
            batch = legacy.create_batch([self.neon.rows[1]])
            data = self.commons.bytes
            path = legacy.asset_dir(batch) / "old-photo.jpg"
            path.write_bytes(data)
            asset = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            item = legacy.get(batch, 1)
            item.update(asset=asset, review={"decision": "rejected"})
            legacy.save(item, "rejected")
            cloud = CloudState(self.storage, Path(old))
            workflow = Workflow(self.settings, cloud, self.neon, self.commons, self.storage)
            result = migrate_local(workflow, apply=True, remove_images=True)
            self.assertEqual(result["removed_local_images"], 1)
            self.assertFalse(path.exists())
            self.assertEqual(cloud.get(batch, 1)["status"], "rejected")
            self.assertEqual(workflow.asset_bytes(cloud.get(batch, 1)["asset"]), data)
            self.assertEqual(self.neon.writes, [])


class R2IntegrityTests(unittest.TestCase):
    def test_json_writes_require_matching_etag(self):
        settings = Settings(bucket="public", review_bucket="review", endpoint="https://r2.example.com", access_key="test", secret_key="test")
        with patch("trivia_photo.storage.boto3.client") as client:
            storage = R2(settings)
            storage.put_json("state.json", {"status": "rejected"}, '"etag"')
            self.assertEqual(client.return_value.put_object.call_args.kwargs["IfMatch"], '"etag"')
            storage.put_json("new.json", {"status": "queued"})
            self.assertEqual(client.return_value.put_object.call_args.kwargs["IfNoneMatch"], "*")

    def test_matching_object_metadata_does_not_hide_changed_image_body(self):
        settings = Settings(bucket="public", review_bucket="review", endpoint="https://r2.example.com", access_key="test", secret_key="test")
        data = b"original"
        sha = hashlib.sha256(data).hexdigest()
        with patch("trivia_photo.storage.boto3.client") as client:
            client.return_value.get_object.return_value = {"ContentLength": len(data), "Metadata": {"sha256": sha}, "Body": BytesIO(b"tampered")}
            storage = R2(settings)
            with self.assertRaisesRegex(ValueError, "変更されています"):
                storage.read_asset({"sha256": sha, "size": len(data), "r2": {"bucket": "review", "key": "photo.webp"}})
