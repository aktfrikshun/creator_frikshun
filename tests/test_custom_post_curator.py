import unittest

from frikshun_creator.services.custom_post_curator import (
    CUSTOM_POST_PLATFORMS,
    CustomPostCurator,
)


class CustomPostCuratorTest(unittest.TestCase):
    def test_curates_all_live_platforms_and_preserves_source_meaning(self):
        source = "I found this frame in the archive. It still knows more than I do."
        drafts = CustomPostCurator(source, ["recovered memory"]).curate()

        self.assertEqual(list(CUSTOM_POST_PLATFORMS), [draft["platform"] for draft in drafts])
        self.assertTrue(all(draft["status"] == "draft" for draft in drafts))
        self.assertTrue(all(draft["caption"].startswith("I found this frame") for draft in drafts))
        instagram = next(draft for draft in drafts if draft["platform"] == "instagram")
        self.assertIn("recoveredmemory", instagram["hashtags"])

    def test_x_copy_is_shortened_at_a_readable_boundary(self):
        source = ("The archive returned another detail. " * 20).strip()
        draft = CustomPostCurator(source).draft_for("x")

        prepared_length = len(draft["caption"]) + 2 + len(
            " ".join(f"#{tag}" for tag in draft["hashtags"])
        )
        self.assertLessEqual(prepared_length, 280)
        self.assertTrue(draft["caption"].endswith((".", "...")))


if __name__ == "__main__":
    unittest.main()
