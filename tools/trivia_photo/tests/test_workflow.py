from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from trivia_photo.config import Settings
from trivia_photo.database import Neon
from trivia_photo.harness import candidate_snapshot, read_json
from trivia_photo.licenses import licensed_metadata, non_photo
from trivia_photo.review import render
from trivia_photo.state import State
from trivia_photo.storage import R2
from trivia_photo.workflow import Workflow


def info(license_name="CC BY 4.0", license_code="cc-by-4.0", license_url="https://creativecommons.org/licenses/by/4.0/"):
    return {"descriptionurl": "https://commons.wikimedia.org/wiki/File:Beaver.jpg", "extmetadata": {
        "LicenseShortName": {"value": license_name}, "License": {"value": license_code},
        "LicenseUrl": {"value": license_url}, "Artist": {"value": "<a href='https://example.com'>Test Author</a>"},
        "Copyrighted": {"value": "False" if license_code == "pd" else "True"},
    }}


class FakeNeon:
    def __init__(self):
        self.rows = {i: {"id": i, "title": f"題材{i}", "content": "入力は確認済み", "explanation": "説明", "category": "動物", "image_url": None} for i in range(1, 6)}
        self.writes = []

    def fetch(self, limit, ids, excluded):
        return [copy.deepcopy(row) for i, row in self.rows.items() if not row["image_url"] and i not in excluded and (ids is None or i in ids)][:limit]

    def current(self, trivia_id):
        return copy.deepcopy(self.rows[trivia_id])

    def publish(self, snapshot, url, credit, metadata):
        self.writes.append((snapshot["id"], url, credit, metadata))
        self.rows[snapshot["id"]]["image_url"] = url

    def publish_gallery(self, snapshot, photos):
        self.writes.append((snapshot["id"], [photo["url"] for photo in photos],
                            [photo["credit"] for photo in photos], [photo["metadata"] for photo in photos]))
        self.rows[snapshot["id"]]["image_url"] = photos[0]["url"]
        self.rows[snapshot["id"]]["image_urls"] = [photo["url"] for photo in photos]


class FakeCommons:
    def __init__(self):
        stream = BytesIO()
        Image.new("RGB", (800, 600), "#4e7758").save(stream, "JPEG")
        self.bytes = stream.getvalue()
        self.metadata = licensed_metadata(info(), "File:Beaver.jpg")
        self.calls = 0

    def search(self, query):
        self.calls += 1
        return [{"page_id": self.calls, "file_title": "File:Beaver.jpg", "download_url": "https://upload.wikimedia.org/test.jpg", "description": "Animal photograph", "metadata": copy.deepcopy(self.metadata)}]

    def download(self, url):
        return self.bytes

    def refresh_metadata(self, selected):
        return copy.deepcopy(self.metadata)


class FakeStorage:
    def __init__(self):
        self.staged = []
        self.published = []
        self.fail = False
        self.objects = {}
        self.documents = {}
        self.settings = Settings(review_prefix="trivia-photo-review", review_bucket="review")

    def store_asset(self, batch, trivia_id, asset, source=False):
        location = {"bucket": "review", "key": f"review/{batch}/assets/{trivia_id}-{asset['sha256'][:20]}{'-source' if source else ''}.webp"}
        self.objects[(location["bucket"], location["key"])] = asset["data"]
        return dict({k: v for k, v in asset.items() if k not in {"data", "source"}}, r2=location)

    def read_asset(self, asset):
        location = asset["r2"]
        data = self.objects[(location["bucket"], location["key"])]
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("R2画像が変更されています")
        return data

    def confirm_asset(self, asset):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.staged.append(asset["sha256"])
        return dict(asset["r2"])

    def image_url(self, asset):
        return "https://images.example.test/" + asset["r2"]["key"] if asset.get("r2") else ""

    def head(self, bucket, key):
        data = self.objects.get((bucket, key))
        return {"ContentLength": len(data), "Metadata": {"sha256": hashlib.sha256(data).hexdigest()}} if data is not None else None

    def list_keys(self, prefix):
        return [key for key in self.documents if key.startswith(prefix)]

    def get_json(self, key):
        from trivia_photo.harness import digest
        value = self.documents.get(key)
        return (copy.deepcopy(value), digest(value)) if value is not None else (None, None)

    def put_json(self, key, value, etag=None):
        from trivia_photo.harness import digest
        current = self.documents.get(key)
        if (current is not None and etag != digest(current)) or (current is None and etag is not None):
            raise ValueError("別の処理がR2の作業記録を更新しました")
        self.documents[key] = copy.deepcopy(value)

    def stage(self, batch, trivia_id, sha, data):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.staged.append((batch, trivia_id, sha))
        return {"bucket": "review", "key": f"review/{batch}/{trivia_id}-{sha[:20]}.webp"}

    def publish(self, item):
        self.published.append(item["trivia_id"])
        return f"https://images.example.com/trivia/auto/{item['trivia_id']}-{item['asset']['sha256'][:20]}.webp"


