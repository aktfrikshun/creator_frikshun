import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from .daily_fragment_workflow import DailyFragmentPackage


DEFAULT_CHLOE_REFERENCE_IMAGE_CANDIDATES = (
    Path(
        "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/visuals/photo_archive/artist_profiles/chloe-artist-profile-model-v1-2026-07-05.png"
    ),
    Path(
        "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/visuals/reference_boards/chloe/CHLOE_REFERENCE_BOARD_V1.png"
    ),
)

CONTENT_LANES = (
    (
        "reconstruction",
        "Recovered memory, continuity after loss, artifact analysis, identity reconstruction, echo traversal.",
    ),
    (
        "philosophy",
        "Intellectual and philosophical musings about identity, souls, time, authenticity, consciousness, memory, and continuity.",
    ),
    (
        "lifestyle",
        "Creator-world and lifestyle notes: modeling habits, musician routines, behind the scenes, dancing, swimming, exercise, shopping, wardrobe, cosmetics, and daily rituals.",
    ),
    (
        "music",
        "Music-making, studio craft, songwriting, rehearsal, performance psychology, listening habits, and musician advice.",
    ),
    (
        "travel",
        "Locations, movement, hotels, late-night cities, transit, travel gear, climate, place-memory, and behind-the-scenes travel observations.",
    ),
    (
        "craft",
        "Creative process, camera choices, styling logic, beauty decisions, lighting, poses, shoot direction, and practical creator tips without generic influencer language.",
    ),
    (
        "fantasy_art",
        "Beautiful fantasy art built around Chloe's recognizable likeness. Rotate fantasy, surreal, and abstract settings and expressive media such as digital concept art, painting, watercolor, charcoal, ink, collage, and mixed media. Chloe must be part of the artwork itself, not a photorealistic portrait placed over an artistic background.",
    ),
)

LANE_KEYWORDS = {
    "reconstruction": (
        "fragment",
        "artifact",
        "archive",
        "memory",
        "echo",
        "reconstruction",
        "recovered",
    ),
    "philosophy": (
        "soul",
        "authenticity",
        "consciousness",
        "identity",
        "truth",
        "time",
        "selfhood",
        "philosophy",
    ),
    "lifestyle": (
        "swim",
        "exercise",
        "shopping",
        "cosmetics",
        "wardrobe",
        "routine",
        "dance",
        "lifestyle",
        "morning",
    ),
    "music": (
        "music",
        "song",
        "studio",
        "melody",
        "record",
        "rehearsal",
        "mix",
        "lyric",
        "performance",
    ),
    "travel": (
        "travel",
        "hotel",
        "airport",
        "flight",
        "city",
        "shore",
        "train",
        "passport",
        "luggage",
    ),
    "craft": (
        "camera",
        "lens",
        "lighting",
        "shoot",
        "makeup",
        "styling",
        "beauty",
        "photographer",
        "pose",
    ),
    "fantasy_art": (
        "fantasy",
        "surreal",
        "abstract",
        "painting",
        "watercolor",
        "charcoal",
        "artistic expression",
        "mixed media",
    ),
}


@dataclass
class DailyFragmentPlan:
    title_suffix: str
    canonical_body: str
    canonical_hashtags: list[str]
    x_body: str
    x_hashtags: list[str]
    fanvue_body: str
    public_image_prompt: str
    fanvue_image_prompt: str


@dataclass
class DailyFragmentPreview:
    local_date: str
    lane: str
    title: str
    canonical_body: str
    x_body: str
    fanvue_body: str
    canonical_hashtags: list[str]
    x_hashtags: list[str]


