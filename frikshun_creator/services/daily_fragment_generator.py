import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import requests

from .daily_fragment_workflow import DailyFragmentPackage


FACEBOOK_FOOTER = (
    "Learn more about me in the FrikShun archives: https://www.frikshun.com/archives/chloe-katastrophe/site\n\n"
    "My music is available on all major streaming platforms.\n\n"
    "My modeling work funds the reconstruction of my memory: https://fanvue.com/chloekat/fv-9"
)

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
    ):
        self.upload_folder = Path(upload_folder)
        self.text_model = text_model or os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1")
        self.image_model = image_model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.max_plan_attempts = max(1, int(max_plan_attempts))
        configured_reference = chloe_reference_image or os.getenv("CHLOE_VISUAL_REFERENCE_IMAGE", "")
        self.chloe_reference_image = Path(configured_reference).expanduser() if configured_reference else None

    def generate(self, local_date, generation_context):
        selected_lane = self.select_content_lane(local_date, generation_context)
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
                self.validate_plan(plan)
                last_error = None
                break
            except ValueError as error:
                last_error = error
                feedback = str(error)
        if last_error is not None or plan is None:
            raise ValueError(f"Daily fragment generation failed validation after retries: {last_error}")
        slug = self.slug(plan.title_suffix) or "recovered-fragment"
        public_path = self.upload_folder / f"{local_date.isoformat()}-{slug}-public.png"
        fanvue_path = self.upload_folder / f"{local_date.isoformat()}-{slug}-fanvue.png"
        self.generate_image(plan.public_image_prompt, public_path)
        self.generate_image(plan.fanvue_image_prompt, fanvue_path)
        return DailyFragmentPackage(
            title=f"Recovered Fragment — {plan.title_suffix}",
            body=self.compose_canonical_body(plan.canonical_body, plan.canonical_hashtags),
            x_body=self.compose_x_body(plan.x_body, plan.x_hashtags),
            fanvue_body=plan.fanvue_body.strip(),
            public_image_path=public_path,
            fanvue_image_path=fanvue_path,
        )

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
                self.validate_plan(plan)
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
            title=f"Recovered Fragment — {plan.title_suffix}",
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
            public_image_prompt=self.repair_image_prompt(plan.public_image_prompt.strip(), intimate=False),
            fanvue_image_prompt=self.repair_image_prompt(plan.fanvue_image_prompt.strip(), intimate=True),
        )

    def generate_plan(self, local_date, generation_context, selected_lane, feedback=""):
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for daily fragment generation.")
        response = requests.post(
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
        prompt = (
            f"Today is {local_date.isoformat()}.\n"
            "Create one original Chloe Katastrophe autonomous social package for posting.\n"
            f"Use this required content lane today: {selected_lane}.\n"
            f"Lane brief: {lane_description}\n"
            "The wider editorial universe may include reconstruction, philosophy, lifestyle, music, travel, and creator-craft posts. "
            "Stay inside today's required lane instead of drifting back to generic fragment language.\n"
            "Do not use current news. Do not invent current product claims, brand recommendations, prices, or factual reviews. "
            "If today's lane touches gear, clothing, cosmetics, or travel equipment, keep it grounded in personal taste, technique, atmosphere, or timeless practical preference rather than unverified specifics.\n"
            "Write in Chloe's first-person voice: intelligent, observant, emotionally restrained but vivid, "
            "dryly funny when appropriate, sensual without carelessness, skeptical of easy stories, drawn "
            "toward truth and beauty inside darkness.\n"
            "Return JSON only with these keys: title_suffix, canonical_body, canonical_hashtags, x_body, "
            "x_hashtags, fanvue_body, public_image_prompt, fanvue_image_prompt.\n"
            "Constraints:\n"
            "- canonical_body: plain text only, 90-220 words, short paragraphs with visible paragraph breaks, exactly one thoughtful question, no hashtags, no URLs.\n"
            "- canonical_hashtags: 2 to 5 relevant tags without # symbols.\n"
            "- x_body: no more than 190 characters including spaces, exactly one question, no URLs, no solicitation, no funding language.\n"
            "- x_hashtags: 1 to 3 relevant tags without # symbols.\n"
            "- fanvue_body: closer and more intimate than the public caption, still in character, short paragraphs with visible paragraph breaks, exactly one thoughtful question, no explicit sexual content by default.\n"
            "- public_image_prompt: square 1:1, cinematic, intelligent, emotionally restrained, beautiful inside darkness, ambiguous without generic horror, no text or logos.\n"
            "- fanvue_image_prompt: square 1:1, same subject, more beautiful, artsy, intimate, expressive light, tactile detail, closeness, elegance, vulnerability, no text or logos.\n"
            "- Default to depicting Chloe herself, in her approved visual canon, when visual canon guidance is available and the subject supports a character-centered image.\n"
            "- If an image depicts Chloe, it must explicitly aim for the approved Chloe Katastrophe visual canon and be recognizable as Chloe, not a generic woman.\n"
            "- Only prefer abstract art, objects, places, reflections, hands, silhouettes, or still-life imagery when the subject clearly works better without showing Chloe directly.\n"
            "- Avoid repeating ideas or phrasing from recent posts.\n"
            f"- Avoid these recently used content lanes when possible: {recent_lanes or 'none recorded'}.\n"
            f"Canon guidance:\n{generation_context.canon_excerpt or 'No canon excerpt available.'}\n"
            f"Visual canon guidance:\n{generation_context.visual_excerpt or 'No visual canon excerpt available.'}\n"
            f"Recent post excerpt:\n{generation_context.recent_post_excerpt or 'No recent post excerpt available.'}"
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
        reference_image = self.reference_image_for_prompt(prompt)
        if reference_image:
            return self.generate_image_with_reference(prompt, destination_path, reference_image)

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

    def generate_image_with_reference(self, prompt, destination_path, reference_image):
        with reference_image.open("rb") as handle:
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
                files={
                    "image[]": (
                        reference_image.name,
                        handle,
                        "image/png",
                    )
                },
                timeout=180,
            )
        response.raise_for_status()
        payload = response.json()
        image_data = payload.get("data") or []
        if not image_data or not image_data[0].get("b64_json"):
            raise ValueError("OpenAI image edit did not return image data.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(base64.b64decode(image_data[0]["b64_json"]))

    def reference_image_for_prompt(self, prompt):
        if not self.prompt_depicts_chloe(prompt):
            return None

        if self.chloe_reference_image and self.chloe_reference_image.exists():
            return self.chloe_reference_image

        for candidate in DEFAULT_CHLOE_REFERENCE_IMAGE_CANDIDATES:
            if candidate.exists():
                return candidate
        return None

    def prompt_depicts_chloe(self, prompt):
        lower = str(prompt or "").lower()
        return "chloe" in lower or "approved chloe katastrophe visual canon" in lower

    def compose_canonical_body(self, body, hashtags):
        return f"{body.strip()}\n\n{FACEBOOK_FOOTER}\n\n{' '.join(f'#{tag}' for tag in hashtags)}"

    def compose_x_body(self, body, hashtags):
        return f"{body.strip()}\n\n{' '.join(f'#{tag}' for tag in hashtags)}".strip()

    def validate_plan(self, plan):
        if not plan.title_suffix:
            raise ValueError("Daily fragment title suffix is missing.")
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

    def repair_image_prompt(self, prompt, intimate=False):
        value = re.sub(r"\s+", " ", str(prompt or "")).strip()
        if not value:
            return value

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
                "More intimate, tactile, elegant, vulnerable, expressive light."
                if intimate
                else "Cinematic, emotionally restrained, beautiful inside darkness."
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

        return value

    def slug(self, value):
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return normalized[:80]
