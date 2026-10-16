"""Exercise the admin's actual Streamlit reruns without external services.

Run from apps/api with: venv/Scripts/python.exe -m unittest tests.test_admin_dashboard
No .env is loaded, and every database write goes to a fresh in-memory SQLite DB.
"""

from contextlib import ExitStack
import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.mocks = ExitStack()
        self.addCleanup(self.mocks.close)
        self.mocks.enter_context(patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:///:memory:",
            "APP_DATABASE_URL": "sqlite:///:memory:",
            "OPENAI_API_KEY": "test-key-never-sent",
            "ADMIN_DASHBOARD_PASSWORD": "",
            "TRIVIA_IMAGE_R2_BASE_URL": "https://images.example.test",
            "R2_ENDPOINT_URL": "https://r2.example.test",
            "R2_ACCESS_KEY_ID": "test-access",
            "R2_SECRET_ACCESS_KEY": "test-secret",
            "R2_BUCKET_NAME": "test-bucket",
            "R2_TRIVIA_IMAGE_PREFIX": "trivia",
        }))
        self.mocks.enter_context(patch("dotenv.load_dotenv", return_value=False))
        database = importlib.import_module("database")
        self.models = importlib.import_module("models")
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        self.models.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.mocks.enter_context(patch.object(database, "SessionLocal", self.sessions))
        self.mocks.enter_context(patch.object(database, "engine", self.engine))
        self.mocks.enter_context(patch.object(database, "app_engine", self.engine))
        self.mocks.enter_context(patch(
            "scripts.migrations.migrate_trivia_candidates.migrate", return_value=None,
        ))
        self.openai = self.mocks.enter_context(patch("openai.OpenAI"))
        self.r2 = MagicMock()
        self.r2.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}
        self.r2.get_paginator.return_value.paginate.return_value = []
        self.mocks.enter_context(patch("boto3.client", return_value=self.r2))
        self.network = self.mocks.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Tests must not call external HTTP services"),
        ))
        self.mocks.enter_context(patch(
            "socket.socket.connect", side_effect=OSError("Network disabled in tests"),
        ))
        self.app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "admin_dashboard.py"),
            default_timeout=15,
        )

    def run_app(self):
        self.app.run()
        self.assertFalse(list(self.app.exception), [e.message for e in self.app.exception])
        return self.app

    def by_label(self, widgets, label):
        matches = [widget for widget in widgets if widget.label == label]
        self.assertEqual(len(matches), 1, f"Expected one {label!r}; found {len(matches)}")
        return matches[0]

    def open_section(self, label):
        self.app.radio(key="admin_section").set_value(label)
        return self.run_app()

    def fill_new_map(self, target="新規作成（地図用）", *, coordinates=True):
        self.app.radio(key="new_register_target").set_value(target)
        self.run_app()
        self.app.text_input(key="new_title").set_value("東京タワーの色")
        self.app.text_area(key="new_content").set_value("タワーの色には正式な名前があります。")
        self.app.text_input(key="new_map_prefecture").set_value("東京都")
        self.app.text_input(key="new_map_address").set_value("東京タワー / 東京都港区芝公園4-2-8")
        if coordinates:
            self.app.number_input(key="new_map_latitude").set_value(35.6586)
            self.app.number_input(key="new_map_longitude").set_value(139.7454)

    def seed(self, model, **values):
        with self.sessions() as db:
            row = model(**values)
            db.add(row)
            db.commit()
            return row.id

    def seed_map(self, **overrides):
        values = {
            "title": "東京タワーの色",
            "content": "東京タワーの色には正式な名前があります。",
            "explanation": "航空機から目立つように塗り分けられています。",
            "source": "https://example.test/tower",
            "category": "地理",
            "map_address": "東京タワー / 東京都港区芝公園4-2-8",
            "map_prefecture": "東京都",
            "map_latitude": 35.6586,
            "map_longitude": 139.7454,
            "map_radius": 1200,
            "map_hint": "芝公園の赤と白の塔を探そう",
        }
        values.update(overrides)
        return self.seed(self.models.MapTrivia, **values)

    def test_map_target_immediately_displays_location_inputs(self):
        self.run_app()
        target = self.app.radio(key="new_register_target")
        # AppTest.run() forces a rerun even for form controls. Real browsers do
        # not, so checking form_id is essential to cover the reported failure.
        self.assertEqual(target.proto.form_id, "", "The dynamic target must be outside a form")
        target.set_value("新規作成（地図用）")
        self.run_app()
        self.by_label(self.app.text_input, "都道府県")
        self.by_label(self.app.text_input, "住所・施設名")
        self.by_label(self.app.number_input, "緯度")
        self.by_label(self.app.number_input, "経度")
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.MapTrivia).count(), 0)

    def test_switching_registration_targets_keeps_map_draft(self):
        self.run_app()
        self.fill_new_map()
        self.app.text_area(key="new_map_hint").set_value("保存前の場所のヒント")
        self.run_app()
        self.app.radio(key="new_register_target").set_value("通常の雑学")
        self.run_app()
        self.assertFalse(any(widget.key == "new_map_prefecture" for widget in self.app.text_input))
        self.app.radio(key="new_register_target").set_value("新規作成（地図用）")
        self.run_app()
        self.assertEqual(self.app.text_input(key="new_title").value, "東京タワーの色")
        self.assertEqual(self.app.text_input(key="new_map_prefecture").value, "東京都")
        self.assertEqual(self.app.text_input(key="new_map_address").value, "東京タワー / 東京都港区芝公園4-2-8")
        self.assertAlmostEqual(self.app.number_input(key="new_map_latitude").value, 35.6586)
        self.assertAlmostEqual(self.app.number_input(key="new_map_longitude").value, 139.7454)
        self.assertEqual(self.app.text_area(key="new_map_hint").value, "保存前の場所のヒント")

    def test_switching_sections_keeps_new_registration_draft(self):
        self.run_app()
        self.app.text_input(key="new_title").set_value("管理画面を見てから戻る下書き")
        self.app.text_area(key="new_content").set_value("未登録の本文を残します。")
        self.app.text_input(key="new_image_url").set_value("trivia/draft.webp")
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.open_section("🆕 新規登録")
        self.assertEqual(self.app.text_input(key="new_title").value, "管理画面を見てから戻る下書き")
        self.assertEqual(self.app.text_area(key="new_content").value, "未登録の本文を残します。")
        self.assertEqual(self.app.text_input(key="new_image_url").value, "trivia/draft.webp")
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)

    def test_registration_keeps_draft_when_validation_fails(self):
        self.run_app()
        self.app.text_input(key="new_title").set_value("修正を続けたい下書き")
        self.app.button(key="new_submit").click()
        self.run_app()
        self.assertTrue(any("必須" in error.value for error in self.app.error))
        # An unrelated rerun catches client-side form clearing as well.
        self.run_app()
        self.assertEqual(
            self.app.text_input(key="new_title").value,
            "修正を続けたい下書き",
        )
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)

    def test_registration_rejects_whitespace_only_required_fields(self):
        self.run_app()
        self.app.text_input(key="new_title").set_value("   ")
        self.app.text_area(key="new_content").set_value("\n \n")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)

    def test_map_registration_saves_location_hint_and_r2_image(self):
        self.run_app()
        self.fill_new_map()
        self.app.text_input(key="new_image_url").set_value("trivia/tower.webp")
        self.app.text_area(key="new_map_hint").set_value("赤と白の塔を探そう")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)
            rows = db.query(self.models.MapTrivia).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].map_hint, "赤と白の塔を探そう")
            self.assertEqual(rows[0].map_address, "東京タワー / 東京都港区芝公園4-2-8")
            self.assertAlmostEqual(rows[0].map_latitude, 35.6586)
            self.assertAlmostEqual(rows[0].map_longitude, 139.7454)
            self.assertEqual(rows[0].image_url, "https://images.example.test/trivia/tower.webp")

    def test_map_registration_requires_explicit_coordinates(self):
        self.run_app()
        self.fill_new_map(coordinates=False)
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.MapTrivia).count(), 0)
        self.assertTrue(any("緯度" in error.value or "座標" in error.value for error in self.app.error))
        self.assertEqual(self.app.text_input(key="new_title").value, "東京タワーの色")

    def test_registration_keeps_draft_when_save_fails(self):
        self.run_app()
        self.fill_new_map("通常 + 地図")
        with patch("admin_views.create_manual_trivia", side_effect=ValueError("保存失敗のテスト")):
            self.app.button(key="new_submit").click()
            self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)
            self.assertEqual(db.query(self.models.MapTrivia).count(), 0)
        self.assertEqual(self.app.text_input(key="new_title").value, "東京タワーの色")
        self.assertTrue(any("保存失敗のテスト" in error.value for error in self.app.error))

    def test_editing_map_title_preserves_existing_hint(self):
        row_id = self.seed_map()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.radio(key="manage_target").set_value("雑学MAP")
        self.run_app()
        self.app.text_input(key=f"map_title_map_{row_id}").set_value("更新後のタワーの色")
        self.app.button(key=f"map_update_map_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            row = db.get(self.models.MapTrivia, row_id)
            self.assertEqual(row.title, "更新後のタワーの色")
            self.assertEqual(row.map_hint, "芝公園の赤と白の塔を探そう")

    def test_map_archive_and_restore_preserve_record_and_unlock_history(self):
        row_id = self.seed_map(legacy_spot_id="legacy_tokyo_tower", legacy_trivia_id=42)
        unlock_id = self.seed(self.models.MapTriviaUnlock, user_id="test-user", map_trivia_id=row_id)
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.radio(key="manage_target").set_value("雑学MAP")
        self.run_app()
        self.app.radio(key="map_status").set_value("すべて")
        self.run_app()
        self.app.checkbox(key=f"map_archive_confirm_map_{row_id}").set_value(True)
        self.run_app()
        self.app.button(key=f"map_delete_map_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertFalse(db.get(self.models.MapTrivia, row_id).is_active)
            self.assertEqual(db.get(self.models.MapTriviaUnlock, unlock_id).map_trivia_id, row_id)
        self.app.button(key=f"map_delete_map_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            row = db.get(self.models.MapTrivia, row_id)
            self.assertTrue(row.is_active)
            self.assertEqual(db.query(self.models.MapTrivia).count(), 1)
            self.assertEqual(row.title, "東京タワーの色")
            self.assertEqual(row.legacy_spot_id, "legacy_tokyo_tower")
            self.assertEqual(row.legacy_trivia_id, 42)
            self.assertEqual(row.map_hint, "芝公園の赤と白の塔を探そう")
            unlock = db.get(self.models.MapTriviaUnlock, unlock_id)
            self.assertEqual(unlock.user_id, "test-user")
            self.assertEqual(unlock.map_trivia_id, row_id)

    def test_existing_normal_trivia_can_be_registered_on_map(self):
        row_id = self.seed(self.models.Trivia,
            title="東京タワー", content="タワーの色の雑学です。", explanation="色の由来です。",
            source="https://example.test/tower", category="地理",
            image_url="https://images.example.test/trivia/tower.webp",
        )
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.text_input(key=f"edit_map_{row_id}_prefecture").set_value("東京都")
        self.app.text_input(key=f"edit_map_{row_id}_address").set_value("東京タワー / 東京都港区芝公園")
        self.app.number_input(key=f"edit_map_{row_id}_latitude").set_value(35.6586)
        self.app.number_input(key=f"edit_map_{row_id}_longitude").set_value(139.7454)
        self.app.button(key=f"map_register_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 1)
            rows = db.query(self.models.MapTrivia).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].map_prefecture, "東京都")
            self.assertEqual(rows[0].image_url, "https://images.example.test/trivia/tower.webp")

    def test_candidate_map_checkbox_reveals_fields_and_publishes_without_openai_key(self):
        row_id = self.seed(self.models.TriviaCandidate,
            title="東京タワーの色", content="タワーの色には正式な名前があります。",
            source="https://example.test/tower", category="地理", status="pending",
            image_url="https://images.example.test/trivia/tower.webp",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.run_app()
            self.open_section("🤖 AI収集・承認")
            checkbox = self.app.checkbox(key=f"candidate_{row_id}_map")
            self.assertEqual(checkbox.proto.form_id, "")
            checkbox.set_value(True)
            self.app.checkbox(key=f"candidate_{row_id}_normal").set_value(False)
            self.run_app()
            key = f"candidate_{row_id}_location"
            self.app.text_input(key=f"{key}_prefecture").set_value("東京都")
            self.app.text_input(key=f"{key}_address").set_value("東京タワー / 東京都港区芝公園")
            self.app.number_input(key=f"{key}_latitude").set_value(35.6586)
            self.app.number_input(key=f"{key}_longitude").set_value(139.7454)
            self.app.text_area(key=f"{key}_hint").set_value("赤と白の塔")
            self.app.button(key=f"candidate_{row_id}_approve").click()
            self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 0)
            row = db.query(self.models.MapTrivia).one()
            self.assertEqual(row.map_hint, "赤と白の塔")
            self.assertEqual(row.image_url, "https://images.example.test/trivia/tower.webp")
            self.assertNotEqual(db.get(self.models.TriviaCandidate, row_id).status, "pending")
        self.openai.assert_not_called()

    def test_saving_candidate_keeps_both_destinations_for_publication(self):
        row_id = self.seed(self.models.TriviaCandidate,
            title="東京タワーの色", content="タワーの色には正式な名前があります。",
            source="https://example.test/tower", category="地理", status="pending",
        )
        self.run_app()
        self.open_section("🤖 AI収集・承認")
        self.app.checkbox(key=f"candidate_{row_id}_map").set_value(True)
        self.run_app()
        key = f"candidate_{row_id}_location"
        self.app.text_input(key=f"{key}_prefecture").set_value("東京都")
        self.app.text_input(key=f"{key}_address").set_value("東京タワー / 東京都港区芝公園")
        self.app.number_input(key=f"{key}_latitude").set_value(35.6586)
        self.app.number_input(key=f"{key}_longitude").set_value(139.7454)
        self.app.button(key=f"candidate_{row_id}_save").click()
        self.run_app()
        self.assertTrue(self.app.checkbox(key=f"candidate_{row_id}_normal").value)
        self.assertTrue(self.app.checkbox(key=f"candidate_{row_id}_map").value)
        with self.sessions() as db:
            candidate = db.get(self.models.TriviaCandidate, row_id)
            self.assertEqual(candidate.status, "pending")
            self.assertEqual(candidate.map_prefecture, "東京都")
        self.app.button(key=f"candidate_{row_id}_approve").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.Trivia).count(), 1)
            self.assertEqual(db.query(self.models.MapTrivia).count(), 1)
            self.assertEqual(db.get(self.models.TriviaCandidate, row_id).status, "approved")

    def test_unlinking_shared_r2_image_keeps_other_references(self):
        image_url = "https://images.example.test/trivia/shared.webp"
        row_id = self.seed(self.models.Trivia,
            title="共有写真を使う雑学", content="通常の雑学です。", category="地理",
            source="https://example.test/source", image_url=image_url,
        )
        map_id = self.seed_map(image_url=image_url)
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.button(key=f"image_delete_edit_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertFalse(db.get(self.models.Trivia, row_id).image_url)
            self.assertEqual(db.get(self.models.MapTrivia, map_id).image_url, image_url)
        self.r2.delete_object.assert_not_called()

    def test_opening_dashboard_does_not_list_r2_or_check_candidate_urls(self):
        self.seed(self.models.TriviaCandidate,
            title="確認待ちの候補", content="本文です。", category="科学",
            source="https://example.test/source", status="pending",
        )
        self.run_app()
        self.network.assert_not_called()
        self.r2.list_objects_v2.assert_not_called()
        self.r2.get_paginator.assert_not_called()
        self.openai.return_value.chat.completions.create.assert_not_called()
        self.open_section("🤖 AI収集・承認")
        self.network.assert_not_called()
        self.r2.list_objects_v2.assert_not_called()

    def test_r2_candidate_can_be_selected_and_registered_without_reloading(self):
        self.r2.list_objects_v2.return_value = {
            "Contents": [{"Key": "trivia/candidates/tower.webp", "Size": 4096}],
            "IsTruncated": False,
        }
        self.run_app()
        self.r2.list_objects_v2.assert_not_called()
        self.by_label(self.app.button, "画像候補を読み込む / 更新").click()
        self.run_app()
        self.assertEqual(self.r2.list_objects_v2.call_count, 1)
        self.by_label(self.app.button, "この写真を追加").click()
        self.run_app()
        expected_url = "https://images.example.test/trivia/candidates/tower.webp"
        self.assertEqual(self.app.text_input(key="new_image_url").value, expected_url)
        self.app.text_input(key="new_title").set_value("タワーの色")
        self.app.text_area(key="new_content").set_value("タワーの正式な色の名前です。")
        self.app.button(key="new_submit").click()
        self.run_app()
        self.assertEqual(self.r2.list_objects_v2.call_count, 1)
        self.r2.put_object.assert_not_called()
        self.r2.delete_object.assert_not_called()
        with self.sessions() as db:
            row = db.query(self.models.Trivia).one()
            self.assertEqual(row.image_url, expected_url)

    def test_incomplete_image_url_can_be_corrected_without_crashing(self):
        self.run_app()
        self.app.text_input(key="new_image_url").set_value("https://")
        self.run_app()
        self.app.text_input(key="new_title").set_value("写真を修正できる雑学")
        self.app.text_area(key="new_content").set_value("入力途中の写真URLから修正します。")
        self.app.text_input(key="new_image_url").set_value("trivia/corrected.webp")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(
                db.query(self.models.Trivia).one().image_url,
                "https://images.example.test/trivia/corrected.webp",
            )

    def test_filtering_resets_an_out_of_range_management_page(self):
        for index in range(21):
            self.seed(self.models.Trivia,
                title=f"検索用{index}", content=f"内容{index}", category="科学",
                source="https://example.test/source",
            )
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.by_label(self.app.number_input, "ページ").set_value(2)
        self.run_app()
        self.by_label(self.app.text_input, "🔍 検索 (タイトルまたは本文)").set_value("検索用20")
        self.run_app()
        self.assertEqual(self.by_label(self.app.number_input, "ページ").value, 1)
        self.assertTrue(any("検索用20" in widget.value for widget in self.app.text_input))


if __name__ == "__main__":
    unittest.main()
