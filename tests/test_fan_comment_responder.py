from tempfile import TemporaryDirectory
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, EngagementSenderPolicy, PostDraft, PostInteraction, PostPublication
from frikshun_creator.publishers.facebook import FacebookAdapter
from frikshun_creator.services.fan_comment_responder import FanCommentResponder


class StubResponder(FanCommentResponder):
    def generate_reply(self, interaction):
        if self.is_russian(interaction.body):
            return {
                "action": "auto_reply",
                "language": "ru",
                "reply": "Спасибо. Иногда память узнаёт нас раньше, чем мы узнаём её.",
                "reason": "safe fan reflection",
            }
        return {
            "action": "auto_reply",
            "language": "en",
            "reply": "Thank you. Memory has excellent timing and terrible manners.",
            "reason": "safe fan reflection",
        }


class FanCommentResponderTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "AUTO_CREATE_TABLES": True,
            "UPLOAD_FOLDER": self.uploads.name,
        })

    def tearDown(self):
        self.uploads.cleanup()

    def add_comment(self, session, body, external_id="comment-1", author_id="fan-1"):
        artifact = Artifact(title="Recovered Signal")
        draft = PostDraft(artifact=artifact, platform="facebook", caption="Memory remains.", status="published")
        publication = PostPublication(
            post_draft=draft, platform="facebook", status="published", external_post_id="post-1"
        )
        interaction = PostInteraction(
            post_publication=publication,
            platform="facebook",
            interaction_type="comment",
            external_id=external_id,
            author_platform_id=author_id,
            author_name="Fan",
            body=body,
            reply_status="pending_review",
        )
        session.add(interaction)
        session.commit()
        return interaction

    def test_russian_comment_gets_russian_reply_and_is_sent_live(self):
        with self.app.app_context():
            session = get_session()
            interaction = self.add_comment(session, "Это напомнило мне потерянный сон.")
            responder = StubResponder(
                session, FacebookAdapter(dry_run=True, page_id="page-1"), api_key="test", page_id="page-1", live=True
            )

            result = responder.run()

            self.assertEqual(1, result.sent)
            self.assertEqual("sent", interaction.reply_status)
            self.assertRegex(interaction.suggested_reply, r"[А-Яа-я]")
            self.assertEqual("ru", interaction.raw_payload["reply_language"])
            self.assertTrue(interaction.raw_payload["reply_external_id"].startswith("dry-run-reply-"))

    def test_review_only_mode_drafts_safe_reply_without_publishing(self):
        with self.app.app_context():
            session = get_session()
            interaction = self.add_comment(session, "The mirror remembers.")
            responder = StubResponder(
                session, FacebookAdapter(dry_run=True, page_id="page-1"), api_key="test", page_id="page-1", live=False
            )

            result = responder.run()

            self.assertEqual(0, result.sent)
            self.assertEqual(1, result.held)
            self.assertEqual("drafted", interaction.reply_status)
            self.assertTrue(interaction.suggested_reply)

    def test_sensitive_comment_is_held_without_generation(self):
        with self.app.app_context():
            session = get_session()
            interaction = self.add_comment(session, "Please call me about a business proposal.")
            responder = StubResponder(
                session, FacebookAdapter(dry_run=True, page_id="page-1"), api_key="test", page_id="page-1", live=True
            )

            result = responder.run()

            self.assertEqual(1, result.held)
            self.assertEqual("needs_review", interaction.reply_status)
            self.assertEqual("", interaction.suggested_reply)

    def test_page_authored_comment_is_ignored(self):
        with self.app.app_context():
            session = get_session()
            interaction = self.add_comment(session, "A Page reply.", author_id="page-1")
            responder = StubResponder(
                session, FacebookAdapter(dry_run=True, page_id="page-1"), api_key="test", page_id="page-1", live=True
            )

            result = responder.run()

            self.assertEqual(1, result.ignored)
            self.assertEqual("ignored", interaction.reply_status)

    def test_own_reply_and_already_answered_comment_are_ignored(self):
        with self.app.app_context():
            session = get_session()
            own_reply = self.add_comment(session, "Our reply.", external_id="own-reply")
            own_reply.platform = "threads"
            own_reply.interaction_type = "reply"
            own_reply.raw_payload = {"is_owned_by_me": True}
            answered = self.add_comment(session, "Already answered.", external_id="answered")
            answered.platform = "instagram"
            answered.raw_payload = {"already_replied_by_us": True}
            session.commit()
            responder = StubResponder(
                session, api_key="test", adapters={
                    "instagram": FacebookAdapter(dry_run=True),
                    "threads": FacebookAdapter(dry_run=True),
                }, live=True,
            )

            result = responder.run()

            self.assertEqual(2, result.ignored)
            self.assertEqual("ignored", own_reply.reply_status)
            self.assertEqual("ignored", answered.reply_status)
            self.assertEqual("", own_reply.suggested_reply)
            self.assertEqual("", answered.suggested_reply)

    def test_whitelisted_sender_auto_publishes_while_global_mode_is_review_only(self):
        with self.app.app_context():
            session = get_session()
            interaction = self.add_comment(session, "The mirror remembers.")
            session.add(EngagementSenderPolicy(
                platform="facebook", author_platform_id="fan-1", author_name="Fan", auto_approve=True
            ))
            session.commit()
            responder = StubResponder(
                session, FacebookAdapter(dry_run=True, page_id="page-1"), api_key="test", page_id="page-1", live=False
            )

            result = responder.run()

            self.assertEqual(1, result.sent)
            self.assertEqual("sent", interaction.reply_status)


if __name__ == "__main__":
    unittest.main()
