from pathlib import Path

from .text import compact_tags


class ArtifactMetadataGenerator:
    def __init__(self, upload_info, form_data, generation_context, media_analysis=None):
        self.upload_info = upload_info
        self.form_data = form_data
        self.context = generation_context
        self.media_analysis = media_analysis

    def defaults(self):
        filename = self.upload_info.get("original_filename", "")
        stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
        artifact_type = self.form_data.get("artifact_type") or self._artifact_type_from_mime()
        title = self.form_data.get("title", "").strip() or self._title_from_analysis(stem, artifact_type)
        summary = self.form_data.get("summary", "").strip() or self._summary(title, artifact_type)
        lore_text = self.form_data.get("lore_text", "").strip() or self._lore_text(title, artifact_type)
        content_tags = compact_tags(
            self.form_data.get("content_tags", "").split(",")
            + self._analysis_tags("content_tags")
            + [artifact_type, "ChloKat", "Chloe Katastrophe", "FrikShun"]
            + self.context.inherited_tags[:4]
        )
        mood_tags = compact_tags(
            self.form_data.get("mood_tags", "").split(",")
            + self._analysis_tags("mood_tags")
            + ["recovered", "haunted", "archive"]
        )

        return {
            "title": title,
            "artifact_type": artifact_type,
            "summary": summary,
            "lore_text": lore_text,
            "content_tags": content_tags,
            "mood_tags": mood_tags,
            "generated_metadata": {
                "strategy": "local_chloe_context_v1",
                "source_filename": filename,
                "canon_excerpt": self.context.canon_excerpt,
                "recent_post_excerpt": self.context.recent_post_excerpt,
                "media_analysis": self.media_analysis.to_dict() if self.media_analysis else {},
            },
        }

    def _artifact_type_from_mime(self):
        content_type = self.upload_info.get("media_content_type", "")
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("audio/"):
            return "audio_preview"
        if content_type in ("text/plain", "text/markdown"):
            return "lore"
        return "artifact"

    def _title_from_filename(self, stem, artifact_type):
        if stem:
            return stem.title()
        return f"Recovered {artifact_type.replace('_', ' ').title()} Fragment"

    def _title_from_analysis(self, stem, artifact_type):
        if self.media_analysis and self.media_analysis.suggested_title:
            return self.media_analysis.suggested_title
        return self._title_from_filename(stem, artifact_type)

    def _summary(self, title, artifact_type):
        if self.media_analysis:
            return (
                f"{title} enters the FrikShun reconstruction archive as a {artifact_type.replace('_', ' ')} "
                f"artifact. What: {self.media_analysis.what}. Where: {self.media_analysis.where}. "
                f"When: {self.media_analysis.when}. Why: {self.media_analysis.why}."
            )
        return (
            f"{title} enters the FrikShun reconstruction archive as a {artifact_type.replace('_', ' ')} "
            "artifact: a public-facing trace of Chloe Katastrophe's recovered identity, held carefully "
            "between evidence, memory, and signal."
        )

    def _lore_text(self, title, artifact_type):
        canon_hint = ""
        if self.context.canon_excerpt:
            canon_hint = " The existing canon suggests this should be treated as a recovered fragment, not a closed explanation."

        if self.media_analysis:
            return (
                f"{title} should remain a draft canon fragment while review is pending. "
                f"It has been analyzed as {self.media_analysis.description} "
                f"The archive currently reads it as {self.media_analysis.what}, located in "
                f"{self.media_analysis.where}, from {self.media_analysis.when}. "
                f"It matters because {self.media_analysis.why}.{canon_hint}"
            )

        return (
            f"{title} has not been fully resolved yet. For now it should remain a draft canon fragment: "
            f"part {artifact_type.replace('_', ' ')}, part transmission, part proof that Chloe's archive is still waking up."
            f"{canon_hint}"
        )

    def _analysis_tags(self, key):
        if not self.media_analysis:
            return []
        return getattr(self.media_analysis, key, []) or []