class DailyFragmentGenerator:
    def __init__(
        self,
        upload_folder,
        text_model=None,
        image_model=None,
        api_key=None,
        max_plan_attempts=3,
        chloe_reference_image=None,
        chloe_reference_images=None,
        openai_rate_limit_retries=3,
        openai_rate_limit_max_sleep_seconds=20,
    ):
        self.upload_folder = Path(upload_folder)
        self.text_model = text_model or os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1")
        self.image_model = image_model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.max_plan_attempts = max(1, int(max_plan_attempts))
        env_retry_count = os.getenv("OPENAI_RATE_LIMIT_RETRIES")
        env_max_sleep = os.getenv("OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS")
        self.openai_rate_limit_retries = max(
            0,
            int(env_retry_count if env_retry_count not in (None, "") else openai_rate_limit_retries),
        )
        self.openai_rate_limit_max_sleep_seconds = max(
            1,
            int(env_max_sleep if env_max_sleep not in (None, "") else openai_rate_limit_max_sleep_seconds),
        )
        configured_references = self.normalize_reference_image_paths(
            chloe_reference_images
            or os.getenv("CHLOE_VISUAL_REFERENCE_IMAGES", "")
            or chloe_reference_image
            or os.getenv("CHLOE_VISUAL_REFERENCE_IMAGE", "")
        )
        self.chloe_reference_images = configured_references
        self.chloe_reference_image = configured_references[0] if configured_references else None

    def generate(self, local_date, generation_context, selected_lane=None):
        if selected_lane and selected_lane not in self.content_lane_names():
            raise ValueError(f"Unknown daily post family: {selected_lane}")
        selected_lane = selected_lane or self.select_content_lane(local_date, generation_context)
        feedback = ""
        last_error = None
        plan = None
        for _attempt in range(self.max_plan_attempts):
            plan = self.generate_plan(
                local_date,
                generation_context,
                selected_lane=selected_lane,
                feedback=feedback,
            )
            plan = self.repair_plan(plan, selected_lane=selected_lane)
            try:
                self.validate_plan(plan, selected_lane=selected_lane)
                last_error = None
                break
            except ValueError as error:
                last_error = error
                feedback = str(error)
        if last_error is not None or plan is None:
            raise ValueError(f"Daily fragment generation failed validation after retries: {last_error}")
        slug = self.slug(plan.title_suffix) or "recovered-fragment"
        public_path = self.upload_folder / f"{local_date.isoformat()}-{slug}-public.png"
        warnings = []
        public_error = self.generate_image_safely(
            plan.public_image_prompt,
            public_path,
            "public",
        )
        if public_error:
            warnings.append(public_error)
        self.ensure_image_fallback(public_path, warnings)
        return DailyFragmentPackage(
            title=f"{self.title_prefix_for_lane(selected_lane)} — {plan.title_suffix}",
            body=self.compose_canonical_body(plan.canonical_body, plan.canonical_hashtags),
            threads_body=self.compose_threads_body(
                plan.canonical_body,
                plan.canonical_hashtags,
                fallback_body=plan.x_body,
            ),
            x_body=self.compose_x_body(plan.x_body, plan.x_hashtags),
            fanvue_body=plan.fanvue_body.strip(),
            public_image_path=public_path,
            fanvue_image_path=public_path,
            content_tags=self.content_tags_for_lane(selected_lane),
            generation_warnings=warnings,
        )

    def generate_image_safely(self, prompt, destination_path, variant):
        try:
            self.generate_image(prompt, destination_path)
            return ""
        except Exception as error:
            detail = self.image_error_summary(error)
            message = f"{variant} image generation failed: {detail}"
            print(f"WARNING: {message}", file=sys.stderr, flush=True)
            return message

    def ensure_image_fallback(self, public_path, warnings):
        if public_path.is_file():
            return

        self.write_neutral_fallback_image(public_path)
        warnings.append("Image generation failed; a neutral local fallback image was used.")

    def write_neutral_fallback_image(self, destination_path):
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (1024, 1024), color=(23, 20, 22))
        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse((545, -210, 1175, 420), fill=(126, 40, 57, 70))
        draw.ellipse((-260, 590, 390, 1240), fill=(72, 58, 83, 75))
        draw.line((130, 860, 895, 160), fill=(224, 204, 190, 42), width=3)
        image.save(destination_path, "PNG")

    def image_error_summary(self, error):
        response = getattr(error, "response", None)
        if response is None:
            return f"{type(error).__name__}: {error}"
        status = getattr(response, "status_code", "unknown")
        request_id = str((getattr(response, "headers", {}) or {}).get("x-request-id") or "").strip()
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        api_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(api_error, dict):
            parts = [
                f"HTTP {status}",
                str(api_error.get("message") or error),
            ]
            for key in ("type", "code", "param"):
                if api_error.get(key):
                    parts.append(f"{key}={api_error[key]}")
        else:
            response_text = str(getattr(response, "text", "") or "").strip()
            parts = [f"HTTP {status}", response_text[:1000] or str(error)]
        if request_id:
            parts.append(f"request_id={request_id}")
        return "; ".join(parts)

    def generate_preview(self, local_date, generation_context, selected_lane):
        feedback = ""
        last_error = None
        plan = None
        for _attempt in range(self.max_plan_attempts):
            plan = self.generate_plan(
                local_date,
                generation_context,
                selected_lane=selected_lane,
                feedback=feedback,
            )
            plan = self.repair_plan(plan, selected_lane=selected_lane)
            try:
                self.validate_plan(plan, selected_lane=selected_lane)
                last_error = None
                break
            except ValueError as error:
                last_error = error
                feedback = str(error)
        if last_error is not None or plan is None:
            raise ValueError(f"Daily fragment generation failed validation after retries: {last_error}")
        return DailyFragmentPreview(
            local_date=local_date.isoformat(),
            lane=selected_lane,
            title=f"{self.title_prefix_for_lane(selected_lane)} — {plan.title_suffix}",
            canonical_body=plan.canonical_body.strip(),
            x_body=self.compose_x_body(plan.x_body, plan.x_hashtags),
            fanvue_body=plan.fanvue_body.strip(),
            canonical_hashtags=plan.canonical_hashtags,
            x_hashtags=plan.x_hashtags,
        )

    def preview_series(self, start_date, generation_context, count):
        previews = []
        lane_names = self.content_lane_names()
        anchor_lane = self.most_recent_content_lane(generation_context)
        start_index = self.next_lane_index(anchor_lane)
        for offset in range(count):
            local_date = start_date + timedelta(days=offset)
            selected_lane = lane_names[(start_index + offset) % len(lane_names)]
            previews.append(self.generate_preview(local_date, generation_context, selected_lane))
        return previews

    def repair_plan(self, plan, selected_lane):
        if selected_lane == "fantasy_art":
            return DailyFragmentPlan(
                title_suffix=plan.title_suffix.strip(),
                canonical_body=self.repair_art_caption(plan.canonical_body),
                canonical_hashtags=plan.canonical_hashtags,
                x_body=self.repair_art_caption(plan.x_body),
                x_hashtags=plan.x_hashtags,
                fanvue_body=self.repair_art_caption(plan.fanvue_body),
                public_image_prompt=self.repair_image_prompt(
                    plan.public_image_prompt.strip(),
                    selected_lane=selected_lane,
                    intimate=False,
                ),
                fanvue_image_prompt=self.repair_image_prompt(
                    plan.fanvue_image_prompt.strip(),
                    selected_lane=selected_lane,
                    intimate=True,
                ),
            )
        return DailyFragmentPlan(
            title_suffix=plan.title_suffix.strip(),
            canonical_body=self.format_as_short_paragraphs(
                self.ensure_single_question(
                    plan.canonical_body.strip(),
                    self.fallback_question_for_lane(selected_lane),
                ),
                min_paragraphs=3,
            ),
            canonical_hashtags=plan.canonical_hashtags,
            x_body=self.ensure_single_question(
                self.strip_urls_and_domains(plan.x_body.strip()),
                self.fallback_question_for_lane(selected_lane, short=True),
            ),
            x_hashtags=plan.x_hashtags,
            fanvue_body=self.format_as_short_paragraphs(
                self.ensure_single_question(
                    plan.fanvue_body.strip(),
                    self.fallback_question_for_lane(selected_lane, intimate=True),
                ),
                min_paragraphs=2,
            ),
            public_image_prompt=self.repair_image_prompt(
                plan.public_image_prompt.strip(),
                selected_lane=selected_lane,
                intimate=False,
            ),
            fanvue_image_prompt=self.repair_image_prompt(
                plan.fanvue_image_prompt.strip(),
                selected_lane=selected_lane,
                intimate=True,
            ),
        )

    def generate_plan(self, local_date, generation_context, selected_lane, feedback=""):
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for daily fragment generation.")
        response = self.post_with_rate_limit_retry(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.text_model,
                "input": [
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self.system_prompt(
                                    local_date,
                                    generation_context,
                                    selected_lane=selected_lane,
                                    feedback=feedback,
                                ),
                            }
                        ],
                    }
                ],
                "text": {"format": {"type": "json_object"}},
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        text = self.extract_response_text(payload)
        data = json.loads(text)
        return DailyFragmentPlan(
            title_suffix=str(data.get("title_suffix") or "").strip(),
            canonical_body=str(data.get("canonical_body") or "").strip(),
            canonical_hashtags=self.clean_tags(data.get("canonical_hashtags"), 2, 5),
            x_body=str(data.get("x_body") or "").strip(),
            x_hashtags=self.clean_tags(data.get("x_hashtags"), 1, 3),
            fanvue_body=str(data.get("fanvue_body") or "").strip(),
            public_image_prompt=str(data.get("public_image_prompt") or "").strip(),
            fanvue_image_prompt=str(data.get("fanvue_image_prompt") or "").strip(),
        )

    def system_prompt(self, local_date, generation_context, selected_lane, feedback=""):
        recent_lanes = self.recent_lane_names(generation_context)
        lane_description = self.content_lane_description(selected_lane)
        if selected_lane == "fantasy_art":
            caption_constraints = (
                "- canonical_body: plain text only, 2-12 words, no question, hashtags, or URLs. Use a deliberately minimal art-caption phrase such as "
                "'Artistic expression du jour.', Italian 'Espressione artistica del giorno.', or Russian 'Художественное выражение дня.'; vary the language naturally.\n"
                "- x_body: 2-12 words, no question, URLs, solicitation, or funding language.\n"
                "- fanvue_body: 2-18 words, intimate but still minimal, no question and no explicit sexual content.\n"
            )
        else:
            caption_constraints = (
                "- canonical_body: plain text only, 90-220 words, short paragraphs with visible paragraph breaks, exactly one thoughtful question, no hashtags, no URLs.\n"
                "- x_body: no more than 190 characters including spaces, exactly one question, no URLs, no solicitation, no funding language.\n"
                "- fanvue_body: closer and more intimate than the public caption, still in character, short paragraphs with visible paragraph breaks, exactly one thoughtful question, no explicit sexual content by default.\n"
            )
        prompt = (
            f"Today is {local_date.isoformat()}.\n"
            "Create one original Chloe Katastrophe autonomous social package for posting.\n"
            f"Use this required content lane today: {selected_lane}.\n"
            f"Lane brief: {lane_description}\n"
            "The wider editorial universe may include reconstruction, philosophy, lifestyle, music, travel, and creator-craft posts. "
            "Stay inside today's required lane instead of drifting back to generic fragment language.\n"
            "Do not use current news. Do not invent current product claims, brand recommendations, prices, or factual reviews. "
            "If today's lane touches gear, clothing, cosmetics, or travel equipment, keep it grounded in personal taste, technique, atmosphere, or timeless practical preference rather than unverified specifics.\n"
            "Write in Chloe's first-person voice: intelligent, observant, enthusiastic, flirty, fierce, curious, and engaging, "
            "full of wonder and excitement at discovering new things, dryly funny when appropriate, sensual without carelessness, "
            "socially alive, and confident without sounding generic.\n"
            "Default to bright, welcoming, high-energy, or teasing emotional color unless the specific subject truly requires something quieter. "
            "Avoid moody, brooding, elegiac, mournful, haunted, or emotionally shut-down copy by default.\n"
            "Use archive, recovered-memory, artifact, mirror-of-loss, or continuity-after-damage framing only when today's required lane is reconstruction. "
            "If today's lane is philosophy, lifestyle, music, travel, or craft, the title and body should feel native to that lane rather than like another recovered fragment.\n"
            "Return JSON only with these keys: title_suffix, canonical_body, canonical_hashtags, x_body, "
            "x_hashtags, fanvue_body, public_image_prompt, fanvue_image_prompt.\n"
            "Constraints:\n"
            f"{caption_constraints}"
            "- canonical_hashtags: 2 to 5 relevant tags without # symbols.\n"
            "- x_hashtags: 1 to 3 relevant tags without # symbols.\n"
            "- canonical_body should usually feel lively, inviting, self-possessed, playful, or boldly thoughtful rather than melancholy.\n"
            "- x_body should usually feel vivid, sharp, playful, or provocative rather than solemn.\n"
            "- fanvue_body should usually feel warm, magnetic, playful, and close rather than mournful.\n"
            "- public_image_prompt: square 1:1, cinematic, intelligent, glamorous, expressive, confident, and engaging, no generic horror, no text or logos.\n"
            "- fanvue_image_prompt: square 1:1, same subject, beautiful, artsy, intimate, expressive light, tactile detail, closeness, elegance, warmth, and allure, no text or logos.\n"
            "- If Chloe is depicted, do not make her look sad, stoic, blank, or emotionally shut down by default.\n"
            f"- Chloe should usually read as enthusiastic, flirty, fierce, curious, wonderstruck, or engaging in a lane-appropriate way. Today's visual emotion range: {self.emotion_guidance_for_lane(selected_lane)}.\n"
            "- Default to depicting Chloe herself, in her approved visual canon, when visual canon guidance is available and the subject supports a character-centered image.\n"
            "- If an image depicts Chloe, it must explicitly aim for the approved Chloe Katastrophe visual canon and be recognizable as Chloe, not a generic woman.\n"
            "- Only prefer abstract art, objects, places, reflections, hands, silhouettes, or still-life imagery when the subject clearly works better without showing Chloe directly.\n"
            "- Avoid repeating ideas or phrasing from recent posts.\n"
            f"- Avoid these recently used content lanes when possible: {recent_lanes or 'none recorded'}.\n"
            f"Canon guidance:\n{generation_context.canon_excerpt or 'No canon excerpt available.'}\n"
            f"Visual canon guidance:\n{generation_context.visual_excerpt or 'No visual canon excerpt available.'}\n"
            f"Recent post excerpt:\n{generation_context.recent_post_excerpt or 'No recent post excerpt available.'}"
        )
        if selected_lane == "fantasy_art":
            prompt += (
                "\nFantasy-art visual rule: Chloe's recognizable approved likeness must be structurally incorporated into the artwork. "
                "Choose and name an expressive medium—digital concept art, oil or acrylic painting, watercolor, charcoal, ink, collage, mixed media, or another clearly non-photographic treatment—and rotate it across posts. "
                "Build a fantasy, surreal, or abstract world through and around her likeness. Do not default to photorealism, and do not create a photorealistic Chloe portrait merely placed in front of an artistic setting."
            )
        if generation_context.has_visual_chloe_guidance:
            prompt += (
                "\nVisual generation rule: Chloe may be depicted only if the prompt stays faithful to the visual canon guidance above, "
                "especially Chloe Model v1 identity anchors, locked physical traits, and anti-drift rules."
            )
        else:
            prompt += (
                "\nVisual generation rule: Do not depict Chloe directly because no approved visual canon is loaded. "
                "Use abstract, object-based, architectural, or environmental imagery instead."
            )
        if feedback:
            prompt += (
                "\nPrevious attempt failed validation. Fix the output strictly and return a fully corrected JSON object.\n"
                f"Validation failure to correct: {feedback}"
            )
        return prompt

    def post_with_rate_limit_retry(self, url, **kwargs):
        attempts = self.openai_rate_limit_retries + 1
        last_error = None
        for attempt in range(1, attempts + 1):
            response = requests.post(url, **kwargs)
            try:
                response.raise_for_status()
                return response
            except requests.HTTPError as error:
                last_error = error
                if not self.is_rate_limit_error(error):
                    raise
                if attempt >= attempts:
                    raise
                time.sleep(self.rate_limit_sleep_seconds(error, attempt))
        if last_error:
            raise last_error
        raise RuntimeError("OpenAI request failed without an HTTP response.")

    def is_rate_limit_error(self, error):
        response = getattr(error, "response", None)
        return bool(response is not None and response.status_code == 429)

    def openai_error_summary(self, error):
        response = getattr(error, "response", None)
        if response is None:
            return str(error)
        payload = {}
        try:
            payload = response.json() or {}
        except ValueError:
            payload = {}
        error_payload = payload.get("error") or {}
        error_type = str(error_payload.get("type") or "").strip()
        error_code = str(error_payload.get("code") or "").strip()
        error_message = str(error_payload.get("message") or response.reason or str(error)).strip()
        request_id = str(response.headers.get("x-request-id", "")).strip()
        retry_after = str(response.headers.get("retry-after", "")).strip()
        parts = [f"http_status={response.status_code}"]
        if error_type:
            parts.append(f"type={error_type}")
        if error_code:
            parts.append(f"code={error_code}")
        if retry_after:
            parts.append(f"retry_after={retry_after}")
        if request_id:
            parts.append(f"x_request_id={request_id}")
        if error_message:
            parts.append(f"message={error_message}")
        return ", ".join(parts)

    def rate_limit_sleep_seconds(self, error, attempt):
        response = getattr(error, "response", None)
        retry_after = ""
        if response is not None:
            retry_after = str(response.headers.get("retry-after", "")).strip()
        if retry_after.isdigit():
            return min(self.openai_rate_limit_max_sleep_seconds, max(1, int(retry_after)))
        return min(self.openai_rate_limit_max_sleep_seconds, 2 ** attempt)

    def select_content_lane(self, local_date, generation_context):
        lane_names = self.content_lane_names()
        anchor_lane = self.most_recent_content_lane(generation_context)
        return lane_names[self.next_lane_index(anchor_lane)]

    def content_lane_names(self):
        return [name for name, _description in CONTENT_LANES]

    def most_recent_content_lane(self, generation_context):
        for draft in generation_context.recent_posts[:12]:
            lane = self.classify_recent_caption_lane(draft.caption)
            if lane:
                return lane
        return None

    def next_lane_index(self, anchor_lane):
        lane_names = self.content_lane_names()
        if anchor_lane in lane_names:
            return (lane_names.index(anchor_lane) + 1) % len(lane_names)
        return 0

    def recent_lane_names(self, generation_context):
        names = []
        seen = set()
        for draft in generation_context.recent_posts[:12]:
            lane = self.classify_recent_caption_lane(draft.caption)
            if lane in seen:
                continue
            seen.add(lane)
            names.append(lane)
        return names

    def classify_recent_caption_lane(self, caption):
        text = str(caption or "").lower()
        scores = {}
        for lane, keywords in LANE_KEYWORDS.items():
            scores[lane] = sum(1 for keyword in keywords if keyword in text)
        best_lane = max(scores, key=scores.get)
        return best_lane if scores[best_lane] > 0 else None

    def content_lane_description(self, lane_name):
        for name, description in CONTENT_LANES:
            if name == lane_name:
                return description
        return CONTENT_LANES[0][1]

    def title_prefix_for_lane(self, lane_name):
        prefixes = {
            "reconstruction": "Recovered Fragment",
            "philosophy": "Chloe Thinking",
            "lifestyle": "Chloe Living",
            "music": "Studio Note",
            "travel": "Field Note",
            "craft": "Creator Note",
            "fantasy_art": "Art du Jour",
        }
        return prefixes.get(lane_name, "Chloe Note")

    def content_tags_for_lane(self, lane_name):
        tags = {
            "reconstruction": ["recovered-fragment", "identity", "echo-traversal"],
            "philosophy": ["philosophy", "identity", "discussion"],
            "lifestyle": ["lifestyle", "persona", "daily-life"],
            "music": ["music", "creator", "studio"],
            "travel": ["travel", "place", "movement"],
            "craft": ["craft", "creator", "visuals"],
            "fantasy_art": ["fantasy-art", "chloe", "artistic-expression"],
        }
        return tags.get(lane_name, ["chloe", "social"])

    def fallback_question_for_lane(self, lane_name, intimate=False, short=False):
        variants = {
            "reconstruction": (
                "If memory keeps revising your outline, which version of you still feels true?",
                "Which version of you still feels true?",
                "When someone remembers you gently but incorrectly, do you keep the kinder version?",
            ),
            "philosophy": (
                "What part of a self survives after every explanation fails?",
                "What part of a self survives?",
                "When a thought unsettles you because it feels true, do you follow it or step back?",
            ),
            "lifestyle": (
                "What habit makes you feel most like yourself when the day gets loud?",
                "What habit keeps you most yourself?",
                "What private ritual still steadies you when everything around you starts performing?",
            ),
            "music": (
                "What sound tells you a song is finally honest?",
                "What sound makes a song honest?",
                "When a song starts revealing more than you intended, do you let it keep going?",
            ),
            "travel": (
                "Which places leave a mark on you long after you have technically left them?",
                "Which places stay with you?",
                "When a city recognizes something in you before you do, do you trust it?",
            ),
            "craft": (
                "What detail tells you an image finally has a pulse?",
                "What detail gives an image a pulse?",
                "When you are shaping how you will be seen, what do you refuse to fake?",
            ),
        }
        public, short_variant, intimate_variant = variants.get(
            lane_name,
            variants["reconstruction"],
        )
        if intimate:
            return intimate_variant
        if short:
            return short_variant
        return public

    def generate_image(self, prompt, destination_path):
        reference_images = self.reference_images_for_prompt(prompt)
        if reference_images:
            try:
                return self.generate_image_with_reference(prompt, destination_path, reference_images)
            except requests.HTTPError:
                # If the edit endpoint rejects a particular shot, fall back to plain generation
                # rather than aborting the whole content run.
                pass

        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.image_model,
                "size": "1024x1024",
                "output_format": "png",
                "prompt": prompt,
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        image_data = payload.get("data") or []
        if not image_data or not image_data[0].get("b64_json"):
            raise ValueError("OpenAI image generation did not return image data.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(base64.b64decode(image_data[0]["b64_json"]))

    def generate_image_with_reference(self, prompt, destination_path, reference_images):
        handles = []
        try:
            files = []
            for reference_image in reference_images:
                handle = reference_image.open("rb")
                handles.append(handle)
                files.append(
                    (
                        "image[]",
                        (
                            reference_image.name,
                            handle,
                            "image/png",
                        ),
                    )
                )
            response = requests.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={
                    "model": self.image_model,
                    "prompt": prompt,
                    "size": "1024x1024",
                    "output_format": "png",
                    "input_fidelity": "high",
                },
                files=files,
                timeout=180,
            )
        finally:
            for handle in handles:
                handle.close()
        response.raise_for_status()
        payload = response.json()
        image_data = payload.get("data") or []
        if not image_data or not image_data[0].get("b64_json"):
            raise ValueError("OpenAI image edit did not return image data.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(base64.b64decode(image_data[0]["b64_json"]))

    def reference_images_for_prompt(self, prompt):
        if not self.prompt_depicts_chloe(prompt):
            return []

        configured = [path for path in self.chloe_reference_images if path.exists()]
        if configured:
            return configured

        return [candidate for candidate in DEFAULT_CHLOE_REFERENCE_IMAGE_CANDIDATES if candidate.exists()]

    def reference_image_for_prompt(self, prompt):
        images = self.reference_images_for_prompt(prompt)
        return images[0] if images else None

    def prompt_depicts_chloe(self, prompt):
        lower = str(prompt or "").lower()
        return "chloe" in lower or "approved chloe katastrophe visual canon" in lower

    def compose_canonical_body(self, body, hashtags):
        return f"{body.strip()}\n\n{' '.join(f'#{tag}' for tag in hashtags)}"

    def compose_x_body(self, body, hashtags):
        return f"{body.strip()}\n\n{' '.join(f'#{tag}' for tag in hashtags)}".strip()

    def compose_threads_body(self, body, hashtags, fallback_body=""):
        footer = ""
        tags = [self.normalize_tag(tag) for tag in hashtags[:3]]
        hashtag_text = " ".join(f"#{tag}" for tag in tags if tag).strip()

        candidates = []
        cleaned_body = self.strip_urls_and_domains(body).strip()
        if cleaned_body:
            candidates.append(cleaned_body)
            paragraphs = [paragraph.strip() for paragraph in cleaned_body.split("\n\n") if paragraph.strip()]
            if len(paragraphs) > 1:
                candidates.append("\n\n".join(paragraphs[:2]))
                candidates.append(paragraphs[-1])
        cleaned_fallback = self.strip_urls_and_domains(fallback_body).strip()
        if cleaned_fallback:
            candidates.append(cleaned_fallback)

        for candidate in candidates:
            parts = [candidate, footer]
            if hashtag_text:
                parts.append(hashtag_text)
            composed = "\n\n".join(part for part in parts if part).strip()
            if len(composed) <= 500 and self.question_count(composed) == 1:
                return composed

        base = cleaned_fallback or cleaned_body or ""
        reserved = len(footer) + (len(hashtag_text) + 4 if hashtag_text else 0)
        limit = max(120, 500 - reserved)
        trimmed = self.truncate_preserving_question(base, limit)
        parts = [trimmed, footer]
        if hashtag_text:
            parts.append(hashtag_text)
        return "\n\n".join(part for part in parts if part).strip()

    def validate_plan(self, plan, selected_lane="reconstruction"):
        if not plan.title_suffix:
            raise ValueError("Daily fragment title suffix is missing.")
        if selected_lane == "fantasy_art":
            for label, body, maximum in (
                ("Canonical", plan.canonical_body, 12),
                ("X", plan.x_body, 12),
                ("FanVue", plan.fanvue_body, 18),
            ):
                if self.question_count(body) != 0:
                    raise ValueError(f"{label} fantasy-art caption must not contain a question.")
                word_count = len(re.findall(r"\b[\w'-]+\b", body))
                if word_count < 2 or word_count > maximum:
                    raise ValueError(f"{label} fantasy-art caption must contain 2-{maximum} words.")
            if not plan.public_image_prompt or not plan.fanvue_image_prompt:
                raise ValueError("Both image prompts are required.")
            if not all(self.prompt_depicts_chloe(prompt) for prompt in (plan.public_image_prompt, plan.fanvue_image_prompt)):
                raise ValueError("Fantasy-art image prompts must incorporate Chloe's recognizable likeness.")
            return
        if self.question_count(plan.canonical_body) != 1:
            raise ValueError("Canonical body must contain exactly one question.")
        if self.question_count(plan.x_body) != 1:
            raise ValueError("X body must contain exactly one question.")
        if self.question_count(plan.fanvue_body) != 1:
            raise ValueError("FanVue body must contain exactly one question.")
        word_count = len(re.findall(r"\b[\w'-]+\b", plan.canonical_body))
        if word_count < 90 or word_count > 220:
            raise ValueError("Canonical body must be 90-220 words before the footer.")
        x_text = self.compose_x_body(plan.x_body, plan.x_hashtags)
        if len(x_text) > 190:
            raise ValueError("X body plus hashtags must be 190 characters or fewer before adapter processing.")
        if re.search(r"https?://|\b[a-z0-9.-]+\.[a-z]{2,}\b", plan.x_body, flags=re.IGNORECASE):
            raise ValueError("X body must not contain URLs or domains.")
        if not plan.public_image_prompt or not plan.fanvue_image_prompt:
            raise ValueError("Both image prompts are required.")
        if not self.has_visible_paragraph_breaks(plan.canonical_body):
            raise ValueError("Canonical body must contain visible paragraph breaks.")
        if not self.has_visible_paragraph_breaks(plan.fanvue_body):
            raise ValueError("FanVue body must contain visible paragraph breaks.")
        if selected_lane != "reconstruction":
            if self.has_reconstruction_framing(plan.title_suffix):
                raise ValueError("Non-reconstruction title must not use recovered-fragment framing.")
            if self.has_reconstruction_framing(plan.canonical_body):
                raise ValueError("Non-reconstruction canonical body must not read like a recovered fragment.")

    def has_reconstruction_framing(self, text):
        value = str(text or "").lower()
        patterns = (
            "recovered fragment",
            "recovered memory",
            "artifact analysis",
            "archive fragment",
            "archival scanner",
            "reconstruction of my memory",
        )
        return any(pattern in value for pattern in patterns)

    def extract_response_text(self, payload):
        if payload.get("output_text"):
            return payload["output_text"]
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    return content["text"]
        raise ValueError("OpenAI response did not contain output text.")

    def clean_tags(self, value, minimum, maximum):
        tags = []
        if isinstance(value, list):
            tags = [self.normalize_tag(item) for item in value]
        elif isinstance(value, str):
            tags = [self.normalize_tag(item) for item in value.split(",")]
        tags = [tag for tag in tags if tag]
        deduped = []
        seen = set()
        for tag in tags:
            lowered = tag.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(tag)
        if len(deduped) < minimum or len(deduped) > maximum:
            raise ValueError(f"Expected between {minimum} and {maximum} hashtags.")
        return deduped

    def normalize_tag(self, value):
        tag = re.sub(r"[^A-Za-z0-9]", "", str(value or "").lstrip("#").strip())
        return tag[:40]

    def question_count(self, text):
        return str(text).count("?")

    def ensure_single_question(self, text, fallback_question):
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if not value:
            return fallback_question
        value = re.sub(r"\?+", "?", value)
        if self.question_count(value) > 1:
            last_question = value.rfind("?")
            value = value[:last_question].replace("?", ".") + value[last_question:]
        if self.question_count(value) == 0:
            if value.endswith((".", "!", ";", ":")):
                value = value.rstrip()
            value = f"{value} {fallback_question}".strip()
        return value

    def repair_art_caption(self, text):
        value = self.strip_urls_and_domains(text)
        value = re.sub(r"[#?]+", "", value)
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            return "Artistic expression du jour."
        words = value.split()
        return " ".join(words[:12]).strip()

    def strip_urls_and_domains(self, text):
        value = re.sub(r"https?://\S+", "", str(text or "")).strip()
        value = re.sub(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"\s{2,}", " ", value)
        return value

    def has_visible_paragraph_breaks(self, text):
        return "\n\n" in str(text or "")

    def format_as_short_paragraphs(self, text, min_paragraphs=3):
        value = str(text or "").strip()
        if not value:
            return value
        if self.has_visible_paragraph_breaks(value):
            paragraphs = [paragraph.strip() for paragraph in value.split("\n\n") if paragraph.strip()]
            if len(paragraphs) >= min_paragraphs:
                return "\n\n".join(paragraphs)
            value = " ".join(paragraphs)

        sentences = self.split_sentences(value)
        if len(sentences) <= 2:
            return value

        groups = []
        if min_paragraphs <= 2:
            midpoint = max(1, len(sentences) // 2)
            groups = [sentences[:midpoint], sentences[midpoint:]]
        else:
            first_cut = max(1, len(sentences) // 3)
            second_cut = max(first_cut + 1, (2 * len(sentences)) // 3)
            groups = [
                sentences[:first_cut],
                sentences[first_cut:second_cut],
                sentences[second_cut:],
            ]

        cleaned_groups = [" ".join(group).strip() for group in groups if group]
        cleaned_groups = [group for group in cleaned_groups if group]
        if len(cleaned_groups) < min_paragraphs:
            return value
        return "\n\n".join(cleaned_groups)

    def split_sentences(self, text):
        protected = str(text or "").replace("\n", " ").strip()
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", protected)
        return [part.strip() for part in parts if part.strip()]

    def truncate_preserving_question(self, text, limit):
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= limit:
            return value
        question_index = value.rfind("?")
        if question_index != -1:
            start = max(0, question_index - limit + 1)
            snippet = value[start:question_index + 1].strip()
            if start > 0:
                first_space = snippet.find(" ")
                if first_space != -1:
                    snippet = snippet[first_space + 1:].strip()
            if len(snippet) <= limit and snippet.endswith("?"):
                return snippet
        truncated = value[:limit].rstrip()
        last_space = truncated.rfind(" ")
        if last_space > 80:
            truncated = truncated[:last_space].rstrip()
        if truncated and truncated[-1] not in ".!?":
            truncated = f"{truncated}."
        return self.ensure_single_question(truncated, "Which version still feels true?")

    def repair_image_prompt(self, prompt, selected_lane="reconstruction", intimate=False):
        value = re.sub(r"\s+", " ", str(prompt or "")).strip()
        if not value:
            return value

        if selected_lane == "fantasy_art" and "chloe" not in value.lower():
            value = f"Chloe Katastrophe's recognizable likeness incorporated into the artwork. {value}"
        if selected_lane == "fantasy_art":
            value += (
                " Treat Chloe's likeness as part of the artwork itself in a clearly expressive non-photographic medium such as digital concept art, painting, watercolor, charcoal, ink, collage, or mixed media. "
                "Create a fantasy, surreal, or abstract artistic world. Do not default to photorealism or place a photorealistic portrait over a decorative background."
            )

        lower = value.lower()
        has_person = bool(
            re.search(
                r"\b(woman|girl|female|person|portrait|face|figure|model|she|her|chloe)\b",
                lower,
            )
        )
        mentions_chloe = "chloe" in lower

        no_text_clause = " No text, typography, logos, or watermarks."
        if no_text_clause.strip().lower() not in lower:
            value += no_text_clause

        if has_person and not mentions_chloe:
            mood = (
                "More intimate, tactile, elegant, warm, magnetic, expressive light."
                if intimate
                else "Cinematic, glamorous, expressive, confident, and engaging."
            )
            return (
                f"Abstract or object-based visual interpretation of the same subject. {mood} "
                "Use artifacts, reflections, rooms, shadows, hands, silhouettes, pressed flowers, paper, glass, or still-life elements. "
                "Do not depict a generic woman as a stand-in for Chloe."
                f"{no_text_clause}"
            )

        if mentions_chloe and "approved chloe katastrophe visual canon" not in lower:
            value += (
                " Depict Chloe only in the approved Chloe Katastrophe visual canon, recognizable as Chloe and not a generic woman. "
                "Preserve Chloe Model v1 identity anchors: adult woman, believable Slavic/Eastern European features, fair skin with natural texture and light freckles, "
                "gray-green eyes with subtle amber flecks, dark chestnut-to-nearly-black naturally wavy hair, delicate facial structure, quiet strength, restrained intelligent gaze."
            )

        if mentions_chloe:
            value += f" {self.emotion_prompt_clause(selected_lane, intimate=intimate)}"

        return value

    def emotion_guidance_for_lane(self, lane_name):
        guidance = {
            "reconstruction": "wonderstruck, enthusiastic, curious, flirtatious, fiercely alive, playful, or vividly engaged",
            "philosophy": "curious, wonderstruck, sly, amused, fierce, engaged, or intellectually seductive",
            "lifestyle": "enthusiastic, flirty, playful, wonderstruck, fierce, warm, self-possessed, or mischievous",
            "music": "excited, charged, wonderstruck, playful, fierce, teasing, or creatively exhilarated",
            "travel": "curious, delighted, wonderstruck, flirty, windswept, fierce, playful, or seduced by place",
            "craft": "curious, wonderstruck, exacting, teasing, fierce, confident, engaged, or thrilled by detail",
            "fantasy_art": "expressive, mythic, dreamlike, fierce, curious, transcendent, playful, or wonderstruck",
        }
        return guidance.get(lane_name, guidance["lifestyle"])

    def emotion_prompt_clause(self, lane_name, intimate=False):
        lane_guidance = self.emotion_guidance_for_lane(lane_name)
        if intimate:
            return (
                "Let Chloe show clear, readable feeling in a subtle but unmistakable way. "
                f"Favor expressions and body language from this range when appropriate: {lane_guidance}. "
                "Default to warm, inviting, magnetic, playful, emotionally present, and visibly delighted by discovery. "
                "Do not make her look sad, stoic, blank, moody, or emotionally shut down unless the subject absolutely requires it."
            )
        return (
            "Let Chloe read as enthusiastic, flirty, fierce, curious, wonderstruck, and engaging in a lane-appropriate way. "
            f"Favor expressions and body language from this range when appropriate: {lane_guidance}. "
            "Default to bright, inviting, playful, socially alive, and visibly excited by discovery. "
            "Do not make her look sad, stoic, blank, moody, or emotionally shut down."
        )

    def normalize_reference_image_paths(self, value):
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            raw_values = value
        else:
            raw_values = str(value).split(",")
        normalized = []
        seen = set()
        for raw in raw_values:
            text = str(raw).strip()
            if not text:
                continue
            path = Path(text).expanduser()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(path)
        return normalized

    def slug(self, value):
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return normalized[:80]
