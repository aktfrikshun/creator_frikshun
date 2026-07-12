from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from frikshun_creator.services.media_analyzer import MediaAnalyzer


class MediaAnalyzerTest(unittest.TestCase):
    def test_openai_image_analysis_parses_json_response(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rain-room.png"
            path.write_bytes(b"image bytes")
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "output_text": (
                    '{"description":"A sepia room with rain, blinds, an old telephone, and a watchful woman.",'
                    '"what":"noir portrait with vintage telephone",'
                    '"where":"rain-lit interior with blinds",'
                    '"when":"late-night recovered still",'
                    '"why":"to frame Chloe as guarded and unresolved",'
                    '"mood_tags":["noir","rain"],'
                    '"content_tags":["image","portrait"],'
                    '"suggested_title":"Telephone In The Rain Room"}'
                )
            }

            with patch("frikshun_creator.services.media_analyzer.requests.post", return_value=response) as post:
                analysis = MediaAnalyzer(provider="openai", api_key="test-key", model="vision-test").analyze(
                    {
                        "original_filename": "rain-room.png",
                        "media_path": str(path),
                        "media_content_type": "image/png",
                    }
                )

        self.assertEqual("Telephone In The Rain Room", analysis.suggested_title)
        self.assertIn("vintage telephone", analysis.what)
        self.assertEqual(["noir", "rain"], analysis.mood_tags)
        request_payload = post.call_args.kwargs["json"]
        self.assertEqual("vision-test", request_payload["model"])
        self.assertEqual("input_image", request_payload["input"][0]["content"][1]["type"])

    def test_openai_api_key_env_is_supported(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "canonical-key"}, clear=True):
            analyzer = MediaAnalyzer(provider="openai")

        self.assertEqual("canonical-key", analyzer.api_key)


if __name__ == "__main__":
    unittest.main()
