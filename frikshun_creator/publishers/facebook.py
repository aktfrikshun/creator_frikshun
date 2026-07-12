import os
from uuid import uuid4

from .base import PublishResult, PublisherAdapter


class FacebookAdapter(PublisherAdapter):
    platform = "facebook"

    def __init__(
        self,
        page_id=None,
        access_token=None,
        graph_version=None,
        dry_run=None,
        target_type=None,
    ):
        self.page_id = page_id or os.getenv("FACEBOOK_PAGE_ID", "")
        self.access_token = access_token or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
        self.graph_version = graph_version or os.getenv("FACEBOOK_GRAPH_VERSION", "v20.0")
        self.target_type = target_type or os.getenv("FACEBOOK_TARGET_TYPE", "page")
        if dry_run is None:
            dry_run = os.getenv("FACEBOOK_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run

    def validate(self, post_draft):
        base_result = super().validate(post_draft)
        if not base_result.success:
            return base_result

        if self.target_type != "page":
            return PublishResult(
                success=False,
                status="manual_required",
                error_message=(
                    "FacebookAdapter only supports automated publishing to Pages. "
                    "Personal profile publishing should use manual copy/paste."
                ),
            )

        if not self.dry_run and (not self.page_id or not self.access_token):
            return PublishResult(
                success=False,
                status="failed",
                error_message=(
                    "FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN are required "
                    "when FACEBOOK_DRY_RUN=false."
                ),
            )

        return PublishResult(success=True, status="validated")

    def publish(self, post_draft):
        validation = self.validate(post_draft)
        if not validation.success:
            return validation

        message = self.prepare(post_draft)

        if self.dry_run:
            external_post_id = f"dry-run-facebook-{uuid4()}"
            return PublishResult(
                success=True,
                status="published",
                external_post_id=external_post_id,
                external_url=f"dry-run://facebook/{external_post_id}",
                raw_response={
                    "dry_run": True,
                    "target_type": self.target_type,
                    "page_id": self.page_id,
                    "message": message,
                },
            )

        import requests

        endpoint = f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/feed"
        response = requests.post(
            endpoint,
            data={
                "message": message,
                "access_token": self.access_token,
            },
            timeout=20,
        )

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}

        if not response.ok:
            return PublishResult(
                success=False,
                status="failed",
                error_message=payload.get("error", {}).get("message", response.reason),
                raw_response=payload,
            )

        external_post_id = payload.get("id", "")
        return PublishResult(
            success=True,
            status="published",
            external_post_id=external_post_id,
            external_url=f"https://www.facebook.com/{external_post_id}" if external_post_id else "",
            raw_response=payload,
        )
