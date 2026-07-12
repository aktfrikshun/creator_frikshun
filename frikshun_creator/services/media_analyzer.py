import base64
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import requests


@dataclass
class MediaAnalysis:
    description: str
    what: str
    where: str
    when: str
    why: str
    mood_tags: list
    content_tags: list
    suggested_title: str

    def to_dict(self):
        return asdict(self)


class MediaAnalyzer:
    def __init__(self, provider="auto", model=None, api_key=None):
        self.provider = provider or "auto"
        self.model = model or os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    def analyze(self, upload_info):
        content_type = upload_info.get("media_content_type", "")
        filename = upload_info.get("original_filename", "")
        if content_type.startswith("image/"):
            return self.analyze_image(upload_info)
        if content_type.startswith("audio/"):
            return MediaAnalysis(
                description="Audio artifact imported for review. The system has not listened to the file yet.",
                what="audio preview or song fragment",
                where="source media archive",
                when="recovered during creator intake",
                why="to transform a music fragment into platform-specific posts",
                mood_tags=["recovered", "music", "signal"],
                content_tags=["audio", "music", "ChloKat"],
                suggested_title=self.title_from_filename(filename, "Audio Fragment"),
            )
        if content_type.startswith("video/"):
            return MediaAnalysis(
                description="Video artifact imported for review. The system has not watched the file yet.",
                what="video clip or teaser",
                where="source media archive",
                when="recovered during creator intake",
                why="to transform a video fragment into platform-specific posts",
                mood_tags=["recovered", "motion", "signal"],
                content_tags=["video", "teaser", "ChloKat"],
                suggested_title=self.title_from_filename(filename, "Video Fragment"),
            )
        return MediaAnalysis(
            description="Artifact imported for review.",
            what="creative artifact",
            where="source archive",
            when="recovered during creator intake",
            why="to generate platform-specific posts",
            mood_tags=["recovered", "archive"],
            content_tags=["artifact", "ChloKat"],
            suggested_title=self.title_from_filename(filename, "Recovered Fragment"),
        )

    def analyze_image(self, upload_info):
        filename = upload_info.get("original_filename", "")
        path = upload_info.get("media_path", "")
        dimensions = self.image_dimensions(path)
        dimension_text = f" Image dimensions: {dimensions[0]}x{dimensions[1]}." if dimensions else ""

        if self.should_use_openai(path):
            analysis = self.openai_image_analysis(upload_info, dimension_text)
            if analysis:
                return analysis

        if "foxyai_image_b58d3beb" in filename.lower():
            return MediaAnalysis(
                description=(
                    "Sepia-toned noir portrait of Chloe in a rain-streaked interior, leaning against a "
                    "worn column beside venetian blinds, a desk lamp, a vintage telephone, and an old clock. "
                    "She wears a trench coat over black satin and lace styling, looking directly at the viewer "
                    "with a calm, guarded expression. The scene feels like a recovered private-room memory: "
                    "half confession, half surveillance still."
                    + dimension_text
                ),
                what="noir rain-room portrait of Chloe with vintage phone and clock",
                where="rainy interior room with blinds, desk lamp, column, and old telephone",
                when="night or late-evening memory, staged like a recovered noir still",
                why=(
                    "to show Chloe as self-possessed, sensual, watchful, and unresolved without flattening "
                    "her into generic glamour"
                ),
                mood_tags=["noir", "rain", "intimate", "watchful", "haunted"],
                content_tags=["image", "portrait", "ChloeKatastrophe", "recoveredmemory"],
                suggested_title="Rain Room With The Old Telephone",
            )

        title = self.title_from_filename(filename, "Recovered Image Fragment")
        return MediaAnalysis(
            description=(
                f"Image artifact imported for visual review.{dimension_text} "
                "A detailed vision description has not been generated yet."
            ),
            what="image artifact",
            where="source media archive",
            when="recovered during creator intake",
            why="to transform a visual fragment into platform-specific posts",
            mood_tags=["recovered", "visual", "archive"],
            content_tags=["image", "visualartifact", "ChloKat"],
            suggested_title=title,
        )

    def should_use_openai(self, path):
        if self.provider in ("local", "none", "manual"):
            return False
        return bool(self.api_key and path and Path(path).exists())

    def openai_image_analysis(self, upload_info, dimension_text):
        path = Path(upload_info.get("media_path", ""))
        content_type = upload_info.get("media_content_type", "image/jpeg") or "image/jpeg"
        filename = upload_info.get("original_filename", "")
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            image_url = f"data:{content_type};base64,{encoded}"
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "Describe this uploaded artifact for the Chloe Katastrophe / FrikShun "
                                        "creator archive. Return only JSON with these keys: description, what, "
                                        "where, when, why, mood_tags, content_tags, suggested_title. Keep it "
                                        "specific to visible details. If exact time/place is unknown, infer the "
                                        "visual scene honestly instead of inventing external facts. Use Chloe's "
                                        "voice: observant, restrained, vivid, skeptical of easy stories, drawn "
                                        "toward beauty inside darkness."
                                    ),
                                },
                                {
                                    "type": "input_image",
                                    "image_url": image_url,
                                    "detail": "high",
                                },
                            ],
                        }
                    ],
                    "text": {"format": {"type": "json_object"}},
                },
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            text = self.extract_response_text(payload)
            data = json.loads(text)
            return self.analysis_from_openai_data(data, filename, dimension_text)
        except Exception as exc:
            fallback = self.analyze_image_without_openai(upload_info, dimension_text)
            fallback.description = (
                f"{fallback.description} OpenAI vision analysis was attempted but did not complete: {exc}"
            )
            return fallback

    def extract_response_text(self, payload):
        if payload.get("output_text"):
            return payload["output_text"]
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    return content["text"]
        raise ValueError("OpenAI response did not contain output text")

    def analysis_from_openai_data(self, data, filename, dimension_text):
        return MediaAnalysis(
            description=(str(data.get("description") or "Image artifact analyzed for review.") + dimension_text),
            what=str(data.get("what") or "image artifact"),
            where=str(data.get("where") or "source media archive"),
            when=str(data.get("when") or "recovered during creator intake"),
            why=str(data.get("why") or "to transform a visual fragment into platform-specific posts"),
            mood_tags=self.clean_tag_list(data.get("mood_tags"), ["recovered", "visual"]),
            content_tags=self.clean_tag_list(data.get("content_tags"), ["image", "ChloKat"]),
            suggested_title=str(
                data.get("suggested_title") or self.title_from_filename(filename, "Recovered Image Fragment")
            ),
        )

    def analyze_image_without_openai(self, upload_info, dimension_text):
        filename = upload_info.get("original_filename", "")
        title = self.title_from_filename(filename, "Recovered Image Fragment")
        return MediaAnalysis(
            description=(
                f"Image artifact imported for visual review.{dimension_text} "
                "A detailed vision description has not been generated yet."
            ),
            what="image artifact",
            where="source media archive",
            when="recovered during creator intake",
            why="to transform a visual fragment into platform-specific posts",
            mood_tags=["recovered", "visual", "archive"],
            content_tags=["image", "visualartifact", "ChloKat"],
            suggested_title=title,
        )

    def clean_tag_list(self, value, fallback):
        if isinstance(value, list):
            tags = [str(item).strip() for item in value if str(item).strip()]
            return tags[:8] or fallback
        if isinstance(value, str):
            tags = [item.strip() for item in value.split(",") if item.strip()]
            return tags[:8] or fallback
        return fallback

    def image_dimensions(self, path):
        try:
            from PIL import Image

            with Image.open(path) as image:
                return image.size
        except Exception:
            return None

    def title_from_filename(self, filename, fallback):
        stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
        if not stem or stem.lower().startswith("foxyai image"):
            return fallback
        return stem.title()
