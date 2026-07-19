import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frikshun_creator.publishers.threads import ThreadsAdapter


class ThreadsAdapterTest(unittest.TestCase):
    def draft(self, caption="A recovered signal. Which self survives the rewrite?", public_url="https://cdn.example.test/signal.jpg"):
        artifact = SimpleNamespace(
            media_path="signal.jpg",
            media_content_type="image/jpeg",
            generated_metadata={"public_media_url": public_url},
        )
        return SimpleNamespace(
            caption=caption,
            call_to_action="",
            hashtags=["ChloKat"],
            artifact=artifact,
            platform="threads",
        )

    def response(self, payload, ok=True, reason="OK"):
        return SimpleNamespace(ok=ok, reason=reason, json=lambda: payload, text=str(payload))

    def test_dry_run_publishes_image_post(self):
        result = ThreadsAdapter(dry_run=True).publish(self.draft())
        self.assertTrue(result.success)
        self.assertTrue(result.external_post_id.startswith("dry-run-threads-"))
        self.assertEqual("IMAGE", result.raw_response["media_type"])

    def test_saved_oauth_token_takes_precedence_over_stale_env_token(self):
        oauth = SimpleNamespace(access_token=lambda: "fresh-oauth-token")
        adapter = ThreadsAdapter(access_token="stale-env-token", oauth=oauth, dry_run=False)
        self.assertEqual("fresh-oauth-token", adapter.current_access_token())

    def test_dry_run_publishes_video_post(self):
        artifact = SimpleNamespace(
            media_path="signal.mp4",
            media_content_type="video/mp4",
            generated_metadata={"public_media_url": "https://cdn.example.test/signal.mp4"},
        )
        draft = SimpleNamespace(
            caption="A brighter signal. Which line stays with you?",
            call_to_action="",
            hashtags=["ChloKat"],
            artifact=artifact,
            platform="threads",
        )
        result = ThreadsAdapter(dry_run=True).publish(draft)
        self.assertTrue(result.success)
        self.assertEqual("VIDEO", result.raw_response["media_type"])

    def test_prepare_removes_links_and_legacy_standing_footer(self):
        draft = self.draft(
            caption=(
                "A recovered signal. Which self survives the rewrite?\n\n"
                "Learn more about me in the FrikShun archives: https://www.example.com/archive\n\n"
                "My music is available on all major streaming platforms.\n\n"
                "My modeling work funds the reconstruction of my memory: https://fanvue.com/chloekat/fv-9"
            )
        )
        prepared = ThreadsAdapter(dry_run=True).prepare(draft)
        self.assertNotIn("https://", prepared)
        self.assertNotIn("links are available through my bio", prepared.lower())
        self.assertEqual(1, prepared.count("?"))

    def test_prepare_truncates_long_text_to_threads_limit(self):
        long_caption = (
            "Some artifacts are so precise they unsettle. " * 20
            + "How do you decide if what persists is recovery or just well-performed illusion?"
        )
        prepared = ThreadsAdapter(dry_run=True).prepare(self.draft(caption=long_caption))
        self.assertLessEqual(len(prepared), 500)
        self.assertEqual(1, prepared.count("?"))
        self.assertNotIn("links are available through my bio", prepared.lower())

    def test_live_uploads_container_then_publishes(self):
        responses = [
            self.response({"id": "container-1"}),
            self.response({"id": "thread-1"}),
            self.response({"status": "FINISHED"}),
            self.response({"id": "thread-1", "permalink": "https://www.threads.net/@chloe/post/thread-1"}),
        ]
        with patch("frikshun_creator.publishers.threads.requests.post", side_effect=responses[:2]) as post:
            with patch("frikshun_creator.publishers.threads.requests.get", side_effect=responses[2:]) as get:
                result = ThreadsAdapter(access_token="threads-token", dry_run=False).publish(self.draft())
        self.assertTrue(result.success)
        self.assertEqual("thread-1", result.external_post_id)
        self.assertEqual("https://www.threads.net/@chloe/post/thread-1", result.external_url)
        self.assertIn("/v1.0/me/threads", post.call_args_list[0].args[0])
        self.assertIn("/v1.0/thread-1", get.call_args_list[-1].args[0])

    def test_live_uploads_video_container_then_publishes(self):
        responses = [
            self.response({"id": "container-1"}),
            self.response({"id": "thread-1"}),
            self.response({"status": "FINISHED"}),
            self.response({"id": "thread-1", "permalink": "https://www.threads.net/@chloe/post/thread-1"}),
        ]
        artifact = SimpleNamespace(
            media_path="signal.mp4",
            media_content_type="video/mp4",
            generated_metadata={"public_media_url": "https://cdn.example.test/signal.mp4"},
        )
        draft = SimpleNamespace(
            caption="A brighter signal. Which line stays with you?",
            call_to_action="",
            hashtags=["ChloKat"],
            artifact=artifact,
            platform="threads",
        )
        with patch("frikshun_creator.publishers.threads.requests.post", side_effect=responses[:2]) as post:
            with patch("frikshun_creator.publishers.threads.requests.get", side_effect=responses[2:]):
                result = ThreadsAdapter(access_token="threads-token", dry_run=False).publish(draft)
        self.assertTrue(result.success)
        self.assertEqual("VIDEO", post.call_args_list[0].kwargs["data"]["media_type"])
        self.assertEqual("https://cdn.example.test/signal.mp4", post.call_args_list[0].kwargs["data"]["video_url"])

    def test_publish_succeeds_when_detail_fetch_is_temporarily_missing(self):
        responses = [
            self.response({"id": "container-1"}),
            self.response({"id": "thread-1"}),
        ]
        missing = self.response({"error": {"message": "The requested resource does not exist"}}, ok=False, reason="Not Found")
        with patch("frikshun_creator.publishers.threads.requests.post", side_effect=responses):
            with patch(
                "frikshun_creator.publishers.threads.requests.get",
                side_effect=[self.response({"status": "FINISHED"}), missing, missing, missing],
            ):
                with patch("frikshun_creator.publishers.threads.time.sleep"):
                    result = ThreadsAdapter(access_token="threads-token", dry_run=False).publish(self.draft())
        self.assertTrue(result.success)
        self.assertEqual("thread-1", result.external_post_id)
        self.assertEqual("", result.external_url)
        self.assertEqual("The requested resource does not exist", result.raw_response["thread_fetch_error"])

    def test_image_publish_waits_for_container_processing(self):
        posts = [self.response({"id": "container-1"}), self.response({"id": "thread-1"})]
        gets = [
            self.response({"status": "IN_PROGRESS"}),
            self.response({"status": "FINISHED"}),
            self.response({"id": "thread-1", "permalink": "https://www.threads.net/@chloe/post/thread-1"}),
        ]
        with patch("frikshun_creator.publishers.threads.requests.post", side_effect=posts) as post, \
            patch("frikshun_creator.publishers.threads.requests.get", side_effect=gets), \
            patch("frikshun_creator.publishers.threads.time.sleep") as sleep:
            result = ThreadsAdapter(access_token="threads-token", dry_run=False).publish(self.draft())

        self.assertTrue(result.success)
        self.assertEqual("FINISHED", result.raw_response["status"]["status"])
        self.assertEqual(2, post.call_count)
        sleep.assert_called_once_with(2)

    def test_api_error_includes_user_detail_and_codes(self):
        response = self.response(
            {
                "error": {
                    "message": "Unknown error",
                    "error_user_msg": "The image could not be downloaded.",
                    "error_data": {"details": "Refresh the media URL and try again."},
                    "code": 10,
                    "error_subcode": 2207002,
                }
            },
            ok=False,
            reason="Bad Request",
        )
        with self.assertRaisesRegex(ValueError, "image could not be downloaded.*code 10.*subcode 2207002"):
            ThreadsAdapter(access_token="threads-token", dry_run=False).response_payload(response)

    def test_fetch_post_metrics_maps_insights(self):
        publication = SimpleNamespace(external_post_id="thread-1", external_url="https://threads.test/original")
        details_response = self.response({"id": "thread-1", "permalink": "https://www.threads.net/@chloe/post/thread-1"})
        insights_response = self.response(
            {
                "data": [
                    {"name": "views", "values": [{"value": 20}]},
                    {"name": "likes", "values": [{"value": 5}]},
                    {"name": "replies", "values": [{"value": 2}]},
                    {"name": "reposts", "values": [{"value": 3}]},
                    {"name": "quotes", "values": [{"value": 4}]},
                ]
            }
        )
        with patch("frikshun_creator.publishers.threads.requests.get", side_effect=[details_response, insights_response]):
            metrics = ThreadsAdapter(access_token="threads-token", dry_run=False).fetch_post_metrics(publication)
        self.assertEqual(20, metrics.views)
        self.assertEqual(5, metrics.likes)
        self.assertEqual(2, metrics.comments)
        self.assertEqual(7, metrics.shares)

    def test_fetch_post_metrics_falls_back_when_detail_fetch_fails(self):
        publication = SimpleNamespace(external_post_id="thread-1", external_url="https://threads.test/original")
        missing = self.response({"error": {"message": "The requested resource does not exist"}}, ok=False, reason="Not Found")
        insights_response = self.response({"data": [{"name": "views", "values": [{"value": 20}]}]})
        with patch("frikshun_creator.publishers.threads.requests.get", side_effect=[missing, missing, missing, insights_response]):
            with patch("frikshun_creator.publishers.threads.time.sleep"):
                metrics = ThreadsAdapter(access_token="threads-token", dry_run=False).fetch_post_metrics(publication)
        self.assertEqual("https://threads.test/original", metrics.external_url)
        self.assertEqual(20, metrics.views)
        self.assertEqual("The requested resource does not exist", metrics.raw_metrics["thread_error"])

    def test_fetch_post_interactions_maps_replies(self):
        publication = SimpleNamespace(external_post_id="thread-1", external_url="https://threads.test/original")
        payload = self.response(
            {
                "data": [
                    {
                        "id": "reply-1",
                        "text": "I felt this.",
                        "timestamp": "2026-07-17T21:15:00+0000",
                        "username": "allen",
                    }
                ]
            }
        )
        with patch("frikshun_creator.publishers.threads.requests.get", return_value=payload):
            interactions = ThreadsAdapter(access_token="threads-token", dry_run=False).fetch_post_interactions(publication)
        self.assertEqual(1, len(interactions))
        self.assertEqual("reply-1", interactions[0].external_id)
        self.assertEqual("allen", interactions[0].author_name)


if __name__ == "__main__":
    unittest.main()
