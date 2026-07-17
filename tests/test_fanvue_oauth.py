import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from frikshun_creator.services.fanvue_oauth import FanvueOAuth


class FanvueOAuthTest(unittest.TestCase):
    def test_begin_builds_pkce_authorization_url(self):
        oauth = FanvueOAuth("client", "secret", "https://example.test/callback")
        url, state, verifier = oauth.begin()
        query = parse_qs(urlparse(url).query)
        self.assertEqual(["client"], query["client_id"])
        self.assertEqual(["S256"], query["code_challenge_method"])
        self.assertIn("write:post", query["scope"][0])
        self.assertTrue(state)
        self.assertGreaterEqual(len(verifier), 43)

    def test_exchange_stores_tokens_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tokens.json"
            oauth = FanvueOAuth("client", "secret", "https://example.test/callback", path)
            response = unittest.mock.Mock(ok=True)
            response.json.return_value = {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
            }
            with patch("frikshun_creator.services.fanvue_oauth.requests.post", return_value=response) as post:
                saved = oauth.exchange("code", "verifier")
            self.assertEqual(("client", "secret"), post.call_args.kwargs["auth"])
            self.assertNotIn("client_secret", post.call_args.kwargs["data"])
            self.assertEqual("access", saved["access_token"])
            self.assertEqual("refresh", oauth.load_tokens()["refresh_token"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
