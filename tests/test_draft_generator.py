import unittest

from frikshun_creator.models import Artifact
from frikshun_creator.services.draft_generator import ArtifactDraftGenerator


class ArtifactDraftGeneratorTest(unittest.TestCase):
    def test_generates_all_platform_drafts(self):
        artifact = Artifact(
            title="Mirror Signal",
            summary="Chloe appears in a damaged mirror frame.",
            lore_text="Recovered from the studio archive.",
            content_tags=["archive", "mirror"],
            mood_tags=["haunted"],
        )

        drafts = ArtifactDraftGenerator(artifact).generate()

        self.assertEqual(7, len(drafts))
        self.assertEqual(
            {
                "facebook",
                "instagram",
                "youtube",
                "tiktok",
                "x",
                "fanvue",
                "chlokat_archive",
            },
            {draft["platform"] for draft in drafts},
        )

        facebook = next(draft for draft in drafts if draft["platform"] == "facebook")
        self.assertIn("This shot comes from", facebook["caption"])
        self.assertIn("archive", [tag.lower() for tag in facebook["hashtags"]])

    def test_media_analysis_is_composed_from_chloe_perspective(self):
        artifact = Artifact(
            title="Rain Room With The Old Telephone",
            summary="A noir visual fragment.",
            lore_text="Recovered from the studio archive.",
            content_tags=["portrait", "noir"],
            mood_tags=["rain", "watchful"],
            generated_metadata={
                "media_analysis": {
                    "description": "A woman leans near a desk in a rain-lit room.",
                    "what": "film noir portrait with vintage telephone and clock",
                    "where": "a rain-lit studio interior with venetian blinds",
                    "when": "late winter, near midnight",
                    "why": "to show Chloe as guarded, sensual, and unresolved",
                    "mood_tags": ["noir", "rain", "intimate"],
                }
            },
        )

        drafts = ArtifactDraftGenerator(artifact).generate()
        facebook = next(draft for draft in drafts if draft["platform"] == "facebook")

        self.assertIn(
            "This shot comes from a film noir portrait with vintage telephone and clock shoot we did",
            facebook["caption"],
        )
        self.assertIn("I wanted the image", facebook["caption"])
        self.assertIn("In the moment, I was thinking", facebook["caption"])
        self.assertNotIn("A woman", facebook["caption"])
        self.assertNotIn("The visible record", facebook["caption"])

    def test_media_analysis_copy_normalizes_raw_vision_phrases(self):
        artifact = Artifact(
            title="Midnight Rain in Sepia",
            summary="A noir visual fragment.",
            lore_text="Recovered from the studio archive.",
            content_tags=["portrait", "noir"],
            mood_tags=["mysterious"],
            generated_metadata={
                "media_analysis": {
                    "what": (
                        "A tense, cinematic portrait of a lone woman, drenched indoors as if caught "
                        "in a private storm."
                    ),
                    "where": (
                        "A dimly lit interior room that evokes mid-20th-century offices or apartments, "
                        "characterized by wooden blinds, a rotary phone, and a classic mantel clock."
                    ),
                    "when": (
                        "Ambiguous but likely nighttime or late evening, inferred from the lamp lighting "
                        "and the heavy shadows."
                    ),
                    "why": (
                        "Perhaps a moment captured in suspense or waiting, a private revelation or "
                        "confrontation imminent under the rain indoors."
                    ),
                    "mood_tags": ["noir", "mysterious", "tense", "sensual"],
                }
            },
        )

        facebook = next(
            draft for draft in ArtifactDraftGenerator(artifact).generate() if draft["platform"] == "facebook"
        )

        self.assertIn("This shot comes from a tense, cinematic portrait", facebook["caption"])
        self.assertIn("shoot we did in a dimly lit interior room", facebook["caption"])
        self.assertIn("I wanted the image to hold a moment captured in suspense", facebook["caption"])
        self.assertIn("\n\n", facebook["caption"])
        self.assertNotIn("from a A", facebook["caption"])
        self.assertNotIn("hold Perhaps", facebook["caption"])
        self.assertNotIn("..", facebook["caption"])

    def test_beach_location_and_craft_copy_do_not_use_room_language(self):
        artifact = Artifact(
            title="Beneath the Pier",
            summary="A beach portrait.",
            lore_text="Recovered from the studio archive.",
            content_tags=["portrait", "beach"],
            mood_tags=["contemplative"],
            generated_metadata={
                "media_analysis": {
                    "what": (
                        "A posed portrait of a woman on the beach under a pier, interacting with "
                        "the ocean water at her feet."
                    ),
                    "where": (
                        "on a sandy beach, under a long wooden pier extending over the ocean. "
                        "Exact location unknown."
                    ),
                    "when": (
                        "daytime, likely late morning or afternoon based on the angled shadows "
                        "and bright but soft sunlight."
                    ),
                    "why": (
                        "to capture a striking visual tension between the natural ocean environment "
                        "and the structured lines of the pier."
                    ),
                    "mood_tags": ["contemplative", "serene", "edgy", "natural"],
                }
            },
        )

        facebook = next(
            draft for draft in ArtifactDraftGenerator(artifact).generate() if draft["platform"] == "facebook"
        )

        self.assertIn("shoot we did on a sandy beach", facebook["caption"])
        self.assertIn("let the tide, the pier, and the light argue", facebook["caption"])
        self.assertIn("I wanted the image to capture", facebook["caption"])
        self.assertNotIn("in on a sandy beach", facebook["caption"])
        self.assertNotIn("let the room", facebook["caption"])


if __name__ == "__main__":
    unittest.main()
