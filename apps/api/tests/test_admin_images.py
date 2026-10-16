from io import BytesIO
import unittest
from unittest.mock import Mock

from PIL import Image

from services.admin_images import (
    build_unique_image_key,
    image_preview_url,
    image_url_for_key,
    list_r2_images,
    normalize_image_reference,
    optimize_image_upload,
    r2_object_key,
    render_r2_image_browser,
)


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.clicked = set()
        self.previews = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def expander(self, *args, **kwargs):
        return self

    def spinner(self, *args, **kwargs):
        return self

    def columns(self, count):
        return [self] * count

    def text_input(self, label, value="", *, key, **kwargs):
        return self.session_state.setdefault(key, value)

    def button(self, label, *, key, disabled=False, **kwargs):
        return key in self.clicked and not disabled

    def caption(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def image(self, value, **kwargs):
        self.previews.append(value)

    def rerun(self):
        pass


class AdminImageReferenceTests(unittest.TestCase):
    def test_extracts_only_own_public_url_without_query_and_decodes_key(self):
        base = "https://images.example.test/media"
        self.assertEqual(
            r2_object_key("https://images.example.test/media/folder/a%20b.jpg?token=secret#preview", base),
            "folder/a b.jpg",
        )
        self.assertEqual(r2_object_key("https://images.example.test/media-other/a.jpg", base), "")
        self.assertEqual(r2_object_key("https://images.example.test.evil/media/a.jpg", base), "")
        self.assertEqual(r2_object_key("https://other.example.test/media/a.jpg", base), "")
        self.assertEqual(r2_object_key("https://images.example.test/media/%2e%2e/a.jpg", base), "")
        self.assertEqual(r2_object_key("https://images.example.test/media/a.jpg"), "")
        self.assertEqual(r2_object_key("https://[invalid/a.jpg", base), "")

    def test_bare_keys_are_safe_and_public_urls_encode_reserved_characters(self):
        self.assertEqual(r2_object_key(" /trivia/a b.jpg "), "trivia/a b.jpg")
        self.assertEqual(r2_object_key("../a.jpg"), "")
        self.assertEqual(r2_object_key("data:image/png;base64,a"), "")
        self.assertEqual(r2_object_key("//other.example.test/a.jpg"), "")
        self.assertEqual(
            image_url_for_key("候補/a b#1.jpg", "https://images.example.test/"),
            "https://images.example.test/%E5%80%99%E8%A3%9C/a%20b%231.jpg",
        )

    def test_reference_validation_rejects_unsupported_urls(self):
        for value in ["javascript:alert(1)", "data:image/png;base64,a", "https:///image.jpg", "//example.test/a.jpg", "https://user:password@example.test/a.jpg", "https://[invalid/a.jpg", "https://example.test:invalid/a.jpg", "https://example. test/a.jpg", "https://example.test/a\nb.jpg"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_image_reference(value)
        self.assertEqual(normalize_image_reference(" https://example.test/a.jpg?x=1 "), "https://example.test/a.jpg?x=1")
        self.assertEqual(normalize_image_reference("trivia/a.jpg"), "trivia/a.jpg")
        self.assertEqual(normalize_image_reference(""), "")

    def test_upload_keys_are_unique_and_retain_namespace(self):
        keys = {build_unique_image_key("/pending/", 123, ".webp") for _ in range(100)}
        self.assertEqual(len(keys), 100)
        for key in keys:
            self.assertRegex(key, r"^pending/123-\d{20}-[0-9a-f]{12}\.webp$")


class AdminImageProcessingTests(unittest.TestCase):
    def make_upload(self, image, image_format="PNG", **save_options):
        stream = BytesIO()
        image.save(stream, format=image_format, **save_options)
        stream.seek(0)
        # Filename and client-supplied MIME must not determine the actual type.
        stream.name = "misleading.jpg"
        stream.type = "image/jpeg"
        return stream

    def test_intentional_crop_is_kept_even_when_encoded_image_is_larger(self):
        original = self.make_upload(Image.new("RGBA", (2, 1), (220, 10, 40, 120)), optimize=True)
        result, extension, content_type = optimize_image_upload(original, 1)
        self.assertGreater(len(result.getvalue()), len(original.getvalue()))
        with Image.open(result) as image:
            self.assertEqual(image.size, (1, 1))
        self.assertEqual((extension, content_type), (".webp", "image/webp"))

    def test_resize_and_exif_orientation_are_applied_before_encoding(self):
        image = Image.new("RGB", (60, 20), "red")
        exif = image.getexif()
        exif[274] = 6
        original = self.make_upload(image, "JPEG", exif=exif)
        result, _, _ = optimize_image_upload(original, max_dimension=30)
        with Image.open(result) as image:
            self.assertEqual(image.size, (10, 30))

    def test_crop_preserves_palette_transparency(self):
        image = Image.new("P", (20, 10), 0)
        image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        original = self.make_upload(image, transparency=0)
        result, _, _ = optimize_image_upload(original, 1)
        with Image.open(result) as processed:
            self.assertEqual(processed.getpixel((0, 0))[-1], 0)

    def test_rejects_invalid_oversized_and_empty_uploads(self):
        for stream, options in [
            (BytesIO(b"not an image"), {}),
            (BytesIO(b""), {}),
            (BytesIO(b"12345"), {"max_upload_bytes": 4}),
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                optimize_image_upload(stream, **options)
        with self.assertRaises(ValueError):
            optimize_image_upload(self.make_upload(Image.new("RGB", (10, 10))), float("nan"))

    def test_gif_animation_is_preserved_without_crop(self):
        original = self.make_upload(Image.new("RGB", (10, 10), "red"), "GIF", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")], duration=100, loop=0)
        result, extension, content_type = optimize_image_upload(original)
        self.assertEqual(result.getvalue(), original.getvalue())
        self.assertEqual((extension, content_type), (".gif", "image/gif"))


class R2ImageListingTests(unittest.TestCase):
    def test_filters_image_keys_and_continues_without_losing_results(self):
        client = Mock()
        client.list_objects_v2.side_effect = [
            {"Contents": [{"Key": "pending/cat.JPG", "Size": 100}, {"Key": "pending/readme.txt", "Size": 10}], "IsTruncated": True, "NextContinuationToken": "page2"},
            {"Contents": [{"Key": "pending/cat2.webp", "Size": 200}], "IsTruncated": True, "NextContinuationToken": "page3"},
        ]
        result = list_r2_images(client, "bucket", prefix="pending/", search="CAT", page_size=2)
        self.assertEqual([image.key for image in result.images], ["pending/cat.JPG", "pending/cat2.webp"])
        self.assertEqual(result.next_token, "page3")
        self.assertEqual(result.scanned_count, 3)
        self.assertEqual(client.list_objects_v2.call_args_list[1].kwargs, {"Bucket": "bucket", "Prefix": "pending/", "MaxKeys": 1, "ContinuationToken": "page2"})

    def test_search_scanning_has_a_limit_and_can_resume(self):
        client = Mock()
        client.list_objects_v2.side_effect = [
            {"Contents": [{"Key": "other.jpg"}], "IsTruncated": True, "NextContinuationToken": "continue"},
            {"Contents": [{"Key": "match.jpg", "Size": 20}], "IsTruncated": False},
        ]
        result = list_r2_images(client, "bucket", search="match", page_size=1, max_scan_pages=1)
        self.assertEqual(result.images, ())
        self.assertEqual(result.next_token, "continue")
        following = list_r2_images(client, "bucket", search="match", continuation_token=result.next_token, page_size=1)
        self.assertEqual(following.images[0].key, "match.jpg")
        self.assertIsNone(following.next_token)

    def test_empty_bucket_and_repeated_continuation_token(self):
        client = Mock()
        client.list_objects_v2.return_value = {}
        self.assertEqual(list_r2_images(client, "bucket").images, ())
        client.list_objects_v2.return_value = {"IsTruncated": True, "NextContinuationToken": "same"}
        with self.assertRaises(RuntimeError):
            list_r2_images(client, "bucket", continuation_token="same")

    def test_skips_noncanonical_or_unsafe_object_keys(self):
        client = Mock()
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": "../outside.jpg"}, {"Key": "/leading.jpg"}, {"Key": "good.jpg", "Size": 20}],
            "IsTruncated": False,
        }
        self.assertEqual([image.key for image in list_r2_images(client, "bucket").images], ["good.jpg"])

    def test_signed_url_is_for_preview_only(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://private.example.test/a?signature=temporary"
        self.assertEqual(image_preview_url(client, "bucket", "pending/a.jpg"), "https://private.example.test/a?signature=temporary")
        client.generate_presigned_url.assert_called_once_with("get_object", Params={"Bucket": "bucket", "Key": "pending/a.jpg"}, ExpiresIn=3600)
        self.assertEqual(image_url_for_key("pending/a.jpg"), "pending/a.jpg")


class R2ImageBrowserTests(unittest.TestCase):
    def render(self, st, client_factory):
        return render_r2_image_browser(st, key="new", client_factory=client_factory, bucket="bucket", default_prefix="pending/", target_key="image_url")

    def test_no_client_or_network_before_explicit_load(self):
        st = FakeStreamlit()
        factory = Mock()
        self.assertIsNone(self.render(st, factory))
        factory.assert_not_called()

    def test_load_preview_select_and_clear_durable_key(self):
        st = FakeStreamlit()
        client = Mock()
        client.list_objects_v2.return_value = {"Contents": [{"Key": "pending/a.jpg", "Size": 200}], "IsTruncated": False}
        client.generate_presigned_url.return_value = "https://private.example.test/a?signature=temporary"
        factory = Mock(return_value=client)
        st.clicked = {"new:r2_browser:load"}
        self.render(st, factory)
        self.assertEqual(st.previews, ["https://private.example.test/a?signature=temporary"])
        st.clicked = {"new:r2_browser:choose:0"}
        self.assertEqual(self.render(st, factory), "pending/a.jpg")
        self.assertEqual(st.session_state["image_url"], "pending/a.jpg")
        factory.assert_called_once()
        client.list_objects_v2.assert_called_once()
        st.clicked = {"new:r2_browser:clear"}
        self.assertIsNone(self.render(st, factory))
        self.assertEqual(st.session_state["image_url"], "")
        self.assertFalse(client.delete_object.called)
        self.assertFalse(client.put_object.called)

    def test_previous_page_uses_cache_and_changed_query_hides_old_results(self):
        st = FakeStreamlit()
        client = Mock()
        client.list_objects_v2.side_effect = [
            {"Contents": [{"Key": f"pending/{index}.jpg", "Size": 10} for index in range(12)], "IsTruncated": True, "NextContinuationToken": "next"},
            {"Contents": [{"Key": "pending/end.jpg", "Size": 10}], "IsTruncated": False},
        ]
        factory = Mock(return_value=client)
        st.clicked = {"new:r2_browser:load"}
        self.render(st, factory)
        st.clicked = {"new:r2_browser:next"}
        self.render(st, factory)
        self.assertEqual(client.list_objects_v2.call_count, 2)
        st.clicked = {"new:r2_browser:previous"}
        self.render(st, factory)
        self.assertEqual(client.list_objects_v2.call_count, 2)
        st.session_state["new:r2_browser:search"] = "new query"
        st.previews.clear()
        st.clicked = set()
        self.render(st, factory)
        self.assertEqual(st.previews, [])
        self.assertEqual(client.list_objects_v2.call_count, 2)


if __name__ == "__main__":
    unittest.main()
