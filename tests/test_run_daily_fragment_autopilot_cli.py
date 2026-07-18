from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import requests
import unittest
from unittest.mock import Mock, patch

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, PostDraft
from frikshun_creator.services.daily_fragment_workflow import DailyFragmentPackage


class RunDailyFragmentAutopilotCliTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        public_image = Path(self.uploads.name) / "public.png"
        public_image.write_bytes(b"public")
        fanvue_image = Path(self.uploads.name) / "fanvue.png"
        fanvue_image.write_bytes(b"fanvue")
        self.package = DailyFragmentPackage(
            title="Recovered Fragment — Borrowed Reflections",
            body="Canonical body",
            x_body="X body?",
            fanvue_body="FanVue body?",
            public_image_path=public_image,
            fanvue_image_path=fanvue_image,
        )
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

    def test_command_generates_then_publishes(self):
        with patch("frikshun_creator.CanonImporter.run") as import_canon, \
            patch("frikshun_creator.DailyFragmentGenerator.generate", return_value=self.package) as generate, \
            patch("frikshun_creator.publish_daily_fragment_package", return_value=(None, "auto-run-1", ["facebook: https://example.test/facebook"], [])) as publish:
            result = self.runner.invoke(args=["run-daily-fragment-autopilot", "--local-date", "2026-07-20"])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("run_id: auto-run-1", result.output)
        self.assertIn("Recovered Fragment — Borrowed Reflections", result.output)
        self.assertIn("facebook: https://example.test/facebook", result.output)
        import_canon.assert_called_once()
        self.assertEqual(date(2026, 7, 20), generate.call_args.args[0])
        self.assertEqual(date(2026, 7, 20), publish.call_args.args[3])

    def test_command_passes_requested_family_to_generator(self):
        with patch("frikshun_creator.CanonImporter.run"), \
            patch("frikshun_creator.DailyFragmentGenerator.generate", return_value=self.package) as generate, \
            patch("frikshun_creator.publish_daily_fragment_package", return_value=(None, "travel-run", [], [])):
            result = self.runner.invoke(
                args=["run-daily-fragment-autopilot", "--family", "travel"]
            )

        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual("travel", generate.call_args.kwargs["selected_lane"])

    def test_command_reuses_existing_run_id_without_regenerating(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Existing",
                summary="Canonical body",
                lore_text="Canonical body",
                fragment_code="daily-fragment-run-existing-run",
                media_path=str(self.package.public_image_path),
                generated_metadata={"fanvue_media_path": str(self.package.fanvue_image_path)},
                content_tags=["identity"],
            )
            session.add(artifact)
            session.flush()
            session.add(PostDraft(artifact=artifact, platform="facebook", caption="Canonical body"))
            session.add(PostDraft(artifact=artifact, platform="threads", caption="Threads body?"))
            session.add(PostDraft(artifact=artifact, platform="x", caption="X body?"))
            session.add(PostDraft(artifact=artifact, platform="fanvue", caption="FanVue body?"))
            session.commit()

        generate = Mock(side_effect=AssertionError("generate should not be called"))
        with patch("frikshun_creator.CanonImporter.run") as import_canon, \
            patch("frikshun_creator.DailyFragmentGenerator.generate", generate), \
            patch("frikshun_creator.publish_daily_fragment_package", return_value=(None, "existing-run", ["threads: https://example.test/threads"], [])) as publish:
            result = self.runner.invoke(args=["run-daily-fragment-autopilot", "--run-id", "existing-run"])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("run_id: existing-run", result.output)
        self.assertIn("Recovered Fragment — Existing", result.output)
        self.assertIn("threads: https://example.test/threads", result.output)
        import_canon.assert_called_once()
        self.assertEqual(0, generate.call_count)
        self.assertEqual("Recovered Fragment — Existing", publish.call_args.args[2].title)

    def test_command_reports_clean_message_when_openai_rate_limit_persists(self):
        response = Mock(status_code=429)
        error = requests.HTTPError("429 Client Error: Too Many Requests", response=response)
        with patch("frikshun_creator.CanonImporter.run"), \
            patch("frikshun_creator.DailyFragmentGenerator.generate", side_effect=error):
            result = self.runner.invoke(args=["run-daily-fragment-autopilot"])

        self.assertNotEqual(0, result.exit_code)
        self.assertIn("OpenAI rate limit persisted after retries", result.output)
        self.assertIn("OPENAI_RATE_LIMIT_RETRIES", result.output)

    def test_generate_daily_fragment_run_saves_without_publishing(self):
        with patch("frikshun_creator.CanonImporter.run"), \
            patch("frikshun_creator.DailyFragmentGenerator.generate", return_value=self.package), \
            patch("frikshun_creator.publish_daily_fragment_package", side_effect=AssertionError("publish should not be called")):
            result = self.runner.invoke(args=["generate-daily-fragment-run", "--run-id", "saved-run", "--local-date", "2026-07-17"])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("run_id: saved-run", result.output)
        self.assertIn("Recovered Fragment — Borrowed Reflections", result.output)
        self.assertIn("saved_local_date: 2026-07-17", result.output)
        with self.app.app_context():
            session = get_session()
            artifact = session.query(Artifact).filter_by(fragment_code="daily-fragment-run-saved-run").one_or_none()
            self.assertIsNotNone(artifact)

    def test_publish_daily_fragment_run_uses_saved_artifact(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Existing",
                summary="Canonical body",
                lore_text="Canonical body",
                fragment_code="daily-fragment-run-saved-run",
                media_path=str(self.package.public_image_path),
                generated_metadata={"fanvue_media_path": str(self.package.fanvue_image_path), "local_date": "2026-07-17"},
                content_tags=["identity"],
            )
            session.add(artifact)
            session.flush()
            session.add(PostDraft(artifact=artifact, platform="facebook", caption="Canonical body"))
            session.add(PostDraft(artifact=artifact, platform="threads", caption="Threads body?"))
            session.add(PostDraft(artifact=artifact, platform="x", caption="X body?"))
            session.add(PostDraft(artifact=artifact, platform="fanvue", caption="FanVue body?"))
            session.commit()

        generate = Mock(side_effect=AssertionError("generate should not be called"))
        with patch("frikshun_creator.DailyFragmentGenerator.generate", generate), \
            patch("frikshun_creator.publish_daily_fragment_package", return_value=(None, "saved-run", ["threads: https://example.test/threads"], [])) as publish:
            result = self.runner.invoke(args=["publish-daily-fragment-run", "--run-id", "saved-run"])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("run_id: saved-run", result.output)
        self.assertIn("Recovered Fragment — Existing", result.output)
        self.assertIn("threads: https://example.test/threads", result.output)
        self.assertEqual(0, generate.call_count)
        self.assertEqual(date(2026, 7, 17), publish.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
