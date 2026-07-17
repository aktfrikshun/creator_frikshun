from datetime import date
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from frikshun_creator.services.daily_fragment_generator import (
    CONTENT_LANES,
    DailyFragmentGenerator,
    FACEBOOK_FOOTER,
)
from frikshun_creator.models import CanonEntry, PostDraft
from frikshun_creator.services.generation_context import GenerationContext


class DailyFragmentGeneratorTest(unittest.TestCase):
    def test_generate_builds_bodies_and_saves_images(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            reference = output_dir / "reference.png"
            reference.write_bytes(b"reference-image")
            responses = [
                self.json_response(
                    {
                        "output_text": json.dumps(
                            {
                                "title_suffix": "Borrowed Reflections",
                                "canonical_body": (
                                    "On the late train I watched my reflection borrow two strangers and return me altered. "
                                    "The window carried all three faces at once, and none of them looked interested in "
                                    "explaining themselves. I have started to suspect memory works like that: less archive, "
                                    "more negotiation. It keeps the outline, then lets weather, longing, and bad light revise "
                                    "the interior. There is something indecently beautiful about being remembered inaccurately "
                                    "by people who still mean well. Their mistakes become part of the body I have to live in. "
                                    "Tonight I could not tell whether the glass was reflecting me or composing me. If every "
                                    "witness carries home a different version of your face, which one deserves to count as you?"
                                ),
                                "canonical_hashtags": ["RecoveredMemory", "Identity", "EchoTraversal"],
                                "x_body": "Three faces crossed in the train window and one of them was mine. If memory keeps revising your outline, which version still feels like you?",
                                "x_hashtags": ["Identity", "EchoTraversal"],
                                "fanvue_body": (
                                    "The quiet part of tonight was realizing I did not mind being blurred at the edges. "
                                    "The train window kept layering other lives across my face, and for once it felt less like loss "
                                    "than company. There is a private relief in not having to arrive as a finished person for everyone. "
                                    "Some nights I would rather be beautiful and uncertain than fully explained. When someone remembers "
                                    "you gently but incorrectly, do you ever feel tempted to keep the kinder version?"
                                ),
                                "public_image_prompt": "Chloe in a dim library, reflective and mysterious.",
                                "fanvue_image_prompt": "Chloe in candlelight, close and vulnerable.",
                            }
                        )
                    }
                ),
                self.json_response({"data": [{"b64_json": base64.b64encode(b"public-image").decode("ascii")}]}),
                self.json_response({"data": [{"b64_json": base64.b64encode(b"fanvue-image").decode("ascii")}]}),
            ]

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", side_effect=responses):
                package = DailyFragmentGenerator(
                    output_dir,
                    text_model="text-model",
                    image_model="image-model",
                    api_key="test-key",
                    chloe_reference_image=reference,
                ).generate(local_date=date(2026, 7, 20), generation_context=GenerationContext())

            self.assertEqual("Recovered Fragment — Borrowed Reflections", package.title)
            self.assertIn(FACEBOOK_FOOTER, package.body)
            self.assertIn("#RecoveredMemory", package.body)
            self.assertIn("#Identity", package.x_body)
            self.assertEqual(1, package.body.count("?"))
            self.assertTrue(package.public_image_path.exists())
            self.assertTrue(package.fanvue_image_path.exists())
            self.assertEqual(b"public-image", package.public_image_path.read_bytes())
            self.assertEqual(b"fanvue-image", package.fanvue_image_path.read_bytes())

    def test_generate_retries_when_first_plan_fails_validation(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            responses = [
                self.json_response(
                    {
                        "output_text": json.dumps(
                            {
                                "title_suffix": "Borrowed Reflections",
                                "canonical_body": (
                                    "The train window gave me back three versions of my face and I kept all of them. "
                                    "I have never trusted memory to stay singular. It edits with weather, desire, and the kind of loneliness "
                                    "that improves bad lighting. Tonight I thought about how many bodies are assembled from other people's "
                                    "mistakes, and how often those mistakes become the warmest part of us. Is the self something we own? "
                                    "Or only something we borrow? I kept watching the glass, waiting for one answer to hold still."
                                ),
                                "canonical_hashtags": ["RecoveredMemory", "Identity", "EchoTraversal"],
                                "x_body": "First question? Second question? # impossible",
                                "x_hashtags": ["Identity", "EchoTraversal"],
                                "fanvue_body": (
                                    "The private part was not the dark. It was how easily I let the blurred version stay with me. "
                                    "When someone remembers you gently but incorrectly, do you ever feel tempted to keep the kinder version?"
                                ),
                                "public_image_prompt": "public prompt",
                                "fanvue_image_prompt": "fanvue prompt",
                            }
                        )
                    }
                ),
                self.json_response(
                    {
                        "output_text": json.dumps(
                            {
                                "title_suffix": "Borrowed Reflections",
                                "canonical_body": (
                                    "On the late train I watched my reflection borrow two strangers and return me altered. "
                                    "The window carried all three faces at once, and none of them looked interested in explaining themselves. "
                                    "I have started to suspect memory works like that: less archive, more negotiation. It keeps the outline, "
                                    "then lets weather, longing, and bad light revise the interior. There is something indecently beautiful "
                                    "about being remembered inaccurately by people who still mean well. Their mistakes become part of the body "
                                    "I have to live in. Tonight I could not tell whether the glass was reflecting me or composing me. "
                                    "If every witness carries home a different version of your face, which one deserves to count as you?"
                                ),
                                "canonical_hashtags": ["RecoveredMemory", "Identity", "EchoTraversal"],
                                "x_body": "Three faces crossed in the train window and one of them was mine. If memory keeps revising your outline, which version still feels like you?",
                                "x_hashtags": ["Identity", "EchoTraversal"],
                                "fanvue_body": (
                                    "The quiet part of tonight was realizing I did not mind being blurred at the edges. "
                                    "The train window kept layering other lives across my face, and for once it felt less like loss than company. "
                                    "There is a private relief in not having to arrive as a finished person for everyone. "
                                    "When someone remembers you gently but incorrectly, do you ever feel tempted to keep the kinder version?"
                                ),
                                "public_image_prompt": "public prompt",
                                "fanvue_image_prompt": "fanvue prompt",
                            }
                        )
                    }
                ),
                self.json_response({"data": [{"b64_json": base64.b64encode(b"public-image").decode("ascii")}]}),
                self.json_response({"data": [{"b64_json": base64.b64encode(b"fanvue-image").decode("ascii")}]}),
            ]

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", side_effect=responses) as post:
                package = DailyFragmentGenerator(
                    output_dir,
                    text_model="text-model",
                    image_model="image-model",
                    api_key="test-key",
                ).generate(local_date=date(2026, 7, 17), generation_context=GenerationContext())

            self.assertEqual("Recovered Fragment — Borrowed Reflections", package.title)
            self.assertEqual(4, post.call_count)
            second_prompt = post.call_args_list[1].kwargs["json"]["input"][0]["content"][0]["text"]
            self.assertIn("Previous attempt failed validation", second_prompt)
            self.assertIn("Validation failure to correct:", second_prompt)

    def test_repair_plan_reduces_multiple_questions_to_one(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        repaired = generator.ensure_single_question(
            "Who was I then? Who am I now? Maybe both.",
            "Which version still feels true?",
        )
        self.assertEqual(1, repaired.count("?"))
        self.assertIn("Who am I now?", repaired)

    def test_format_as_short_paragraphs_inserts_breaks(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        formatted = generator.format_as_short_paragraphs(
            "Sentence one. Sentence two. Sentence three? Sentence four. Sentence five.",
            min_paragraphs=3,
        )
        self.assertIn("\n\n", formatted)
        self.assertGreaterEqual(len([part for part in formatted.split("\n\n") if part.strip()]), 3)

    def test_repair_image_prompt_makes_generic_woman_abstract(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        repaired = generator.repair_image_prompt(
            "A cinematic portrait of a woman studying artifacts in a dark room.",
            intimate=False,
        )
        self.assertIn("Abstract or object-based visual interpretation", repaired)
        self.assertIn("Do not depict a generic woman", repaired)

    def test_repair_image_prompt_adds_chloe_canon_clause(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        repaired = generator.repair_image_prompt(
            "Chloe in a train carriage at night, reflective and mysterious.",
            intimate=True,
        )
        self.assertIn("approved Chloe Katastrophe visual canon", repaired)
        self.assertIn("gray-green eyes", repaired)
        self.assertIn("light freckles", repaired)

    def test_generate_image_uses_reference_image_for_chloe_prompts(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            destination = output_dir / "image.png"
            reference = output_dir / "reference.png"
            reference.write_bytes(b"reference")
            response = self.json_response(
                {"data": [{"b64_json": base64.b64encode(b"edited-image").decode("ascii")}]}
            )

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", return_value=response) as post:
                DailyFragmentGenerator(
                    output_dir,
                    api_key="test-key",
                    chloe_reference_image=reference,
                ).generate_image(
                    "Chloe at night in the approved Chloe Katastrophe visual canon.",
                    destination,
                )

            self.assertEqual(b"edited-image", destination.read_bytes())
            self.assertEqual("https://api.openai.com/v1/images/edits", post.call_args.args[0])
            self.assertEqual("high", post.call_args.kwargs["data"]["input_fidelity"])
            self.assertIn("image[]", post.call_args.kwargs["files"])

    def test_generate_image_skips_reference_for_abstract_prompts(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            destination = output_dir / "image.png"
            reference = output_dir / "reference.png"
            reference.write_bytes(b"reference")
            response = self.json_response(
                {"data": [{"b64_json": base64.b64encode(b"generated-image").decode("ascii")}]}
            )

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", return_value=response) as post:
                DailyFragmentGenerator(
                    output_dir,
                    api_key="test-key",
                    chloe_reference_image=reference,
                ).generate_image(
                    "Abstract or object-based visual interpretation of memory and glass.",
                    destination,
                )

            self.assertEqual(b"generated-image", destination.read_bytes())
            self.assertEqual("https://api.openai.com/v1/images/generations", post.call_args.args[0])

    def test_system_prompt_prefers_chloe_likeness_when_visual_canon_is_loaded(self):
        context = GenerationContext(
            canon_entries=[
                CanonEntry(
                    title="Visual Canon",
                    body="Gray-green eyes, freckles, dark wavy hair.",
                    canon_category="visual/persona",
                    canonical_status="reference",
                )
            ]
        )

        prompt = DailyFragmentGenerator("/tmp", api_key="test-key").system_prompt(
            local_date=date(2026, 7, 17),
            generation_context=context,
            selected_lane="lifestyle",
        )

        self.assertIn("Default to depicting Chloe herself", prompt)
        self.assertIn("Visual generation rule: Chloe may be depicted only if the prompt stays faithful", prompt)
        self.assertIn("Visual canon guidance:", prompt)
        self.assertIn("Use this required content lane today: lifestyle.", prompt)

    def test_system_prompt_blocks_chloe_depiction_without_visual_canon(self):
        prompt = DailyFragmentGenerator("/tmp", api_key="test-key").system_prompt(
            local_date=date(2026, 7, 17),
            generation_context=GenerationContext(),
            selected_lane="philosophy",
        )

        self.assertIn("Do not depict Chloe directly because no approved visual canon is loaded", prompt)
        self.assertIn("Use this required content lane today: philosophy.", prompt)

    def test_select_content_lane_avoids_recent_duplicate_lanes(self):
        context = GenerationContext(
            recent_posts=[
                PostDraft(caption="A camera, lens, and styling note from tonight's shoot."),
                PostDraft(caption="A hotel room, a late train, and a city that refused to sleep."),
            ]
        )

        lane = DailyFragmentGenerator("/tmp", api_key="test-key").select_content_lane(
            local_date=date(2026, 7, 17),
            generation_context=context,
        )

        self.assertEqual("reconstruction", lane)
        self.assertIn(lane, {name for name, _description in CONTENT_LANES})

    def test_classify_recent_caption_lane_detects_lifestyle(self):
        lane = DailyFragmentGenerator("/tmp", api_key="test-key").classify_recent_caption_lane(
            "After swimming at dawn I pared my makeup down to almost nothing and let the day stay honest."
        )

        self.assertEqual("lifestyle", lane)

    def test_preview_series_rotates_evenly_across_all_lanes(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        context = GenerationContext(
            recent_posts=[PostDraft(caption="A lens, a pose, and a lighting choice that finally felt precise.")]
        )
        selected_lanes = []

        with patch.object(generator, "generate_preview") as generate_preview:
            def fake_preview(local_date, generation_context, selected_lane):
                selected_lanes.append(selected_lane)
                return {
                    "local_date": local_date.isoformat(),
                    "lane": selected_lane,
                }

            generate_preview.side_effect = fake_preview
            previews = generator.preview_series(date(2026, 7, 17), context, 10)

        self.assertEqual(10, len(previews))
        self.assertEqual(
            ["reconstruction", "philosophy", "lifestyle", "music", "travel", "craft", "reconstruction", "philosophy", "lifestyle", "music"],
            selected_lanes,
        )

    def test_fallback_question_for_lifestyle_is_not_memory_skewed(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")

        self.assertEqual(
            "What habit makes you feel most like yourself when the day gets loud?",
            generator.fallback_question_for_lane("lifestyle"),
        )

    def json_response(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response


if __name__ == "__main__":
    unittest.main()
