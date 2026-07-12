import unittest

from frikshun_creator.models import Artifact, PostDraft
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


if __name__ == "__main__":
    unittest.main()
