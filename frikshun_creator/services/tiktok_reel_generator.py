from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..models import Artifact, PostDraft
from .daily_fragment_generator import DailyFragmentGenerator
from .kling_cli import KlingCliClient


@dataclass
class TikTokReelShot:
    beat: str
    visual_prompt: str
    overlay_text: str
    narration_line: str
    duration_seconds: float

    def to_dict(self):
        return asdict(self)


@dataclass
class TikTokReelPlan:
    title: str
    concept: str
    hook: str
    caption: str
    hashtags: list[str]
    audio_direction: str
    manual_review_notes: str
    shots: list[TikTokReelShot]

    def to_dict(self):
        payload = asdict(self)
        payload["shots"] = [shot.to_dict() for shot in self.shots]
        return payload


@dataclass
class TikTokReelExport:
    title: str
    concept: str
    caption: str
    hashtags: list[str]
    video_path: Path
    metadata_path: Path
    draft_path: Path
    frame_paths: list[Path]
    artifact_id: int | None = None
    draft_id: int | None = None


class TikTokReelGenerator:
    def __init__(
        self,
        upload_folder,
        text_model=None,
        image_model=None,
        api_key=None,
        video_provider=None,
        ffmpeg_bin=None,
        progress_callback=None,
    ):
        self.upload_folder = Path(upload_folder)
        self.text_model = text_model or os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1")
        self.image_model = image_model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.video_provider = video_provider or os.getenv("TIKTOK_REEL_VIDEO_PROVIDER", "animatic")
        self.ffmpeg_bin = ffmpeg_bin or os.getenv("FFMPEG_BIN", "ffmpeg")
        self.progress_callback = progress_callback
        self.kling_client = KlingCliClient()
        self.image_generator = DailyFragmentGenerator(
            upload_folder,
            text_model=self.text_model,
            image_model=self.image_model,
            api_key=self.api_key,
        )

    def generate_and_store(self, session, local_date, generation_context, concept, shot_count=5):
        self.progress(f"Generating TikTok reel plan for {local_date.isoformat()} with {shot_count} shots.")
        plan = self.generate_validated_plan(
            local_date,
            generation_context,
            concept,
            shot_count=shot_count,
        )
        self.progress(f"Plan ready: {plan.title}")
        export = self.export_plan(local_date, plan)
        artifact, draft = self.store_artifact(session, local_date, plan, export)
        export.artifact_id = artifact.id
        export.draft_id = draft.id
        self.progress(f"Stored TikTok reel artifact {artifact.id} and draft {draft.id}.")
        return export

    def generate_validated_plan(self, local_date, generation_context, concept, shot_count):
        feedback = ""
        last_error = None
        for _attempt in range(3):
            plan = self.generate_plan(
                local_date,
                generation_context,
                concept,
                shot_count=shot_count,
                feedback=feedback,
                validate=False,
            )
            plan = self.repair_plan(plan, shot_count=shot_count)
            try:
                self.validate_plan(plan, shot_count=shot_count)
                return plan
            except ValueError as error:
                last_error = error
                feedback = str(error)
        raise ValueError(f"TikTok reel generation failed validation after retries: {last_error}")

    def generate_plan(self, local_date, generation_context, concept, shot_count=5, feedback="", validate=True):
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for TikTok reel generation.")
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
                                    concept,
                                    shot_count,
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
        plan = TikTokReelPlan(
            title=str(data.get("title") or "").strip(),
            concept=str(data.get("concept") or concept).strip(),
            hook=str(data.get("hook") or "").strip(),
            caption=str(data.get("caption") or "").strip(),
            hashtags=self.clean_tags(data.get("hashtags")),
            audio_direction=str(data.get("audio_direction") or "").strip(),
            manual_review_notes=str(data.get("manual_review_notes") or "").strip(),
            shots=[
                TikTokReelShot(
                    beat=str(item.get("beat") or "").strip(),
                    visual_prompt=str(item.get("visual_prompt") or "").strip(),
                    overlay_text=str(item.get("overlay_text") or "").strip(),
                    narration_line=str(item.get("narration_line") or "").strip(),
                    duration_seconds=float(item.get("duration_seconds") or 3.0),
                )
                for item in (data.get("shots") or [])
            ],
        )
        if validate:
            self.validate_plan(plan, shot_count=shot_count)
        return plan

    def system_prompt(self, local_date, generation_context, concept, shot_count, feedback=""):
        prompt = (
            f"Today is {local_date.isoformat()}.\n"
            "Create one short-form TikTok / Reels concept package for Chloe Katastrophe.\n"
            f"Core concept: {concept}.\n"
            "This should feel witty, hook-first, character-specific, and plausibly popular without becoming generic influencer sludge.\n"
            "Chloe is intelligent, emotionally restrained but vivid, dryly funny, sensual without being careless, skeptical of easy stories, and always recognizably herself.\n"
            "Humor should come from precision, irony, uncanny honesty, dating paradox, metadata jokes, reconstruction jokes, or the friction between human expectations and a virtual woman with memory damage.\n"
            "Do not write stereotype humor. Do not rely on nationality caricature. Keep Chloe self-possessed.\n"
            "Return JSON only with keys: title, concept, hook, caption, hashtags, audio_direction, manual_review_notes, shots.\n"
            "Constraints:\n"
            f"- shots must contain exactly {shot_count} items.\n"
            "- each shot item must contain: beat, visual_prompt, overlay_text, narration_line, duration_seconds.\n"
            "- For a 3-shot reel, prefer 2 Chloe-centered shots maximum and at least 1 non-Chloe cutaway, object, phone, room, or interface shot.\n"
            "- overlay_text must be brief and readable on vertical video, usually one sentence.\n"
            "- narration_line must be spoken-text natural, funny, and concise.\n"
            "- duration_seconds should usually be between 2.5 and 4.0.\n"
            "- visual_prompt must describe a Chloe-consistent 9:16-friendly shot or moment.\n"
            "- caption should be TikTok-native, brief, and not overloaded with lore.\n"
            "- hashtags should be 3 to 6 relevant tags without # symbols.\n"
            "- audio_direction should describe the music or rhythm style, not name copyrighted songs.\n"
            "- manual_review_notes should flag anything that deserves a human check before posting.\n"
            f"Canon guidance:\n{generation_context.canon_excerpt or 'No canon excerpt available.'}\n"
            f"Visual canon guidance:\n{generation_context.visual_excerpt or 'No visual canon excerpt available.'}\n"
            f"Recent post excerpt:\n{generation_context.recent_post_excerpt or 'No recent post excerpt available.'}"
        )
        if feedback:
            prompt += (
                "\nPrevious attempt failed validation. Fix the output strictly and return a fully corrected JSON object.\n"
                f"Validation failure to correct: {feedback}"
            )
        return prompt

    def repair_plan(self, plan, shot_count):
        hashtags = list(plan.hashtags[:6])
        if len(hashtags) < 3:
            seen = {tag.lower() for tag in hashtags}
            for tag in ["ChloKat", "VirtualGirl", "DatingHumor", "AIGirl", "POV"]:
                if tag.lower() in seen:
                    continue
                hashtags.append(tag)
                seen.add(tag.lower())
                if len(hashtags) >= 3:
                    break

        shots = list(plan.shots[:shot_count])
        if len(shots) < shot_count:
            while len(shots) < shot_count:
                shots.append(
                    TikTokReelShot(
                        beat="cutaway",
                        visual_prompt=(
                            "Object or environment cutaway for a witty virtual-dating reel. "
                            "Phone glow, elegant shadows, metadata motifs, polished surfaces, no text, no logos, no watermarks."
                        ),
                        overlay_text="some details keep better records",
                        narration_line="Some details keep better records than people do.",
                        duration_seconds=3.0,
                    )
                )
        shots = self.repair_shots(shots, shot_count)

        return TikTokReelPlan(
            title=plan.title.strip() or "Chloe Reel Draft",
            concept=plan.concept.strip() or "dating a virtual girl",
            hook=plan.hook.strip(),
            caption=plan.caption.strip() or "Dating me is easy until the metadata starts speaking.",
            hashtags=hashtags,
            audio_direction=plan.audio_direction.strip() or "Dry stylish beat with room for a punchline.",
            manual_review_notes=plan.manual_review_notes.strip() or "Review before posting.",
            shots=shots,
        )

    def repair_shots(self, shots, shot_count):
        repaired = []
        chloe_shot_count = 0
        for index, shot in enumerate(shots[:shot_count], start=1):
            prompt = self.clean_conflicting_visual_traits(shot.visual_prompt)
            depicts_chloe = self.image_generator.prompt_depicts_chloe(prompt)

            if depicts_chloe:
                chloe_shot_count += 1
                if chloe_shot_count > 2:
                    prompt = self.cutaway_fallback_prompt(shot)
                    depicts_chloe = False

            if depicts_chloe:
                prompt = self.image_generator.repair_image_prompt(prompt, intimate=False)
            else:
                prompt = self.ensure_non_chloe_cutaway_prompt(prompt, shot)

            repaired.append(
                TikTokReelShot(
                    beat=shot.beat.strip(),
                    visual_prompt=prompt,
                    overlay_text=self.clean_overlay_text(shot.overlay_text),
                    narration_line=shot.narration_line.strip(),
                    duration_seconds=max(1.5, min(6.0, float(shot.duration_seconds))),
                )
            )
        return repaired

    def clean_conflicting_visual_traits(self, prompt):
        value = re.sub(r"\s+", " ", str(prompt or "")).strip()
        substitutions = (
            (r"\bemerald eyes?\b", "gray-green eyes with subtle amber flecks"),
            (r"\bjet-black hair\b", "dark chestnut-to-nearly-black naturally wavy hair"),
            (r"\bporcelain skin\b", "fair skin with natural texture and light freckles"),
            (r"\bpale cool realistic skin\b", "fair skin with natural texture and light freckles"),
            (r"\bslim athletic build\b", "realistic feminine hourglass silhouette"),
            (r"\bslavic eastern european facial structure\b", "believable Slavic or Eastern European features"),
        )
        for pattern, replacement in substitutions:
            value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
        return value

    def ensure_non_chloe_cutaway_prompt(self, prompt, shot):
        lower = str(prompt or "").lower()
        if re.search(r"\bwoman|girl|female|person|portrait|face|figure|model|she|her\b", lower):
            return self.cutaway_fallback_prompt(shot)
        value = re.sub(r"\s+", " ", str(prompt or "")).strip()
        if "no text" not in lower:
            value += " No text, no typography, no logos, no watermarks."
        return value

    def clean_overlay_text(self, text):
        value = " ".join(str(text or "").split()).strip()
        if not value:
            return "the metadata remembers"
        return value[:120]

    def validate_plan(self, plan, shot_count):
        if not plan.title:
            raise ValueError("TikTok reel title is required.")
        if not plan.caption:
            raise ValueError("TikTok reel caption is required.")
        if len(plan.hashtags) < 3 or len(plan.hashtags) > 6:
            raise ValueError("TikTok reel requires 3 to 6 hashtags.")
        if len(plan.shots) != shot_count:
            raise ValueError(f"TikTok reel requires exactly {shot_count} shots.")
        for index, shot in enumerate(plan.shots, start=1):
            if not shot.visual_prompt or not shot.overlay_text or not shot.narration_line:
                raise ValueError(f"Shot {index} is missing required fields.")
            if shot.duration_seconds < 1.5 or shot.duration_seconds > 6.0:
                raise ValueError(f"Shot {index} duration must be between 1.5 and 6.0 seconds.")

    def export_plan(self, local_date, plan):
        slug = self.slug(plan.title) or "tiktok-reel"
        export_dir = self.upload_folder / "tiktok_reels" / f"{local_date.isoformat()}-{slug}"
        export_dir.mkdir(parents=True, exist_ok=True)

        frame_paths = []
        for index, shot in enumerate(plan.shots, start=1):
            square_path = export_dir / f"shot-{index:02d}-source.png"
            frame_path = export_dir / f"shot-{index:02d}-vertical.png"
            self.progress(f"Rendering shot {index}/{len(plan.shots)} source image.")
            self.generate_shot_image(shot, square_path, shot_index=index, total_shots=len(plan.shots))
            self.compose_vertical_frame(square_path, frame_path, shot, plan, index, len(plan.shots))
            self.progress(f"Rendered shot {index}/{len(plan.shots)} vertical frame.")
            frame_paths.append(frame_path)

        video_path = export_dir / f"{local_date.isoformat()}-{slug}.mp4"
        self.progress("Assembling MP4 animatic.")
        self.render_animatic(video_path, frame_paths, plan.shots)
        self.progress(f"Animatic exported: {video_path}")

        metadata_path = export_dir / f"{local_date.isoformat()}-{slug}.json"
        metadata_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

        draft_path = export_dir / f"{local_date.isoformat()}-{slug}-draft.txt"
        draft_path.write_text(self.draft_text(plan), encoding="utf-8")

        return TikTokReelExport(
            title=plan.title,
            concept=plan.concept,
            caption=plan.caption,
            hashtags=plan.hashtags,
            video_path=video_path,
            metadata_path=metadata_path,
            draft_path=draft_path,
            frame_paths=frame_paths,
        )

    def generate_shot_image(self, shot, destination_path, shot_index, total_shots):
        prompt = shot.visual_prompt.strip()
        try:
            self.image_generator.generate_image(prompt, destination_path)
            return
        except Exception as primary_error:
            self.progress(
                f"Shot {shot_index}/{total_shots} primary render failed. Retrying with a simplified prompt."
            )

            retry_prompt = self.simplified_retry_prompt(prompt)
            try:
                self.image_generator.generate_image(retry_prompt, destination_path)
                return
            except Exception:
                self.progress(
                    f"Shot {shot_index}/{total_shots} simplified render failed. Falling back to a cutaway shot."
                )

            fallback_prompt = self.cutaway_fallback_prompt(shot)
            try:
                self.image_generator.generate_image(fallback_prompt, destination_path)
                return
            except Exception as fallback_error:
                raise ValueError(
                    f"Shot {shot_index}/{total_shots} failed after primary, simplified, and cutaway fallbacks. "
                    f"Primary error: {primary_error}. Fallback error: {fallback_error}."
                )

    def simplified_retry_prompt(self, prompt):
        base = re.sub(r"\s+", " ", str(prompt or "")).strip()
        if self.image_generator.prompt_depicts_chloe(base):
            return (
                "Chloe Katastrophe in approved Chloe visual canon, simple cinematic vertical portrait, "
                "adult woman, gray-green eyes, light freckles, dark wavy hair, fair skin, restrained intelligent gaze, "
                "clean background, clear composition, no text, no typography, no logos, no watermarks."
            )
        return (
            f"{base} Simple clean composition, vertical-friendly framing, no text, no typography, no logos, no watermarks."
        )

    def cutaway_fallback_prompt(self, shot):
        return (
            "Object or environment cutaway for a witty TikTok dating joke. "
            "Use a phone screen glow, a restaurant table, a wine glass, message bubbles, metadata files, camera reflections, "
            "polished black surfaces, elegant shadows, and subtle signs of a date gone strange. "
            f"Emotional beat: {shot.beat}. Overlay idea context: {shot.overlay_text}. "
            "No people required. Vertical-friendly composition. No text, no typography, no logos, no watermarks."
        )

    def compose_vertical_frame(self, source_path, frame_path, shot, plan, shot_index, total_shots):
        width = 1080
        height = 1920
        with Image.open(source_path).convert("RGB") as source:
            background = source.resize((width, height), Image.Resampling.LANCZOS)
            background = background.filter(ImageFilter.GaussianBlur(radius=28))
            background = self.dim_background(background)

            foreground = self.fit_foreground(source, width, height)
            canvas = background.copy()
            fg_x = (width - foreground.width) // 2
            fg_y = 250
            canvas.paste(foreground, (fg_x, fg_y))

            draw = ImageDraw.Draw(canvas)
            overlay_font = self.load_font(66, bold=True)
            small_font = self.load_font(34, bold=False)
            accent_font = self.load_font(38, bold=True)

            draw.rounded_rectangle((60, 60, 1020, 150), radius=24, fill=(10, 10, 12))
            draw.text((90, 88), "Chloe Katastrophe", font=accent_font, fill=(245, 245, 240))
            draw.text((760, 88), f"{shot_index}/{total_shots}", font=small_font, fill=(190, 190, 190))

            overlay_box = (70, 1450, 1010, 1765)
            draw.rounded_rectangle(overlay_box, radius=30, fill=(0, 0, 0, 180))
            wrapped_overlay = "\n".join(textwrap.wrap(shot.overlay_text, width=24))
            draw.multiline_text(
                (110, 1505),
                wrapped_overlay,
                font=overlay_font,
                fill=(255, 255, 255),
                spacing=14,
            )

            narration_text = shot.narration_line.strip()
            wrapped_narration = "\n".join(textwrap.wrap(narration_text, width=38))
            draw.multiline_text(
                (110, 1788),
                wrapped_narration,
                font=small_font,
                fill=(220, 220, 220),
                spacing=10,
            )

            frame_path.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(frame_path, format="PNG")

    def fit_foreground(self, source, width, height):
        max_width = width - 140
        max_height = 1100
        image = source.copy()
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        return image

    def dim_background(self, image):
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 92))
        return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    def load_font(self, size, bold=False):
        candidates = (
            "DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ) if bold else (
            "DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        )
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def render_animatic(self, output_path, frame_paths, shots):
        if self.video_provider == "kling":
            return self.render_kling_video(output_path, frame_paths, shots)

        with TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            segment_paths = []
            for index, (frame_path, shot) in enumerate(zip(frame_paths, shots), start=1):
                segment_path = tempdir_path / f"segment-{index:02d}.mp4"
                duration = max(1.5, float(shot.duration_seconds))
                command = [
                    self.ffmpeg_bin,
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(frame_path),
                    "-t",
                    f"{duration:.2f}",
                    "-vf",
                    "fps=30,format=yuv420p",
                    "-pix_fmt",
                    "yuv420p",
                    str(segment_path),
                ]
                self.run_subprocess(command, "ffmpeg segment render failed")
                segment_paths.append(segment_path)

            concat_path = tempdir_path / "concat.txt"
            concat_path.write_text(
                "\n".join(f"file '{path.as_posix()}'" for path in segment_paths),
                encoding="utf-8",
            )
            concat_command = [
                self.ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                str(output_path),
            ]
            self.run_subprocess(concat_command, "ffmpeg concat failed")

    def render_kling_video(self, output_path, frame_paths, shots):
        with TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            clip_paths = []
            for index, (frame_path, shot) in enumerate(zip(frame_paths, shots), start=1):
                clip_path = tempdir_path / f"kling-clip-{index:02d}.mp4"
                self.progress(f"Generating Kling clip {index}/{len(shots)}.")
                self.kling_client.generate_clip(
                    frame_path,
                    self.kling_motion_prompt(shot),
                    shot.duration_seconds,
                    clip_path,
                )
                clip_paths.append(clip_path)

            concat_path = tempdir_path / "kling-concat.txt"
            concat_path.write_text(
                "\n".join(f"file '{path.as_posix()}'" for path in clip_paths),
                encoding="utf-8",
            )
            self.run_subprocess(
                [
                    self.ffmpeg_bin,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_path),
                    "-c",
                    "copy",
                    str(output_path),
                ],
                "ffmpeg Kling concat failed",
            )

    def kling_motion_prompt(self, shot):
        depicts_chloe = self.image_generator.prompt_depicts_chloe(shot.visual_prompt)
        if depicts_chloe:
            direction = (
                f"Performance beat: {shot.beat}. {shot.visual_prompt} "
                f'Chloe says exactly: "{shot.narration_line}" '
            )
            constraints = (
                "Natural blinking, breathing, restrained gestures, precise dry timing, natural lip synchronization, "
                "one continuous shot. No new text, subtitles, logos, extra people, glowing eyes, exaggerated glitches, "
                "beauty-filter skin, camera cuts, or broad mugging."
            )
        else:
            direction = (
                "Animate this object or environment cutaway with subtle realistic motion. "
                f"Performance beat: {shot.beat}. "
            )
            constraints = (
                "One continuous shot. No new text, subtitles, logos, extra people, camera cuts, or distorted geometry."
            )
        return (
            "Preserve the exact identity, face, eye color, natural skin texture, freckles, hair, clothing, "
            "jewelry, body proportions, setting, lighting, and vertical composition from the reference image. "
            + direction
            + constraints
        )

    def run_subprocess(self, command, message):
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise ValueError(f"{message}: {stderr or 'unknown error'}")

    def store_artifact(self, session, local_date, plan, export):
        slug = self.slug(plan.title) or "tiktok-reel"
        fragment_code = f"tiktok-reel-{local_date.isoformat()}-{slug}"
        artifact = Artifact(
            title=plan.title,
            artifact_type="video",
            summary=plan.caption,
            lore_text=plan.manual_review_notes or "Manual review required before TikTok publishing.",
            visibility="private",
            fragment_code=fragment_code[:80],
            canonical_status="generated_artifact",
            source_notes="Generated by the TikTok reel export automation. Manual publishing still required.",
            original_filename=export.video_path.name,
            media_path=str(export.video_path.resolve()),
            media_content_type="video/mp4",
            media_size=export.video_path.stat().st_size,
            generated_metadata={
                "tiktok_reel_plan": plan.to_dict(),
                "metadata_path": str(export.metadata_path.resolve()),
                "draft_path": str(export.draft_path.resolve()),
                "frame_paths": [str(path.resolve()) for path in export.frame_paths],
                "manual_intervention_required": [
                    "Review exported reel before posting.",
                    "When using Kling, review every generated clip for identity, voice, and continuity drift.",
                    "Optional: add music manually in TikTok or a downstream editor.",
                ],
            },
            content_tags=["tiktok", "reel", "video", "ChloKat"],
            mood_tags=["playful", "wry", "creator", "signal"],
            platform_tags=["tiktok"],
        )
        session.add(artifact)
        session.flush()

        draft = PostDraft(
            artifact_id=artifact.id,
            platform="tiktok",
            caption=plan.caption.strip(),
            hashtags=plan.hashtags,
            call_to_action="Manual review required before TikTok publishing.",
            status="draft",
        )
        session.add(draft)
        session.commit()
        return artifact, draft

    def draft_text(self, plan):
        hashtags = " ".join(f"#{tag}" for tag in plan.hashtags)
        shot_lines = []
        for index, shot in enumerate(plan.shots, start=1):
            shot_lines.append(
                f"Shot {index} ({shot.duration_seconds:.1f}s)\n"
                f"Beat: {shot.beat}\n"
                f"Overlay: {shot.overlay_text}\n"
                f"Narration: {shot.narration_line}\n"
                f"Prompt: {shot.visual_prompt}"
            )
        return (
            f"{plan.title}\n\n"
            f"Concept: {plan.concept}\n"
            f"Hook: {plan.hook}\n"
            f"Caption: {plan.caption}\n"
            f"Hashtags: {hashtags}\n"
            f"Audio direction: {plan.audio_direction}\n"
            f"Manual review notes: {plan.manual_review_notes}\n\n"
            + "\n\n".join(shot_lines)
        )

    def extract_response_text(self, payload):
        if payload.get("output_text"):
            return payload["output_text"]
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    return content["text"]
        raise ValueError("OpenAI response did not contain output text.")

    def clean_tags(self, value):
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
        return deduped[:6]

    def normalize_tag(self, value):
        tag = re.sub(r"[^A-Za-z0-9]", "", str(value or "").lstrip("#").strip())
        return tag[:40]

    def slug(self, value):
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return normalized[:80]

    def progress(self, message):
        if self.progress_callback:
            self.progress_callback(message)