def plan():
    return {"subject": "animal", "exact_queries": ["beaver"], "reference_queries": [], "required_features": "animal", "avoid": "illustrations"}


def choice(item, index=0, **changes):
    result = {"candidate_snapshot": candidate_snapshot(item), "candidate_index": index,
              "relationship": "general" if index is not None else "unusable", "reason": "一般的な主題に合う写真" if index is not None else "使える写真がない",
              "rights_review_required": False, "is_photograph": index is not None,
              "inspected_image_sha256": item["candidates"][index]["asset"]["sha256"] if index is not None else None,
              "visual_review": "16:9の主題と構図を確認", "rights_review": "CC BYの作者・出典・加工表記を記録"}
    return dict(result, **changes)


def stage_fixture(workflow, batch, trivia_id):
    workflow.search(batch, trivia_id, plan())
    workflow.select(batch, trivia_id, choice(workflow.state.get(batch, trivia_id)))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.temp.name))
        self.settings = Settings(database_url="postgresql://user:password@project.neon.tech/neondb", data_dir=self.state.root)
        self.neon, self.commons, self.storage = FakeNeon(), FakeCommons(), FakeStorage()
        self.workflow = Workflow(self.settings, self.state, self.neon, self.commons, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, limit=1):
        batch = self.workflow.collect(limit)["batch"]
        for item in self.state.items(batch):
            stage_fixture(self.workflow, batch, item["trivia_id"])
        return batch

    def approved(self):
        batch = self.collect()
        self.workflow.decision(batch, 1, True)
        return batch

    def test_collection_only_stages_without_neon_writes(self):
        batch = self.collect(2)
        self.assertEqual(len(self.storage.staged), 2)
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])
        self.assertEqual([item["status"] for item in self.state.items(batch)], ["staged", "staged"])

    def test_collect_only_exports_trivia_without_search_upload_or_api_usage(self):
        result = self.workflow.collect(2)
        self.assertEqual(result["statuses"], {"queued": 2})
        self.assertEqual(self.commons.calls, 0)
        self.assertEqual(self.storage.staged, [])
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(result["api_usage_history"]["calls"], 0)
        task = read_json(Path(result["tasks"][0]["task_file"]))
        self.assertEqual(task["trivia"]["content"], "入力は確認済み")
        self.assertNotIn("database_url", task)

    def test_search_only_downloads_and_can_reuse_candidates(self):
        batch = self.workflow.collect(1)["batch"]
        first = self.workflow.search(batch, 1, plan())
        self.assertEqual(first["status"], "candidates")
        calls = self.commons.calls
        self.workflow.search(batch, 1)
        self.assertEqual(self.commons.calls, calls)
        self.assertEqual(self.storage.staged, [])
        self.assertEqual(self.neon.writes, [])
        packet = read_json(Path(first["task_file"]))
        self.assertEqual(packet["candidate_snapshot"], candidate_snapshot(self.state.get(batch, 1)))
        self.assertIn("r2", packet["candidates"][0]["asset"])
        self.assertFalse(list(self.state.root.rglob("*.webp")))

    def test_stale_candidate_snapshot_cannot_upload(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        old = choice(self.state.get(batch, 1))
        self.workflow.search(batch, 1, plan(), refresh=True)
        with self.assertRaisesRegex(ValueError, "候補が変更"):
            self.workflow.select(batch, 1, old)
        self.assertEqual(self.storage.staged, [])

    def test_wrong_inspected_hash_cannot_upload(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        selection = choice(self.state.get(batch, 1), inspected_image_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "実際に確認"):
            self.workflow.select(batch, 1, selection)
        self.assertEqual(self.storage.staged, [])

    def test_tampered_candidate_cannot_upload(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        item = self.state.get(batch, 1)
        location = item["candidates"][0]["asset"]["r2"]
        self.storage.objects[(location["bucket"], location["key"])] = b"tampered"
        with self.assertRaisesRegex(ValueError, "変更されています"):
            self.workflow.select(batch, 1, choice(item))
        self.assertEqual(self.storage.staged, [])

    def test_invalid_codex_json_does_not_change_state(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        item = self.state.get(batch, 1)
        for invalid in (dict(choice(item), candidate_index=True), choice(item, visual_review="   "), choice(item, rights_review_required="false")):
            with self.assertRaises(ValueError):
                self.workflow.select(batch, 1, invalid)
            self.assertEqual(self.state.get(batch, 1), item)
        self.assertEqual(self.storage.staged, [])

    def test_approved_item_cannot_be_researched_or_reselected(self):
        batch = self.approved()
        item = self.state.get(batch, 1)
        with self.assertRaises(ValueError):
            self.workflow.search(batch, 1, plan(), refresh=True)
        with self.assertRaises(ValueError):
            self.workflow.select(batch, 1, choice(item))
        self.assertEqual(self.state.get(batch, 1), item)

    def test_reference_search_cannot_be_promoted_to_exact(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, dict(plan(), reference_queries=["related animal"]))
        item = self.state.get(batch, 1)
        reference_index = next(i for i, c in enumerate(item["candidates"]) if c["search_relationship"] == "reference")
        self.workflow.select(batch, 1, choice(item, reference_index, relationship="exact"))
        result = self.state.get(batch, 1)
        self.assertEqual(result["metadata"]["relationship"], "reference")
        self.assertTrue(result["metadata"]["is_reference"])

    def test_selection_records_codex_visual_rights_and_instruction_version(self):
        batch = self.collect()
        record = self.state.get(batch, 1)["metadata"]["codex_review"]
        self.assertEqual(record["actor"], "codex")
        self.assertEqual(len(record["instructions_version"]), 64)
        self.assertEqual(record["inspected_image_sha256"], self.state.get(batch, 1)["asset"]["sha256"])
        self.assertEqual(self.state.usage(batch)["calls"], 0)

    def test_legacy_api_usage_remains_history_without_new_calls(self):
        batch = self.collect()
        with self.state.connect() as db:
            db.execute("INSERT INTO usage(batch_id,purpose,input_tokens,output_tokens,cost,status) VALUES(?,?,?,?,?,?)",
                       (batch, "legacy-api", 123, 45, 0.001, "complete"))
        self.workflow.collect(resume=batch)
        summary = self.workflow.summary(batch)
        self.assertEqual(summary["api_usage_history"]["tokens"], 168)
        self.assertIn("旧方式のAPI使用履歴", render(self.workflow, batch, offline=True))

    def test_next_batch_skips_previous_attempts(self):
        first, second = self.collect(2), self.collect(2)
        self.assertEqual([i["trivia_id"] for i in self.state.items(first)], [1, 2])
        self.assertEqual([i["trivia_id"] for i in self.state.items(second)], [3, 4])

    def test_approval_does_not_publish(self):
        self.approved()
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])

    def test_publish_requires_approval(self):
        batch = self.collect()
        with self.assertRaises(ValueError):
            self.workflow.publish(batch, ids=[1], apply=True, credits_ready=True)
        self.assertEqual(self.storage.published, [])

    def test_dry_run_never_writes_or_copies(self):
        batch = self.approved()
        result = self.workflow.publish(batch, credits_ready=True)
        self.assertEqual(result[0]["status"], "dry_run")
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])

    def test_required_credits_block_publication(self):
        batch = self.approved()
        result = self.workflow.publish(batch, apply=True)
        self.assertEqual(result[0]["status"], "waiting_for_credit_display")
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])

    def test_publish_updates_url_and_credit_together(self):
        batch = self.approved()
        result = self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(result[0]["status"], "published")
        self.assertEqual(len(self.neon.writes), 1)
        self.assertIn("CC BY 4.0", self.neon.writes[0][2])
        self.assertIn("source_url", self.neon.writes[0][3])
        self.assertEqual(self.state.get(batch, 1)["status"], "published")

    def test_publish_is_idempotent(self):
        batch = self.approved()
        self.workflow.publish(batch, apply=True, credits_ready=True)
        self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(len(self.storage.published), 1)
        self.assertEqual(len(self.neon.writes), 1)

    def test_existing_url_blocks_copy_and_update(self):
        batch = self.approved()
        self.neon.rows[1]["image_url"] = "https://existing.example.com/photo.webp"
        result = self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(self.storage.published, [])
        self.assertEqual(self.neon.writes, [])

    def test_changed_content_blocks_publication_without_fact_checking(self):
        batch = self.approved()
        self.neon.rows[1]["content"] = "ユーザーが後から編集"
        result = self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(self.storage.published, [])

    def test_changed_license_blocks_publication(self):
        batch = self.approved()
        self.commons.metadata["license"] = "CC BY-SA 4.0"
        result = self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(self.storage.published, [])

    def test_illustration_category_blocks_publication(self):
        batch = self.approved()
        self.commons.metadata["evidence"]["extmetadata"]["Categories"] = {"value": "Octopus vulgaris illustrations|PD-old-100"}
        result = self.workflow.publish(batch, apply=True, credits_ready=True)
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(self.storage.published, [])

    def test_unusable_result_is_not_staged(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        self.workflow.select(batch, 1, choice(self.state.get(batch, 1), None))
        self.assertEqual(self.state.get(batch, 1)["status"], "needs_review")
        self.assertEqual(self.storage.staged, [])

    def test_targeted_reselection_does_not_change_other_items(self):
        batch = self.collect(2)
        self.workflow.decision(batch, 1, True)
        before = self.state.get(batch, 1)
        self.workflow.search(batch, 2, plan(), refresh=True)
        self.workflow.select(batch, 2, choice(self.state.get(batch, 2)))
        self.assertEqual(self.state.get(batch, 1), before)
        self.assertTrue(self.state.get(batch, 2)["selection_history"])

    def test_resume_reuses_codex_selection_after_storage_failure(self):
        self.storage.fail = True
        batch = self.collect()
        self.assertEqual(self.state.get(batch, 1)["status"], "error")
        calls = self.commons.calls
        decision = self.state.get(batch, 1)["selection"]
        self.storage.fail = False
        self.workflow.collect(resume=batch)
        self.assertEqual(self.commons.calls, calls)
        self.assertEqual(self.state.get(batch, 1)["selection"], decision)
        self.assertEqual(self.state.get(batch, 1)["status"], "staged")

    def test_rejected_item_does_not_publish(self):
        batch = self.approved()
        self.workflow.decision(batch, 1, False)
        self.assertEqual(self.workflow.publish(batch, apply=True, credits_ready=True), [])

    def test_reformat_pending_legacy_asset_without_search_ai_or_neon_update(self):
        batch = self.collect()
        item = self.state.get(batch, 1)
        # Represent a pre-16:9 saved photo, using its preserved full-frame source.
        item["asset"] = item["asset"]["source"]
        self.state.save(item)
        calls = self.commons.calls
        result = self.workflow.reformat(batch)
        self.assertEqual(result[0]["status"], "formatted")
        self.assertEqual((result[0]["width"], result[0]["height"]), (800, 450))
        self.assertEqual(self.commons.calls, calls)
        self.assertEqual(self.neon.writes, [])
        self.assertEqual(self.storage.published, [])
        self.assertIn("16:9中央トリミング", self.state.get(batch, 1)["metadata"]["changes"])

    def test_reformat_does_not_alter_approved_image(self):
        batch = self.approved()
        before = self.state.get(batch, 1)
        result = self.workflow.reformat(batch)
        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(self.state.get(batch, 1), before)

    def test_reformat_is_idempotent(self):
        batch = self.collect()
        item = self.state.get(batch, 1)
        item["asset"] = item["asset"]["source"]
        self.state.save(item)
        self.workflow.reformat(batch)
        before, count = self.state.get(batch, 1), len(self.storage.staged)
        self.assertEqual(self.workflow.reformat(batch)[0]["status"], "already_formatted")
        self.assertEqual(self.state.get(batch, 1), before)
        self.assertEqual(len(self.storage.staged), count)

    def test_retry_review_reuses_candidates_without_search_or_planning(self):
        batch = self.workflow.collect(1)["batch"]
        self.workflow.search(batch, 1, plan())
        self.workflow.select(batch, 1, choice(self.state.get(batch, 1), None))
        search_calls = self.commons.calls
        self.assertEqual(self.state.get(batch, 1)["status"], "needs_review")
        self.workflow.collect(resume=batch, retry=True)
        self.workflow.select(batch, 1, choice(self.state.get(batch, 1)))
        self.assertEqual(self.commons.calls, search_calls)
        self.assertEqual(self.state.get(batch, 1)["status"], "staged")

    def test_asset_change_blocks_approval(self):
        batch = self.collect()
        location = self.state.get(batch, 1)["asset"]["r2"]
        self.storage.objects[(location["bucket"], location["key"])] = b"changed"
        with self.assertRaises(ValueError):
            self.workflow.decision(batch, 1, True)

    def test_extra_rights_must_be_confirmed(self):
        batch = self.collect()
        item = self.state.get(batch, 1)
        item["metadata"]["rights_review_required"] = True
        self.state.save(item)
        with self.assertRaises(ValueError):
            self.workflow.decision(batch, 1, True)
        self.workflow.decision(batch, 1, True, rights_confirmed=True)
        self.assertEqual(self.state.get(batch, 1)["status"], "approved")

    def test_review_escapes_external_text(self):
        batch = self.collect()
        item = self.state.get(batch, 1)
        item["metadata"]["author"] = '<script>alert("xss")</script>'
        self.state.save(item)
        page = render(self.workflow, batch, offline=True)
        self.assertNotIn('<script>alert("xss")</script>', page)
        self.assertIn("&lt;script&gt;", page)

    def test_cannot_escape_asset_directory(self):
        with self.assertRaises(ValueError):
            self.state.asset_dir("../../elsewhere")


class LicenseTests(unittest.TestCase):
    def test_categories_exclude_scanned_illustrations_and_generated_images(self):
        for category in ("Octopus vulgaris illustrations", "AI-generated images", "Watercolor paintings", "Scientific diagrams"):
            metadata = {"evidence": {"extmetadata": {"Categories": {"value": category}}}}
            self.assertTrue(non_photo(metadata))
        self.assertFalse(non_photo({"evidence": {"extmetadata": {"Categories": {"value": "Photographs of octopuses"}}}}))

    def test_commercial_cc_by_and_cc_by_sa_allowed(self):
        for name, code, url in [("CC BY 4.0", "cc-by-4.0", "https://creativecommons.org/licenses/by/4.0/"),
                                ("CC BY-SA 3.0", "cc-by-sa-3.0", "http://creativecommons.org/licenses/by-sa/3.0/")]:
            metadata = licensed_metadata(info(name, code, url), "File:Beaver.jpg")
            self.assertTrue(metadata["attribution_required"])
            self.assertEqual(metadata["author"], "Test Author")

    def test_nc_nd_unknown_and_fair_use_rejected(self):
        for name in ("CC BY-NC 4.0", "CC BY-ND 4.0", "Fair use", "Free image"):
            with self.assertRaises(ValueError):
                licensed_metadata(info(name), "File:Beaver.jpg")

    def test_mismatched_license_url_rejected(self):
        with self.assertRaises(ValueError):
            licensed_metadata(info(license_url="https://creativecommons.org/licenses/by-nc/4.0/"), "File:Beaver.jpg")

    def test_pd_requires_metadata_evidence(self):
        metadata = licensed_metadata(info("Public domain", "pd", ""), "File:Beaver.jpg")
        self.assertFalse(metadata["attribution_required"])
        raw = info("Public domain", "pd", "")
        raw["extmetadata"].pop("Copyrighted")
        with self.assertRaises(ValueError):
            licensed_metadata(raw, "File:Beaver.jpg")


class BoundaryTests(unittest.TestCase):

    def test_r2_stage_never_uses_publish_prefix(self):
        settings = Settings(bucket="public", review_bucket="review", endpoint="https://r2.example.com", access_key="test", secret_key="test")
        data = b"sample"
        sha = hashlib.sha256(data).hexdigest()
        with patch("trivia_photo.storage.boto3.client") as client:
            storage = R2(settings)
            with patch.object(storage, "head", side_effect=[None, {"ContentLength": len(data), "Metadata": {"sha256": sha}}]):
                location = storage.stage("batch", 1, sha, data)
            self.assertTrue(location["key"].startswith("trivia-photo-review/"))
            self.assertEqual(client.return_value.put_object.call_args.kwargs["Bucket"], "review")
            client.return_value.copy_object.assert_not_called()

    def test_neon_detects_race_before_update(self):
        neon = Neon("postgresql://user:password@project.neon.tech/neondb")
        conn, cur = MagicMock(), MagicMock()
        conn.__enter__.return_value = conn
        cur.__enter__.return_value = cur
        conn.cursor.return_value = cur
        snapshot = {"id": 1, "title": "Test", "content": "Verified", "explanation": "", "category": "General"}
        cur.fetchone.return_value = dict(snapshot, image_url="https://existing.example.com/image.webp")
        with patch.object(neon, "connect", return_value=conn), self.assertRaises(ValueError):
            neon.publish(snapshot, "https://new.example.com/image.webp", "Credit", {})
        self.assertFalse(any("UPDATE public.trivia" in call.args[0] for call in cur.execute.call_args_list))

    def test_neon_gallery_updates_cover_all_urls_and_matching_photo_sources_together(self):
        neon = Neon("postgresql://user:password@project.neon.tech/neondb")
        conn, cur = MagicMock(), MagicMock()
        conn.__enter__.return_value = conn
        cur.__enter__.return_value = cur
        conn.cursor.return_value = cur
        snapshot = {"id": 1, "title": "Test", "content": "Verified", "explanation": "", "category": "General"}
        cur.fetchone.return_value = dict(snapshot, image_url=None, image_urls=[])
        photos = [dict(url=f"https://images.example.com/{index}.webp", credit=f"Author {index}",
                       metadata={"source_url": f"https://commons.wikimedia.org/wiki/File:{index}.jpg"})
                  for index in (1, 2)]
        with patch.object(neon, "connect", return_value=conn):
            neon.publish_gallery(snapshot, photos)
        writes = [call for call in cur.execute.call_args_list if "UPDATE public.trivia" in call.args[0]]
        self.assertEqual(len(writes), 1)
        parameters = writes[0].args[1]
        self.assertEqual(parameters[0], photos[0]["url"])
        self.assertEqual(parameters[1].adapted, [photo["url"] for photo in photos])
        self.assertIn("Author 2", parameters[2].adapted[photos[1]["url"]])
        self.assertIn(photos[1]["metadata"]["source_url"], parameters[2].adapted[photos[1]["url"]])
        self.assertEqual(parameters[4].adapted["photos"], photos)

    def test_neon_gallery_refuses_changed_extra_photo_even_when_cover_matches(self):
        neon = Neon("postgresql://user:password@project.neon.tech/neondb")
        conn, cur = MagicMock(), MagicMock()
        conn.__enter__.return_value = conn
        cur.__enter__.return_value = cur
        conn.cursor.return_value = cur
        snapshot = {"id": 1, "title": "Test", "content": "Verified", "explanation": "", "category": "General"}
        photos = [dict(url=f"https://images.example.com/{index}.webp", credit="Author", metadata={}) for index in (1, 2)]
        cur.fetchone.return_value = dict(snapshot, image_url=photos[0]["url"],
                                        image_urls=[photos[0]["url"], "https://images.example.com/existing.webp"])
        with patch.object(neon, "connect", return_value=conn), self.assertRaises(ValueError):
            neon.publish_gallery(snapshot, photos)
        self.assertFalse(any("UPDATE public.trivia" in call.args[0] for call in cur.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
