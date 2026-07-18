from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact
from frikshun_creator.publishers.base import PublishResult
from frikshun_creator.services.s3_media_storage import StoredMedia


class PublishDailyFragmentCliTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.public_image = Path(self.uploads.name) / "public.png"
        self.public_image.write_bytes(b"public-image")
        self.fanvue_image = Path(self.uploads.name) / "fanvue.png"
        self.fanvue_image.write_bytes(b"fanvue-image")
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
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
                "FANVUE_TOKEN_PATH": str(Path(self.uploads.name) / "fanvue-token.json"),
                "S3_MEDIA_BUCKET": "bucket",
            }
        )
        self.runner = self.app.test_cli_runner()

    def tearDown(self):
        self.uploads.cleanup()

    def invoke(self, *extra_args):
        return self.runner.invoke(
            args=[
                "publish-daily-fragment",
                "--title",
                "Recovered Fragment — Override",
                "--image",
                str(self.public_image),
                "--fanvue-image",
                str(self.fanvue_image),
                "--body",
                "Canonical body",
                "--x-body",
                "X body?",
                "--fanvue-body",
                "FanVue body?",
                *extra_args,
            ]
        )

    def publish_result(self, platform):
        return PublishResult(
            success=True,
            status="published",
            external_post_id=f"{platform}-post-1",
            external_url=f"https://example.test/{platform}/post-1",
            raw_response={"platform": platform},
        )

    def stored_media(self):
        stored_path = Path(self.uploads.name) / "stored.jpg"
        stored_path.write_bytes(b"jpeg")
        return StoredMedia(
            local_path=stored_path,
            object_key="social/2026/07/20/stored.jpg",
            signed_url="https://signed.example.test/stored.jpg",
        )

    def publisher_patches(self):
        return (
            patch("frikshun_creator.services.daily_fragment_workflow.S3MediaStorage.store_instagram_image", return_value=self.stored_media()),
            patch("frikshun_creator.services.daily_fragment_workflow.FacebookAdapter.publish", return_value=self.publish_result("facebook")),
            patch("frikshun_creator.services.daily_fragment_workflow.InstagramAdapter.publish", return_value=self.publish_result("instagram")),
            patch("frikshun_creator.services.daily_fragment_workflow.ThreadsAdapter.publish", return_value=self.publish_result("threads")),
            patch("frikshun_creator.services.daily_fragment_workflow.XAdapter.publish", return_value=self.publish_result("x")),
            patch("frikshun_creator.services.daily_fragment_workflow.FanvueAdapter.publish", return_value=self.publish_result("fanvue")),
        )

    def test_local_date_override_sets_fragment_code_and_storage_day(self):
        with self.publisher_patches()[0], self.publisher_patches()[1], self.publisher_patches()[2], \
            self.publisher_patches()[3], self.publisher_patches()[4], self.publisher_patches()[5]:
            result = self.invoke("--local-date", "2026-07-20", "--run-id", "demo-run-1")

        self.assertEqual(0, result.exit_code, result.output)
        with self.app.app_context():
            artifact = get_session().query(Artifact).filter_by(fragment_code="daily-fragment-run-demo-run-1").one()
            self.assertEqual("Recovered Fragment — Override", artifact.title)
            self.assertEqual("2026-07-20", artifact.generated_metadata["local_date"])
            self.assertEqual("demo-run-1", artifact.generated_metadata["run_id"])

    def test_repeated_run_id_skips_already_published_platforms(self):
        with self.publisher_patches()[0], self.publisher_patches()[1], self.publisher_patches()[2], \
            self.publisher_patches()[3], self.publisher_patches()[4], self.publisher_patches()[5]:
            first = self.invoke("--local-date", "2026-07-20", "--run-id", "retry-run")

        self.assertEqual(0, first.exit_code, first.output)

        x_publish = Mock(side_effect=AssertionError("x should be skipped"))
        fanvue_publish = Mock(side_effect=AssertionError("fanvue should be skipped"))
        facebook_publish = Mock(side_effect=AssertionError("facebook should be skipped"))
        instagram_publish = Mock(side_effect=AssertionError("instagram should be skipped"))
        threads_publish = Mock(side_effect=AssertionError("threads should be skipped"))

        with patch("frikshun_creator.services.daily_fragment_workflow.S3MediaStorage.store_instagram_image", return_value=self.stored_media()), \
            patch("frikshun_creator.services.daily_fragment_workflow.FacebookAdapter.publish", facebook_publish), \
            patch("frikshun_creator.services.daily_fragment_workflow.InstagramAdapter.publish", instagram_publish), \
            patch("frikshun_creator.services.daily_fragment_workflow.ThreadsAdapter.publish", threads_publish), \
            patch("frikshun_creator.services.daily_fragment_workflow.XAdapter.publish", x_publish), \
            patch("frikshun_creator.services.daily_fragment_workflow.FanvueAdapter.publish", fanvue_publish):
            second = self.invoke("--local-date", "2026-07-20", "--run-id", "retry-run")

        self.assertEqual(0, second.exit_code, second.output)
        self.assertEqual(0, x_publish.call_count)
        self.assertEqual(0, fanvue_publish.call_count)
        self.assertEqual(0, facebook_publish.call_count)
        self.assertEqual(0, instagram_publish.call_count)
        self.assertEqual(0, threads_publish.call_count)
        self.assertIn("https://example.test/x/post-1", second.output)
        self.assertIn("https://example.test/fanvue/post-1", second.output)

    def test_two_runs_same_date_create_distinct_artifacts_without_run_id_reuse(self):
        with self.publisher_patches()[0], self.publisher_patches()[1], self.publisher_patches()[2], \
            self.publisher_patches()[3], self.publisher_patches()[4], self.publisher_patches()[5]:
            first = self.invoke("--local-date", "2026-07-20", "--run-id", "run-a")
            second = self.invoke("--local-date", "2026-07-20", "--run-id", "run-b")

        self.assertEqual(0, first.exit_code, first.output)
        self.assertEqual(0, second.exit_code, second.output)
        with self.app.app_context():
            artifacts = get_session().query(Artifact).order_by(Artifact.fragment_code.asc()).all()
            self.assertEqual(2, len(artifacts))
            self.assertEqual(
                ["daily-fragment-run-run-a", "daily-fragment-run-run-b"],
                [artifact.fragment_code for artifact in artifacts],
            )


if __name__ == "__main__":
    unittest.main()
