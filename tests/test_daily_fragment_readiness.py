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

        ok_response = SimpleNamespace(ok=True, json=lambda: {"id": "123", "name": "Chloe", "username": "chloe"})

        with app.app_context(), \
            patch("frikshun_creator.services.daily_fragment_readiness.boto3.Session") as session_cls, \
            patch("frikshun_creator.services.daily_fragment_readiness.requests.get", return_value=ok_response), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity", return_value={"data": {"id": "1", "username": "chloekatastroph"}}), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            session_cls.return_value.get_credentials.return_value = object()
            checks = checker.run()

        self.assertTrue(all(check.ok for check in checks), checks)

    def test_run_flags_missing_openai_key(self):
        app = self.make_app(OPENAI_API_KEY="")
        checker = DailyFragmentReadinessChecker(app)

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
            app.app_context(), \
            patch("frikshun_creator.services.daily_fragment_readiness.boto3.Session") as session_cls, \
            patch("frikshun_creator.services.daily_fragment_readiness.requests.get"), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity"), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            session_cls.return_value.get_credentials.return_value = object()
            checks = checker.run()

        openai = next(check for check in checks if check.name == "openai")
        self.assertFalse(openai.ok)
        self.assertIn("missing", openai.detail.lower())

    def test_run_flags_remote_publisher_failures(self):
        app = self.make_app()
        checker = DailyFragmentReadinessChecker(app)
        facebook_fail = SimpleNamespace(
            ok=False,
            reason="Unauthorized",
            json=lambda: {"error": {"message": "Invalid OAuth access token."}},
        )
        instagram_ok = SimpleNamespace(ok=True, json=lambda: {"id": "ig_1", "username": "chloe"})

        with app.app_context(), \
            patch("frikshun_creator.services.daily_fragment_readiness.boto3.Session") as session_cls, \
            patch("frikshun_creator.services.daily_fragment_readiness.requests.get", side_effect=[facebook_fail, instagram_ok]), \
            patch("frikshun_creator.services.daily_fragment_readiness.XAdapter.verify_identity", side_effect=ValueError("Bad authentication data")), \
            patch("frikshun_creator.services.fanvue_oauth.FanvueOAuth.access_token", return_value="fanvue-token"):
            session_cls.return_value.get_credentials.return_value = object()
            checks = checker.run()

        facebook = next(check for check in checks if check.name == "facebook_remote")
        x_remote = next(check for check in checks if check.name == "x_remote")
        self.assertFalse(facebook.ok)
        self.assertIn("oauth", facebook.detail.lower())
        self.assertFalse(x_remote.ok)
        self.assertIn("authentication", x_remote.detail.lower())


if __name__ == "__main__":
    unittest.main()
