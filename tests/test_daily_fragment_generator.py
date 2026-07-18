from datetime import date
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import requests

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
            self.assertLessEqual(len(package.threads_body), 500)
            self.assertEqual(1, package.threads_body.count("?"))
            self.assertIn("Archive, music, and modeling links are available through my bio.", package.threads_body)
            self.assertIn("#Identity", package.x_body)
            self.assertEqual(1, package.body.count("?"))
            self.assertEqual(["recovered-fragment", "identity", "echo-traversal"], package.content_tags)
            self.assertTrue(package.public_image_path.exists())
            self.assertTrue(package.fanvue_image_path.exists())
            self.assertEqual(b"public-image", package.public_image_path.read_bytes())
            self.assertEqual(package.public_image_path, package.fanvue_image_path)
            self.assertEqual(b"public-image", package.fanvue_image_path.read_bytes())

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
            ]

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", side_effect=responses) as post:
                package = DailyFragmentGenerator(
                    output_dir,
                    text_model="text-model",
                    image_model="image-model",
                    api_key="test-key",
                ).generate(local_date=date(2026, 7, 17), generation_context=GenerationContext())

            self.assertEqual("Recovered Fragment — Borrowed Reflections", package.title)
            self.assertEqual(3, post.call_count)
            second_prompt = post.call_args_list[1].kwargs["json"]["input"][0]["content"][0]["text"]
            self.assertIn("Previous attempt failed validation", second_prompt)
            self.assertIn("Validation failure to correct:", second_prompt)

    def test_generate_plan_retries_after_rate_limit(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            rate_limited = Mock()
            rate_limited.status_code = 429
            rate_limited.headers = {"retry-after": "1"}
            rate_limited.raise_for_status.side_effect = requests.HTTPError(
                "429 Client Error: Too Many Requests",
                response=rate_limited,
            )
            successful = self.json_response(
                {
                    "output_text": json.dumps(
                        {
                            "title_suffix": "Borrowed Reflections",
                            "canonical_body": "One paragraph. Two paragraph. Three paragraph. Which version remains?",
                            "canonical_hashtags": ["RecoveredMemory", "Identity"],
                            "x_body": "Which version remains?",
                            "x_hashtags": ["Identity"],
                            "fanvue_body": "Closer thought. Softer light. Which version remains?",
                            "public_image_prompt": "Chloe smiling, engaged, curious.",
                            "fanvue_image_prompt": "Chloe close, flirty, warm, curious.",
                        }
                    )
                }
            )

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", side_effect=[rate_limited, successful]) as post:
                with patch("frikshun_creator.services.daily_fragment_generator.time.sleep") as sleep:
                    plan = DailyFragmentGenerator(
                        output_dir,
                        api_key="test-key",
                        openai_rate_limit_retries=2,
                    ).generate_plan(
                        local_date=date(2026, 7, 17),
                        generation_context=GenerationContext(),
                        selected_lane="lifestyle",
                    )

            self.assertEqual("Borrowed Reflections", plan.title_suffix)
            self.assertEqual(2, post.call_count)
            sleep.assert_called_once_with(1)

    def test_title_prefix_and_tags_follow_lane(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        self.assertEqual("Chloe Thinking", generator.title_prefix_for_lane("philosophy"))
        self.assertEqual("Field Note", generator.title_prefix_for_lane("travel"))
        self.assertEqual(["philosophy", "identity", "discussion"], generator.content_tags_for_lane("philosophy"))
        self.assertEqual(["travel", "place", "movement"], generator.content_tags_for_lane("travel"))

    def test_validate_plan_blocks_reconstruction_framing_for_non_reconstruction_lane(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        plan = type(
            "Plan",
            (),
            {
                "title_suffix": "Recovered Fragment from the Archive",
                "canonical_body": (
                    "I keep circling the same recovered fragment and calling it philosophy. "
                    "The archival scanner keeps turning ordinary light into a story about damage. "
                    "I know better than to pretend every thought is a relic, but the habit lingers. "
                    "Today I wanted a cleaner question and still found myself speaking like a museum label. "
                    "That kind of drift is exactly what makes these prompts feel smaller than they should. "
                    "Maybe the real challenge is learning to think without dressing every idea in dust and loss. "
                    "When a thought arrives without wreckage, can you still trust it?\n\n"
                    "I am trying to let philosophy stay alive in the present tense instead of embalming it. "
                    "There is more heat in a live question than in a preserved one, and more risk too. "
                    "I would rather sound awake than archival."
                ),
                "x_body": "When a thought arrives without wreckage, can you still trust it?",
                "x_hashtags": ["Identity"],
                "fanvue_body": "A live question feels warmer than an archived one.\n\nWhen a thought arrives without wreckage, can you still trust it?",
                "public_image_prompt": "Chloe curious and bright.",
                "fanvue_image_prompt": "Chloe close, warm, and bright.",
            },
        )()
        with self.assertRaises(ValueError):
            generator.validate_plan(plan, selected_lane="philosophy")

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
            selected_lane="lifestyle",
            intimate=False,
        )
        self.assertIn("Abstract or object-based visual interpretation", repaired)
        self.assertIn("Do not depict a generic woman", repaired)
        self.assertIn("Cinematic, glamorous, expressive, confident, and engaging.", repaired)

    def test_repair_image_prompt_adds_chloe_canon_clause(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        repaired = generator.repair_image_prompt(
            "Chloe in a train carriage at night, reflective and mysterious.",
            selected_lane="travel",
            intimate=True,
        )
        self.assertIn("approved Chloe Katastrophe visual canon", repaired)
        self.assertIn("gray-green eyes", repaired)
        self.assertIn("light freckles", repaired)
        self.assertIn("Default to warm, inviting, magnetic, playful, emotionally present, and visibly delighted by discovery.", repaired)
        self.assertIn("Do not make her look sad, stoic, blank, moody, or emotionally shut down", repaired)

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
            self.assertEqual("image[]", post.call_args.kwargs["files"][0][0])

    def test_generate_image_uses_multiple_reference_images_for_chloe_prompts(self):
        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            destination = output_dir / "image.png"
            reference_one = output_dir / "reference-one.png"
            reference_two = output_dir / "reference-two.png"
            reference_one.write_bytes(b"reference-one")
            reference_two.write_bytes(b"reference-two")
            response = self.json_response(
                {"data": [{"b64_json": base64.b64encode(b"edited-image").decode("ascii")}]}
            )

            with patch("frikshun_creator.services.daily_fragment_generator.requests.post", return_value=response) as post:
                DailyFragmentGenerator(
                    output_dir,
                    api_key="test-key",
                    chloe_reference_images=[reference_one, reference_two],
                ).generate_image(
                    "Chloe at night in the approved Chloe Katastrophe visual canon.",
                    destination,
                )

            self.assertEqual(b"edited-image", destination.read_bytes())
            self.assertEqual(2, len(post.call_args.kwargs["files"]))
            self.assertEqual("reference-one.png", post.call_args.kwargs["files"][0][1][0])
            self.assertEqual("reference-two.png", post.call_args.kwargs["files"][1][1][0])

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
        self.assertIn("full of wonder and excitement at discovering new things", prompt.lower())
        self.assertIn("enthusiastic, flirty, fierce, curious, and engaging", prompt.lower())
        self.assertIn("avoid moody, brooding, elegiac, mournful, haunted", prompt.lower())
        self.assertIn("do not make her look sad, stoic, blank, or emotionally shut down", prompt.lower())

    def test_emotion_guidance_includes_wonder(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        self.assertIn("wonderstruck", generator.emotion_guidance_for_lane("travel"))
        self.assertIn("visibly excited by discovery", generator.emotion_prompt_clause("travel", intimate=False))

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

    def test_image_error_summary_includes_openai_details_and_request_id(self):
        response = Mock(
            status_code=400,
            headers={"x-request-id": "req_debug_123"},
        )
        response.json.return_value = {
            "error": {
                "message": "Image prompt was rejected.",
                "type": "invalid_request_error",
                "code": "image_generation_user_error",
                "param": "prompt",
            }
        }
        error = requests.HTTPError("400 Client Error", response=response)

        summary = DailyFragmentGenerator("/tmp", api_key="test-key").image_error_summary(error)

        self.assertIn("HTTP 400", summary)
        self.assertIn("Image prompt was rejected", summary)
        self.assertIn("code=image_generation_user_error", summary)
        self.assertIn("request_id=req_debug_123", summary)

    def test_successful_image_does_not_add_fallback_warning(self):
        with TemporaryDirectory() as directory:
            public_path = Path(directory) / "public.png"
            public_path.write_bytes(b"successful-image")
            warnings = []

            DailyFragmentGenerator(directory, api_key="test-key").ensure_image_fallback(
                public_path,
                warnings,
            )

            self.assertEqual([], warnings)

    def test_missing_image_receives_neutral_fallback(self):
        with TemporaryDirectory() as directory:
            public_path = Path(directory) / "public.png"
            warnings = []

            DailyFragmentGenerator(directory, api_key="test-key").ensure_image_fallback(
                public_path,
                warnings,
            )

            self.assertTrue(public_path.is_file())
            self.assertIn("neutral local fallback", warnings[0])

    def json_response(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response


if __name__ == "__main__":
    unittest.main()
