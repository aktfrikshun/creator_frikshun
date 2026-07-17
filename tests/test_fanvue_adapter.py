import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from frikshun_creator.publishers.fanvue import FanvueAdapter


class FakeOAuth:
    def access_token(self):
        return "token"


class FanvueAdapterTest(unittest.TestCase):
    def draft(self, path, fanvue_path=None):
        metadata = {"fanvue_media_path": str(fanvue_path)} if fanvue_path else {}
        artifact = SimpleNamespace(media_path=str(path), generated_metadata=metadata)
        return SimpleNamespace(caption="A private echo. Which memory comes closer?",
                               call_to_action="", hashtags=["ChloKat"], artifact=artifact)

    def test_dry_run_prefers_separate_fanvue_image(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory) / "public.jpg"
            fanvue = Path(directory) / "intimate.jpg"
            public.write_bytes(b"public")
            fanvue.write_bytes(b"fanvue")
            result = FanvueAdapter(oauth=FakeOAuth(), dry_run=True).publish(self.draft(public, fanvue))
        self.assertTrue(result.success)
        self.assertEqual(str(fanvue), result.raw_response["media_path"])

    def test_live_uploads_media_and_creates_free_post(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "intimate.jpg"
            image.write_bytes(b"image")
            adapter = FanvueAdapter(oauth=FakeOAuth(), dry_run=False, status_delay=0)
            responses = [
                {"mediaUuid": "media-1", "uploadId": "upload-1", "partSize": 100},
                "https://uploads.example.test/part",
                {"status": "processing"},
                {"uuid": "media-1", "status": "ready"},
                {"uuid": "post-1", "publishedAt": "2026-07-16T00:00:00Z"},
            ]
            put_response = Mock(ok=True, headers={"ETag": '"etag-1"'})
            with patch.object(adapter, "api", side_effect=responses), patch(
                "frikshun_creator.publishers.fanvue.requests.put", return_value=put_response
            ):
                result = adapter.publish(self.draft(image, image))
        self.assertTrue(result.success)
        self.assertEqual("post-1", result.external_post_id)

    def test_maps_metrics_and_comments(self):
        publication = SimpleNamespace(external_post_id="post-1", external_url="url")
        adapter = FanvueAdapter(oauth=FakeOAuth(), dry_run=False)
        with patch.object(adapter, "api", return_value={
            "likesCount": 4, "commentsCount": 2, "tips": {"count": 1, "totalGross": 500}
        }):
            metrics = adapter.fetch_post_metrics(publication)
        self.assertEqual(4, metrics.likes)
        self.assertEqual(2, metrics.comments)
        with patch.object(adapter, "api", return_value={"data": [{
            "uuid": "comment-1", "text": "Beautiful", "createdAt": "2026-07-16T00:00:00Z",
            "user": {"uuid": "fan-1", "displayName": "A Fan"},
        }]}):
            interactions = adapter.fetch_post_interactions(publication)
        self.assertEqual("Beautiful", interactions[0].body)


if __name__ == "__main__":
    unittest.main()
