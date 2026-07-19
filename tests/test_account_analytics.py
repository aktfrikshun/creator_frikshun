import unittest
from datetime import datetime, timezone

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import (
    Artifact,
    PlatformAccount,
    PostDraft,
    PostPublication,
    RemoteContent,
)
from frikshun_creator.publishers.base import (
    AccountMetricsData,
    ContentDiscoveryPage,
    PostMetrics,
    RemoteContentData,
)
from frikshun_creator.services.account_analytics import AccountAnalyticsSync


class FakeAnalyticsAdapter:
    def fetch_account_metrics(self):
        return AccountMetricsData(followers=2400, views=90000, engagements=4100)

    def discover_account_content(self, cursor="", limit=100):
        if not cursor:
            return ContentDiscoveryPage(
                items=[RemoteContentData(external_content_id="known", title="Known post")],
                next_cursor="page-2",
            )
        return ContentDiscoveryPage(
            items=[RemoteContentData(external_content_id="manual", title="Manual post")]
        )

    def fetch_remote_content_metrics(self, remote_content):
        return PostMetrics(
            platform="youtube",
            external_post_id=remote_content.external_content_id,
            views=100,
            likes=12,
            comments=3,
        )


class AccountAnalyticsSyncTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "DATABASE_URL": "sqlite+pysqlite:///:memory:"})

    def test_discovers_reconciles_and_snapshots_account_wide_content(self):
        with self.app.app_context():
            session = get_session()
            account = PlatformAccount(platform="youtube", analytics_status="configured")
            artifact = Artifact(title="Known artifact")
            draft = PostDraft(artifact=artifact, platform="youtube")
            publication = PostPublication(
                post_draft=draft,
                platform="youtube",
                status="published",
                external_post_id="known",
            )
            session.add_all([account, publication])
            session.commit()

            result = AccountAnalyticsSync(
                session,
                account,
                FakeAnalyticsAdapter(),
                now=datetime(2026, 7, 18, 20, 15, tzinfo=timezone.utc),
            ).run()

            self.assertEqual(2, result.discovered)
            self.assertEqual(1, result.reconciled)
            self.assertEqual(1, result.account_snapshots)
            self.assertEqual(2, result.content_snapshots)
            manual = session.query(RemoteContent).filter_by(external_content_id="manual").one()
            known = session.query(RemoteContent).filter_by(external_content_id="known").one()
            self.assertIsNone(manual.post_publication_id)
            self.assertEqual(publication.id, known.post_publication_id)
            self.assertEqual(100, manual.metric_snapshots[0].views)
            self.assertEqual("connected", account.analytics_status)

            repeated = AccountAnalyticsSync(
                session,
                account,
                FakeAnalyticsAdapter(),
                now=datetime(2026, 7, 18, 23, 45, tzinfo=timezone.utc),
            ).run()
            self.assertEqual(0, repeated.discovered)
            self.assertEqual(0, repeated.account_snapshots)
            self.assertEqual(0, repeated.content_snapshots)
            self.assertEqual(2, session.query(RemoteContent).count())
            self.assertEqual("daily", account.sync_runs[-1].sync_type)

            next_day = AccountAnalyticsSync(
                session,
                account,
                FakeAnalyticsAdapter(),
                now=datetime(2026, 7, 19, 0, 15, tzinfo=timezone.utc),
            ).run()
            self.assertEqual(1, next_day.account_snapshots)
            self.assertEqual(2, next_day.content_snapshots)

    def test_marks_remote_content_unavailable_without_deleting_history(self):
        class MissingAdapter(FakeAnalyticsAdapter):
            def discover_account_content(self, cursor="", limit=100):
                return ContentDiscoveryPage()

            def fetch_remote_content_metrics(self, remote_content):
                raise RuntimeError("video not found")

        with self.app.app_context():
            session = get_session()
            account = PlatformAccount(platform="youtube")
            content = RemoteContent(platform_account=account, external_content_id="deleted")
            session.add(content)
            session.commit()

            result = AccountAnalyticsSync(session, account, MissingAdapter()).run()
            self.assertEqual(1, result.unavailable)
            self.assertEqual("unavailable", content.status)


if __name__ == "__main__":
    unittest.main()
