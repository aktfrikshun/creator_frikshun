import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from frikshun_creator.services.tiktok_oauth import TikTokOAuth


class TikTokOAuthTest(unittest.TestCase):
    def test_begin_requests_analytics_scopes(self):
        oauth = TikTokOAuth("key", "secret", "https://example.test/callback")
        url, state = oauth.begin()
        self.assertIn("client_key=key", url)
        self.assertIn("user.info.stats", url)
        self.assertIn("video.list", url)
        self.assertTrue(state)

    def test_exchange_saves_refreshable_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Mock(ok=True)
            response.json.return_value = {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 86400,
                "open_id": "chloe-open-id",
            }
            oauth = TikTokOAuth(
                "key", "secret", "https://example.test/callback", Path(directory) / "token.json"
            )
            with patch("frikshun_creator.services.tiktok_oauth.requests.post", return_value=response):
                saved = oauth.exchange("code")
            self.assertEqual("refresh", saved["refresh_token"])
            self.assertTrue(saved["expires_at"])
            self.assertEqual("access", oauth.load_tokens()["access_token"])


if __name__ == "__main__":
    unittest.main()
