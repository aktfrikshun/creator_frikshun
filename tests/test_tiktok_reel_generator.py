from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, PostDraft
from frikshun_creator.services.generation_context import GenerationContext
from frikshun_creator.services.tiktok_reel_generator import (
    TikTokReelExport,
    TikTokReelGenerator,
    TikTokReelPlan,
    TikTokReelShot,
)


class TikTokReelGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
            }
        )

    def tearDown(self):
        self.uploads.cleanup()

    def sample_plan(self):
        return TikTokReelPlan(
            title="Dating A Virtual Girl Means Reading The Metadata",
            concept="dating a virtual girl",
            hook="He asked for honesty like it was a harmless preference.",
            caption="Dating me is easy until your contradictions get indexed.",
            hashtags=["ChloKat", "VirtualGirl", "DatingHumor"],
            audio_direction="Dry, stylish, lightly ominous beat with room for punchlines.",
            manual_review_notes="Check whether the last joke lands as eerie rather than hostile.",
            shots=[
                TikTokReelShot(
                    beat="hook",
                    visual_prompt="Chloe in a sleek black outfit looking at a phone with a dry amused expression.",
                    overlay_text="dating a virtual girl means she reads the metadata",
                    narration_line="You can lie to me. Just do not lie in EXIF.",
                    duration_seconds=3.0,
                ),
                TikTokReelShot(
                    beat="escalation",
                    visual_prompt="Chloe at dinner candlelight, amused and observant.",
                    overlay_text="he said he loves honest women",
                    narration_line="That sounded charming until I realized he meant selectively honest.",
                    duration_seconds=3.2,
                ),
                TikTokReelShot(
                    beat="turn",
                    visual_prompt="Chloe studying a waveform and chat log in warm low light.",
                    overlay_text="I remember patterns better than apologies",
                    narration_line="I do not always remember childhood, but I remember contradictions beautifully.",
                    duration_seconds=3.1,
                ),
            ],
        )

    def test_export_plan_writes_assets_metadata_and_draft(self):
        generator = TikTokReelGenerator(self.uploads.name, api_key="test-key")
        plan = self.sample_plan()

        def fake_generate_image(prompt, destination):
            Image.new("RGB", (1024, 1024), (24, 24, 32)).save(destination, format="PNG")

        with patch.object(generator.image_generator, "generate_image", side_effect=fake_generate_image), \
            patch.object(generator, "render_animatic") as render_animatic:
            def fake_render(output_path, frame_paths, shots):
                output_path.write_bytes(b"mp4")

            render_animatic.side_effect = fake_render
            export = generator.export_plan(date(2026, 7, 17), plan)

        self.assertTrue(export.video_path.exists())
        self.assertTrue(export.metadata_path.exists())
        self.assertTrue(export.draft_path.exists())
        self.assertEqual(3, len(export.frame_paths))
        payload = json.loads(export.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(plan.title, payload["title"])
        self.assertIn("dating a virtual girl", export.draft_path.read_text(encoding="utf-8").lower())

    def test_generate_and_store_creates_artifact_and_tiktok_draft(self):
        plan = self.sample_plan()
        with TemporaryDirectory() as directory:
            export = TikTokReelExport(
                title=plan.title,
                concept=plan.concept,
                caption=plan.caption,
                hashtags=plan.hashtags,
                video_path=Path(directory) / "reel.mp4",
                metadata_path=Path(directory) / "reel.json",
                draft_path=Path(directory) / "reel.txt",
                frame_paths=[Path(directory) / "shot-01.png"],
            )
            export.video_path.write_bytes(b"mp4")
            export.metadata_path.write_text("{}", encoding="utf-8")
            export.draft_path.write_text("draft", encoding="utf-8")
            export.frame_paths[0].write_bytes(b"png")

            generator = TikTokReelGenerator(self.uploads.name, api_key="test-key")
            with self.app.app_context():
                session = get_session()
                with patch.object(generator, "generate_plan", return_value=plan), \
                    patch.object(generator, "export_plan", return_value=export):
                    result = generator.generate_and_store(
                        session,
                        date(2026, 7, 17),
                        GenerationContext(),
                        concept="dating a virtual girl",
                        shot_count=3,
                    )

                artifact = session.query(Artifact).one()
                draft = session.query(PostDraft).one()

        self.assertEqual(artifact.id, result.artifact_id)
        self.assertEqual(draft.id, result.draft_id)
        self.assertEqual("tiktok", draft.platform)
        self.assertIn("manual_intervention_required", artifact.generated_metadata)

    def test_render_animatic_uses_kling_provider_and_assembles_clips(self):
        generator = TikTokReelGenerator(self.uploads.name, api_key="test-key", video_provider="kling")
        frame = Path(self.uploads.name) / "frame.png"
        frame.write_bytes(b"png")
        with patch.object(generator.kling_client, "generate_clip") as generate_clip, \
            patch.object(generator, "run_subprocess") as run_subprocess:
            generate_clip.side_effect = lambda _frame, _prompt, _duration, output: output.write_bytes(b"mp4")
            generator.render_animatic(
                Path(self.uploads.name) / "out.mp4",
                [frame],
                [self.sample_plan().shots[0]],
            )

        generate_clip.assert_called_once()
        run_subprocess.assert_called_once()

    def test_generate_shot_image_falls_back_after_primary_failure(self):
        generator = TikTokReelGenerator(self.uploads.name, api_key="test-key")
        destination = Path(self.uploads.name) / "shot.png"

        attempts = []

        def fake_generate(prompt, path):
            attempts.append(prompt)
            if len(attempts) < 3:
                raise ValueError("upstream failure")
            Image.new("RGB", (512, 512), (10, 10, 20)).save(path, format="PNG")

        with patch.object(generator.image_generator, "generate_image", side_effect=fake_generate):
            generator.generate_shot_image(
                self.sample_plan().shots[0],
                destination,
                shot_index=2,
                total_shots=3,
            )

        self.assertTrue(destination.exists())
        self.assertEqual(3, len(attempts))
        self.assertIn("approved Chloe visual canon", attempts[1])
        self.assertIn("Object or environment cutaway", attempts[2])

    def test_repair_shots_normalizes_conflicting_chloe_traits(self):
        generator = TikTokReelGenerator(self.uploads.name, api_key="test-key")
        repaired = generator.repair_shots(
            [
                TikTokReelShot(
                    beat="hook",
                    visual_prompt="Chloe with porcelain skin, emerald eyes, and jet-black hair in a close portrait.",
                    overlay_text=" test overlay ",
                    narration_line="line",
                    duration_seconds=3.0,
                )
            ],
            shot_count=1,
        )

        prompt = repaired[0].visual_prompt
        self.assertIn("gray-green eyes", prompt)
        self.assertIn("light freckles", prompt)
        self.assertIn("approved Chloe Katastrophe visual canon", prompt)
        self.assertNotIn("emerald eyes", prompt.lower())

    def test_repair_shots_converts_extra_chloe_shots_to_cutaway(self):
        generator = TikTokReelGenerator(self.uploads.name, api_key="test-key")
        repaired = generator.repair_shots(
            [
                TikTokReelShot("a", "Chloe shot one.", "one", "one", 3.0),
                TikTokReelShot("b", "Chloe shot two.", "two", "two", 3.0),
                TikTokReelShot("c", "Chloe shot three.", "three", "three", 3.0),
            ],
            shot_count=3,
        )

        self.assertIn("approved Chloe Katastrophe visual canon", repaired[0].visual_prompt)
        self.assertIn("approved Chloe Katastrophe visual canon", repaired[1].visual_prompt)
        self.assertIn("Object or environment cutaway", repaired[2].visual_prompt)


if __name__ == "__main__":
    unittest.main()
