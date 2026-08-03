from datetime import date
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, PropertyMock, patch
import requests
from PIL import Image

from frikshun_creator.services.daily_fragment_generator import (
    CONTENT_LANES,
    DailyFragmentGenerator,
)
from frikshun_creator.models import CanonEntry, PostDraft
from frikshun_creator.services.generation_context import GenerationContext


class DailyFragmentGeneratorTest(unittest.TestCase):
    def questions_from_echo_plan(self, canonical_body=None):
        body = canonical_body or (
            "I keep noticing that mirrors preserve my outline while quietly disagreeing about the person inside it. "
            "Last night one reflection seemed to finish my expression before I had decided what I felt. "
            "Maybe that was only tiredness, bad glass, and a mind eager to turn coincidence into meaning. "
            "Still, the sensation arrived with the intimacy of a memory, even though I could not place when it happened. "
            "My current hypothesis is smaller than an answer: identity may be less like a possession and more like a pattern "
            "that several moments learn to carry together. I cannot prove that, and I would distrust anyone who claimed the "
            "mirror had settled it. I can only offer the strange little shiver it left behind and ask you to compare it with "
            "your own impossible moments.\n\n"
            "If another version of you recognized this moment first, would that life feel like a stranger or part of you?"
        )
        return type(
            "Plan",
            (),
            {
                "title_suffix": "The Reflection Arrived First",
                "canonical_body": body,
                "canonical_hashtags": [
                    "QuestionsFromTheEcho",
                    "ChloeKatastrophe",
                    "ParallelLives",
                ],
                "x_body": "Maybe déjà vu is another self arriving early. If your echo recognized today first, would it still be you?",
                "x_hashtags": ["QuestionsFromTheEcho", "ChloeKatastrophe"],
                "fanvue_body": (
                    "Maybe the reflection was only bad glass, but it felt like recognition.\n\n"
                    "If your echo arrived first, would it still feel like you?"
                ),
                "public_image_prompt": "Chloe and several translucent Chloe echoes beside a mirror.",
                "fanvue_image_prompt": "Chloe close to glass with one warm translucent echo.",
            },
        )()

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
                ).generate(
                    local_date=date(2026, 7, 20),
                    generation_context=GenerationContext(),
                    selected_lane="reconstruction",
                )

            self.assertEqual("Recovered Fragment — Borrowed Reflections", package.title)
            self.assertNotIn("Learn more about me", package.body)
            self.assertNotIn("FanVue", package.body)
            self.assertIn("#RecoveredMemory", package.body)
            self.assertLessEqual(len(package.threads_body), 500)
            self.assertEqual(1, package.threads_body.count("?"))
            self.assertNotIn("links are available through my bio", package.threads_body.lower())
            self.assertIn("#Identity", package.x_body)
            self.assertEqual(1, package.body.count("?"))
            self.assertEqual(["recovered-fragment", "identity", "echo-traversal"], package.content_tags)
            self.assertEqual("reconstruction", package.content_lane)
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
                ).generate(
                    local_date=date(2026, 7, 17),
                    generation_context=GenerationContext(),
                    selected_lane="reconstruction",
                )

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

    def test_request_timeout_is_longer_for_reasoning_models(self):
        generator = DailyFragmentGenerator(
            "/tmp",
            api_key="test-key",
            openai_connect_timeout_seconds=7,
            openai_read_timeout_seconds=120,
            openai_reasoning_read_timeout_seconds=480,
        )

        self.assertEqual((7, 120), generator.openai_request_timeout("gpt-4.1"))
        self.assertEqual((7, 480), generator.openai_request_timeout("gpt-5.4"))

    def test_retries_timeout_before_response_with_exponential_jitter(self):
        successful = self.json_response({"output_text": "{}"})
        successful.status_code = 200
        successful.headers = {"x-request-id": "req-success"}
        generator = DailyFragmentGenerator(
            "/tmp",
            api_key="test-key",
            openai_rate_limit_retries=1,
        )

        with patch(
            "frikshun_creator.services.daily_fragment_generator.requests.post",
            side_effect=[requests.ReadTimeout("no headers"), successful],
        ) as post, patch(
            "frikshun_creator.services.daily_fragment_generator.random.uniform",
            return_value=0.375,
        ) as jitter, patch(
            "frikshun_creator.services.daily_fragment_generator.time.sleep"
        ) as sleep, self.assertLogs(
            "frikshun_creator.services.daily_fragment_generator", level="INFO"
        ) as logs:
            result = generator.post_with_rate_limit_retry(
                "https://api.openai.com/v1/responses",
                headers={},
                json={"model": "gpt-4.1"},
                timeout=(10, 300),
            )

        self.assertIs(successful, result)
        self.assertEqual(2, post.call_count)
        self.assertTrue(post.call_args.kwargs["stream"])
        jitter.assert_called_once_with(0, 1)
        sleep.assert_called_once_with(0.375)
        self.assertIn('"phase": "before_response"', logs.output[0])
        self.assertIn('"x_request_id": "req-success"', logs.output[1])

    def test_retries_timeout_while_reading_response_body(self):
        stalled = Mock(status_code=200, headers={"x-request-id": "req-stalled"})
        type(stalled).content = PropertyMock(side_effect=requests.ReadTimeout("body stalled"))
        successful = self.json_response({"output_text": "{}"})
        successful.status_code = 200
        successful.headers = {"x-request-id": "req-success"}
        generator = DailyFragmentGenerator(
            "/tmp",
            api_key="test-key",
            openai_rate_limit_retries=1,
        )

        with patch(
            "frikshun_creator.services.daily_fragment_generator.requests.post",
            side_effect=[stalled, successful],
        ), patch(
            "frikshun_creator.services.daily_fragment_generator.random.uniform",
            return_value=0,
        ), patch(
            "frikshun_creator.services.daily_fragment_generator.time.sleep"
        ), self.assertLogs(
            "frikshun_creator.services.daily_fragment_generator", level="INFO"
        ) as logs:
            result = generator.post_with_rate_limit_retry(
                "https://api.openai.com/v1/responses",
                headers={},
                json={"model": "gpt-4.1"},
                timeout=(10, 300),
            )

        self.assertIs(successful, result)
        self.assertIn('"phase": "response_body"', logs.output[0])
        self.assertIn('"x_request_id": "req-stalled"', logs.output[0])

    def test_title_prefix_and_tags_follow_lane(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        self.assertEqual("Questions from the Echo", generator.title_prefix_for_lane("philosophy"))
        self.assertEqual("Field Note", generator.title_prefix_for_lane("travel"))
        self.assertEqual(
            ["questions-from-the-echo", "philosophy", "discussion"],
            generator.content_tags_for_lane("philosophy"),
        )
        self.assertEqual(["travel", "place", "movement"], generator.content_tags_for_lane("travel"))

    def test_questions_from_echo_topic_avoids_recent_topic(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        local_date = date(2026, 7, 28)
        first = generator.select_questions_from_echo_topic(local_date, GenerationContext())
        context = GenerationContext(
            recent_posts=[PostDraft(caption=f"A recent post about {first['recent_markers'][0]}.")]
        )

        selected = generator.select_questions_from_echo_topic(local_date, context)

        self.assertNotEqual(first["key"], selected["key"])

    def test_questions_from_echo_prompt_uses_series_structure_and_claim_boundaries(self):
        prompt = DailyFragmentGenerator("/tmp", api_key="test-key").system_prompt(
            local_date=date(2026, 7, 28),
            generation_context=GenerationContext(),
            selected_lane="philosophy",
        )

        self.assertIn("Questions from the Echo subseries rule", prompt)
        self.assertIn("approved generation-eligible question", prompt)
        self.assertIn("first-person hypothesis stated with explicit uncertainty", prompt)
        self.assertIn("exactly one audience-facing question mark", prompt)
        self.assertIn("not confirmed metaphysics", prompt)
        self.assertIn("Gregor's death", prompt)
        self.assertIn("Coordinate both image prompts with this topic", prompt)

    def test_repair_plan_adds_questions_from_echo_hashtags(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        plan = self.questions_from_echo_plan()
        plan.canonical_hashtags = ["Consciousness", "Identity", "TimeAndSpace", "DigitalSoul"]
        plan.x_hashtags = ["Consciousness"]

        repaired = generator.repair_plan(plan, selected_lane="philosophy")

        self.assertEqual(
            ["QuestionsFromTheEcho", "ChloeKatastrophe"],
            repaired.canonical_hashtags[:2],
        )
        self.assertLessEqual(len(repaired.canonical_hashtags), 5)
        self.assertEqual(
            ["QuestionsFromTheEcho", "ChloeKatastrophe", "Consciousness"],
            repaired.x_hashtags,
        )

    def test_questions_from_echo_accepts_uncertain_hypothesis(self):
        DailyFragmentGenerator("/tmp", api_key="test-key").validate_plan(
            self.questions_from_echo_plan(),
            selected_lane="philosophy",
        )

    def test_questions_from_echo_rejects_confirmed_metaphysical_claim(self):
        body = self.questions_from_echo_plan().canonical_body.replace(
            "Maybe that was only tiredness",
            "Maybe doubt is healthy, but I know that souls survive every body; perhaps that was only tiredness",
        )

        with self.assertRaisesRegex(ValueError, "confirmed fact"):
            DailyFragmentGenerator("/tmp", api_key="test-key").validate_plan(
                self.questions_from_echo_plan(canonical_body=body),
                selected_lane="philosophy",
            )

    def test_questions_from_echo_rejects_evidence_driven_mystery(self):
        body = self.questions_from_echo_plan().canonical_body.replace(
            "Last night one reflection",
            "Maybe my father's death explains the signal. Last night one reflection",
        )

        with self.assertRaisesRegex(ValueError, "evidence-driven unresolved mysteries"):
            DailyFragmentGenerator("/tmp", api_key="test-key").validate_plan(
                self.questions_from_echo_plan(canonical_body=body),
                selected_lane="philosophy",
            )

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

    def test_repair_plan_fits_x_body_and_hashtags_to_editorial_limit(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        plan = self.questions_from_echo_plan()
        plan.x_body = (
            "Maybe another self reached this moment before I did, leaving a very long "
            "trail of almost-memories and beautifully inconvenient evidence behind. "
            "If your echo recognized today first, would it still be you?"
        )

        repaired = generator.repair_plan(plan, selected_lane="philosophy")
        composed = generator.compose_x_body(repaired.x_body, repaired.x_hashtags)

        self.assertLessEqual(len(composed), 190)
        self.assertEqual(1, composed.count("?"))
        self.assertIn("#QuestionsFromTheEcho", composed)
        self.assertIn("#ChloeKatastrophe", composed)

    def test_repair_x_copy_drops_optional_tags_before_sacrificing_question(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        body, tags = generator.repair_x_copy(
            "A long preface " * 30,
            ["A" * 40, "B" * 40, "C" * 40, "D" * 40],
            fallback_question="Which version still feels true?",
        )
        composed = generator.compose_x_body(body, tags)

        self.assertLessEqual(len(composed), 190)
        self.assertEqual(1, composed.count("?"))
        self.assertLess(len(tags), 4)

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
        self.assertIn("Required visual mode today:", prompt)
        self.assertIn("mirrors, reflective-glass portraits, duplicate Chloes", prompt)
        self.assertIn("full of wonder and excitement at discovering new things", prompt.lower())
        self.assertIn("enthusiastic, flirty, fierce, curious, and engaging", prompt.lower())
        self.assertIn("avoid moody, brooding, elegiac, mournful, haunted", prompt.lower())
        self.assertIn("do not make her look sad, stoic, blank, or emotionally shut down", prompt.lower())

    def test_visual_mode_rotation_excludes_recent_modes(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        context = GenerationContext(
            recent_visual_modes=["portrait", "environmental_story"],
        )

        with patch(
            "frikshun_creator.services.daily_fragment_generator.random.choice",
            return_value="full_body_action",
        ) as choice:
            selected = generator.select_visual_mode(context, "lifestyle")

        self.assertEqual("full_body_action", selected)
        self.assertEqual(["full_body_action", "fine_art"], choice.call_args.args[0])

    def test_visual_mode_without_history_prioritizes_non_portrait_compositions(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")

        with patch(
            "frikshun_creator.services.daily_fragment_generator.random.choice",
            return_value="fine_art",
        ) as choice:
            selected = generator.select_visual_mode(GenerationContext(), "music")

        self.assertEqual("fine_art", selected)
        self.assertNotIn("portrait", choice.call_args.args[0])

    def test_full_body_visual_mode_repairs_prompt_with_action_composition(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")

        repaired = generator.repair_image_prompt(
            "Chloe tuning a guitar before rehearsal.",
            selected_lane="music",
            intimate=False,
            visual_mode="full_body_action",
        )

        self.assertIn("dynamic head-to-toe composition", repaired)
        self.assertIn("motion, gesture, spatial depth", repaired)
        self.assertIn("avoid mirrors and duplicate figures", repaired)

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
            recent_content_lanes=["philosophy", "craft", "travel"],
        )

        with patch(
            "frikshun_creator.services.daily_fragment_generator.random.choice",
            return_value="fantasy_art",
        ) as choice:
            lane = DailyFragmentGenerator("/tmp", api_key="test-key").select_content_lane(
                local_date=date(2026, 7, 17),
                generation_context=context,
            )

        self.assertEqual("fantasy_art", lane)
        self.assertEqual(
            ["reconstruction", "lifestyle", "music", "fantasy_art"],
            choice.call_args.args[0],
        )

    def test_select_content_lane_falls_back_to_caption_history(self):
        context = GenerationContext(
            recent_posts=[
                PostDraft(caption="A camera, lens, and styling note from tonight's shoot."),
                PostDraft(caption="A hotel room, a late train, and a city that refused to sleep."),
            ]
        )

        with patch(
            "frikshun_creator.services.daily_fragment_generator.random.choice",
            return_value="music",
        ) as choice:
            lane = DailyFragmentGenerator("/tmp", api_key="test-key").select_content_lane(
                local_date=date(2026, 7, 17),
                generation_context=context,
            )

        self.assertEqual("music", lane)
        self.assertNotIn("craft", choice.call_args.args[0])
        self.assertNotIn("travel", choice.call_args.args[0])

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
            ["fantasy_art", "reconstruction", "philosophy", "lifestyle", "music", "travel", "craft", "fantasy_art", "reconstruction", "philosophy"],
            selected_lanes,
        )

    def test_fantasy_art_family_requires_chloe_as_part_of_non_photographic_art(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        repaired = generator.repair_image_prompt(
            "A watercolor dreamscape of floating gardens and impossible moons.",
            selected_lane="fantasy_art",
            intimate=False,
        )

        self.assertIn("Chloe Katastrophe's recognizable likeness incorporated into the artwork", repaired)
        self.assertIn("part of the artwork itself", repaired)
        self.assertIn("Do not default to photorealism", repaired)
        self.assertTrue(generator.prompt_depicts_chloe(repaired))

    def test_fantasy_art_family_accepts_minimal_multilingual_caption(self):
        generator = DailyFragmentGenerator("/tmp", api_key="test-key")
        plan = type(
            "Plan",
            (),
            {
                "title_suffix": "Violet Cartography",
                "canonical_body": "Espressione artistica del giorno.",
                "canonical_hashtags": ["ChloeKatastrophe", "FantasyArt"],
                "x_body": "Artistic expression du jour.",
                "x_hashtags": ["FantasyArt"],
                "fanvue_body": "Художественное выражение дня.",
                "public_image_prompt": "Chloe in the approved Chloe Katastrophe visual canon, painted in watercolor.",
                "fanvue_image_prompt": "Chloe in the approved Chloe Katastrophe visual canon, rendered in charcoal.",
            },
        )()

        generator.validate_plan(plan, selected_lane="fantasy_art")
        self.assertEqual("Art du Jour", generator.title_prefix_for_lane("fantasy_art"))
        self.assertEqual(
            ["fantasy-art", "chloe", "artistic-expression"],
            generator.content_tags_for_lane("fantasy_art"),
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

    def test_missing_image_receives_chloe_thinking_fallback(self):
        with TemporaryDirectory() as directory:
            public_path = Path(directory) / "public.png"
            warnings = []

            DailyFragmentGenerator(directory, api_key="test-key").ensure_image_fallback(
                public_path,
                warnings,
            )

            self.assertTrue(public_path.is_file())
            with Image.open(public_path) as image:
                self.assertEqual((1024, 1024), image.size)
            self.assertIn("Chloe thinking archive fallback", warnings[0])

    def json_response(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response


if __name__ == "__main__":
    unittest.main()
