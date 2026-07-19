from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, MetricsPollRun, PostDraft, PostInteraction, PostMetricSnapshot, PostPublication
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


class MissingPostAdapter:
    def fetch_post_metrics(self, publication):
        raise ValueError("Post not found")


class ExpiredTokenAdapter:
    calls = 0

    def fetch_post_metrics(self, publication):
        self.calls += 1
        raise ValueError("Error validating access token: Session has expired")


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
            poll_run = session.query(MetricsPollRun).one()
            self.assertEqual("succeeded", poll_run.status)
            self.assertEqual(1, poll_run.snapshots_created)
            self.assertIsNotNone(poll_run.completed_at)

            result = PostMetricsPoller(
                session, adapters={"facebook": FakeMetricsAdapter()}
            ).run()

            self.assertEqual(1, result.snapshots_created)
            self.assertEqual(0, result.interactions_created)
            self.assertEqual(1, result.interactions_updated)
            self.assertEqual(2, session.query(PostMetricSnapshot).count())
            self.assertEqual(1, session.query(PostInteraction).count())
            self.assertEqual(2, session.query(MetricsPollRun).count())

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

    def test_missing_platform_post_returns_draft_to_approved(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Deleted Platform Signal")
            draft = PostDraft(
                artifact=artifact,
                platform="instagram",
                caption="Restore this signal?",
                status="published",
            )
            session.add(draft)
            session.flush()
            publication = PostPublication(
                post_draft=draft,
                platform="instagram",
                status="published",
                external_post_id="deleted-media-id",
            )
            session.add(publication)
            session.commit()

            result = PostMetricsPoller(
                session, adapters={"instagram": MissingPostAdapter()}
            ).run()

            self.assertEqual(1, result.marked_unpublished)
            self.assertEqual([], result.errors)
            self.assertEqual("not_found", publication.status)
            self.assertEqual("approved", draft.status)
            self.assertEqual("Post not found", publication.error_message)

            second = PostMetricsPoller(
                session, adapters={"instagram": MissingPostAdapter()}
            ).run()
            self.assertEqual(0, second.scanned)

    def test_authentication_failure_does_not_unpublish_post(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Current Platform Signal")
            draft = PostDraft(
                artifact=artifact,
                platform="facebook",
                caption="Keep published state?",
                status="published",
            )
            session.add(draft)
            session.flush()
            publication = PostPublication(
                post_draft=draft,
                platform="facebook",
                status="published",
                external_post_id="current-facebook-id",
            )
            session.add(publication)
            session.commit()

            result = PostMetricsPoller(
                session, adapters={"facebook": ExpiredTokenAdapter()}
            ).run()

            self.assertEqual(0, result.marked_unpublished)
            self.assertEqual(1, len(result.errors))
            self.assertEqual("published", publication.status)
            self.assertEqual("published", draft.status)

    def test_authentication_failure_short_circuits_remaining_platform_posts(self):
        with self.app.app_context():
            session = get_session()
            adapter = ExpiredTokenAdapter()
            for index in range(3):
                draft = PostDraft(
                    artifact=Artifact(title=f"Facebook Signal {index}"),
                    platform="facebook",
                    caption="Keep state?",
                    status="published",
                )
                session.add(draft)
                session.flush()
                session.add(
                    PostPublication(
                        post_draft=draft,
                        platform="facebook",
                        status="published",
                        external_post_id=f"facebook-{index}",
                    )
                )
            session.commit()

            result = PostMetricsPoller(session, adapters={"facebook": adapter}).run()

            self.assertEqual(1, adapter.calls)
            self.assertEqual(1, len(result.errors))
            self.assertEqual(2, result.skipped)


if __name__ == "__main__":
    unittest.main()
