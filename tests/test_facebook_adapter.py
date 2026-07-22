import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from frikshun_creator.models import Artifact, PostDraft, PostPublication
from frikshun_creator.publishers.facebook import FacebookAdapter


class FacebookAdapterTest(unittest.TestCase):
    def test_dry_run_publish_returns_success_without_credentials(self):
        artifact = Artifact(title="Signal Test")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="FrikShun recovered a new fragment.",
            hashtags=["ChloKat"],
            call_to_action="Enter the ChloKat archive.",
        )

        result = FacebookAdapter(dry_run=True, page_id="", access_token="").publish(draft)

        self.assertTrue(result.success)
        self.assertEqual("published", result.status)
        self.assertTrue(result.external_post_id.startswith("dry-run-facebook-"))
        self.assertIn("message", result.raw_response)
        self.assertTrue(result.raw_response["message"].endswith("@allenktaylor @chloekatastropheai"))

    def test_prepare_does_not_duplicate_existing_account_tags(self):
        artifact = Artifact(title="Signal Test")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="Recovered with @AllenKTaylor already in the signal.",
            hashtags=[],
        )

        message = FacebookAdapter(dry_run=True).prepare(draft)

        self.assertEqual(1, message.lower().count("@allenktaylor"))
        self.assertEqual(1, message.lower().count("@chloekatastropheai"))
        self.assertTrue(message.endswith("@chloekatastropheai"))

    def test_account_tags_can_be_overridden(self):
        artifact = Artifact(title="Signal Test")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="A custom signal.",
            hashtags=[],
        )

        message = FacebookAdapter(dry_run=True, tag_usernames=["@customaccount"]).prepare(draft)

        self.assertTrue(message.endswith("@customaccount"))
        self.assertNotIn("@allenktaylor", message)

    def test_profile_target_requires_manual_publishing(self):
        artifact = Artifact(title="Signal Test")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="Profile publishing should not be automated.",
        )

        result = FacebookAdapter(dry_run=True, target_type="profile").publish(draft)

        self.assertFalse(result.success)
        self.assertEqual("manual_required", result.status)
        self.assertIn("Personal profile", result.error_message)

    def test_publish_image_artifact_uses_photos_endpoint(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "signal.jpg"
            image_path.write_bytes(b"fake image bytes")
            artifact = Artifact(
                title="Image Signal",
                media_path=str(image_path),
                media_content_type="image/jpeg",
            )
            draft = PostDraft(
                artifact=artifact,
                platform="facebook",
                caption="Image post copy.",
                hashtags=["ChloKat"],
            )
            response = Mock()
            response.ok = True
            response.json.return_value = {
                "id": "photo_1",
                "post_id": "page_1_photo_1",
            }

            with patch("frikshun_creator.publishers.facebook.requests.post", return_value=response) as post:
                result = FacebookAdapter(
                    dry_run=False,
                    page_id="page_1",
                    access_token="token",
                ).publish(draft)

        self.assertTrue(result.success)
        self.assertEqual("page_1_photo_1", result.external_post_id)
        self.assertIn("/photos", post.call_args.args[0])
        self.assertIn("caption", post.call_args.kwargs["data"])
        self.assertIn("source", post.call_args.kwargs["files"])

    def test_publish_image_falls_back_to_unpublished_photo_then_feed_post(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "signal.jpg"
            image_path.write_bytes(b"fake image bytes")
            artifact = Artifact(
                title="Image Signal",
                media_path=str(image_path),
                media_content_type="image/jpeg",
            )
            draft = PostDraft(
                artifact=artifact,
                platform="facebook",
                caption="Image post copy with a long caption.",
                hashtags=["ChloKat"],
            )
            initial = Mock()
            initial.ok = False
            initial.reason = "Bad Request"
            initial.json.return_value = {
                "error": {"message": "Please reduce the amount of data you're asking for, then retry your request"}
            }
            upload = Mock()
            upload.ok = True
            upload.json.return_value = {"id": "photo_1"}
            feed = Mock()
            feed.ok = True
            feed.json.return_value = {"id": "page_1_post_1"}

            with patch("frikshun_creator.publishers.facebook.requests.post", side_effect=[initial, upload, feed]) as post:
                result = FacebookAdapter(
                    dry_run=False,
                    page_id="page_1",
                    access_token="token",
                ).publish(draft)

        self.assertTrue(result.success)
        self.assertEqual("page_1_post_1", result.external_post_id)
        self.assertIn("/photos", post.call_args_list[0].args[0])
        self.assertEqual("false", post.call_args_list[1].kwargs["data"]["published"])
        self.assertIn("/feed", post.call_args_list[2].args[0])
        self.assertIn("attached_media[0]", post.call_args_list[2].kwargs["data"])

    def test_publish_text_artifact_uses_feed_endpoint(self):
        artifact = Artifact(title="Text Signal")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="Text-only post copy.",
            hashtags=["ChloKat"],
        )
        response = Mock()
        response.ok = True
        response.json.return_value = {"id": "page_1_post_1"}

        with patch("frikshun_creator.publishers.facebook.requests.post", return_value=response) as post:
            result = FacebookAdapter(
                dry_run=False,
                page_id="page_1",
                access_token="token",
            ).publish(draft)

        self.assertTrue(result.success)
        self.assertEqual("page_1_post_1", result.external_post_id)
        self.assertIn("/feed", post.call_args.args[0])
        self.assertIn("message", post.call_args.kwargs["data"])
        self.assertNotIn("files", post.call_args.kwargs)

    def test_publish_video_artifact_uses_videos_endpoint(self):
        with TemporaryDirectory() as directory:
            video_path = Path(directory) / "signal.mp4"
            video_path.write_bytes(b"fake video bytes")
            artifact = Artifact(
                title="Video Signal",
                media_path=str(video_path),
                media_content_type="video/mp4",
            )
            draft = PostDraft(
                artifact=artifact,
                platform="facebook",
                caption="Video post copy.",
                hashtags=["ChloKat"],
            )
            response = Mock()
            response.ok = True
            response.json.return_value = {"id": "video_1"}

            with patch("frikshun_creator.publishers.facebook.requests.post", return_value=response) as post:
                result = FacebookAdapter(
                    dry_run=False,
                    page_id="page_1",
                    access_token="token",
                ).publish(draft)

        self.assertTrue(result.success)
        self.assertEqual("video_1", result.external_post_id)
        self.assertIn("/videos", post.call_args.args[0])
        self.assertIn("description", post.call_args.kwargs["data"])
        self.assertIn("source", post.call_args.kwargs["files"])

    def test_fetch_post_metrics_parses_graph_payload(self):
        publication = PostPublication(
            platform="facebook",
            status="published",
            external_post_id="page_123",
            external_url="https://www.facebook.com/page_123",
        )
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "permalink_url": "https://facebook.com/post",
            "shares": {"count": 3},
            "comments": {
                "summary": {"total_count": 4},
                "data": [
                    {
                        "id": "comment_1",
                        "from": {"name": "Archivist", "id": "user_1"},
                        "message": "The signal came through.",
                        "created_time": "2026-07-12T16:30:00+0000",
                    }
                ],
            },
            "reactions": {"summary": {"total_count": 9}},
            "insights": {
                "data": [
                    {"name": "post_impressions", "values": [{"value": 120}]},
                    {"name": "post_impressions_unique", "values": [{"value": 80}]},
                    {"name": "post_clicks", "values": [{"value": 7}]},
                ]
            },
        }

        with patch("frikshun_creator.publishers.facebook.requests.get", return_value=response):
            adapter = FacebookAdapter(
                dry_run=False,
                page_id="page",
                access_token="token",
            )
            metrics = adapter.fetch_post_metrics(publication)
            interactions = adapter.fetch_post_interactions(publication)

        self.assertEqual(120, metrics.views)
        self.assertEqual(80, metrics.reach)
        self.assertEqual(9, metrics.likes)
        self.assertEqual(4, metrics.comments)
        self.assertEqual(3, metrics.shares)
        self.assertEqual(7, metrics.clicks)
        self.assertEqual("https://facebook.com/post", metrics.external_url)
        self.assertEqual(1, len(interactions))
        self.assertEqual("comment_1", interactions[0].external_id)
        self.assertEqual("The signal came through.", interactions[0].body)


if __name__ == "__main__":
    unittest.main()
