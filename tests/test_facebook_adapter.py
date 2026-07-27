import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from frikshun_creator.models import Artifact, PostDraft, PostPublication
from frikshun_creator.publishers.facebook import FacebookAdapter


class FacebookAdapterTest(unittest.TestCase):
    def test_dry_run_block_sender_returns_success(self):
        payload = FacebookAdapter(dry_run=True, page_id="page-1").block_sender("fan-42")

        self.assertTrue(payload["success"])
        self.assertEqual("fan-42", payload["blocked_id"])

    def test_dry_run_reply_to_comment_returns_synthetic_id(self):
        payload = FacebookAdapter(dry_run=True, page_id="page-1").reply_to_comment(
            "comment-1", "The signal reached me."
        )

        self.assertEqual("dry-run-reply-comment-1", payload["id"])

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
        self.assertNotIn("@allenktaylor", result.raw_response["message"])
        self.assertNotIn("@chloekatastrophe", result.raw_response["message"])

    def test_dry_run_identifies_multi_photo_post(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.jpg"
            second = Path(directory) / "second.jpg"
            video = Path(directory) / "motion.mp4"
            for path in (first, second, video):
                path.write_bytes(b"media")
            artifact = Artifact(
                title="Multi Signal",
                media_path=str(first),
                media_content_type="image/jpeg",
                generated_metadata={
                    "additional_media": [
                        {"media_path": str(second), "media_content_type": "image/jpeg"},
                        {"media_path": str(video), "media_content_type": "video/mp4"},
                    ]
                },
            )
            draft = PostDraft(
                artifact=artifact,
                platform="facebook",
                caption="Several views of the same signal.",
                hashtags=[],
            )
            result = FacebookAdapter(dry_run=True).publish(draft)
        self.assertTrue(result.success)
        self.assertEqual("multi_photo", result.raw_response["publish_kind"])
        self.assertEqual(3, len(result.raw_response["media_paths"]))

    def test_prepare_preserves_user_supplied_mentions_without_adding_fake_tags(self):
        artifact = Artifact(title="Signal Test")
        draft = PostDraft(
            artifact=artifact,
            platform="facebook",
            caption="Recovered with @AllenKTaylor already in the signal.",
            hashtags=[],
        )

        message = FacebookAdapter(dry_run=True).prepare(draft)

        self.assertEqual(1, message.lower().count("@allenktaylor"))
        self.assertNotIn("@chloekatastrophe", message.lower())

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

    def test_fetch_page_interactions_includes_manually_created_posts(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "data": [{
                "id": "page_manual_post_1",
                "message": "A manually published communication policy.",
                "created_time": "2026-07-22T18:00:00+0000",
                "permalink_url": "https://facebook.test/manual-post",
                "comments": {"data": [{
                    "id": "manual_comment_1",
                    "from": {"name": "Allen", "id": "fan_42"},
                    "message": "I remember this boundary.",
                    "created_time": "2026-07-22T18:05:00+0000",
                    "permalink_url": "https://facebook.test/manual-comment",
                }]},
            }]
        }

        with patch("frikshun_creator.publishers.facebook.requests.get", return_value=response):
            interactions = FacebookAdapter(
                dry_run=False, page_id="page", access_token="token"
            ).fetch_page_interactions()

        self.assertEqual(1, len(interactions))
        self.assertEqual("page_manual_post_1", interactions[0].external_post_id)
        self.assertEqual("manual_comment_1", interactions[0].external_id)
        self.assertEqual("I remember this boundary.", interactions[0].body)
        self.assertEqual(
            "A manually published communication policy.",
            interactions[0].raw_payload["source_post_message"],
        )

    def test_fetch_page_interactions_paginates_posts_and_comments(self):
        post_page_one = Mock(ok=True)
        post_page_one.json.return_value = {
            "data": [{
                "id": "post-1", "message": "First post", "comments": {
                    "data": [{"id": "comment-1", "message": "First comment"}],
                    "paging": {"next": "https://graph.facebook.test/post-1/comments?after=one"},
                }
            }],
            "paging": {"next": "https://graph.facebook.test/page/posts?after=one"},
        }
        comment_page_two = Mock(ok=True)
        comment_page_two.json.return_value = {
            "data": [{"id": "comment-2", "message": "Second comment"}]
        }
        post_page_two = Mock(ok=True)
        post_page_two.json.return_value = {
            "data": [{
                "id": "post-2", "message": "Older post",
                "comments": {"data": [{"id": "comment-3", "message": "Older comment"}]},
            }]
        }

        with patch(
            "frikshun_creator.publishers.facebook.requests.get",
            side_effect=[post_page_one, comment_page_two, post_page_two],
        ) as get:
            interactions = FacebookAdapter(
                dry_run=False, page_id="page", access_token="token"
            ).fetch_page_interactions()

        self.assertEqual(3, get.call_count)
        self.assertEqual(["comment-1", "comment-2", "comment-3"], [item.external_id for item in interactions])
        self.assertEqual(["post-1", "post-1", "post-2"], [item.external_post_id for item in interactions])


if __name__ == "__main__":
    unittest.main()
