import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from frikshun_creator.services.kling_cli import KlingCliClient, KlingCliError


class KlingCliClientTest(unittest.TestCase):
    def test_generate_clip_runs_cli_and_downloads_watermark_free_work(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            output = Path(directory) / "clip.mp4"
            source.write_bytes(b"png")
            runner = Mock()
            runner.return_value = Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "body": {
                            "generation_id": "gen-123",
                            "works": [
                                {
                                    "url": "https://example.test/watermarked.mp4",
                                    "url_without_watermark": "https://example.test/clean.mp4",
                                }
                            ],
                        }
                    }
                ),
                stderr="",
            )
            response = Mock(content=b"video")
            response.raise_for_status.return_value = None
            downloader = Mock(return_value=response)
            client = KlingCliClient(runner=runner, downloader=downloader, poll_seconds=30)

            result = client.generate_clip(source, "subtle motion", 5.4, output)

            self.assertEqual(b"video", output.read_bytes())
            self.assertEqual("gen-123", result["generation_id"])
            command = runner.call_args.args[0]
            self.assertIn("kling-video-v3_0", command)
            self.assertIn("--poll", command)
            self.assertIn("30", command)
            downloader.assert_called_once_with("https://example.test/clean.mp4", timeout=180)

    def test_generate_clip_does_not_run_without_source_frame(self):
        runner = Mock()
        client = KlingCliClient(runner=runner)
        with self.assertRaises(KlingCliError):
            client.generate_clip("missing.png", "motion", 5, "out.mp4")
        runner.assert_not_called()
