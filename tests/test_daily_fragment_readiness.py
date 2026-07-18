import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frikshun_creator import create_app
from frikshun_creator.services.daily_fragment_readiness import DailyFragmentReadinessChecker


class DailyFragmentReadinessTest(unittest.TestCase):
    def make_app(self, **overrides):
        config = {
            "TESTING": True,
            "AUTO_CREATE_TABLES": False,
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "OPENAI_API_KEY": "key",
            "FACEBOOK_DRY_RUN": False,
            "FACEBOOK_PAGE_ID": "page_1",
            "FACEBOOK_PAGE_ACCESS_TOKEN": "fb-token",
            "INSTAGRAM_DRY_RUN": False,
            "INSTAGRAM_USER_ID": "ig_1",
            "INSTAGRAM_ACCESS_TOKEN": "ig-token",
            "THREADS_DRY_RUN": False,
            "THREADS_ACCESS_TOKEN": "threads-token",
            "X_DRY_RUN": False,
            "X_USERNAME": "chloekatastroph",
            "X_CONSUMER_KEY": "x-key",
            "X_SECRET_KEY": "x-secret",
            "X_ACCESS_TOKEN": "x-token",
            "X_ACCESS_TOKEN_SECRET": "x-token-secret",
            "FANVUE_DRY_RUN": False,
            "FANVUE_CLIENT_ID": "fanvue-client",
            "FANVUE_CLIENT_SECRET": "fanvue-secret",
            "FANVUE_REDIRECT_URI": "https://example.test/callback",
            "FANVUE_AUDIENCE": "followers-and-subscribers",
            "S3_MEDIA_BUCKET": "bucket",
        }
        config.update(overrides)
        return create_app(config)

    def test_run_reports_ready_when_all_checks_pass(self):
        app = self.make_app()
        checker = DailyFragmentReadinessChecker(app)

        with app.app_context(), \
            patch.object(checker, "check_facebook_remote", return_value=SimpleNamespace(name="facebook_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_instagram_remote", return_value=SimpleNamespace(name="instagram_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_threads_remote", return_value=SimpleNamespace(name="threads_remote", ok=True, detail="ready")), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity", return_value={"data": {"id": "1", "username": "chloekatastroph"}}), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            checks = checker.run()

        self.assertTrue(all(check.ok for check in checks), checks)

    def test_run_flags_missing_openai_key(self):
        app = self.make_app(OPENAI_API_KEY="")
        checker = DailyFragmentReadinessChecker(app)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
            app.app_context(), \
            patch.object(checker, "check_facebook_remote", return_value=SimpleNamespace(name="facebook_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_instagram_remote", return_value=SimpleNamespace(name="instagram_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_threads_remote", return_value=SimpleNamespace(name="threads_remote", ok=True, detail="ready")), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity"), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            checks = checker.run()

        openai = next(check for check in checks if check.name == "openai")
        self.assertFalse(openai.ok)
        self.assertIn("missing", openai.detail.lower())

    def test_run_flags_x_remote_publisher_failure(self):
        app = self.make_app()
        checker = DailyFragmentReadinessChecker(app)

        with app.app_context(), \
            patch.object(checker, "check_facebook_remote", return_value=SimpleNamespace(name="facebook_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_instagram_remote", return_value=SimpleNamespace(name="instagram_remote", ok=True, detail="ready")), \
            patch.object(checker, "check_threads_remote", return_value=SimpleNamespace(name="threads_remote", ok=True, detail="ready")), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity", side_effect=ValueError("Bad authentication data")), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            checks = checker.run()

        x_remote = next(check for check in checks if check.name == "x_remote")
        self.assertFalse(x_remote.ok)
        self.assertIn("authentication", x_remote.detail.lower())
        self.assertIn("facebook_remote", {check.name for check in checks})
        self.assertIn("instagram_remote", {check.name for check in checks})
        self.assertIn("threads_remote", {check.name for check in checks})


if __name__ == "__main__":
    unittest.main()
