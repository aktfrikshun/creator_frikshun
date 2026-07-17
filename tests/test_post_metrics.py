from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, PostDraft, PostInteraction, PostMetricSnapshot, PostPublication
from frikshun_creator.publishers.base import PostInteractionData, PostMetrics
from frikshun_creator.services.post_metrics import PostMetricsPoller


class FakeMetricsAdapter:
    def fetch_post_metrics(self, publication):
        return PostMetrics(
            platform=publication.platform,
            external_post_id=publication.external_post_id,
            external_url="https://example.test/post",
            views=42,
            reach=30,
            likes=8,
            comments=2,
            shares=1,
            clicks=5,
            raw_metrics={"source": "fake"},
        )

    def fetch_post_interactions(self, publication):
        return [
            PostInteractionData(
                platform=publication.platform,
                interaction_type="comment",
                external_id="comment-1",
                external_post_id=publication.external_post_id,
                author_name="Allen",
                author_platform_id="user-1",
                body="This feels alive.",
                received_at=datetime(2026, 7, 12, 16, 45, tzinfo=timezone.utc),
                raw_payload={"id": "comment-1"},
            )
        ]


class PostMetricsPollerTest(unittest.TestCase):
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

    def tearDown(self):
        self.uploads.cleanup()

    def test_poller_stores_metric_snapshots_and_upserts_interactions(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Metric Signal")
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="facebook",
                caption="Metric copy.",
                status="published",
            )
            session.add(draft)
            session.flush()
            publication = PostPublication(
                post_draft_id=draft.id,
                platform="facebook",
                status="published",
                external_post_id="facebook-post-1",
                external_url="https://facebook.test/post",
            )
            session.add(publication)
            session.commit()

            result = PostMetricsPoller(
                session, adapters={"facebook": FakeMetricsAdapter()}
            ).run()

            self.assertEqual(1, result.snapshots_created)
            self.assertEqual(1, result.interactions_created)
            snapshot = session.query(PostMetricSnapshot).one()
            self.assertEqual(42, snapshot.views)
            self.assertEqual(8, snapshot.likes)
            interaction = session.query(PostInteraction).one()
            self.assertEqual("pending_review", interaction.reply_status)
            self.assertEqual("This feels alive.", interaction.body)

            result = PostMetricsPoller(
                session, adapters={"facebook": FakeMetricsAdapter()}
            ).run()

            self.assertEqual(1, result.snapshots_created)
            self.assertEqual(0, result.interactions_created)
            self.assertEqual(1, result.interactions_updated)
            self.assertEqual(2, session.query(PostMetricSnapshot).count())
            self.assertEqual(1, session.query(PostInteraction).count())

    def test_poller_skips_recorded_dry_run_publications(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Dry Signal")
            draft = PostDraft(artifact=artifact, platform="facebook", caption="Dry copy.")
            session.add(draft)
            session.flush()
            session.add(
                PostPublication(
                    post_draft_id=draft.id,
                    platform="facebook",
                    status="published",
                    external_post_id="dry-run-facebook-example",
                )
            )
            session.commit()

            result = PostMetricsPoller(
                session, adapters={"facebook": FakeMetricsAdapter()}
            ).run()

            self.assertEqual(1, result.skipped)
            self.assertEqual(0, result.snapshots_created)


if __name__ == "__main__":
    unittest.main()
