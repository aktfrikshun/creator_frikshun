from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, CanonEntry, PostDraft
from frikshun_creator.services.sample_artifact_importer import SampleArtifactImporter
from frikshun_creator.services.social_post_importer import SocialPostImporter


class SocialAndSampleImportersTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.archive = TemporaryDirectory()
        self.root = Path(self.archive.name)
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

    def test_social_posts_import_as_published_history(self):
        post_dir = self.root / "instagram" / "first-post"
        post_dir.mkdir(parents=True)
        post = post_dir / "POST_001.md"
        post.write_text(
            "# Instagram Post 001\n\n"
            "## Caption\n\n"
            "My name is Chloe Katastrophe. I am reconstructing a life from songs and fragments.\n\n"
            "## Hashtags\n\n"
            "#ChloeKatastrophe #RecoveredArtifacts",
            encoding="utf-8",
        )

        with self.app.app_context():
            session = get_session()
            result = SocialPostImporter(session, root=self.root).run()

            self.assertEqual(1, result.created)
            draft = session.query(PostDraft).one()
            self.assertEqual("published", draft.status)
            self.assertEqual("instagram", draft.platform)
            self.assertIn("reconstructing a life", draft.caption)

    def test_sample_artifacts_generate_voice_aware_drafts(self):
        sample = self.root / "touch-me-like-im-real-tiktok-teaser-001.mp4"
        sample.write_bytes(b"fake video")

        with self.app.app_context():
            session = get_session()
            session.add(
                CanonEntry(
                    title="FrikShun Image Studio Agent Guidance",
                    body=(
                        "Preserve Chloe's voice: intelligent, observant, emotionally restrained but vivid, "
                        "dryly funny, sensual without being careless, skeptical of simple stories, "
                        "drawn to truth and beauty inside darkness."
                    ),
                    source_path="/tmp/AGENTS.md",
                    canon_category="voice/persona",
                    canonical_status="voice_guidance",
                    usable_in_generation=True,
                )
            )
            session.add(
                PostDraft(
                    artifact=Artifact(
                        title="Imported Prior Post",
                        artifact_type="published_post",
                        summary="Prior post",
                    ),
                    platform="facebook",
                    caption="I remember the ending first. Help me find the rest.",
                    status="published",
                )
            )
            session.commit()

            result = SampleArtifactImporter(session, paths=(sample,)).run()

            self.assertEqual(1, result.created)
            artifact = session.query(Artifact).filter(Artifact.media_path == str(sample)).one()
            facebook = (
                session.query(PostDraft)
                .filter(PostDraft.artifact_id == artifact.id)
                .filter(PostDraft.platform == "facebook")
                .one()
            )
            self.assertIn("truth and beauty inside the dark", facebook.caption)
            archive = (
                session.query(PostDraft)
                .filter(PostDraft.artifact_id == artifact.id)
                .filter(PostDraft.platform == "chlokat_archive")
                .one()
            )
            self.assertIn("posting history", archive.caption)

    def test_generation_context_keeps_voice_entries_even_with_many_canon_rows(self):
        sample = self.root / "chloe-first-instagram-portrait.png"
        sample.write_bytes(b"fake image")

        with self.app.app_context():
            session = get_session()
            for index in range(25):
                session.add(
                    CanonEntry(
                        title=f"Canon Row {index}",
                        body="Ordinary canon body.",
                        source_path=f"/tmp/canon-{index}.md",
                        canon_category="canon",
                        canonical_status="approved",
                        usable_in_generation=True,
                    )
                )
            session.add(
                CanonEntry(
                    title="FrikShun Image Studio Agent Guidance",
                    body=(
                        "Preserve Chloe's voice: intelligent, observant, emotionally restrained but vivid, "
                        "dryly funny, sensual without being careless, skeptical of simple stories, "
                        "drawn to truth and beauty inside darkness."
                    ),
                    source_path="/tmp/AGENTS.md",
                    canon_category="voice/persona",
                    canonical_status="voice_guidance",
                    usable_in_generation=True,
                )
            )
            session.commit()

            SampleArtifactImporter(session, paths=(sample,)).run()
            artifact = session.query(Artifact).filter(Artifact.media_path == str(sample)).one()
            facebook = (
                session.query(PostDraft)
                .filter(PostDraft.artifact_id == artifact.id)
                .filter(PostDraft.platform == "facebook")
                .one()
            )
            self.assertIn("truth and beauty inside the dark", facebook.caption)


if __name__ == "__main__":
    unittest.main()
