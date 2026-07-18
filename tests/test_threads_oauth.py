import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from frikshun_creator.services.threads_oauth import ThreadsOAuth


class ThreadsOAuthTest(unittest.TestCase):
    def test_begin_builds_authorization_url(self):
        oauth = ThreadsOAuth(
            app_id="app-id",
            app_secret="secret",
            redirect_uri="https://example.test/oauth/threads/callback",
        )
        url, state = oauth.begin()
        query = parse_qs(urlparse(url).query)
        self.assertEqual(["app-id"], query["client_id"])
        self.assertEqual(["code"], query["response_type"])
        self.assertIn("threads_content_publish", query["scope"][0])
        self.assertTrue(state)

    def test_exchange_stores_long_lived_token_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "threads.json"
            oauth = ThreadsOAuth(
                app_id="app-id",
                app_secret="secret",
                redirect_uri="https://example.test/oauth/threads/callback",
                token_path=path,
            )
            short_response = unittest.mock.Mock(ok=True)
            short_response.json.return_value = {"access_token": "short-token", "user_id": "123"}
            long_response = unittest.mock.Mock(ok=True)
            long_response.json.return_value = {
                "access_token": "long-token",
                "token_type": "bearer",
                "expires_in": 5184000,
            }
            with patch("frikshun_creator.services.threads_oauth.requests.post", return_value=short_response) as post:
                with patch("frikshun_creator.services.threads_oauth.requests.get", return_value=long_response) as get:
                    saved = oauth.exchange("code-1")
            self.assertEqual("code-1", post.call_args.kwargs["params"]["code"])
            self.assertEqual("short-token", get.call_args.kwargs["params"]["access_token"])
            self.assertEqual("long-token", saved["access_token"])
            self.assertEqual("123", oauth.load_tokens()["user_id"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_refresh_updates_stored_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "threads.json"
            oauth = ThreadsOAuth(
                app_id="app-id",
                app_secret="secret",
                redirect_uri="https://example.test/oauth/threads/callback",
                token_path=path,
            )
            oauth.save_tokens(
                {
                    "access_token": "long-token",
                    "long_lived_access_token": "long-token",
                    "user_id": "123",
                    "expires_in": 5184000,
                }
            )
            response = unittest.mock.Mock(ok=True)
            response.json.return_value = {"access_token": "longer-token", "expires_in": 5184000}
            with patch("frikshun_creator.services.threads_oauth.requests.get", return_value=response):
                saved = oauth.refresh()
            self.assertEqual("longer-token", saved["access_token"])
            self.assertEqual("longer-token", oauth.load_tokens()["long_lived_access_token"])


if __name__ == "__main__":
    unittest.main()
