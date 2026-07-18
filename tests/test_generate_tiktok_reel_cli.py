from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from frikshun_creator import create_app
from frikshun_creator.services.tiktok_reel_generator import TikTokReelExport


class GenerateTikTokReelCliTest(unittest.TestCase):
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

    def test_command_exports_reel_without_publishing(self):
        reel_dir = Path(self.uploads.name) / "exports"
        reel_dir.mkdir()
        export = TikTokReelExport(
            title="Dating A Virtual Girl Means Reading The Metadata",
            concept="dating a virtual girl",
            caption="Dating me is easy until your contradictions get indexed.",
            hashtags=["ChloKat", "VirtualGirl", "DatingHumor"],
            video_path=reel_dir / "reel.mp4",
            metadata_path=reel_dir / "reel.json",
            draft_path=reel_dir / "reel.txt",
            frame_paths=[reel_dir / "shot-01.png"],
            artifact_id=11,
            draft_id=22,
        )

        with patch("frikshun_creator.CanonImporter.run") as import_canon, \
            patch("frikshun_creator.TikTokReelGenerator.generate_and_store", return_value=export) as generate:
            result = self.runner.invoke(
                args=[
                    "generate-tiktok-reel",
                    "--concept",
                    "dating a virtual girl",
                    "--shot-count",
                    "5",
                    "--local-date",
                    "2026-07-17",
                ]
            )

        self.assertEqual(0, result.exit_code, result.output)
        import_canon.assert_called_once()
        self.assertIn("artifact_id: 11", result.output)
        self.assertIn("draft_id: 22", result.output)
        self.assertIn("manual_review_required: true", result.output)
        self.assertEqual("dating a virtual girl", generate.call_args.kwargs["concept"])


if __name__ == "__main__":
    unittest.main()
