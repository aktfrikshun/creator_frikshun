import unittest
from unittest.mock import Mock, patch

from frikshun_creator.models import Artifact, PostDraft, PostPublication
from frikshun_creator.publishers.instagram import InstagramAdapter


class InstagramAdapterTest(unittest.TestCase):
    def draft(self, content_type="image/jpeg", public_url="https://cdn.example.test/signal.jpg"):
        artifact = Artifact(
            title="Signal",
            media_path="/local/signal.jpg",
            media_content_type=content_type,
            generated_metadata={"public_media_url": public_url} if public_url else {},
        )
        return PostDraft(
            artifact=artifact,
            platform="instagram",
            caption="A recovered signal.",
            hashtags=["ChloKat"],
        )

    def response(self, payload):
        response = Mock()
        response.ok = True
        response.json.return_value = payload
        return response

    def test_dry_run_returns_container_preview(self):
        result = InstagramAdapter(dry_run=True).publish(self.draft())

        self.assertTrue(result.success)
        self.assertTrue(result.external_post_id.startswith("dry-run-instagram-"))
        self.assertEqual("https://cdn.example.test/signal.jpg", result.raw_response["media_url"])
        self.assertIn("#ChloKat", result.raw_response["caption"])

    def test_prepare_removes_urls_and_replaces_standing_footer(self):
        draft = self.draft()
        draft.caption = (
            "A recovered signal.\n\n"
            "Learn more about me in the FrikShun archives: "
            "https://www.frikshun.com/archives/chloe-katastrophe/site\n\n"
            "My music is available on all major streaming platforms.\n\n"
            "My modeling work funds the reconstruction of my memory: "
            "https://fanvue.com/chloekat/fv-9"
        )

        caption = InstagramAdapter(dry_run=True).prepare(draft)

        self.assertNotIn("http", caption)
        self.assertNotIn("FanVue", caption)
        self.assertNotIn("funds", caption)
        self.assertIn("links are available through my bio", caption)
        self.assertTrue(caption.endswith("#ChloKat"))

    def test_rejects_missing_public_https_url(self):
        result = InstagramAdapter(dry_run=True).publish(self.draft(public_url=""))

        self.assertFalse(result.success)
        self.assertIn("public HTTPS media URL", result.error_message)

    def test_rejects_non_jpeg_artifact(self):
        result = InstagramAdapter(dry_run=True).publish(self.draft(content_type="image/png"))

        self.assertFalse(result.success)
        self.assertIn("JPEG", result.error_message)

    def test_dry_run_returns_reel_preview_for_video(self):
        result = InstagramAdapter(dry_run=True).publish(
            self.draft(content_type="video/mp4", public_url="https://cdn.example.test/signal.mp4")
        )

        self.assertTrue(result.success)
        self.assertEqual("reel", result.raw_response["publish_kind"])
        self.assertEqual("https://cdn.example.test/signal.mp4", result.raw_response["media_url"])

    def test_live_publish_creates_waits_and_publishes_container(self):
        post_responses = [
            self.response({"id": "container_1"}),
            self.response({"id": "media_1"}),
        ]
        get_responses = [
            self.response({"status_code": "IN_PROGRESS", "status": "Processing"}),
            self.response({"status_code": "FINISHED"}),
            self.response({"permalink": "https://www.instagram.com/p/example/"}),
        ]

        with patch("frikshun_creator.publishers.instagram.requests.post", side_effect=post_responses) as post:
            with patch("frikshun_creator.publishers.instagram.requests.get", side_effect=get_responses) as get:
                result = InstagramAdapter(
                    dry_run=False,
                    user_id="ig_1",
                    access_token="token",
                    status_attempts=2,
                    status_delay=0,
                ).publish(self.draft())

        self.assertTrue(result.success)
        self.assertEqual("media_1", result.external_post_id)
        self.assertEqual("https://www.instagram.com/p/example/", result.external_url)
        self.assertIn("ig_1/media", post.call_args_list[0].args[0])
        self.assertIn("ig_1/media_publish", post.call_args_list[1].args[0])
        self.assertEqual("container_1", post.call_args_list[1].kwargs["data"]["creation_id"])
        self.assertEqual(3, get.call_count)

    def test_live_video_publish_creates_reel_container(self):
        post_responses = [
            self.response({"id": "container_1"}),
            self.response({"id": "media_1"}),
        ]
        get_responses = [
            self.response({"status_code": "FINISHED"}),
            self.response({"permalink": "https://www.instagram.com/reel/example/"}),
        ]

        with patch("frikshun_creator.publishers.instagram.requests.post", side_effect=post_responses) as post:
            with patch("frikshun_creator.publishers.instagram.requests.get", side_effect=get_responses):
                result = InstagramAdapter(
                    dry_run=False,
                    user_id="ig_1",
                    access_token="token",
                    status_attempts=1,
                    status_delay=0,
                ).publish(self.draft(content_type="video/mp4", public_url="https://cdn.example.test/signal.mp4"))

        self.assertTrue(result.success)
        self.assertEqual("reel", result.raw_response["publish_kind"])
        self.assertEqual("REELS", post.call_args_list[0].kwargs["data"]["media_type"])
        self.assertEqual("https://cdn.example.test/signal.mp4", post.call_args_list[0].kwargs["data"]["video_url"])

    def test_live_api_error_returns_failed_result_with_meta_message(self):
        response = Mock()
        response.ok = False
        response.reason = "Bad Request"
        response.json.return_value = {"error": {"message": "Invalid image URL"}}

        with patch("frikshun_creator.publishers.instagram.requests.post", return_value=response):
            result = InstagramAdapter(
                dry_run=False,
                user_id="ig_1",
                access_token="token",
            ).publish(self.draft())

        self.assertFalse(result.success)
        self.assertEqual("failed", result.status)
        self.assertIn("Invalid image URL", result.error_message)

    def test_fetch_metrics_and_comments(self):
        publication = PostPublication(
            platform="instagram",
            status="published",
            external_post_id="media_1",
            external_url="https://instagram.test/original",
        )
        responses = [
            self.response(
                {
                    "permalink": "https://instagram.test/current",
                    "like_count": 12,
                    "comments_count": 2,
                }
            ),
            self.response(
                {
                    "data": [
                        {"name": "views", "values": [{"value": 120}]},
                        {"name": "reach", "values": [{"value": 80}]},
                        {"name": "saved", "values": [{"value": 3}]},
                        {"name": "shares", "values": [{"value": 4}]},
                    ]
                }
            ),
            self.response(
                {
                    "data": [
                        {
                            "id": "comment_1",
                            "username": "archivist",
                            "text": "I remember this room.",
                            "timestamp": "2026-07-16T18:30:00+0000",
                        }
                    ]
                }
            ),
        ]
        with patch("frikshun_creator.publishers.instagram.requests.get", side_effect=responses):
            adapter = InstagramAdapter(dry_run=False, user_id="ig_1", access_token="token")
            metrics = adapter.fetch_post_metrics(publication)
            comments = adapter.fetch_post_interactions(publication)

        self.assertEqual(12, metrics.likes)
        self.assertEqual(2, metrics.comments)
        self.assertEqual(120, metrics.views)
        self.assertEqual(80, metrics.reach)
        self.assertEqual(3, metrics.saves)
        self.assertEqual(4, metrics.shares)
        self.assertEqual("https://instagram.test/current", metrics.external_url)
        self.assertEqual("archivist", comments[0].author_name)
        self.assertEqual("I remember this room.", comments[0].body)


if __name__ == "__main__":
    unittest.main()
