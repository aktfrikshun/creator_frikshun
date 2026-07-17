from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from frikshun_creator import create_app
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


if __name__ == "__main__":
    unittest.main()
