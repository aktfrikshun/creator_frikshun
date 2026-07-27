import json
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

    def test_prepare_removes_urls_and_legacy_standing_footer(self):
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
        self.assertNotIn("links are available through my bio", caption)
        self.assertTrue(caption.endswith("#ChloKat"))

    def test_rejects_missing_public_https_url(self):
        result = InstagramAdapter(dry_run=True).publish(self.draft(public_url=""))

        self.assertFalse(result.success)
        self.assertIn("public HTTPS media URL", result.error_message)

    def test_rejects_non_jpeg_artifact(self):
        result = InstagramAdapter(dry_run=True).publish(self.draft(content_type="image/png"))

        self.assertFalse(result.success)
        self.assertIn("JPEG", result.error_message)

    def test_accepts_png_artifact_when_public_media_was_converted_to_jpeg(self):
        draft = self.draft(content_type="image/png")
        draft.artifact.generated_metadata["public_media_content_type"] = "image/jpeg"

        result = InstagramAdapter(dry_run=True).publish(draft)

        self.assertTrue(result.success)

    def test_dry_run_returns_reel_preview_for_video(self):
        result = InstagramAdapter(dry_run=True).publish(
            self.draft(content_type="video/mp4", public_url="https://cdn.example.test/signal.mp4")
        )

        self.assertTrue(result.success)
        self.assertEqual("reel", result.raw_response["publish_kind"])
        self.assertEqual("https://cdn.example.test/signal.mp4", result.raw_response["media_url"])

    def test_dry_run_builds_mixed_media_carousel(self):
        draft = self.draft()
        draft.artifact.generated_metadata["additional_media"] = [
            {
                "media_path": "/local/motion.mp4",
                "media_content_type": "video/mp4",
                "public_media_url": "https://cdn.example.test/motion.mp4",
            }
        ]
        result = InstagramAdapter(dry_run=True).publish(draft)
        self.assertTrue(result.success)
        self.assertEqual("carousel", result.raw_response["publish_kind"])
        self.assertEqual(2, len(result.raw_response["media_urls"]))

    def test_carousel_children_use_extended_processing_wait(self):
        draft = self.draft()
        draft.artifact.generated_metadata["additional_media"] = [
            {
                "media_path": "/local/detail.jpg",
                "media_content_type": "image/jpeg",
                "public_media_url": "https://cdn.example.test/detail.jpg",
            }
        ]
        adapter = InstagramAdapter(
            dry_run=False,
            user_id="ig_1",
            access_token="token",
            status_attempts=2,
            status_delay=0,
        )
        with patch.object(
            adapter,
            "graph_post",
            side_effect=[
                {"id": "child-1"},
                {"id": "child-2"},
                {"id": "parent-1"},
                {"id": "media-1"},
            ],
        ), patch.object(
            adapter,
            "wait_for_container",
            return_value={"status_code": "FINISHED"},
        ) as wait, patch.object(
            adapter,
            "fetch_media",
            return_value={"permalink": "https://instagram.test/carousel"},
        ):
            result = adapter.publish(draft)
        self.assertTrue(result.success)
        self.assertEqual([180, 180], [call.kwargs["attempts"] for call in wait.call_args_list[:2]])

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
        self.assertNotIn("user_tags", post.call_args_list[0].kwargs["data"])

    def test_live_image_publish_sends_real_user_tags(self):
        adapter = InstagramAdapter(
            dry_run=False,
            user_id="ig_1",
            access_token="token",
            tag_usernames=["@allenktaylor", "chloekatastrophe"],
        )

        with patch.object(adapter, "graph_post", return_value={"id": "container"} ) as graph_post:
            adapter.create_container(self.draft(), "https://cdn.example.test/signal.jpg", "Signal.")

        tags = json.loads(graph_post.call_args.args[1]["user_tags"])
        self.assertEqual(["allenktaylor", "chloekatastrophe"], [tag["username"] for tag in tags])
        self.assertEqual([0.333, 0.667], [tag["x"] for tag in tags])

    def test_carousel_only_tags_photo_children(self):
        adapter = InstagramAdapter(
            dry_run=False,
            user_id="ig_1",
            access_token="token",
            tag_usernames=["allenktaylor"],
            status_delay=0,
        )
        media = [
            {"media_content_type": "image/jpeg", "public_media_url": "https://cdn.test/a.jpg"},
            {"media_content_type": "video/mp4", "public_media_url": "https://cdn.test/b.mp4"},
        ]
        with patch.object(
            adapter,
            "graph_post",
            side_effect=[{"id": "image-child"}, {"id": "video-child"}, {"id": "parent"}],
        ) as graph_post, patch.object(
            adapter,
            "wait_for_container",
            return_value={"status_code": "FINISHED"},
        ):
            adapter.create_carousel(media, "Signal.")

        self.assertIn("user_tags", graph_post.call_args_list[0].args[1])
        self.assertNotIn("user_tags", graph_post.call_args_list[1].args[1])

    def test_invalid_photo_tag_retries_without_failing_the_post(self):
        adapter = InstagramAdapter(
            dry_run=False,
            user_id="ig_1",
            access_token="token",
            tag_usernames=["invalidaccount"],
        )
        with patch.object(
            adapter,
            "graph_post",
            side_effect=[ValueError("Invalid user id"), {"id": "untagged-container"}],
        ) as graph_post:
            container = adapter.create_container(
                self.draft(),
                "https://cdn.example.test/signal.jpg",
                "Signal.",
            )

        self.assertEqual("untagged-container", container["id"])
        self.assertIn("user_tags", graph_post.call_args_list[0].args[1])
        self.assertNotIn("user_tags", graph_post.call_args_list[1].args[1])
        self.assertEqual(1, len(adapter.tag_warnings))

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

    def test_fetch_account_interactions_covers_media_outside_creator_os(self):
        adapter = InstagramAdapter(dry_run=False, user_id="ig_1", access_token="token")
        adapter.graph_request_url = Mock(side_effect=[
            {"id": "ig_1", "username": "chloekat"},
            {"data": [{
                "id": "media_older", "caption": "Recovered room.",
                "permalink": "https://instagram.test/p/older", "timestamp": "2026-07-01T12:00:00Z",
            }]},
            {"data": [
                {
                    "id": "comment_older", "username": "archivist", "text": "Still listening.",
                    "from": {"id": "fan_1", "username": "archivist"},
                    "timestamp": "2026-07-22T12:00:00Z",
                },
                {
                    "id": "comment_answered", "username": "another_fan", "text": "Already answered.",
                    "from": {"id": "fan_2", "username": "another_fan"},
                    "replies": {"data": [{"id": "our_reply", "from": {"id": "ig_1", "username": "chloekat"}}]},
                },
                {
                    "id": "comment_ours", "username": "chloekat", "text": "Our own comment.",
                    "from": {"id": "ig_1", "username": "chloekat"},
                },
            ]},
        ])

        interactions = adapter.fetch_account_interactions()

        self.assertEqual(3, len(interactions))
        self.assertEqual("media_older", interactions[0].external_post_id)
        self.assertEqual("fan_1", interactions[0].author_platform_id)
        self.assertEqual("https://instagram.test/p/older", interactions[0].raw_payload["source_post_permalink"])
        self.assertTrue(interactions[1].raw_payload["already_replied_by_us"])
        self.assertTrue(interactions[2].raw_payload["is_owned_by_me"])

    def test_dry_run_reply_to_comment(self):
        payload = InstagramAdapter(dry_run=True).reply_to_comment("comment_1", "I hear you.")
        self.assertEqual("dry-run-instagram-reply-comment_1", payload["id"])


if __name__ == "__main__":
    unittest.main()
