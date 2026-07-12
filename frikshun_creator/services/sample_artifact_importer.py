from dataclasses import dataclass
from pathlib import Path
import mimetypes

from ..models import Artifact, PostDraft
from .draft_generator import ArtifactDraftGenerator
from .generation_context import load_generation_context
from .metadata_generator import ArtifactMetadataGenerator


SAMPLE_ARTIFACTS = (
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/social/instagram/first-post/chloe-first-instagram-portrait.png",
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/social/keep-moving-release/keep-moving-teaser-001.wav",
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe/social/tiktok/touch-me-like-im-real/touch-me-like-im-real-tiktok-teaser-001.mp4",
)


@dataclass
class SampleArtifactImportResult:
    scanned: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class SampleArtifactImporter:
    def __init__(self, session, paths=SAMPLE_ARTIFACTS):
        self.session = session
        self.paths = tuple(Path(path) for path in paths)

    def run(self):
        result = SampleArtifactImportResult()
        context = load_generation_context(self.session)
        for path in self.paths:
            result.scanned += 1
            if not path.exists():
                result.skipped += 1
                continue

            upload_info = {
                "original_filename": path.name,
                "media_path": str(path),
                "media_content_type": mimetypes.guess_type(path.name)[0] or "",
                "media_size": path.stat().st_size,
            }
            metadata = ArtifactMetadataGenerator(upload_info, {}, context).defaults()
            artifact = (
                self.session.query(Artifact)
                .filter(Artifact.media_path == str(path))
                .one_or_none()
            )

            if artifact is None:
                artifact = Artifact(
                    title=metadata["title"],
                    artifact_type=metadata["artifact_type"],
                    summary=metadata["summary"],
                    lore_text=metadata["lore_text"],
                    visibility="private",
                    canonical_status="sample_import",
                    content_tags=metadata["content_tags"],
                    mood_tags=metadata["mood_tags"],
                    generated_metadata=metadata["generated_metadata"],
                    **upload_info,
                )
                self.session.add(artifact)
                self.session.flush()
                result.created += 1
            else:
                artifact.title = metadata["title"]
                artifact.summary = metadata["summary"]
                artifact.lore_text = metadata["lore_text"]
                artifact.generated_metadata = metadata["generated_metadata"]
                result.updated += 1

            self.replace_drafts(artifact, context)

        self.session.commit()
        return result

    def replace_drafts(self, artifact, context):
        self.session.query(PostDraft).filter(PostDraft.artifact_id == artifact.id).delete()
        for draft_data in ArtifactDraftGenerator(artifact, context).generate():
            self.session.add(PostDraft(artifact_id=artifact.id, **draft_data))
