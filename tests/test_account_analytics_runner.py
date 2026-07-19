from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.services.account_analytics_runner import AccountAnalyticsRunner


class AccountAnalyticsRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.youtube_token = f"{self.tempdir.name}/youtube.json"
        with open(self.youtube_token, "w", encoding="utf-8") as token_file:
            token_file.write('{"access_token":"token"}')
        self.app = create_app({
            "TESTING": True,
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "YOUTUBE_CLIENT_ID": "client",
            "YOUTUBE_CLIENT_SECRET": "secret",
            "YOUTUBE_REDIRECT_URI": "https://example.test/callback",
            "YOUTUBE_TOKEN_PATH": self.youtube_token,
            "TIKTOK_TOKEN_PATH": f"{self.tempdir.name}/missing-tiktok.json",
        })

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("frikshun_creator.services.account_analytics_runner.AccountAnalyticsSync")
    def test_runs_authorized_platform_and_skips_missing_grant(self, sync_class):
        sync_class.return_value.run.return_value.errors = []
        with self.app.app_context():
            result = AccountAnalyticsRunner(get_session(), self.app.config).run()

        self.assertIn("youtube", result.platform_results)
        self.assertEqual(
            "OAuth authorization has not been completed",
            result.skipped["tiktok"],
        )
        sync_class.assert_called_once()


if __name__ == "__main__":
    unittest.main()
