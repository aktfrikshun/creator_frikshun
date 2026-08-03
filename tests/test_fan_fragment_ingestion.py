from io import BytesIO
from tempfile import TemporaryDirectory
import hashlib
import unittest

from frikshun_creator import create_app
from frikshun_creator.db import get_session
from frikshun_creator.models import Artifact, FanFragmentIngestion


class FanFragmentIngestionTest(unittest.TestCase):
    def setUp(self):
        self.uploads = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "AUTO_CREATE_TABLES": True,
                "UPLOAD_FOLDER": self.uploads.name,
                "FAN_FRAGMENT_INGEST_TOKEN": "shared-secret",
            }
        )
        self.client = self.app.test_client()
        self.headers = {
            "Authorization": "Bearer shared-secret",
            "Idempotency-Key": "fragment-export-1",
        }

    def tearDown(self):
        self.uploads.cleanup()

    def payload(self, attachments=None):
        return {
            "schema_version": 1,
            "source_submission_id": "FSUB-2026-ABC123",
            "classification": "fan_interpretation",
            "title": "A voice in the stairwell",
            "candidate_text": "I heard the same phrase in the recording.",
            "provenance_summary": "Submitted through FrikFan and accepted for review.",
            "source_urls": ["https://example.test/source"],
            "attribution": {"display_name": "Echo Witness", "preference": "alias"},
            "attachments": attachments or [],
        }

    def test_ingestion_requires_service_authentication(self):
        response = self.client.post("/api/v1/intake/fan-fragments", json=self.payload())
        self.assertEqual(401, response.status_code)

    def test_ingestion_is_idempotent(self):
        first = self.client.post(
            "/api/v1/intake/fan-fragments", json=self.payload(), headers=self.headers
        )
        second = self.client.post(
            "/api/v1/intake/fan-fragments", json=self.payload(), headers=self.headers
        )
        self.assertEqual(202, first.status_code)
        self.assertEqual(first.json["ingestion_id"], second.json["ingestion_id"])
        with self.app.app_context():
            self.assertEqual(1, get_session().query(FanFragmentIngestion).count())

    def test_rejects_private_or_unknown_fields(self):
        payload = self.payload()
        payload["submitter_email"] = "private@example.test"
        response = self.client.post(
            "/api/v1/intake/fan-fragments", json=payload, headers=self.headers
        )
        self.assertEqual(422, response.status_code)
        self.assertIn("Unsupported fields", response.json["error"])

    def test_rejects_unsafe_media_identifiers(self):
        payload = self.payload(
            [
                {
                    "media_id": "../escape",
                    "filename": "fragment.jpg",
                    "content_type": "image/jpeg",
                    "byte_size": 4,
                    "checksum_sha256": hashlib.sha256(b"safe").hexdigest(),
                }
            ]
        )
        response = self.client.post(
            "/api/v1/intake/fan-fragments", json=payload, headers=self.headers
        )
        self.assertEqual(422, response.status_code)

    def test_uploads_manifest_media_and_imports_proposed_artifact(self):
        content = b"safe-image-content"
        checksum = hashlib.sha256(content).hexdigest()
        payload = self.payload(
            [
                {
                    "media_id": "media-1",
                    "filename": "fragment.jpg",
                    "content_type": "image/jpeg",
                    "byte_size": len(content),
                    "checksum_sha256": checksum,
                }
            ]
        )
        created = self.client.post(
            "/api/v1/intake/fan-fragments", json=payload, headers=self.headers
        )
        ingestion_id = created.json["ingestion_id"]
        uploaded = self.client.post(
            f"/api/v1/intake/fan-fragments/{ingestion_id}/media/media-1",
            data={"media": (BytesIO(content), "fragment.jpg", "image/jpeg")},
            headers={"Authorization": "Bearer shared-secret"},
        )
        self.assertEqual(201, uploaded.status_code)
        with self.client.session_transaction() as browser_session:
            browser_session["creator_user"] = {"email": "owner@example.test", "name": "Owner"}
        imported = self.client.post(f"/fan-fragment-inbox/{ingestion_id}/import")
        self.assertEqual(302, imported.status_code)
        with self.app.app_context():
            ingestion = get_session().query(FanFragmentIngestion).one()
            artifact = get_session().get(Artifact, ingestion.imported_artifact_id)
            self.assertEqual("proposed_artifact", artifact.canonical_status)
            self.assertEqual("private", artifact.visibility)


if __name__ == "__main__":
    unittest.main()
