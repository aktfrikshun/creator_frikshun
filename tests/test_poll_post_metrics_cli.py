from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import MetricsPollRun


class PollPostMetricsCliTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
            }
        )
        self.runner = self.app.test_cli_runner()

    def tearDown(self):
        self.uploads.cleanup()

    @patch("frikshun_creator.AccountAnalyticsRunner")
    @patch("frikshun_creator.PostMetricsPoller")
    def test_skips_second_scheduled_poll_on_same_utc_day(self, poller, analytics_runner):
        with self.app.app_context():
            session = get_session()
            session.add(
                MetricsPollRun(
                    source="scheduler",
                    status="succeeded",
                    started_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        result = self.runner.invoke(args=["poll-post-metrics"])

        self.assertEqual(0, result.exit_code)
        self.assertIn("already ran today", result.output)
        poller.assert_not_called()
        analytics_runner.assert_not_called()

    @patch("frikshun_creator.AccountAnalyticsRunner")
    @patch("frikshun_creator.PostMetricsPoller")
    def test_force_allows_an_additional_poll(self, poller, analytics_runner):
        with self.app.app_context():
            session = get_session()
            session.add(
                MetricsPollRun(
                    source="scheduler",
                    status="succeeded",
                    started_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

        poller.return_value.run.return_value = type(
            "Result",
            (),
            {
                "snapshots_created": 0,
                "interactions_created": 0,
                "interactions_updated": 0,
                "marked_unpublished": 0,
                "skipped": 0,
                "errors": [],
            },
        )()
        analytics_runner.return_value.run.return_value = type(
            "AccountResult",
            (),
            {"platform_results": {}, "errors": []},
        )()

        result = self.runner.invoke(args=["poll-post-metrics", "--force"])

        self.assertEqual(0, result.exit_code)
        poller.return_value.run.assert_called_once_with()
        analytics_runner.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
