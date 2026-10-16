from __future__ import annotations

import json
import re
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import test_workflow as fixtures
from trivia_photo.config import Settings
from trivia_photo.review import serve
from trivia_photo.state import State
from trivia_photo.workflow import Workflow


class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.temp.name))
        self.neon = fixtures.FakeNeon()
        settings = Settings(database_url="postgresql://user:password@project.neon.tech/neondb")
        self.workflow = Workflow(settings, self.state, self.neon, fixtures.FakeCommons(), fixtures.FakeStorage())
        self.batch = self.workflow.collect(1)["batch"]
        fixtures.stage_fixture(self.workflow, self.batch, 1)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        ready = threading.Event()

        def factory(address, handler):
            self.server = ThreadingHTTPServer(address, handler)
            ready.set()
            return self.server

        self.patcher = patch("trivia_photo.review.ThreadingHTTPServer", side_effect=factory)
        self.patcher.start()
        self.thread = threading.Thread(target=serve, args=(self.workflow, self.batch, self.port), daemon=True)
        self.thread.start()
        self.assertTrue(ready.wait(5))
        self.url = f"http://127.0.0.1:{self.port}"
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.patcher.stop()
        self.temp.cleanup()

    def get(self, path="/", headers=None):
        return self.opener.open(Request(self.url + path, headers=headers or {}), timeout=5)

    def test_page_and_image_display_staged_photo(self):
        with self.get() as response:
            page = response.read().decode()
            self.assertIn("アプリには未反映", page)
            self.assertIn("この写真を承認", page)
            self.assertIn("CC BY 4.0", page)
            self.assertIn("アプリと同じ16:9表示", page)
            self.assertIn("元の写真全体を見る", page)
            self.assertIn("aspect-ratio: 16 / 9", page)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.get(f"/image/{self.batch}/1.webp") as response:
            self.assertEqual(response.headers["Content-Type"], "image/webp")
            self.assertEqual(response.read(), self.workflow.asset_bytes(self.state.get(self.batch, 1)["asset"]))

    def test_full_source_is_available_for_crop_comparison(self):
        with self.get(f"/source/{self.batch}/1.webp") as response:
            self.assertEqual(response.read(), self.workflow.asset_bytes(self.state.get(self.batch, 1)["asset"]["source"]))

    def test_no_token_cannot_approve(self):
        request = Request(self.url + "/api/decision", data=json.dumps({"trivia_id": 1, "decision": "approve"}).encode(), method="POST")
        with self.assertRaises(HTTPError) as error:
            self.opener.open(request, timeout=5)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(self.state.get(self.batch, 1)["status"], "staged")

    def test_browser_approval_only_changes_local_state(self):
        with self.get() as response:
            page = response.read().decode()
        token = json.loads(re.search(r"const context = (\{.*?\});", page).group(1))["token"]
        request = Request(self.url + "/api/decision", data=json.dumps({"trivia_id": 1, "decision": "approve"}).encode(), method="POST",
                          headers={"Content-Type": "application/json", "X-Trivia-Photo-Token": token, "Origin": self.url})
        with self.opener.open(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.state.get(self.batch, 1)["status"], "approved")
        self.assertEqual(self.neon.writes, [])

    def test_other_host_cannot_read_review(self):
        with self.assertRaises(HTTPError) as error:
            self.get(headers={"Host": "attacker.example.com"})
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
