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

    def test_importer_loads_visual_canon_and_model_card(self):
        visuals_dir = self.root / "visuals"
        visuals_dir.mkdir(parents=True)
        guide_file = visuals_dir / "VISUAL_REFERENCE_GUIDE.md"
        guide_file.write_text(
            "# Chloe Visual Guide\n\nLocked physical features and anti-drift rules.",
            encoding="utf-8",
        )

        appearance_file = Path(self.archive.name) / "studio" / "chloe-model" / "appearance.md"
        appearance_file.parent.mkdir(parents=True)
        appearance_file.write_text(
            "# Chloe Katastrophe Visual Canon\n\nFair skin, freckles, gray-green eyes.",
            encoding="utf-8",
        )
        model_card_file = (
            Path(self.archive.name)
            / "studio"
            / "reference-packs"
            / "chloe_model_v1"
            / "MODEL_CARD.md"
        )
        model_card_file.parent.mkdir(parents=True)
        model_card_file.write_text(
            "# MODEL_CARD - Chloe Model v1\n\nUse Chloe Model v1 as top-level visual canon.",
            encoding="utf-8",
        )

        with self.app.app_context():
            session = get_session()
            result = CanonImporter(
                session,
                root=self.root,
                import_paths=("visuals",),
                extra_files=(appearance_file, model_card_file),
            ).run()

            self.assertEqual(3, result.created)

            guide = session.query(CanonEntry).filter_by(title="Chloe Visual Guide").one()
            self.assertEqual("visuals", guide.canon_category)
            self.assertEqual("reference", guide.canonical_status)

            appearance = (
                session.query(CanonEntry)
                .filter_by(title="Chloe Katastrophe Visual Canon")
                .one()
            )
            self.assertEqual("visual/persona", appearance.canon_category)
            self.assertEqual("reference", appearance.canonical_status)

            model_card = session.query(CanonEntry).filter_by(title="MODEL_CARD - Chloe Model v1").one()
            self.assertEqual("visual/persona", model_card.canon_category)
            self.assertTrue(model_card.usable_in_generation)


if __name__ == "__main__":
    unittest.main()
