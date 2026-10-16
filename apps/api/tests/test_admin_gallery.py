"""Photo order and uploads through the actual Streamlit administration UI."""
from io import BytesIO
from hashlib import sha256
import unittest
from unittest.mock import patch

from PIL import Image

from tests import test_admin_dashboard as dashboard


class AdminGalleryTests(unittest.TestCase):
    setUp = dashboard.AdminDashboardTests.setUp
    run_app = dashboard.AdminDashboardTests.run_app
    open_section = dashboard.AdminDashboardTests.open_section
    by_label = dashboard.AdminDashboardTests.by_label
    seed = dashboard.AdminDashboardTests.seed
    seed_map = dashboard.AdminDashboardTests.seed_map

    def seed_normal(self, **overrides):
        return self.seed(self.models.Trivia, **dict(
            title="東京タワーの色", content="東京タワーの色には正式な名前があります。",
            category="地理", source="https://example.test/tower",
            image_url="https://images.example.test/trivia/a.webp",
            image_urls=["https://images.example.test/trivia/a.webp", "https://images.example.test/trivia/b.webp"],
            image_sources={"https://images.example.test/trivia/b.webp": "撮影：山田太郎"},
            **overrides,
        ))

    def test_map_r2_multiple_photos_and_sources_do_not_change_normal_same_id(self):
        normal_id = self.seed_normal()
        map_id = self.seed_map()
        self.assertEqual(normal_id, map_id)
        self.r2.list_objects_v2.return_value = {
            "Contents": [{"Key": f"trivia/map/{name}.webp", "Size": 100} for name in ("a", "b")],
            "IsTruncated": False,
        }
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.radio(key="manage_target").set_value("雑学MAP")
        self.run_app()
        prefix = f"map_{map_id}"
        self.app.button(key=f"{prefix}_r2:r2_browser:load").click()
        self.run_app()
        photos = [f"https://images.example.test/trivia/map/{name}.webp" for name in ("a", "b")]
        for url in photos:
            self.app.checkbox(key=f"{prefix}_r2:r2_browser:select:" + sha256(url.encode()).hexdigest()[:16]).check()
            self.run_app()
        self.app.button(key=f"{prefix}_r2:r2_browser:add_selected").click()
        self.run_app()
        sources = {url: f"写真：作者{index} / CC BY 4.0" for index, url in enumerate(photos)}
        for url, source in sources.items():
            self.app.text_input(key=f"{prefix}_image_source_" + sha256(url.encode()).hexdigest()[:16]).set_value(source)
        self.app.button(key=f"map_update_{prefix}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.MapTrivia, map_id)
            self.assertEqual(item.image_urls, photos)
            self.assertEqual(item.image_url, photos[0])
            self.assertEqual(item.image_sources, sources)
            normal = db.get(self.models.Trivia, normal_id)
            self.assertEqual(normal.image_urls, [f"https://images.example.test/trivia/{name}.webp" for name in ("a", "b")])
        self.app.radio(key="map_photo_status").set_value("写真なし")
        self.run_app()
        self.assertTrue(any("条件に一致するMAP雑学はありません" in info.value for info in self.app.info))
        self.app.radio(key="map_photo_status").set_value("写真あり")
        self.run_app()
        self.assertTrue(any("写真登録済み 1 件 / 未登録 0 件" in caption.value for caption in self.app.caption))
        self.r2.delete_object.assert_not_called()

    def test_r2_images_append_in_order_and_register_together(self):
        self.r2.list_objects_v2.return_value = {
            "Contents": [{"Key": "trivia/a.webp", "Size": 100}, {"Key": "trivia/b.webp", "Size": 100}],
            "IsTruncated": False,
        }
        self.run_app()
        self.app.button(key="new_r2:r2_browser:load").click()
        self.run_app()
        for index in (0, 1, 0):
            self.app.button(key=f"new_r2:r2_browser:choose:{index}").click()
            self.run_app()
        self.assertTrue(any("この雑学に追加済み: 2 / 10枚" in caption.value for caption in self.app.caption))
        self.assertEqual(sum(caption.value == "追加済み ✓" for caption in self.app.caption), 2)
        self.assertFalse(any(caption.value.startswith("選択中:") for caption in self.app.caption))
        self.app.text_input(key="new_title").set_value("写真2枚の雑学")
        self.app.text_area(key="new_content").set_value("登録順を維持します。")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            item = db.query(self.models.Trivia).one()
            self.assertEqual(item.image_urls, ["https://images.example.test/trivia/a.webp", "https://images.example.test/trivia/b.webp"])
            self.assertEqual(item.image_url, item.image_urls[0])
        self.r2.put_object.assert_not_called()
        self.r2.delete_object.assert_not_called()

    def test_editing_and_reordering_photo_sources_keeps_them_with_the_photo(self):
        from hashlib import sha256
        row_id = self.seed_normal()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        image = "https://images.example.test/trivia/a.webp"
        source_key = sha256(image.encode()).hexdigest()[:16]
        self.app.text_input(key=f"edit_{row_id}_image_source_{source_key}").set_value("https://museum.test/original")
        self.app.button(key=f"edit_{row_id}_image_before_1").click()
        self.run_app()
        self.assertEqual(self.app.text_input(key=f"edit_{row_id}_image_source_{source_key}").value,
                         "https://museum.test/original")
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertTrue(item.image_urls[0].endswith("/b.webp"))
            self.assertEqual(item.image_sources, {image: "https://museum.test/original",
                "https://images.example.test/trivia/b.webp": "撮影：山田太郎"})
        self.r2.put_object.assert_not_called()
        self.r2.delete_object.assert_not_called()

    def test_r2_batch_selection_across_pages_registers_all_selected_photos(self):
        self.r2.list_objects_v2.side_effect = [
            {"Contents": [{"Key": "trivia/a.webp", "Size": 100}, {"Key": "trivia/b.webp", "Size": 100}],
             "IsTruncated": True, "NextContinuationToken": "next-photos"},
            {"Contents": [{"Key": "trivia/c.webp", "Size": 100}], "IsTruncated": False},
        ]
        self.run_app()
        self.app.button(key="new_r2:r2_browser:load").click()
        self.run_app()
        for name in ("a", "b"):
            image = f"https://images.example.test/trivia/{name}.webp"
            checkbox_key = "new_r2:r2_browser:select:" + sha256(image.encode()).hexdigest()[:16]
            self.app.checkbox(key=checkbox_key).check()
            self.run_app()
        self.app.button(key="new_r2:r2_browser:next").click()
        self.run_app()
        image = "https://images.example.test/trivia/c.webp"
        self.app.checkbox(key="new_r2:r2_browser:select:" + sha256(image.encode()).hexdigest()[:16]).check()
        self.run_app()
        self.assertIn("3枚", self.app.button(key="new_r2:r2_browser:add_selected").label)
        self.app.button(key="new_r2:r2_browser:add_selected").click()
        self.run_app()
        self.assertTrue(self.app.button(key="new_r2:r2_browser:add_selected").disabled)
        self.assertTrue(any("登録する写真: 3 / 10枚" in caption.value for caption in self.app.caption))
        self.app.text_input(key="new_title").set_value("写真をまとめて登録")
        self.app.text_area(key="new_content").set_value("ページをまたいで選んだ写真を保存します。")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            item = db.query(self.models.Trivia).one()
            self.assertEqual(item.image_urls, [f"https://images.example.test/trivia/{name}.webp" for name in ("a", "b", "c")])
            self.assertEqual(item.image_url, item.image_urls[0])
        self.assertEqual(self.r2.list_objects_v2.call_count, 2)
        self.r2.put_object.assert_not_called()
        self.r2.delete_object.assert_not_called()

    def test_r2_batch_limit_preserves_gallery_and_selection_until_corrected(self):
        gallery = [f"https://images.example.test/trivia/{index}.webp" for index in range(10)]
        self.app.session_state["new_image_gallery"] = gallery
        self.r2.list_objects_v2.return_value = {
            "Contents": [{"Key": "trivia/0.webp", "Size": 100}, {"Key": "trivia/10.webp", "Size": 100}],
            "IsTruncated": False,
        }
        self.run_app()
        self.app.button(key="new_r2:r2_browser:load").click()
        self.run_app()
        keys = []
        for index in (0, 10):
            image = f"https://images.example.test/trivia/{index}.webp"
            checkbox_key = "new_r2:r2_browser:select:" + sha256(image.encode()).hexdigest()[:16]
            keys.append(checkbox_key)
            self.app.checkbox(key=checkbox_key).check()
            self.run_app()
        self.app.button(key="new_r2:r2_browser:add_selected").click()
        self.run_app()
        self.assertTrue(any("合計10枚" in error.value for error in self.app.error))
        self.assertEqual(list(self.app.session_state["new_image_gallery"]), gallery)
        self.assertTrue(self.app.checkbox(key=keys[1]).value)
        self.app.checkbox(key=keys[1]).uncheck()
        self.run_app()
        self.app.button(key="new_r2:r2_browser:add_selected").click()
        self.run_app()
        self.assertEqual(list(self.app.session_state["new_image_gallery"]), gallery)
        self.assertTrue(self.app.button(key="new_r2:r2_browser:add_selected").disabled)
        self.r2.put_object.assert_not_called()

    def test_editing_text_preserves_gallery_and_reordering_changes_cover(self):
        row_id = self.seed_normal()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.text_input(key=f"edit_{row_id}_title").set_value("写真を保持して更新")
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(len(db.get(self.models.Trivia, row_id).image_urls), 2)
        self.app.button(key=f"edit_{row_id}_image_before_1").click()
        self.run_app()
        self.assertTrue(self.app.text_input(key=f"edit_{row_id}_image_url").value.endswith("/b.webp"))
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertEqual(item.image_urls, ["https://images.example.test/trivia/b.webp", "https://images.example.test/trivia/a.webp"])
            self.assertEqual(item.image_url, item.image_urls[0])

    def test_r2_limit_does_not_count_a_key_alias_as_an_extra_photo(self):
        row_id = self.seed_normal()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            item.image_urls = [f"trivia/{i}.webp" for i in range(10)]
            item.image_url = item.image_urls[0]
            db.commit()
        self.r2.list_objects_v2.return_value = {
            "Contents": [{"Key": f"trivia/{i}.webp", "Size": 100} for i in range(11)], "IsTruncated": False,
        }
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.button(key=f"edit_{row_id}_r2:r2_browser:load").click()
        self.run_app()
        self.app.button(key=f"edit_{row_id}_r2:r2_browser:choose:0").click()
        self.run_app()
        self.assertFalse(any("10枚" in error.value for error in self.app.error))
        self.app.button(key=f"edit_{row_id}_r2:r2_browser:choose:10").click()
        self.run_app()
        self.assertTrue(any("10枚" in error.value for error in self.app.error))
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertEqual(len(item.image_urls), 10)
            self.assertEqual(item.image_url, "https://images.example.test/trivia/0.webp")
        self.r2.put_object.assert_not_called()

    def test_removing_every_photo_clears_legacy_cover_and_gallery(self):
        row_id = self.seed_normal()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        for _ in range(2):
            self.app.button(key=f"edit_{row_id}_image_remove_0").click()
            self.run_app()
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertEqual(item.image_urls, [])
            self.assertIsNone(item.image_url)
        self.r2.delete_object.assert_not_called()

    def test_fixing_a_broken_legacy_reference_keeps_other_photos(self):
        row_id = self.seed_normal()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            item.image_urls = [item.image_urls[0], "https://", item.image_urls[1]]
            db.commit()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.button(key=f"edit_{row_id}_image_remove_1").click()
        self.run_app()
        self.app.button(key=f"update_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.get(self.models.Trivia, row_id).image_urls, [
                "https://images.example.test/trivia/a.webp", "https://images.example.test/trivia/b.webp",
            ])

    def test_normal_to_map_registration_copies_all_photos(self):
        row_id = self.seed_normal()
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        prefix = f"edit_map_{row_id}"
        self.app.text_input(key=f"{prefix}_prefecture").set_value("東京都")
        self.app.text_input(key=f"{prefix}_address").set_value("東京タワー")
        self.app.number_input(key=f"{prefix}_latitude").set_value(35.6586)
        self.app.number_input(key=f"{prefix}_longitude").set_value(139.7454)
        self.app.button(key=f"map_register_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(db.query(self.models.MapTrivia).one().image_urls, db.get(self.models.Trivia, row_id).image_urls)
            self.assertEqual(db.query(self.models.MapTrivia).one().image_sources, db.get(self.models.Trivia, row_id).image_sources)

    def test_url_batch_addition_deduplicates_and_rejects_over_limit(self):
        self.run_app()
        self.app.text_area(key="new_image_extra_urls").set_value("trivia/a.webp\n trivia/b.webp \ntrivia/a.webp")
        self.app.button(key="new_image_add_urls").click()
        self.run_app()
        self.app.text_area(key="new_image_extra_urls").set_value("\n".join(f"trivia/extra-{i}.webp" for i in range(9)))
        self.app.button(key="new_image_add_urls").click()
        self.run_app()
        self.assertTrue(any("10枚" in error.value for error in self.app.error))
        self.app.text_input(key="new_title").set_value("上限エラー後も登録")
        self.app.text_area(key="new_content").set_value("有効な2枚は残ります。")
        self.app.button(key="new_submit").click()
        self.run_app()
        with self.sessions() as db:
            self.assertEqual(len(db.query(self.models.Trivia).one().image_urls), 2)

    def image_file(self, name, color):
        stream = BytesIO()
        Image.new("RGB", (40, 20), color).save(stream, format="PNG")
        stream.name = name
        stream.type = "image/png"
        stream.seek(0)
        return stream

    def test_multiple_uploads_are_reused_after_database_save_failure(self):
        import streamlit as st
        files = [self.image_file("first.png", "red"), self.image_file("second.png", "blue")]
        original = st.file_uploader
        with patch("streamlit.file_uploader", side_effect=lambda *args, **kwargs:
                   files if kwargs.get("key") == "new_image_upload" else original(*args, **kwargs)):
            self.run_app()
            self.app.text_input(key="new_title").set_value("2枚アップロード")
            self.app.text_area(key="new_content").set_value("保存に失敗しても再送しません。")
            with patch("admin_views.create_manual_trivia", side_effect=RuntimeError("simulated DB failure")):
                self.app.button(key="new_submit").click()
                self.run_app()
            self.assertEqual(self.r2.put_object.call_count, 2)
            self.app.button(key="new_submit").click()
            self.run_app()
        self.assertEqual(self.r2.put_object.call_count, 2)
        with self.sessions() as db:
            item = db.query(self.models.Trivia).one()
            self.assertEqual(len(item.image_urls), 2)
            self.assertEqual(item.image_url, item.image_urls[0])

    def test_cropping_second_photo_keeps_cover_and_other_photos(self):
        row_id = self.seed_normal()
        source = self.image_file("source.png", "green")
        self.r2.get_object.return_value = {"Body": source, "ContentType": "image/png"}
        self.run_app()
        self.open_section("🛠️ 管理・編集")
        self.app.selectbox(key=f"edit_{row_id}_image_selected").set_value(1)
        self.app.selectbox(key=f"edit_{row_id}_image_crop").set_value("正方形")
        self.run_app()
        self.app.button(key=f"recrop_edit_{row_id}").click()
        self.run_app()
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertEqual(item.image_urls[0], "https://images.example.test/trivia/a.webp")
            self.assertNotEqual(item.image_urls[1], "https://images.example.test/trivia/b.webp")
            self.assertEqual(item.image_url, item.image_urls[0])
        self.assertEqual(self.r2.put_object.call_count, 1)
        with self.sessions() as db:
            item = db.get(self.models.Trivia, row_id)
            self.assertEqual(item.image_sources, {item.image_urls[1]: "撮影：山田太郎"})
        with Image.open(BytesIO(self.r2.put_object.call_args.kwargs["Body"])) as image:
            self.assertEqual(image.width, image.height)


if __name__ == "__main__":
    unittest.main()
