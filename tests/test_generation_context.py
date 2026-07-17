import unittest

from frikshun_creator.models import CanonEntry
from frikshun_creator.services.generation_context import GenerationContext


class GenerationContextTest(unittest.TestCase):
    def test_visual_excerpt_prioritizes_visual_persona_and_visual_archive_entries(self):
        context = GenerationContext(
            canon_entries=[
                CanonEntry(
                    title="Visual Canon",
                    body="Gray-green eyes, freckles, dark wavy hair.",
                    canon_category="visual/persona",
                    canonical_status="reference",
                ),
                CanonEntry(
                    title="Visual Guide",
                    body="Anti-drift rules for Chloe depictions.",
                    canon_category="visuals",
                    canonical_status="reference",
                ),
                CanonEntry(
                    title="Voice",
                    body="Preserve Chloe's voice.",
                    canon_category="voice/persona",
                    canonical_status="voice_guidance",
                ),
            ]
        )

        excerpt = context.visual_excerpt

        self.assertIn("Visual Canon: Gray-green eyes", excerpt)
        self.assertIn("Visual Guide: Anti-drift rules", excerpt)
        self.assertNotIn("Voice:", excerpt)
        self.assertTrue(context.has_visual_chloe_guidance)


if __name__ == "__main__":
    unittest.main()
