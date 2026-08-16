import unittest
from unittest.mock import patch

import render_release


class RenderReleaseTests(unittest.TestCase):
    def test_configure_migrates_old_backend_layout(self):
        current = {
            "type": "web_service",
            "branch": "main",
            "rootDir": "backend",
        }
        configured = {
            "type": "web_service",
            "branch": "main",
            "rootDir": "apps/api",
            "serviceDetails": {
                "healthCheckPath": "/health",
                "envSpecificDetails": {
                    "buildCommand": render_release.EXPECTED_BUILD_COMMAND,
                    "startCommand": render_release.EXPECTED_START_COMMAND,
                },
            },
        }
        with patch.object(render_release, "request_json", side_effect=[current, {}, configured]) as request:
            render_release.configure_production_service("srv-test", "secret")

        patch_request = request.call_args_list[1]
        self.assertEqual(patch_request.kwargs["method"], "PATCH")
        self.assertEqual(patch_request.kwargs["body"]["rootDir"], "apps/api")
        self.assertEqual(patch_request.kwargs["body"]["autoDeploy"], "no")

    def test_update_prompt_refuses_before_render_when_store_is_not_public(self):
        args = type(
            "Args",
            (),
            {
                "app_store_id": "6758872525",
                "version": "1.1.0",
                "service_id": "srv-test",
                "token": "secret",
                "health_url": "https://example.com/health",
            },
        )()
        with patch.object(render_release, "public_app_store_version", return_value="1.0.5"), patch.object(
            render_release, "request_json"
        ) as request:
            with self.assertRaisesRegex(RuntimeError, "Refusing to enable"):
                render_release.activate_update_prompt(args)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
