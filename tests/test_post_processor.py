import unittest

from frikshun_creator.models import CanonEntry
from frikshun_creator.services.generation_context import GenerationContext
from frikshun_creator.services.post_processor import ChloePostProcessor


class ChloePostProcessorTest(unittest.TestCase):
    def test_beautifies_raw_vision_insertions_and_adds_paragraphs(self):
        raw = (
            "This shot is from a A tense, cinematic portrait of a lone woman. shoot we did in "
            "A dimly lit interior room. I wanted the image to hold Perhaps a moment captured "
            "in suspense.. We built the look with noir, mysterious. In the moment, I was "
            "thinking about Perhaps a private revelation. What do you think I was trying not "
            "to say out loud?"
        )

        processed = ChloePostProcessor().process_caption(raw, "facebook")

        self.assertIn("This shot is from a tense, cinematic portrait of me.", processed)
        self.assertIn("shoot we did in a dimly lit interior room.", processed)
        self.assertIn("I wanted the image to hold a moment captured in suspense.", processed)
        self.assertIn("\n\nWe built the look", processed)
        self.assertIn("\n\nIn the moment", processed)
        self.assertIn("\n\nWhat do you think", processed)
        self.assertNotIn("from a A", processed)
        self.assertNotIn("hold Perhaps", processed)
        self.assertNotIn("..", processed)

    def test_enforces_voice_signature_when_voice_canon_is_loaded(self):
        context = GenerationContext(
            canon_entries=[
                CanonEntry(
                    title="Voice",
                    body="Preserve Chloe's voice: intelligent, observant, emotionally restrained but vivid.",
                    canon_category="voice/persona",
                    canonical_status="voice_guidance",
                )
            ]
        )

        processed = ChloePostProcessor(context).process_draft(
            {
                "platform": "facebook",
                "caption": "This shot comes from a noir portrait shoot.",
                "hashtags": [],
            }
        )

        self.assertIn("I keep my own counsel", processed["caption"])

    def test_explicit_character_limit_prefers_complete_paragraphs(self):
        raw = (
            "This shot comes from a noir portrait shoot.\n\n"
            "I wanted the image to feel like evidence, but not the kind that behaves itself.\n\n"
            "We built the look with rain, shadow, and one deliberate pulse of light."
        )

        processed = ChloePostProcessor().process_caption(raw, "facebook", character_limit=80)

        self.assertLessEqual(len(processed), 80)
        self.assertEqual("This shot comes from a noir portrait shoot.", processed)

    def test_explicit_character_limit_truncates_without_breaking_words(self):
        raw = "This sentence is too long to keep whole when the platform budget is tiny."

        processed = ChloePostProcessor().process_caption(raw, "facebook", character_limit=40)

        self.assertLessEqual(len(processed), 40)
        self.assertTrue(processed.endswith("..."))
        self.assertNotIn("  ", processed)

    def test_process_draft_uses_platform_default_limit(self):
        raw = (
            "This shot comes from a noir portrait shoot we did in a room built from rain and bad timing. "
            "I wanted the image to feel like evidence, but not the kind that behaves itself. "
            "We built the look with shadow, restraint, and one deliberate pulse of light."
        )

        processed = ChloePostProcessor().process_draft(
            {
                "platform": "x",
                "caption": raw,
                "hashtags": [],
            }
        )

        self.assertLessEqual(len(processed["caption"]), 280)


if __name__ == "__main__":
    unittest.main()
