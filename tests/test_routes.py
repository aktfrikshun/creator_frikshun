from io import BytesIO
from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, PostDraft, PostMetricSnapshot, PostPublication


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
                "MEDIA_ANALYZER_PROVIDER": "local",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.uploads.cleanup()

    def test_create_artifact_generates_drafts_and_facebook_dry_run_publishes(self):
        response = self.client.post(
            "/artifacts",
            data={
                "title": "Recovered Window",
                "artifact_type": "image",
                "visibility": "public",
                "summary": "A public Chloe archive fragment.",
                "lore_text": "This memory has a broken edge.",
                "content_tags": "archive, image",
                "mood_tags": "haunted",
            },
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Recovered Window", response.data)

        with self.app.app_context():
            session = get_session()
            drafts = session.query(PostDraft).all()
            self.assertEqual(7, len(drafts))
            facebook = next(draft for draft in drafts if draft.platform == "facebook")

        response = self.client.get(f"/drafts/{facebook.id}")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Review Facebook Page Draft", response.data)
        self.assertIn(b"Platform Summary", response.data)

        response = self.client.post(
            f"/drafts/{facebook.id}/save",
            data={
                "caption": "Edited Facebook copy for review.",
                "call_to_action": "Enter the ChloKat archive.",
                "hashtags": "ChloKat, RecoveredMemory",
            },
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Edited Facebook copy for review.", response.data)

        response = self.client.post(
            f"/drafts/{facebook.id}/publish/facebook",
            data={
                "caption": "Edited Facebook copy for publishing.",
                "call_to_action": "Enter the ChloKat archive.",
                "hashtags": "ChloKat, RecoveredMemory",
            },
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)

        with self.app.app_context():
            session = get_session()
            publications = session.query(PostPublication).all()
            self.assertEqual(1, len(publications))
            self.assertEqual("published", publications[0].status)
            updated_draft = session.get(PostDraft, facebook.id)
            self.assertEqual("Edited Facebook copy for publishing.", updated_draft.caption)

    def test_upload_with_blank_metadata_generates_artifact_defaults(self):
        response = self.client.post(
            "/artifacts",
            data={
                "artifact_file": (BytesIO(b"fake image bytes"), "mirror-signal.jpg"),
                "title": "",
                "artifact_type": "image",
                "visibility": "private",
                "summary": "",
                "lore_text": "",
                "content_tags": "",
                "mood_tags": "",
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Mirror Signal", response.data)

        with self.app.app_context():
            session = get_session()
            artifact = session.query(Artifact).filter_by(original_filename="mirror-signal.jpg").one()
            self.assertEqual("Mirror Signal", artifact.title)
            self.assertIn("reconstruction archive", artifact.summary)
            self.assertIn("draft canon fragment", artifact.lore_text)
            self.assertIn("ChloKat", artifact.content_tags)
            self.assertTrue(artifact.media_path)

            draft = session.query(PostDraft).filter_by(artifact_id=artifact.id, platform="facebook").one()

        response = self.client.get(f"/drafts/{draft.id}")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Review Facebook Page Draft", response.data)

    def test_upload_uses_media_analysis_and_archive_filename(self):
        response = self.client.post(
            "/artifacts",
            data={
                "artifact_file": (
                    BytesIO(b"fake image bytes"),
                    "FoxyAI_Image_b58d3beb-f35b-4f81-a66f-52ac005644cb.png",
                ),
                "title": "",
                "artifact_type": "image",
                "visibility": "private",
                "summary": "",
                "lore_text": "",
                "content_tags": "",
                "mood_tags": "",
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Rain Room With The Old Telephone", response.data)

        with self.app.app_context():
            session = get_session()
            artifact = session.query(Artifact).filter_by(
                original_filename="FoxyAI_Image_b58d3beb-f35b-4f81-a66f-52ac005644cb.png"
            ).one()
            self.assertEqual("Rain Room With The Old Telephone", artifact.title)
            self.assertIn("vintage phone", artifact.summary)
            self.assertIn("media_analysis", artifact.generated_metadata)
            self.assertIn("ck-000001-rain-room-with-the-old-telephone", artifact.media_path)
            self.assertNotIn("FoxyAI", artifact.media_path)
            draft = session.query(PostDraft).filter_by(artifact_id=artifact.id, platform="facebook").one()
            self.assertIn("This shot comes from", draft.caption)
            self.assertIn("vintage phone", draft.caption)
            self.assertIn("I wanted the image to show", draft.caption)
            self.assertNotIn("The visible record", draft.caption)
            self.assertNotIn("hold to show", draft.caption)
            self.assertNotIn("my into", draft.caption)

    def test_archive_and_cleanup_hide_unpublished_drafts(self):
        self.client.post(
            "/artifacts",
            data={
                "title": "Cleanup Signal",
                "artifact_type": "image",
                "visibility": "private",
                "summary": "A cleanup test fragment.",
                "lore_text": "",
                "content_tags": "",
                "mood_tags": "",
            },
            follow_redirects=True,
        )

        with self.app.app_context():
            session = get_session()
            facebook = session.query(PostDraft).filter_by(platform="facebook").one()

        response = self.client.post(f"/drafts/{facebook.id}/archive", follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn(b"facebook", response.data)

        self.client.post(
            "/artifacts",
            data={
                "title": "Second Cleanup Signal",
                "artifact_type": "image",
                "visibility": "private",
                "summary": "Another cleanup test fragment.",
                "lore_text": "",
                "content_tags": "",
                "mood_tags": "",
            },
            follow_redirects=True,
        )
        response = self.client.post("/drafts/cleanup-unpublished", follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Archived 13 unpublished drafts.", response.data)
        self.assertNotIn(b"Second Cleanup Signal", response.data)

    def test_metrics_dashboard_displays_published_post_snapshot(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Metric Window")
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="facebook",
                caption="A post with metrics.",
                status="published",
            )
            session.add(draft)
            session.flush()
            publication = PostPublication(
                post_draft_id=draft.id,
                platform="facebook",
                status="published",
                external_post_id="facebook-post-2",
                external_url="https://facebook.test/post",
            )
            session.add(publication)
            session.flush()
            session.add(
                PostMetricSnapshot(
                    post_publication_id=publication.id,
                    platform="facebook",
                    external_post_id="facebook-post-2",
                    views=100,
                    likes=12,
                    comments=3,
                    shares=2,
                    clicks=6,
                    reach=90,
                )
            )
            session.commit()

        response = self.client.get("/metrics")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Post Metrics", response.data)
        self.assertIn(b"Metric Window", response.data)
        self.assertIn(b"facebook-post-2", response.data)
        self.assertIn(b"100", response.data)


if __name__ == "__main__":
    unittest.main()
