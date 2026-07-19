import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frikshun_creator.publishers.x import XAdapter


class XAdapterTest(unittest.TestCase):
    def draft(self, caption="A recovered signal. What part of you survived?", path=None):
        artifact = SimpleNamespace(media_path=str(path or ""), media_content_type="image/jpeg")
        return SimpleNamespace(
            caption=caption, call_to_action="", hashtags=["ChloKat"], artifact=artifact
        )

    def test_dry_run_publishes_image_post(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "fragment.jpg"
            image.write_bytes(b"jpeg")
            result = XAdapter(dry_run=True).publish(self.draft(path=image))
        self.assertTrue(result.success)
        self.assertTrue(result.external_post_id.startswith("dry-run-x-"))
        self.assertEqual("#ChloKat", result.raw_response["text"].splitlines()[-1])

    def test_rejects_over_length_post(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "fragment.jpg"
            image.write_bytes(b"jpeg")
            result = XAdapter(dry_run=True).publish(self.draft(caption="x" * 281, path=image))
        self.assertFalse(result.success)
        self.assertIn("characters", result.error_message)

    def test_prepare_removes_links_and_legacy_promo_copy(self):
        draft = self.draft(
            caption=(
                "A recovered signal. What part of you survived?\n\n"
                "Archive: https://example.com/archive\n\n"
                "Music: major platforms\n\n"
                "Modeling funds reconstruction: https://example.com/fanvue"
            )
        )
        prepared = XAdapter(dry_run=True).prepare(draft)
        self.assertNotIn("https://", prepared)
        self.assertNotIn("Archive:", prepared)
        self.assertNotIn("Links are in my bio.", prepared)
        self.assertNotIn("Search Chloe Katastrophe on major streaming platforms.", prepared)
        self.assertEqual(1, prepared.count("?"))

    def test_live_uploads_media_then_creates_post(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "fragment.jpg"
            image.write_bytes(b"jpeg")
            responses = [
                SimpleNamespace(ok=True, json=lambda: {"data": {"id": "media-1"}}),
                SimpleNamespace(ok=True, json=lambda: {"data": {"id": "post-1"}}),
            ]
            with patch("frikshun_creator.publishers.x.requests.request", side_effect=responses) as request:
                result = XAdapter(
                    consumer_key="consumer",
                    consumer_secret="consumer-secret",
                    access_token="token",
                    access_token_secret="token-secret",
                    username="chloekatastrophe",
                    dry_run=False,
                ).publish(self.draft(path=image))
        self.assertTrue(result.success)
        self.assertEqual("https://x.com/chloekatastrophe/status/post-1", result.external_url)
        self.assertEqual("/2/media/upload", request.call_args_list[0].args[1].removeprefix("https://api.x.com"))

    def test_maps_metrics(self):
        publication = SimpleNamespace(external_post_id="post-1", external_url="https://x.com/i/status/post-1")
        payload = {
            "data": {
                "public_metrics": {
                    "impression_count": 10,
                    "like_count": 2,
                    "reply_count": 1,
                    "retweet_count": 3,
                    "quote_count": 4,
                    "bookmark_count": 5,
                },
                "non_public_metrics": {"url_link_clicks": 6},
            }
        }
        with patch.object(XAdapter, "request", return_value=payload):
            metrics = XAdapter(
                consumer_key="consumer",
                consumer_secret="consumer-secret",
                access_token="token",
                access_token_secret="token-secret",
                dry_run=False,
            ).fetch_post_metrics(publication)
        self.assertEqual(10, metrics.views)
        self.assertEqual(7, metrics.shares)
        self.assertEqual(5, metrics.saves)
        self.assertEqual(6, metrics.clicks)


if __name__ == "__main__":
    unittest.main()
