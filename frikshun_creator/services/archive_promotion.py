from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re

from ..models import CanonEntry


DEFAULT_ARCHIVE_ROOT = Path(
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe"
)

RECORD_TYPES = {
    "daily_signal": ("Daily signal", Path("social/daily-signals")),
    "field_note": ("Field note", Path("social/field-notes")),
    "recovery_log": ("Recovery log", Path("canon/recovery_logs")),
    "collaboration": ("Collaboration record", Path("social/collaborations")),
    "context": ("Context note", Path("context/creator-notes")),
    "canon": ("Canon proposal", Path("canon/creator-promotions")),
}

CANON_STATUSES = {
    "confirmed_canon",
    "accepted_model",
    "draft_canon",
    "proposal",
    "generated_artifact",
    "recovered_fragment",
    "contradiction",
    "unresolved_mystery",
}


@dataclass(frozen=True)
class PromotionResult:
    path: Path
    created: bool


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    return slug[:90] or "untitled"


class ArchivePromotionService:
    """Write an explicitly reviewed Creator post into the durable Chloe archive."""

    def __init__(self, session, root=DEFAULT_ARCHIVE_ROOT):
        self.session = session
        self.root = Path(root).expanduser()

    def promote(
        self,
        artifact,
        *,
        record_type,
        topics,
        canonical_status,
        context_note="",
        usable_in_generation=False,
    ):
        if record_type not in RECORD_TYPES:
            raise ValueError("Choose a valid archive record type.")
        if canonical_status not in CANON_STATUSES:
            raise ValueError("Choose a valid canonical status.")
        topics = self.clean_topics(topics)
        if not topics:
            raise ValueError("Add at least one topic before pushing to the archive.")
        if usable_in_generation and canonical_status not in {"confirmed_canon", "accepted_model"}:
            raise ValueError("Only confirmed canon or an accepted model may guide generation.")

        local_date = str((artifact.generated_metadata or {}).get("local_date") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
            local_date = datetime.now(timezone.utc).date().isoformat()
        label, directory = RECORD_TYPES[record_type]
        stable_id = artifact.fragment_code or f"creator-{artifact.id}"
        filename = f"{local_date}-{slugify(artifact.title)}-{slugify(stable_id)}.md"
        path = self.root / directory / filename
        created = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = self.render(
            artifact,
            label=label,
            record_type=record_type,
            topics=topics,
            canonical_status=canonical_status,
            context_note=context_note,
            local_date=local_date,
            usable_in_generation=usable_in_generation,
        )
        path.write_text(body, encoding="utf-8")

        if record_type in {"canon", "recovery_log", "context"}:
            self.upsert_canon_entry(
                path,
                artifact.title,
                body,
                record_type,
                canonical_status,
                usable_in_generation,
            )
        return PromotionResult(path=path, created=created)

    def render(self, artifact, *, label, record_type, topics, canonical_status, context_note, local_date, usable_in_generation):
        metadata = dict(artifact.generated_metadata or {})
        catalog_id = str(metadata.get("catalog_entry_id") or "").strip()
        topic_text = ", ".join(topics)
        context_note = str(context_note or "").strip()
        source = artifact.fragment_code or f"creator-artifact-{artifact.id}"
        lines = [
            f"# {label} — {artifact.title}",
            "",
            f"Status: {canonical_status.replace('_', ' ').title()}",
            f"Record type: {record_type.replace('_', ' ').title()}",
            f"Date: {local_date}",
            f"Topics: {topic_text}",
            f"Creator source: {source}",
            f"Generation eligible: {'yes' if usable_in_generation else 'no'}",
        ]
        if catalog_id:
            lines.append(f"Catalog entry: {catalog_id}")
        lines.extend(["", "## Record", "", str(artifact.summary or artifact.lore_text or "").strip()])
        if context_note:
            lines.extend(["", "## Archivist context", "", context_note])
        lines.extend(
            [
                "",
                "## Provenance",
                "",
                "Promoted explicitly from FrikShun Creator OS. Social publication, public visibility, "
                "canonical status, and generation eligibility remain separate decisions.",
                "",
            ]
        )
        return "\n".join(lines)

    def upsert_canon_entry(self, path, title, body, record_type, canonical_status, usable_in_generation):
        source_path = str(path.resolve())
        entry = self.session.query(CanonEntry).filter_by(source_path=source_path).one_or_none()
        attrs = {
            "title": title,
            "body": body,
            "source_path": source_path,
            "source_hash": sha256(body.encode("utf-8")).hexdigest(),
            "source_mtime": str(path.stat().st_mtime),
            "canon_category": f"creator/{record_type}",
            "canonical_status": self.generation_status(canonical_status),
            "usable_in_generation": bool(usable_in_generation),
            "usable_in_chat": False,
            "imported_at": datetime.now(timezone.utc),
        }
        if entry is None:
            self.session.add(CanonEntry(**attrs))
        else:
            for key, value in attrs.items():
                setattr(entry, key, value)

    @staticmethod
    def generation_status(status):
        return {"confirmed_canon": "approved", "accepted_model": "reference"}.get(status, status)

    @staticmethod
    def clean_topics(value):
        if isinstance(value, str):
            values = value.split(",")
        else:
            values = value or []
        cleaned = []
        for value in values:
            topic = re.sub(r"\s+", " ", str(value).strip())
            if topic and topic.casefold() not in {item.casefold() for item in cleaned}:
                cleaned.append(topic[:80])
        return cleaned[:12]
