from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from frikshun_creator.services.meta_token_manager import MetaTokenManager


class MetaTokenManagerTest(unittest.TestCase):
    def response(self, payload, ok=True, reason="OK"):
        return SimpleNamespace(ok=ok, reason=reason, json=lambda: payload, text=str(payload))

    def test_upgrade_exchanges_user_token_derives_page_token_and_updates_env(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "META_LONG_LIVED_USER_ACCESS_TOKEN=old-user\n"
                "INSTAGRAM_ACCESS_TOKEN=short-user\n"
                "FACEBOOK_PAGE_ACCESS_TOKEN=short-page\n"
                "UNCHANGED=value\n",
                encoding="utf-8",
            )
            manager = MetaTokenManager("app", "secret", "page", env_path=env_path)
            responses = [
                self.response({"access_token": "long-user", "token_type": "bearer", "expires_in": 3600}),
                self.response({"id": "page", "name": "Chloe Katastrophe", "access_token": "long-page"}),
            ]

            with patch("frikshun_creator.services.meta_token_manager.requests.get", side_effect=responses):
                result = manager.upgrade("short-user")

            saved = env_path.read_text(encoding="utf-8")
            self.assertIn("META_LONG_LIVED_USER_ACCESS_TOKEN=long-user", saved)
            self.assertIn("INSTAGRAM_ACCESS_TOKEN=long-user", saved)
            self.assertIn("FACEBOOK_PAGE_ACCESS_TOKEN=long-page", saved)
            self.assertIn("UNCHANGED=value", saved)
            self.assertEqual("Chloe Katastrophe", result["page_name"])


if __name__ == "__main__":
    unittest.main()
