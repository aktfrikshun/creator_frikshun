import unittest
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
