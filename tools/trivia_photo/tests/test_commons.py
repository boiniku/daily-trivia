import unittest
from unittest.mock import MagicMock

from trivia_photo.commons import Commons


class CommonsDownloadTests(unittest.TestCase):
    def client(self):
        client = Commons("test")
        client.session = MagicMock()
        return client

    def response(self, data=b"image", redirect=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = redirect is not None
        response.headers = {"Location": redirect} if redirect else {}
        response.iter_content.return_value = [data]
        return response

    def test_new_thumbnail_host_and_original_host(self):
        for host in ("upload.wikimedia.org", "thumb.wikimedia.org"):
            with self.subTest(host=host):
                client = self.client()
                client.session.get.return_value = self.response()
                self.assertEqual(client.download(f"https://{host}/image.jpg"), b"image")

    def test_redirect_to_new_thumbnail_host(self):
        client = self.client()
        client.session.get.side_effect = [
            self.response(redirect="https://thumb.wikimedia.org/image.jpg"),
            self.response(),
        ]
        self.assertEqual(client.download("https://upload.wikimedia.org/image.jpg"), b"image")

    def test_untrusted_redirect_is_rejected_before_request(self):
        client = self.client()
        client.session.get.return_value = self.response(redirect="https://example.com/image.jpg")
        with self.assertRaises(ValueError):
            client.download("https://thumb.wikimedia.org/image.jpg")
        self.assertEqual(client.session.get.call_count, 1)

    def test_unsafe_urls_are_rejected_without_request(self):
        for url in (
            "http://thumb.wikimedia.org/image.jpg",
            "https://thumb.wikimedia.org.example.com/image.jpg",
            "https://user:password@thumb.wikimedia.org/image.jpg",
            "https://example.com/image.jpg",
        ):
            with self.subTest(url=url):
                client = self.client()
                with self.assertRaises(ValueError):
                    client.download(url)
                client.session.get.assert_not_called()
