from .text import compact_tags
from ..models import Artifact, CanonEntry, PostDraft


class GenerationContext:
    def __init__(self, canon_entries=None, recent_posts=None, review_feedback=None):
        self.canon_entries = canon_entries or []
        self.recent_posts = recent_posts or []
        self.review_feedback = review_feedback or []

    @property
    def canon_excerpt(self):
        bodies = []
        voice_entries = [
            entry for entry in self.canon_entries if entry.canon_category == "voice/persona"
        ]
        other_entries = [
            entry for entry in self.canon_entries if entry.canon_category != "voice/persona"
        ]
        for entry in (voice_entries + other_entries)[:8]:
            if entry.body:
                bodies.append(f"{entry.title}: {entry.body[:500]}")
        return "\n".join(bodies)

    @property
    def visual_excerpt(self):
        bodies = []
        visual_entries = [
            entry for entry in self.canon_entries if entry.canon_category == "visual/persona"
        ]
        archive_visual_entries = [
            entry
            for entry in self.canon_entries
            if entry.canon_category.startswith("visuals/")
            or entry.canon_category == "visuals"
        ]
        for entry in (visual_entries + archive_visual_entries)[:6]:
            if entry.body:
                bodies.append(f"{entry.title}: {entry.body[:700]}")
        return "\n".join(bodies)

    @property
    def recent_post_excerpt(self):
        captions = []
        for draft in self.recent_posts[:8]:
            if draft.caption:
                captions.append(f"{draft.platform}: {draft.caption[:360]}")
        return "\n".join(captions)

    @property
    def review_feedback_excerpt(self):
        lessons = []
        for item in self.review_feedback[-12:]:
            category = str(item.get("category") or "general").replace("_", " ")
            reason = str(item.get("reason") or "").strip()
            if reason:
                lessons.append(f"Avoid a previously rejected {category} issue: {reason[:300]}")
        return "\n".join(lessons)

    @property
    def inherited_tags(self):
        tags = []
        for entry in self.canon_entries[:10]:
            tags.extend(entry.title.split())
        return compact_tags(tags)

    @property
    def has_chloe_voice_guidance(self):
        for entry in self.canon_entries:
            if entry.canon_category != "voice/persona":
                continue
            if (
                "emotionally restrained but vivid" in entry.body
                or "Preserve Chloe's voice" in entry.body
            ):
                return True
        return False

    @property
    def has_visual_chloe_guidance(self):
        for entry in self.canon_entries:
            category = entry.canon_category or ""
            if category == "visual/persona" or category.startswith("visuals/") or category == "visuals":
                return True
        return False


def load_generation_context(session):
    voice_entries = (
        session.query(CanonEntry)
        .filter(CanonEntry.canon_category == "voice/persona")
        .filter(CanonEntry.canonical_status == "voice_guidance")
        .filter(CanonEntry.usable_in_generation.is_(True))
        .order_by(CanonEntry.id.desc())
        .all()
    )
    visual_entries = (
        session.query(CanonEntry)
        .filter(
            CanonEntry.canon_category.in_(
                [
                    "visual/persona",
                    "visuals",
                    "visuals/photo_archive",
                    "visuals/reference_boards/chloe",
                ]
            )
            | CanonEntry.canon_category.like("visuals/%")
        )
        .filter(CanonEntry.canonical_status.in_(["approved", "reference"]))
        .filter(CanonEntry.usable_in_generation.is_(True))
        .order_by(CanonEntry.id.desc())
        .limit(12)
        .all()
    )
    other_entries = (
        session.query(CanonEntry)
        .filter(CanonEntry.canon_category.not_in(["voice/persona", "visual/persona"]))
        .filter(~CanonEntry.canon_category.like("visuals/%"))
        .filter(CanonEntry.canon_category != "visuals")
        .filter(CanonEntry.canonical_status.in_(["approved", "reference"]))
        .filter(CanonEntry.usable_in_generation.is_(True))
        .order_by(CanonEntry.id.desc())
        .limit(20)
        .all()
    )
    canon_entries = voice_entries + visual_entries + other_entries
    recent_posts = (
        session.query(PostDraft)
        .filter(PostDraft.status.in_(["approved", "published"]))
        .order_by(PostDraft.updated_at.desc())
        .limit(20)
        .all()
    )
    reviewed_artifacts = (
        session.query(Artifact)
        .filter(Artifact.fragment_code.like("daily-fragment-run-%"))
        .order_by(Artifact.updated_at.desc())
        .limit(30)
        .all()
    )
    review_feedback = []
    for artifact in reversed(reviewed_artifacts):
        review_feedback.extend(list((artifact.generated_metadata or {}).get("review_feedback") or []))
    return GenerationContext(
        canon_entries=canon_entries,
        recent_posts=recent_posts,
        review_feedback=review_feedback,
    )
