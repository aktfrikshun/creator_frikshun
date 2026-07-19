import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import (
    AccountMetricSnapshot,
    AnalyticsSyncRun,
    ContentMetricSnapshot,
    PlatformAccount,
    RemoteContent,
)


class AnalyticsModelsTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "DATABASE_URL": "sqlite+pysqlite:///:memory:"})

    def test_account_owns_remote_content_and_historical_snapshots(self):
        with self.app.app_context():
            session = get_session()
            account = PlatformAccount(
                platform="youtube",
                handle="@chloekatastrophe",
                external_account_id="UC-chloe",
                analytics_status="connected",
                publishing_mode="manual",
                capabilities={"account_metrics": True, "content_discovery": True},
            )
            content = RemoteContent(
                platform_account=account,
                external_content_id="video-1",
                content_type="short",
                title="Recovered transmission",
            )
            account.metric_snapshots.append(
                AccountMetricSnapshot(followers=1200, views=45000, engagements=3100)
            )
            content.metric_snapshots.append(
                ContentMetricSnapshot(
                    views=9000,
                    likes=800,
                    comments=42,
                    watch_time_seconds=180000,
                )
            )
            account.sync_runs.append(
                AnalyticsSyncRun(status="succeeded", discovered_count=1, updated_count=1)
            )
            session.add(account)
            session.commit()

            saved = session.query(PlatformAccount).filter_by(platform="youtube").one()
            self.assertEqual("manual", saved.publishing_mode)
            self.assertEqual("video-1", saved.remote_content[0].external_content_id)
            self.assertEqual(45000, saved.metric_snapshots[0].views)
            self.assertEqual(9000, saved.remote_content[0].metric_snapshots[0].views)
            self.assertEqual("succeeded", saved.sync_runs[0].status)

    def test_remote_content_identity_is_unique_within_an_account(self):
        with self.app.app_context():
            session = get_session()
            account = PlatformAccount(platform="tiktok")
            session.add_all(
                [
                    RemoteContent(platform_account=account, external_content_id="clip-1"),
                    RemoteContent(platform_account=account, external_content_id="clip-1"),
                ]
            )
            with self.assertRaises(Exception):
                session.commit()
            session.rollback()


if __name__ == "__main__":
    unittest.main()
