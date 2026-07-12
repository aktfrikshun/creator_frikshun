from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import CanonEntry
from frikshun_creator.services.canon_importer import CanonImporter


class CanonImporterTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.archive = TemporaryDirectory()
        self.root = Path(self.archive.name) / "chloe-katastrophe"
        (self.root / "canon").mkdir(parents=True)
        (self.root / "music").mkdir(parents=True)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
            }
        )

    def tearDown(self):
        self.archive.cleanup()
        self.uploads.cleanup()

    def test_importer_creates_and_updates_by_source_path(self):
        canon_file = self.root / "canon" / "CHLOE_CANON_MASTER.md"
        canon_file.write_text("# Chloe Canon Master\n\nApproved canon body.", encoding="utf-8")
        unresolved_file = self.root / "canon" / "UNRESOLVED_QUESTIONS.md"
        unresolved_file.write_text("# Unresolved Questions\n\nDo not flatten this.", encoding="utf-8")

        with self.app.app_context():
            session = get_session()
            result = CanonImporter(
                session, root=self.root, import_paths=("canon",), extra_files=()
            ).run()

            self.assertEqual(2, result.created)
            self.assertEqual(2, session.query(CanonEntry).count())

            unresolved = session.query(CanonEntry).filter_by(title="Unresolved Questions").one()
            self.assertEqual("unresolved_mystery", unresolved.canonical_status)
            self.assertFalse(unresolved.usable_in_generation)

            canon_file.write_text("# Chloe Canon Master\n\nUpdated canon body.", encoding="utf-8")
            result = CanonImporter(
                session, root=self.root, import_paths=("canon",), extra_files=()
            ).run()

            self.assertEqual(0, result.created)
            self.assertEqual(1, result.updated)
            self.assertEqual(1, result.unchanged)
            self.assertEqual(2, session.query(CanonEntry).count())
            master = session.query(CanonEntry).filter_by(title="Chloe Canon Master").one()
            self.assertIn("Updated canon body", master.body)

    def test_importer_can_import_agents_persona_guidance(self):
        agents_file = Path(self.archive.name) / "AGENTS.md"
        agents_file.write_text(
            "# FrikShun Image Studio Agent Guidance\n\n"
            "Preserve Chloe's voice: intelligent, observant, emotionally restrained but vivid.",
            encoding="utf-8",
        )

        with self.app.app_context():
            session = get_session()
            result = CanonImporter(
                session,
                root=self.root,
                import_paths=(),
                extra_files=(agents_file,),
            ).run()

            self.assertEqual(1, result.created)
            entry = session.query(CanonEntry).one()
            self.assertEqual("voice/persona", entry.canon_category)
            self.assertEqual("voice_guidance", entry.canonical_status)
            self.assertTrue(entry.usable_in_generation)


if __name__ == "__main__":
    unittest.main()
