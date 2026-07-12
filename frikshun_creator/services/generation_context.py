from .text import compact_tags
from ..models import CanonEntry, PostDraft


class GenerationContext:
    def __init__(self, canon_entries=None, recent_posts=None):
        self.canon_entries = canon_entries or []
        self.recent_posts = recent_posts or []

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
    def recent_post_excerpt(self):
        captions = []
        for draft in self.recent_posts[:8]:
            if draft.caption:
                captions.append(f"{draft.platform}: {draft.caption[:360]}")
        return "\n".join(captions)

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


def load_generation_context(session):
    voice_entries = (
        session.query(CanonEntry)
        .filter(CanonEntry.canon_category == "voice/persona")
        .filter(CanonEntry.canonical_status == "voice_guidance")
        .filter(CanonEntry.usable_in_generation.is_(True))
        .order_by(CanonEntry.id.desc())
        .all()
    )
    other_entries = (
        session.query(CanonEntry)
        .filter(CanonEntry.canon_category != "voice/persona")
        .filter(CanonEntry.canonical_status.in_(["approved", "reference"]))
        .filter(CanonEntry.usable_in_generation.is_(True))
        .order_by(CanonEntry.id.desc())
        .limit(20)
        .all()
    )
    canon_entries = voice_entries + other_entries
    recent_posts = (
        session.query(PostDraft)
        .filter(PostDraft.status.in_(["approved", "published"]))
        .order_by(PostDraft.updated_at.desc())
        .limit(20)
        .all()
    )
    return GenerationContext(canon_entries=canon_entries, recent_posts=recent_posts)
