from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ..models import CanonEntry


DEFAULT_CANON_ROOT = Path(
    "/Users/allentaylor/src/frikshun_marketing/archives/chloe-katastrophe"
)

DEFAULT_IMPORT_PATHS = (
    "AGENTS.md",
    "canon",
    "characters",
    "music",
    "stories",
    "brand",
    "releases",
)

DEFAULT_EXTRA_FILES = (
    Path("/Users/allentaylor/src/frikshun_image_studio/AGENTS.md"),
)


@dataclass
class CanonImportResult:
    scanned: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0


class CanonImporter:
    def __init__(
        self,
        session,
        root=DEFAULT_CANON_ROOT,
        import_paths=DEFAULT_IMPORT_PATHS,
        extra_files=DEFAULT_EXTRA_FILES,
    ):
        self.session = session
        self.root = Path(root)
        self.import_paths = tuple(import_paths)
        self.extra_files = tuple(Path(path) for path in extra_files)

    def run(self):
        result = CanonImportResult()
        for path in self.markdown_files():
            result.scanned += 1
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                result.skipped += 1
                continue

            source_path = str(path)
            source_hash = sha256(text.encode("utf-8")).hexdigest()
            entry = (
                self.session.query(CanonEntry)
                .filter(CanonEntry.source_path == source_path)
                .one_or_none()
            )

            attrs = self.entry_attributes(path, text, source_hash)
            if entry is None:
                self.session.add(CanonEntry(**attrs))
                result.created += 1
                continue

            if entry.source_hash == source_hash:
                result.unchanged += 1
                continue

            for key, value in attrs.items():
                setattr(entry, key, value)
            result.updated += 1

        self.session.commit()
        return result

    def markdown_files(self):
        files = []
        for relative in self.import_paths:
            import_root = self.root / relative
            if import_root.is_file() and import_root.suffix.lower() == ".md":
                files.append(import_root)
            elif import_root.exists():
                files.extend(import_root.rglob("*.md"))
        for extra_file in self.extra_files:
            if extra_file.exists() and extra_file.suffix.lower() == ".md":
                files.append(extra_file)
        return sorted(set(files))

    def entry_attributes(self, path, text, source_hash):
        title = self.title_for(path, text)
        status = self.status_for(path)
        return {
            "title": title,
            "body": text,
            "source_path": str(path),
            "source_hash": source_hash,
            "source_mtime": str(path.stat().st_mtime),
            "canon_category": self.category_for(path),
            "canonical_status": status,
            "usable_in_generation": self.usable_in_generation(path, status),
            "usable_in_chat": self.usable_in_chat(path, status),
            "imported_at": datetime.now(timezone.utc),
        }

    def title_for(self, path, text):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return path.stem.replace("_", " ").replace("-", " ").title()

    def category_for(self, path):
        if path.name == "AGENTS.md":
            return "voice/persona"
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return "external"
        parts = relative.parts
        if len(parts) <= 1:
            return parts[0] if parts else "canon"
        return "/".join(parts[:-1])

    def status_for(self, path):
        if path.name == "AGENTS.md":
            return "voice_guidance"
        lowered = str(path).lower()
        if "unresolved" in lowered or "open_mystery" in lowered:
            return "unresolved_mystery"
        if "draft" in lowered:
            return "draft_canon"
        if "visual" in lowered or "modeling" in lowered:
            return "reference"
        return "approved"

    def usable_in_generation(self, path, status):
        if status == "unresolved_mystery":
            return False
        lowered = str(path).lower()
        return "workflow" not in lowered and "chat_exports" not in lowered

    def usable_in_chat(self, path, status):
        if status not in ("approved", "voice_guidance"):
            return False
        lowered = str(path).lower()
        return "/canon/" in lowered or "/music/" in lowered or "/stories/" in lowered
