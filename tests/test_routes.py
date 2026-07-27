from io import BytesIO
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlparse
from unittest.mock import Mock, patch
from zipfile import ZipFile
from pathlib import Path
from types import SimpleNamespace

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import (
    Artifact, EngagementSenderPolicy, MetricsPollRun, PostDraft, PostInteraction, PostMetricSnapshot, PostPublication
)


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
                "CUSTOM_POST_PUBLISH_SYNC": True,
                "THREADS_APP_ID": "threads-app",
                "THREADS_APP_SECRET": "threads-secret",
                "THREADS_REDIRECT_URI": "https://example.test/oauth/threads/callback",
                "THREADS_TOKEN_PATH": f"{self.uploads.name}/threads_oauth.json",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.uploads.cleanup()

    def add_facebook_interaction(self, body="I remember this.", reply="A proposed reply."):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Engagement Signal")
            draft = PostDraft(artifact=artifact, platform="facebook", caption="A recovered signal.", status="published")
            publication = PostPublication(
                post_draft=draft, platform="facebook", status="published",
                external_post_id="facebook-post-engagement", external_url="https://facebook.test/post"
            )
            interaction = PostInteraction(
                post_publication=publication, platform="facebook", interaction_type="comment",
                external_id="comment-engagement", author_name="Archivist", author_platform_id="fan-42",
                body=body, suggested_reply=reply, reply_status="drafted"
            )
            session.add(interaction)
            session.commit()
            return interaction.id

    def test_legal_pages_are_public_and_cross_linked(self):
        expectations = {
            "/terms": b"Terms of Service",
            "/privacy": b"Privacy Policy",
            "/acceptable-use": b"Acceptable Use Policy",
        }

        for path, heading in expectations.items():
            response = self.client.get(path)
            self.assertEqual(200, response.status_code)
            self.assertIn(heading, response.data)
            self.assertIn(b'href="/terms"', response.data)
            self.assertIn(b'href="/privacy"', response.data)
            self.assertIn(b'href="/acceptable-use"', response.data)

    def test_google_auth_protects_creator_and_metrics_but_not_legal_pages(self):
        self.app.config.update(
            CREATOR_AUTH_REQUIRED=True,
            GOOGLE_ALLOWED_EMAILS="aktfrikshun@gmail.com",
        )

        for path in ("/", "/metrics"):
            response = self.client.get(path)
            self.assertEqual(303, response.status_code)
            self.assertIn("/auth/google/login", response.headers["Location"])

        for path in ("/terms", "/privacy", "/acceptable-use"):
            self.assertEqual(200, self.client.get(path).status_code)

        response = self.client.post("/metrics/poll")
        self.assertEqual(303, response.status_code)
        self.assertIn("/auth/google/login", response.headers["Location"])

    def test_google_auth_allows_allowlisted_session(self):
        self.app.config.update(
            CREATOR_AUTH_REQUIRED=True,
            GOOGLE_ALLOWED_EMAILS="aktfrikshun@gmail.com",
        )
        with self.client.session_transaction() as session:
            session["creator_user"] = {"email": "aktfrikshun@gmail.com", "name": "Allen"}

        self.assertEqual(200, self.client.get("/").status_code)
        metrics = self.client.get("/metrics")
        self.assertEqual(200, metrics.status_code)
        self.assertIn(b"Sign out Allen", metrics.data)

    def test_daily_fragment_manual_posting_kit_downloads_images_and_platform_captions(self):
        public_path = Path(self.uploads.name) / "public.png"
        fanvue_path = Path(self.uploads.name) / "fanvue.png"
        public_path.write_bytes(b"public-image")
        fanvue_path.write_bytes(b"fanvue-image")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Manual Signal",
                fragment_code="daily-fragment-run-manual-signal",
                media_path=str(public_path),
                media_content_type="image/png",
                generated_metadata={
                    "run_id": "manual-signal",
                    "local_date": "2026-07-18",
                    "fanvue_media_path": str(fanvue_path),
                },
            )
            session.add(artifact)
            for platform, caption in {
                "facebook": "Facebook body.\n\nLearn more about me in the FrikShun archives: https://example.test",
                "instagram": "Instagram body.\n\nLearn more about me in the FrikShun archives: https://example.test",
                "threads": "Threads body?",
                "x": "X body?",
                "fanvue": "FanVue body?",
            }.items():
                session.add(PostDraft(artifact=artifact, platform=platform, caption=caption))
            session.commit()
            artifact_id = artifact.id

        response = self.client.get(f"/daily-fragments/{artifact_id}/manual-posting-kit")

        self.assertEqual(200, response.status_code)
        self.assertEqual("application/zip", response.mimetype)
        with ZipFile(BytesIO(response.data)) as archive:
            names = set(archive.namelist())
            self.assertIn("manual-signal-image.png", names)
            self.assertNotIn("manual-signal-fanvue.png", names)
            captions = archive.read("manual-signal-captions.txt").decode("utf-8")
        self.assertIn("=== FACEBOOK ===", captions)
        self.assertIn("=== INSTAGRAM ===", captions)
        self.assertNotIn("Archive, music, and modeling links are available through my bio.", captions)
        self.assertNotIn("https://example.test", captions.split("=== INSTAGRAM ===", 1)[1].split("=== THREADS ===", 1)[0])
        response.close()

        response = self.client.get(f"/daily-fragments/{artifact_id}/media/public?download=1")
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"public-image", response.data)
        response.close()

    def test_daily_fragment_can_be_unpublished_edited_and_republished(self):
        image_path = Path(self.uploads.name) / "daily.png"
        image_path.write_bytes(b"old-image")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Editable",
                fragment_code="daily-fragment-run-editable",
                media_path=str(image_path),
                media_content_type="image/png",
                generated_metadata={"run_id": "editable", "public_image_prompt": "A precise image prompt"},
            )
            session.add(artifact)
            for platform in ("facebook", "instagram", "threads", "x", "fanvue"):
                draft = PostDraft(artifact=artifact, platform=platform, caption=f"Old {platform}", status="published")
                session.add(draft)
                session.add(PostPublication(
                    post_draft=draft, platform=platform, status="published",
                    external_post_id=f"dry-run-{platform}-1",
                ))
            session.commit()
            artifact_id = artifact.id

        response = self.client.post(f"/daily-fragments/{artifact_id}/unpublish", follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"ready to edit and republish", response.data)

        response = self.client.post(
            f"/daily-fragments/{artifact_id}/edit",
            data={
                "caption_facebook": "New canonical text",
                "caption_instagram": "New Instagram text",
                "caption_threads": "New Threads text",
                "caption_x": "New X text",
                "caption_fanvue": "New FanVue text",
                "review_status": "not_accepted",
                "feedback_category": "composition",
                "feedback_reason": "The crop felt too static.",
                "primary_image": (BytesIO(b"new-image"), "replacement.png"),
                "additional_images": [(BytesIO(b"extra-image"), "extra.png")],
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Post changes saved", response.data)
        with self.app.app_context():
            session = get_session()
            artifact = session.get(Artifact, artifact_id)
            metadata = artifact.generated_metadata
            self.assertEqual("New canonical text", artifact.summary)
            self.assertEqual("not_accepted", metadata["review_status"])
            self.assertEqual("The crop felt too static.", metadata["review_feedback"][-1]["reason"])
            self.assertEqual(1, len(metadata["additional_media"]))
            self.assertEqual(1, len(metadata["image_history"]))
            self.assertEqual(
                {"approved"},
                {draft.status for draft in artifact.post_drafts},
            )

    def test_daily_fragment_edit_requires_unpublish_first(self):
        image_path = Path(self.uploads.name) / "live.png"
        image_path.write_bytes(b"image")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Live",
                fragment_code="daily-fragment-run-live-edit",
                media_path=str(image_path),
            )
            draft = PostDraft(artifact=artifact, platform="x", caption="Still live", status="published")
            session.add_all([artifact, draft])
            session.add(PostPublication(post_draft=draft, platform="x", status="published", external_post_id="live-1"))
            session.commit()
            artifact_id = artifact.id

        response = self.client.post(
            f"/daily-fragments/{artifact_id}/edit",
            data={"caption_x": "Should not save"},
            follow_redirects=True,
        )
        self.assertIn(b"Unpublish the live post before changing", response.data)
        with self.app.app_context():
            artifact = get_session().get(Artifact, artifact_id)
            self.assertEqual("Still live", artifact.post_drafts[0].caption)

    def test_manually_deleted_publication_can_be_confirmed_to_unlock_editing(self):
        image_path = Path(self.uploads.name) / "manual-delete.png"
        image_path.write_bytes(b"image")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Recovered Fragment — Manually Deleted",
                fragment_code="daily-fragment-run-manually-deleted",
                media_path=str(image_path),
            )
            draft = PostDraft(artifact=artifact, platform="threads", caption="Was live", status="published")
            publication = PostPublication(
                post_draft=draft,
                platform="threads",
                status="published",
                external_post_id="thread-1",
                raw_response={"published": {"id": "thread-1"}},
            )
            session.add_all([artifact, draft, publication])
            session.commit()
            artifact_id = artifact.id
            publication_id = publication.id

        edit = self.client.get(f"/daily-fragments/{artifact_id}/edit")
        self.assertIn(b"Confirm Threads manually deleted", edit.data)

        response = self.client.post(
            f"/daily-fragments/{artifact_id}/publications/{publication_id}/confirm-unpublished",
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Threads was recorded as manually deleted", response.data)
        self.assertNotIn(b"Confirm Threads manually deleted", response.data)
        self.assertIn(b"Republish replacement", response.data)

        with self.app.app_context():
            session = get_session()
            saved = session.get(PostPublication, publication_id)
            self.assertEqual("unpublished", saved.status)
            self.assertEqual("approved", saved.post_draft.status)
            self.assertIn("confirmed_at", saved.raw_response["manual_unpublish"])

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
            self.assertEqual(8, len(drafts))
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

    def test_custom_post_workflow_curates_reviews_and_publishes_selected_platforms(self):
        response = self.client.get("/custom-posts/new")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Create draft post", response.data)

        response = self.client.post(
            "/custom-posts",
            data={
                "image": (BytesIO(b"creator supplied image"), "memory-window.jpg"),
                "source_text": "I found a quiet signal in this window. What does it remember?",
                "title": "The Window Remembers",
                "tags": "archive, morning light",
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Review curated drafts", response.data)
        self.assertIn(b"I found a quiet signal", response.data)

        with self.app.app_context():
            session = get_session()
            artifact = session.query(Artifact).filter_by(title="The Window Remembers").one()
            self.assertEqual("custom_post_v1", artifact.generated_metadata["workflow"])
            self.assertEqual(5, len(artifact.post_drafts))
            artifact_id = artifact.id

        form = {"platforms": ["facebook", "x", "fanvue"]}
        for platform in ("facebook", "instagram", "threads", "x", "fanvue"):
            form[f"caption_{platform}"] = f"Curated {platform} copy."
            form[f"hashtags_{platform}"] = "ChloKat, CustomPost"
            form[f"call_to_action_{platform}"] = ""
        response = self.client.post(
            f"/custom-posts/{artifact_id}/publish",
            data=form,
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Publishing started in the background", response.data)
        self.assertIn(b"Publication job: Completed", response.data)

        with self.app.app_context():
            publications = get_session().query(PostPublication).all()
            self.assertEqual(
                {"facebook", "x", "fanvue"},
                {publication.platform for publication in publications},
            )

    def test_custom_post_requires_an_image_and_text(self):
        response = self.client.post(
            "/custom-posts",
            data={"source_text": "Words without an image."},
            content_type="multipart/form-data",
        )
        self.assertEqual(400, response.status_code)
        self.assertIn(b"Choose one or more photo or video files", response.data)

    def test_custom_post_accepts_multiple_photos_and_videos(self):
        response = self.client.post(
            "/custom-posts",
            data={
                "media": [
                    (BytesIO(b"primary image"), "primary.jpg", "image/jpeg"),
                    (BytesIO(b"second image"), "detail.png", "image/png"),
                    (BytesIO(b"video clip"), "motion.mp4", "video/mp4"),
                ],
                "source_text": "A still frame, a detail, and the moment moving.",
                "title": "Three Views of the Signal",
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"3 attachments", response.data)
        self.assertIn(b"Video attachment 3", response.data)

        with self.app.app_context():
            artifact = get_session().query(Artifact).filter_by(
                title="Three Views of the Signal"
            ).one()
            self.assertEqual(
                ["image/png", "video/mp4"],
                [
                    item["media_content_type"]
                    for item in artifact.generated_metadata["additional_media"]
                ],
            )

    def test_instagram_dry_run_publishes_public_jpeg_draft(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Instagram Signal",
                media_path="/local/instagram-signal.jpg",
                media_content_type="image/jpeg",
                generated_metadata={
                    "public_media_url": "https://cdn.example.test/instagram-signal.jpg"
                },
            )
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="instagram",
                caption="An Instagram fragment.",
                hashtags=["ChloKat"],
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id

        response = self.client.post(
            f"/drafts/{draft_id}/publish/instagram",
            data={
                "caption": "Edited Instagram fragment.",
                "call_to_action": "Follow the signal.",
                "hashtags": "ChloKat, RecoveredMemory",
            },
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Instagram published.", response.data)
        with self.app.app_context():
            session = get_session()
            publication = session.query(PostPublication).filter_by(platform="instagram").one()
            self.assertTrue(publication.external_post_id.startswith("dry-run-instagram-"))

    def test_x_dry_run_publishes_image_draft_from_review_page(self):
        image_path = f"{self.uploads.name}/x-signal.jpg"
        with open(image_path, "wb") as image:
            image.write(b"jpeg")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="X Signal", media_path=image_path, media_content_type="image/jpeg"
            )
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="x",
                caption="Identity leaves an echo. Which echo would you follow?",
                hashtags=["ChloKat"],
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id

        review = self.client.get(f"/drafts/{draft_id}")
        self.assertIn(b"Dry Run Publish", review.data)
        response = self.client.post(
            f"/drafts/{draft_id}/publish/x",
            data={
                "caption": "Identity leaves an echo. Which echo would you follow?",
                "call_to_action": "",
                "hashtags": "ChloKat",
            },
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"X published.", response.data)
        with self.app.app_context():
            publication = get_session().query(PostPublication).filter_by(platform="x").one()
            self.assertTrue(publication.external_post_id.startswith("dry-run-x-"))

    def test_threads_dry_run_publishes_image_draft_from_review_page(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Threads Signal",
                media_path="/local/threads-signal.jpg",
                media_content_type="image/jpeg",
                generated_metadata={
                    "public_media_url": "https://cdn.example.test/threads-signal.jpg"
                },
            )
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="threads",
                caption="A thread survives. Which version of you keeps speaking?",
                hashtags=["ChloKat"],
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id

        review = self.client.get(f"/drafts/{draft_id}")
        self.assertIn(b"Review Threads Draft", review.data)
        self.assertIn(b"Dry Run Publish", review.data)
        response = self.client.post(
            f"/drafts/{draft_id}/publish/threads",
            data={
                "caption": "A thread survives. Which version of you keeps speaking?",
                "call_to_action": "",
                "hashtags": "ChloKat",
            },
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Threads published.", response.data)
        with self.app.app_context():
            publication = get_session().query(PostPublication).filter_by(platform="threads").one()
            self.assertTrue(publication.external_post_id.startswith("dry-run-threads-"))

    def test_threads_retry_refreshes_saved_s3_media_url(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Older Threads Signal",
                media_path="/missing/older-signal.jpg",
                media_content_type="image/jpeg",
                generated_metadata={
                    "public_media_url": "https://expired.example.test/older-signal.jpg",
                    "s3_object_key": "social/older-signal.jpg",
                },
            )
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact_id=artifact.id,
                platform="threads",
                caption="An older signal returns. Which version still speaks?",
                hashtags=["ChloKat"],
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id

        with patch("frikshun_creator.routes.S3MediaStorage.refresh_signed_url", return_value="https://fresh.example.test/older-signal.jpg") as refresh:
            response = self.client.post(
                f"/drafts/{draft_id}/publish/threads",
                data={"caption": "An older signal returns. Which version still speaks?", "hashtags": "ChloKat"},
                follow_redirects=True,
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Threads published.", response.data)
        refresh.assert_called_once_with("social/older-signal.jpg")
        with self.app.app_context():
            saved = get_session().get(PostDraft, draft_id)
            self.assertEqual(
                "https://fresh.example.test/older-signal.jpg",
                saved.artifact.generated_metadata["public_media_url"],
            )

    def test_single_video_is_uploaded_for_instagram_and_threads(self):
        video_path = Path(self.uploads.name) / "single-video.mp4"
        video_path.write_bytes(b"video")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Single Video",
                media_path=str(video_path),
                media_content_type="video/mp4",
                generated_metadata={"workflow": "custom_post_v1"},
            )
            session.add(artifact)
            for platform in ("instagram", "threads"):
                session.add(
                    PostDraft(
                        artifact=artifact,
                        platform=platform,
                        caption="A moving fragment.",
                        hashtags=["ChloKat"],
                    )
                )
            session.commit()
            artifact_id = artifact.id

        stored = SimpleNamespace(
            local_path=video_path,
            object_key="social/2026/07/26/single-video.mp4",
            signed_url="https://signed.example.test/single-video.mp4",
            content_type="video/mp4",
        )
        with patch(
            "frikshun_creator.routes.S3MediaStorage.store_social_media",
            return_value=stored,
        ) as store, patch(
            "frikshun_creator.routes.S3MediaStorage.refresh_signed_url",
            return_value=stored.signed_url,
        ):
            response = self.client.post(
                f"/custom-posts/{artifact_id}/publish",
                data={
                    "platforms": ["instagram", "threads"],
                    "caption_instagram": "A moving fragment.",
                    "hashtags_instagram": "ChloKat",
                    "caption_threads": "A moving fragment.",
                    "hashtags_threads": "ChloKat",
                },
                follow_redirects=True,
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, store.call_count)
        with self.app.app_context():
            saved = get_session().get(Artifact, artifact_id)
            self.assertEqual(
                "https://signed.example.test/single-video.mp4",
                saved.generated_metadata["public_media_url"],
            )
            self.assertEqual(
                {"published"},
                {draft.status for draft in saved.post_drafts},
            )
        library = self.client.get("/")
        self.assertIn(b'<video src="/custom-posts/', library.data)
        self.assertIn(b'aria-label="Video for Single Video"', library.data)

    def test_threads_oauth_start_redirects_to_threads_authorize_url(self):
        response = self.client.get("/oauth/threads/start")
        self.assertEqual(302, response.status_code)
        location = response.headers["Location"]
        self.assertEqual("threads.net", urlparse(location).netloc)
        self.assertIn("client_id=threads-app", location)

    def test_threads_oauth_callback_exchanges_and_stores_token(self):
        self.client.get("/oauth/threads/start")
        with self.client.session_transaction() as session:
            state = session["threads_oauth_state"]

        response_payload = {
            "access_token": "long-token",
            "long_lived_access_token": "long-token",
            "user_id": "123",
            "expires_in": 5184000,
        }
        with patch("frikshun_creator.routes.ThreadsOAuth.exchange", return_value=response_payload) as exchange:
            response = self.client.get(
                f"/oauth/threads/callback?code=code-1&state={state}",
                follow_redirects=True,
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Threads authorization succeeded.", response.data)
        exchange.assert_called_once_with("code-1")

    def test_fanvue_dry_run_publishes_separate_image_from_review_page(self):
        image_path = f"{self.uploads.name}/fanvue-signal.jpg"
        with open(image_path, "wb") as image:
            image.write(b"jpeg")
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="FanVue Signal", media_path=image_path,
                                media_content_type="image/jpeg",
                                generated_metadata={"fanvue_media_path": image_path})
            session.add(artifact)
            session.flush()
            draft = PostDraft(artifact_id=artifact.id, platform="fanvue",
                              caption="A private echo. Which memory comes closer?",
                              hashtags=["ChloKat"])
            session.add(draft)
            session.commit()
            draft_id = draft.id
        response = self.client.post(
            f"/drafts/{draft_id}/publish/fanvue",
            data={"caption": "A private echo. Which memory comes closer?",
                  "call_to_action": "", "hashtags": "ChloKat"},
            follow_redirects=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"FanVue published.", response.data)
        with self.app.app_context():
            publication = get_session().query(PostPublication).filter_by(platform="fanvue").one()
            self.assertTrue(publication.external_post_id.startswith("dry-run-fanvue-"))

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
        self.assertNotIn(f'/drafts/{facebook.id}'.encode(), response.data)

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
        self.assertIn(b"Archived 15 unpublished drafts.", response.data)
        self.assertNotIn(b"Second Cleanup Signal", response.data)

    def test_post_library_searches_caption_and_filters_platform_and_status(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Powder Signal", summary="A quiet room.")
            session.add(artifact)
            session.add(PostDraft(artifact=artifact, platform="x", status="published", caption="A hidden violet phrase."))
            session.commit()

        response = self.client.get("/?q=violet&platform=x&status=published")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Powder Signal", response.data)
        self.assertIn(b"1 post found", response.data)

    def test_post_library_filters_by_post_family(self):
        with self.app.app_context():
            session = get_session()
            recovered = Artifact(
                title="Recovered Fragment — Family Signal",
                fragment_code="daily-fragment-run-recovered-family",
                content_tags=["recovered-fragment", "identity"],
            )
            philosophy = Artifact(
                title="Chloe Thinking — Family Signal",
                fragment_code="daily-fragment-run-philosophy-family",
                content_tags=["philosophy", "identity"],
            )
            session.add_all((recovered, philosophy))
            session.flush()
            session.add_all(
                (
                    PostDraft(artifact=recovered, platform="x", caption="Recovered"),
                    PostDraft(artifact=philosophy, platform="x", caption="Philosophy"),
                )
            )
            session.commit()

        response = self.client.get("/?family=philosophy")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Chloe Thinking", response.data)
        self.assertNotIn(b"Recovered Fragment", response.data)

    @patch("frikshun_creator.routes.subprocess.Popen")
    def test_generate_daily_fragment_starts_ad_hoc_cli(self, popen):
        response = self.client.post("/daily-fragments/generate", follow_redirects=True)

        self.assertEqual(200, response.status_code)
        self.assertIn(b"automatically selected post run has started", response.data)
        command = popen.call_args.args[0]
        self.assertEqual("run-daily-fragment-autopilot", command[-1])

    @patch("frikshun_creator.routes.subprocess.Popen")
    def test_generate_daily_fragment_passes_selected_family(self, popen):
        response = self.client.post(
            "/daily-fragments/generate",
            data={"family": "travel"},
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"travel post run has started", response.data)
        command = popen.call_args.args[0]
        self.assertEqual(["--family", "travel"], command[-2:])

    @patch("frikshun_creator.routes.subprocess.Popen")
    def test_generate_daily_fragment_accepts_fantasy_art_family(self, popen):
        response = self.client.post(
            "/daily-fragments/generate",
            data={"family": "fantasy_art"},
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"beautiful fantasy art post run has started", response.data)
        command = popen.call_args.args[0]
        self.assertEqual(["--family", "fantasy_art"], command[-2:])

    @patch("frikshun_creator.routes.subprocess.Popen")
    def test_publish_daily_fragment_starts_saved_run_publisher(self, popen):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="Publish Signal",
                fragment_code="daily-fragment-run-publish-signal",
                generated_metadata={"run_id": "publish-signal"},
            )
            session.add(artifact)
            session.add(PostDraft(artifact=artifact, platform="x", caption="Publish me?"))
            session.commit()
            artifact_id = artifact.id

        response = self.client.post(
            f"/daily-fragments/{artifact_id}/publish",
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Publishing to all connected platforms has started", response.data)
        command = popen.call_args.args[0]
        self.assertEqual(
            ["publish-daily-fragment-run", "--run-id", "publish-signal"],
            command[-3:],
        )

    def test_library_approved_threads_pill_publishes_saved_draft(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(
                title="One-click Threads Signal",
                fragment_code="daily-fragment-run-one-click-threads",
                media_path="/missing/one-click.jpg",
                media_content_type="image/jpeg",
                generated_metadata={"public_media_url": "https://cdn.example.test/one-click.jpg"},
            )
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact=artifact,
                platform="threads",
                caption="The old signal is ready. Which part still remembers?",
                hashtags=["ChloKat"],
                status="approved",
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id

        library = self.client.get("/")
        self.assertIn(f'/drafts/{draft_id}/publish-from-library'.encode(), library.data)
        self.assertIn(b"Threads \xc2\xb7 approved", library.data)

        response = self.client.post(
            f"/drafts/{draft_id}/publish-from-library",
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Threads published.", response.data)
        with self.app.app_context():
            saved = get_session().get(PostDraft, draft_id)
            self.assertEqual("published", saved.status)
            self.assertEqual(1, len(saved.publications))
            self.assertTrue(saved.publications[0].external_post_id.startswith("dry-run-threads-"))

    def test_library_publish_refuses_duplicate_successful_publication(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Already Sent")
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact=artifact,
                platform="threads",
                caption="Do not duplicate me?",
                status="failed",
            )
            session.add(draft)
            session.flush()
            session.add(
                PostPublication(
                    post_draft=draft,
                    platform="threads",
                    status="published",
                    external_post_id="existing-thread-id",
                )
            )
            session.commit()
            draft_id = draft.id

        response = self.client.post(
            f"/drafts/{draft_id}/publish-from-library",
            follow_redirects=True,
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"already published; no duplicate was created", response.data)
        with self.app.app_context():
            saved = get_session().get(PostDraft, draft_id)
            self.assertEqual("published", saved.status)
            self.assertEqual(1, len(saved.publications))

    def test_library_publish_queues_background_job_in_live_mode(self):
        with self.app.app_context():
            session = get_session()
            artifact = Artifact(title="Slow Threads Retry")
            session.add(artifact)
            session.flush()
            draft = PostDraft(
                artifact=artifact,
                platform="threads",
                caption="A slow carousel should outlive the web request.",
                status="failed",
            )
            session.add(draft)
            session.commit()
            draft_id = draft.id
            artifact_id = artifact.id

        self.app.config["CUSTOM_POST_PUBLISH_SYNC"] = False
        try:
            with patch("frikshun_creator.routes.Thread") as thread:
                response = self.client.post(
                    f"/drafts/{draft_id}/publish-from-library",
                    follow_redirects=True,
                )
        finally:
            self.app.config["CUSTOM_POST_PUBLISH_SYNC"] = True

        self.assertEqual(200, response.status_code)
        self.assertIn(b"publishing started in the background", response.data)
        thread.return_value.start.assert_called_once_with()
        with self.app.app_context():
            saved = get_session().get(Artifact, artifact_id)
            self.assertEqual("queued", saved.generated_metadata["custom_publish_job"]["status"])
            self.assertEqual(["threads"], saved.generated_metadata["custom_publish_job"]["platforms"])

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
        self.assertIn(b"Signal Room", response.data)
        self.assertIn(b"Account-wide leaders", response.data)
        self.assertIn(b"Posts earning attention", response.data)
        self.assertIn(b"performance-grid", response.data)
        self.assertIn(b"Export CSV", response.data)
        self.assertIn(b"Daily metrics poller", response.data)
        self.assertIn(b"Metric Window", response.data)
        self.assertIn(b"facebook-post-2", response.data)
        self.assertIn(b"100", response.data)

    def test_manage_engagement_displays_comment_and_proposed_reply(self):
        self.add_facebook_interaction()

        response = self.client.get("/engagement")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Manage Engagement", response.data)
        self.assertIn(b"Archivist", response.data)
        self.assertIn(b"I remember this.", response.data)
        self.assertIn(b"A proposed reply.", response.data)
        self.assertIn(b"Auto-approve this fan", response.data)
        self.assertIn(b"Block sender", response.data)

    def test_manage_engagement_displays_latest_comment_poll_time(self):
        with self.app.app_context():
            session = get_session()
            session.add(MetricsPollRun(
                source="fan-comment-scheduler",
                status="succeeded",
                started_at=datetime(2026, 7, 22, 17, 15, tzinfo=timezone.utc),
                completed_at=datetime(2026, 7, 22, 17, 15, 8, tzinfo=timezone.utc),
            ))
            session.commit()

        response = self.client.get("/engagement")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Last engagement poll", response.data)
        self.assertIn(b"Jul 22, 2026 13:15:08 EDT", response.data)

    def test_manage_engagement_displays_total_posts_senders_and_comments(self):
        self.add_facebook_interaction()
        with self.app.app_context():
            session = get_session()
            session.add_all([
                PostInteraction(
                    platform="facebook", interaction_type="comment", external_id="comment-two",
                    external_post_id="facebook-post-two", author_name="Second Fan",
                    author_platform_id="fan-84", body="Second comment.", reply_status="pending_review",
                ),
                PostInteraction(
                    platform="facebook", interaction_type="comment", external_id="comment-three",
                    external_post_id="facebook-post-two", author_name="Archivist",
                    author_platform_id="fan-42", body="Third comment.", reply_status="pending_review",
                ),
            ])
            session.commit()

        response = self.client.get("/engagement")

        self.assertEqual(200, response.status_code)
        self.assertIn(b'<strong>2</strong><span>Total posts</span>', response.data)
        self.assertIn(b'<strong>2</strong><span>Distinct senders</span>', response.data)
        self.assertIn(b'<strong>3</strong><span>Total comments</span>', response.data)

    def test_manage_engagement_can_edit_and_publish_reply(self):
        interaction_id = self.add_facebook_interaction()
        response = self.client.post(
            f"/engagement/{interaction_id}/save", data={"reply": "Edited Chloe reply."}, follow_redirects=True
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Proposed reply saved", response.data)

        response = self.client.post(
            f"/engagement/{interaction_id}/publish", data={"reply": "Edited Chloe reply."}, follow_redirects=True
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Reply published to Facebook", response.data)
        with self.app.app_context():
            interaction = get_session().get(PostInteraction, interaction_id)
            self.assertEqual("sent", interaction.reply_status)
            self.assertEqual("Edited Chloe reply.", interaction.suggested_reply)

    def test_manage_engagement_filters_and_publishes_instagram_reply(self):
        with self.app.app_context():
            session = get_session()
            interaction = PostInteraction(
                platform="instagram", interaction_type="comment", external_id="ig-comment-1",
                external_post_id="ig-media-1", author_name="ig_fan", author_platform_id="ig_fan",
                body="I remember this too.", suggested_reply="Then keep the fragment.", reply_status="drafted",
            )
            session.add(interaction)
            session.commit()
            interaction_id = interaction.id

        filtered = self.client.get("/engagement?status=open&platform=instagram")
        self.assertEqual(200, filtered.status_code)
        self.assertIn(b"ig_fan", filtered.data)
        self.assertIn(b"Instagram", filtered.data)

        adapter = Mock()
        adapter.reply_to_comment.return_value = {"id": "ig-reply-1"}
        with patch("frikshun_creator.routes.instagram_adapter", return_value=adapter):
            response = self.client.post(
                f"/engagement/{interaction_id}/publish",
                data={"reply": "Then keep the fragment.", "platform_filter": "instagram"},
                follow_redirects=True,
            )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Reply published to Instagram", response.data)
        adapter.reply_to_comment.assert_called_once_with("ig-comment-1", "Then keep the fragment.")

    def test_manage_engagement_can_whitelist_sender(self):
        interaction_id = self.add_facebook_interaction()

        response = self.client.post(
            f"/engagement/{interaction_id}/whitelist", data={"enable": "true"}, follow_redirects=True
        )

        self.assertEqual(200, response.status_code)
        self.assertIn(b"added to automatic approval", response.data)
        with self.app.app_context():
            policy = get_session().query(EngagementSenderPolicy).one()
            self.assertTrue(policy.auto_approve)
            self.assertFalse(policy.blocked)

    def test_manage_engagement_can_block_sender_in_dry_run(self):
        interaction_id = self.add_facebook_interaction()

        response = self.client.post(f"/engagement/{interaction_id}/block", follow_redirects=True)

        self.assertEqual(200, response.status_code)
        self.assertIn(b"was blocked from the Facebook Page", response.data)
        with self.app.app_context():
            session = get_session()
            policy = session.query(EngagementSenderPolicy).one()
            interaction = session.get(PostInteraction, interaction_id)
            self.assertTrue(policy.blocked)
            self.assertFalse(policy.auto_approve)
            self.assertEqual("sender_blocked", interaction.reply_status)


if __name__ == "__main__":
    unittest.main()
