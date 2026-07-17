from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

import boto3
import requests
from PIL import Image

from ..models import Artifact, PostDraft
from ..publishers.facebook import FacebookAdapter
from ..publishers.instagram import InstagramAdapter
from ..publishers.x import XAdapter
from ..publishers.fanvue import FanvueAdapter


@dataclass
class ReadinessCheck:
    name: str
    ok: bool
    detail: str


class DailyFragmentReadinessChecker:
    def __init__(self, app):
        self.app = app

    def run(self):
        checks = []
        checks.append(self.check_openai())
        checks.append(self.check_upload_folder())
        checks.append(self.check_s3())
        checks.extend(self.check_publishers())
        return checks

    def check_openai(self):
        if self.app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"):
            return ReadinessCheck("openai", True, "OPENAI_API_KEY is configured.")
        return ReadinessCheck("openai", False, "OPENAI_API_KEY is missing.")

    def check_upload_folder(self):
        upload_folder = Path(self.app.config.get("UPLOAD_FOLDER") or "instance/uploads")
        try:
            upload_folder.mkdir(parents=True, exist_ok=True)
            probe = upload_folder / ".readiness-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return ReadinessCheck("upload_folder", True, f"Writable: {upload_folder}")
        except OSError as error:
            return ReadinessCheck("upload_folder", False, f"{upload_folder}: {error}")

    def check_s3(self):
        bucket = str(self.app.config.get("S3_MEDIA_BUCKET") or "").strip()
        if not bucket:
            return ReadinessCheck("s3", False, "S3_MEDIA_BUCKET is missing.")
        creds = boto3.Session().get_credentials()
        if creds is None:
            return ReadinessCheck("s3", False, "AWS credentials are missing from the SDK chain.")
        return ReadinessCheck("s3", True, f"S3 bucket configured: {bucket}")

    def check_publishers(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            public_image = directory_path / "public.jpg"
            fanvue_image = directory_path / "fanvue.jpg"
            Image.new("RGB", (8, 8), color="black").save(public_image, "JPEG")
            Image.new("RGB", (8, 8), color="black").save(fanvue_image, "JPEG")

            artifact = Artifact(
                title="Readiness Probe",
                media_path=str(public_image),
                media_content_type="image/jpeg",
                generated_metadata={
                    "public_media_url": "https://example.test/readiness.jpg",
                    "fanvue_media_path": str(fanvue_image),
                },
            )
            drafts = {
                "facebook": PostDraft(
                    artifact=artifact,
                    platform="facebook",
                    caption="Readiness probe.",
                    hashtags=["ChloeKatastrophe"],
                ),
                "instagram": PostDraft(
                    artifact=artifact,
                    platform="instagram",
                    caption="Readiness probe.",
                    hashtags=["ChloeKatastrophe"],
                ),
                "x": PostDraft(
                    artifact=artifact,
                    platform="x",
                    caption="Readiness probe. Which signal still feels true?",
                    hashtags=["ChloeKatastrophe"],
                ),
                "fanvue": PostDraft(
                    artifact=artifact,
                    platform="fanvue",
                    caption="Readiness probe. Which signal still feels true?",
                    hashtags=["ChloeKatastrophe"],
                ),
            }

            adapters = {
                "facebook": FacebookAdapter(
                    page_id=self.app.config.get("FACEBOOK_PAGE_ID"),
                    access_token=self.app.config.get("FACEBOOK_PAGE_ACCESS_TOKEN"),
                    graph_version=self.app.config.get("FACEBOOK_GRAPH_VERSION"),
                    dry_run=self.app.config.get("FACEBOOK_DRY_RUN"),
                    target_type=self.app.config.get("FACEBOOK_TARGET_TYPE"),
                ),
                "instagram": InstagramAdapter(
                    user_id=self.app.config.get("INSTAGRAM_USER_ID"),
                    access_token=self.app.config.get("INSTAGRAM_ACCESS_TOKEN"),
                    graph_version=self.app.config.get("INSTAGRAM_GRAPH_VERSION"),
                    media_base_url=self.app.config.get("INSTAGRAM_MEDIA_BASE_URL"),
                    dry_run=self.app.config.get("INSTAGRAM_DRY_RUN"),
                ),
                "x": XAdapter(
                    consumer_key=self.app.config.get("X_CONSUMER_KEY"),
                    consumer_secret=self.app.config.get("X_SECRET_KEY"),
                    access_token=self.app.config.get("X_ACCESS_TOKEN"),
                    access_token_secret=self.app.config.get("X_ACCESS_TOKEN_SECRET"),
                    bearer_token=self.app.config.get("X_BEARER_TOKEN"),
                    username=self.app.config.get("X_USERNAME"),
                    dry_run=self.app.config.get("X_DRY_RUN"),
                ),
                "fanvue": FanvueAdapter(
                    api_version=self.app.config.get("FANVUE_API_VERSION"),
                    audience=self.app.config.get("FANVUE_AUDIENCE"),
                    dry_run=self.app.config.get("FANVUE_DRY_RUN"),
                ),
            }

            checks = []
            for platform in ("facebook", "instagram", "x", "fanvue"):
                validation = adapters[platform].validate(drafts[platform])
                ok = bool(validation.success and validation.status == "validated")
                detail = "validated" if ok else str(validation.error_message or validation.status)
                checks.append(ReadinessCheck(platform, ok, detail))

            checks.append(self.check_facebook_remote())
            checks.append(self.check_instagram_remote())
            checks.append(self.check_x_remote(adapters["x"]))
            return checks

    def check_facebook_remote(self):
        if self.app.config.get("FACEBOOK_DRY_RUN"):
            return ReadinessCheck("facebook_remote", False, "FACEBOOK_DRY_RUN must be false.")
        try:
            response = requests.get(
                f"https://graph.facebook.com/{self.app.config.get('FACEBOOK_GRAPH_VERSION')}/{self.app.config.get('FACEBOOK_PAGE_ID')}",
                params={
                    "fields": "id,name",
                    "access_token": self.app.config.get("FACEBOOK_PAGE_ACCESS_TOKEN"),
                },
                timeout=20,
            )
            payload = response.json()
            if response.ok and payload.get("id"):
                return ReadinessCheck(
                    "facebook_remote",
                    True,
                    f"Resolved Page {payload.get('name') or payload.get('id')}.",
                )
            message = (payload.get("error") or {}).get("message") or response.reason
            return ReadinessCheck("facebook_remote", False, str(message))
        except (requests.RequestException, ValueError) as error:
            return ReadinessCheck("facebook_remote", False, str(error))

    def check_instagram_remote(self):
        if self.app.config.get("INSTAGRAM_DRY_RUN"):
            return ReadinessCheck("instagram_remote", False, "INSTAGRAM_DRY_RUN must be false.")
        try:
            response = requests.get(
                f"https://graph.facebook.com/{self.app.config.get('INSTAGRAM_GRAPH_VERSION')}/{self.app.config.get('INSTAGRAM_USER_ID')}",
                params={
                    "fields": "id,username",
                    "access_token": self.app.config.get("INSTAGRAM_ACCESS_TOKEN"),
                },
                timeout=20,
            )
            payload = response.json()
            if response.ok and payload.get("id"):
                return ReadinessCheck(
                    "instagram_remote",
                    True,
                    f"Resolved Instagram account {payload.get('username') or payload.get('id')}.",
                )
            message = (payload.get("error") or {}).get("message") or response.reason
            return ReadinessCheck("instagram_remote", False, str(message))
        except (requests.RequestException, ValueError) as error:
            return ReadinessCheck("instagram_remote", False, str(error))

    def check_x_remote(self, adapter):
        if self.app.config.get("X_DRY_RUN"):
            return ReadinessCheck("x_remote", False, "X_DRY_RUN must be false.")
        try:
            payload = adapter.verify_identity()
            data = payload.get("data") or {}
            if data.get("id"):
                return ReadinessCheck(
                    "x_remote",
                    True,
                    f"Resolved X user @{data.get('username') or data.get('id')}.",
                )
            return ReadinessCheck("x_remote", False, "X identity response did not include a user id.")
        except (requests.RequestException, ValueError) as error:
            return ReadinessCheck("x_remote", False, str(error))
