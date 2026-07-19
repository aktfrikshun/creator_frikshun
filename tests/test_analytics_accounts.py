import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.services.analytics_accounts import synchronize_account_registry


class AnalyticsAccountRegistryTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "DATABASE_URL": "sqlite+pysqlite:///:memory:"})

    def test_registry_creates_manual_analytics_accounts(self):
        with self.app.app_context():
            accounts = synchronize_account_registry(get_session(), {})
            by_platform = {account.platform: account for account in accounts}

            self.assertEqual("manual", by_platform["tiktok"].publishing_mode)
            self.assertEqual("manual", by_platform["youtube"].publishing_mode)
            self.assertEqual("credentials_missing", by_platform["youtube"].analytics_status)
            self.assertTrue(by_platform["youtube"].capabilities["content_discovery"])
            self.assertFalse(by_platform["tiktok"].capabilities["automated_publishing"])

    def test_registry_marks_configured_credentials_without_overwriting_connected_state(self):
        config = {
            "YOUTUBE_CLIENT_ID": "client",
            "YOUTUBE_CLIENT_SECRET": "secret",
            "YOUTUBE_REDIRECT_URI": "https://example.test/oauth/youtube/callback",
            "TIKTOK_CLIENT_KEY": "key",
            "TIKTOK_CLIENT_SECRET": "secret",
            "TIKTOK_REDIRECT_URI": "https://example.test/oauth/tiktok/callback",
        }
        with self.app.app_context():
            session = get_session()
            accounts = synchronize_account_registry(session, config)
            by_platform = {account.platform: account for account in accounts}
            self.assertEqual("configured", by_platform["youtube"].analytics_status)
            by_platform["youtube"].analytics_status = "connected"
            session.commit()

            refreshed = synchronize_account_registry(session, {})
            self.assertEqual(
                "connected",
                {account.platform: account for account in refreshed}["youtube"].analytics_status,
            )


if __name__ == "__main__":
    unittest.main()
