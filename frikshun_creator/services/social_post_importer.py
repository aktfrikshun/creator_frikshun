from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from ..models import Artifact, PostDraft
from .text import compact_tags


DEFAULT_SOCIAL_ROOT = Path(
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/social"
)


@dataclass
class SocialPostImportResult:
    scanned: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class SocialPostImporter:
    def __init__(self, session, root=DEFAULT_SOCIAL_ROOT):
        self.session = session
        self.root = Path(root)

    def run(self):
        result = SocialPostImportResult()
        for path in sorted(self.root.rglob("*.md")):
            result.scanned += 1
            text = path.read_text(encoding="utf-8").strip()
            caption = self.extract_caption(text)
            if not caption:
                result.skipped += 1
                continue

            platform = self.platform_for(path)
            artifact = self.find_or_create_artifact(path, text, platform, result)
            draft = (
                self.session.query(PostDraft)
                .filter(PostDraft.artifact_id == artifact.id)
                .filter(PostDraft.platform == platform)
                .one_or_none()
            )
            if draft is None:
                self.session.add(self.post_draft_for(artifact, platform, caption, text))
            else:
                draft.caption = caption
                draft.hashtags = self.extract_hashtags(text)
                draft.updated_at = datetime.now(timezone.utc)
                result.updated += 1

        self.session.commit()
        return result

    def find_or_create_artifact(self, path, text, platform, result):
        artifact = (
            self.session.query(Artifact)
            .filter(Artifact.media_path == str(path))
            .one_or_none()
        )
        if artifact is not None:
            return artifact

        artifact = Artifact(
            title=self.title_for(path, text),
            artifact_type="published_post",
            summary=f"Published/social post history imported from {platform}.",
            lore_text="Imported as tone and continuity history for future generation.",
            visibility="private",
            canonical_status="published_history",
            source_notes=f"Imported social post: {path}",
            original_filename=path.name,
            media_path=str(path),
            media_content_type="text/markdown",
            media_size=path.stat().st_size,
            content_tags=compact_tags([platform, "published post", "ChloKat"]),
            mood_tags=compact_tags(["archive", "published"]),
        )
        self.session.add(artifact)
        self.session.flush()
        result.created += 1
        return artifact

    def post_draft_for(self, artifact, platform, caption, text):
        return PostDraft(
            artifact_id=artifact.id,
            platform=platform,
            caption=caption,
            hashtags=self.extract_hashtags(text),
            call_to_action="Imported as prior published/social tone.",
            status="published",
            approved_at=datetime.now(timezone.utc),
        )

    def platform_for(self, path):
        try:
            return path.relative_to(self.root).parts[0]
        except ValueError:
            return "social"

    def title_for(self, path, text):
        for line in text.splitlines():
            if line.strip().startswith("#"):
                return line.strip().lstrip("#").strip()
        return path.stem.replace("_", " ").replace("-", " ").title()

    def extract_caption(self, text):
        section = self.extract_section(text, "Caption")
        if section:
            return section
        short = self.extract_section(text, "Short Caption Option")
        if short:
            return short
        match = re.search(r"Post copy:\s*(.+?)(?:\n#|\Z)", text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def extract_section(self, text, heading):
        pattern = rf"## {re.escape(heading)}\s*(.+?)(?:\n## |\Z)"
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def extract_hashtags(self, text):
        return compact_tags(re.findall(r"#([A-Za-z0-9_]+)", text))
