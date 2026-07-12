import os
from datetime import datetime, timezone
from uuid import uuid4

import requests

from .base import PostInteractionData, PostMetrics, PublishResult, PublisherAdapter


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

    def fetch_post_metrics(self, post_publication):
        if self.dry_run:
            return PostMetrics(
                platform=self.platform,
                external_post_id=post_publication.external_post_id,
                external_url=post_publication.external_url,
                raw_metrics={"dry_run": True},
            )

        self.validate_publication(post_publication)
        payload = self.fetch_post_payload(post_publication.external_post_id)
        insights = self.parse_insights(payload.get("insights", {}))
        comments = self.summary_total(payload.get("comments", {}))
        likes = self.summary_total(payload.get("reactions", {}))
        shares = int((payload.get("shares") or {}).get("count") or 0)

        return PostMetrics(
            platform=self.platform,
            external_post_id=post_publication.external_post_id,
            external_url=payload.get("permalink_url") or post_publication.external_url,
            views=insights.get("post_impressions", 0),
            likes=likes,
            comments=comments,
            shares=shares,
            clicks=insights.get("post_clicks", 0),
            reach=insights.get("post_impressions_unique", 0),
            raw_metrics=payload,
        )

    def fetch_post_interactions(self, post_publication):
        if self.dry_run:
            return []

        self.validate_publication(post_publication)
        payload = self.fetch_post_payload(post_publication.external_post_id)
        comments = (payload.get("comments") or {}).get("data") or []
        return [
            PostInteractionData(
                platform=self.platform,
                interaction_type="comment",
                external_id=str(comment.get("id") or ""),
                external_post_id=post_publication.external_post_id,
                author_name=str((comment.get("from") or {}).get("name") or ""),
                author_platform_id=str((comment.get("from") or {}).get("id") or ""),
                body=str(comment.get("message") or ""),
                received_at=self.parse_facebook_time(comment.get("created_time")),
                raw_payload=comment,
            )
            for comment in comments
            if comment.get("id")
        ]

    def validate_publication(self, post_publication):
        if self.target_type != "page":
            raise ValueError("Facebook polling only supports Page publications.")
        if not post_publication.external_post_id:
            raise ValueError("Facebook publication is missing an external post id.")
        if not self.page_id or not self.access_token:
            raise ValueError("FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN are required for polling.")

    def fetch_post_payload(self, external_post_id):
        endpoint = f"https://graph.facebook.com/{self.graph_version}/{external_post_id}"
        fields = (
            "permalink_url,shares,"
            "comments.limit(25).summary(true){id,from,message,created_time,permalink_url},"
            "reactions.limit(0).summary(true),"
            "insights.metric(post_impressions,post_impressions_unique,post_engaged_users,post_clicks)"
        )
        response = requests.get(
            endpoint,
            params={
                "fields": fields,
                "access_token": self.access_token,
            },
            timeout=20,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = payload.get("error", {}).get("message", response.reason)
            raise ValueError(message)
        return payload

    def parse_insights(self, insights_payload):
        parsed = {}
        for item in insights_payload.get("data") or []:
            values = item.get("values") or []
            value = values[-1].get("value") if values else 0
            try:
                parsed[item.get("name")] = int(value or 0)
            except (TypeError, ValueError):
                parsed[item.get("name")] = 0
        return parsed

    def summary_total(self, payload):
        try:
            return int(((payload or {}).get("summary") or {}).get("total_count") or 0)
        except (TypeError, ValueError):
            return 0

    def parse_facebook_time(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
