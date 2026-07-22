import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests

from .base import PostInteractionData, PostMetrics, PublishResult, PublisherAdapter


class FacebookAdapter(PublisherAdapter):
    platform = "facebook"
    DEFAULT_TAG_USERNAMES = ("allenktaylor", "chloekatastropheai")

    def __init__(
        self,
        page_id=None,
        access_token=None,
        graph_version=None,
        dry_run=None,
        target_type=None,
        tag_usernames=None,
    ):
        self.page_id = page_id or os.getenv("FACEBOOK_PAGE_ID", "")
        self.access_token = access_token or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
        self.graph_version = graph_version or os.getenv("FACEBOOK_GRAPH_VERSION", "v20.0")
        self.target_type = target_type or os.getenv("FACEBOOK_TARGET_TYPE", "page")
        if tag_usernames is None:
            tag_usernames = self.DEFAULT_TAG_USERNAMES
        self.tag_usernames = tuple(
            username.strip().lstrip("@")
            for username in tag_usernames
            if username and username.strip().lstrip("@")
        )
        if dry_run is None:
            dry_run = os.getenv("FACEBOOK_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run

    def prepare(self, post_draft):
        message = super().prepare(post_draft)
        missing_tags = [
            f"@{username}"
            for username in self.tag_usernames
            if not re.search(rf"(?<![\w@])@{re.escape(username)}\b", message, re.IGNORECASE)
        ]
        if missing_tags:
            message = f"{message}\n\n{' '.join(missing_tags)}"
        return message

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
                    "media_path": self.media_path(post_draft),
                    "publish_kind": self.publish_kind(post_draft),
                },
            )

        if self.should_publish_photo(post_draft):
            return self.publish_photo(post_draft, message)
        if self.should_publish_video(post_draft):
            return self.publish_video(post_draft, message)
        return self.publish_feed_post(message)

    def unpublish(self, publication):
        if self.dry_run:
            return PublishResult(True, "unpublished", publication.external_post_id,
                                 raw_response={"dry_run": True, "deleted": True})
        response = requests.delete(
            f"https://graph.facebook.com/{self.graph_version}/{publication.external_post_id}",
            data={"access_token": self.access_token}, timeout=20,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok or payload.get("success") is False:
            return PublishResult(False, "failed", publication.external_post_id,
                                 error_message=payload.get("error", {}).get("message", response.reason),
                                 raw_response=payload)
        return PublishResult(True, "unpublished", publication.external_post_id, raw_response=payload)

    def publish_feed_post(self, message):
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

    def publish_photo(self, post_draft, message):
        media_path = Path(self.media_path(post_draft))
        endpoint = f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/photos"
        with media_path.open("rb") as image_file:
            response = requests.post(
                endpoint,
                data={
                    "caption": message,
                    "access_token": self.access_token,
                },
                files={"source": (media_path.name, image_file, self.media_content_type(post_draft))},
                timeout=30,
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}

        if not response.ok:
            error_message = payload.get("error", {}).get("message", response.reason)
            if message and self.should_fallback_to_attached_media(error_message):
                fallback = self.publish_photo_then_feed_post(post_draft, message)
                fallback.raw_response = {
                    "initial_photo_error": payload,
                    "fallback": fallback.raw_response,
                }
                return fallback
            return PublishResult(
                success=False,
                status="failed",
                error_message=error_message,
                raw_response=payload,
            )

        external_post_id = payload.get("post_id") or payload.get("id", "")
        external_url = f"https://www.facebook.com/{external_post_id}" if external_post_id else ""
        return PublishResult(
            success=True,
            status="published",
            external_post_id=external_post_id,
            external_url=external_url,
            raw_response={**payload, "publish_kind": "photo"},
        )

    def publish_photo_then_feed_post(self, post_draft, message):
        media_path = Path(self.media_path(post_draft))
        photo_endpoint = f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/photos"
        with media_path.open("rb") as image_file:
            upload_response = requests.post(
                photo_endpoint,
                data={
                    "published": "false",
                    "access_token": self.access_token,
                },
                files={"source": (media_path.name, image_file, self.media_content_type(post_draft))},
                timeout=30,
            )

        try:
            upload_payload = upload_response.json()
        except ValueError:
            upload_payload = {"raw_body": upload_response.text}

        if not upload_response.ok:
            return PublishResult(
                success=False,
                status="failed",
                error_message=upload_payload.get("error", {}).get("message", upload_response.reason),
                raw_response={"photo_upload": upload_payload},
            )

        photo_id = str(upload_payload.get("id") or "")
        if not photo_id:
            return PublishResult(
                success=False,
                status="failed",
                error_message="Facebook unpublished photo upload did not return an id.",
                raw_response={"photo_upload": upload_payload},
            )

        feed_endpoint = f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/feed"
        feed_response = requests.post(
            feed_endpoint,
            data={
                "message": message,
                "attached_media[0]": f'{{"media_fbid":"{photo_id}"}}',
                "access_token": self.access_token,
            },
            timeout=20,
        )

        try:
            feed_payload = feed_response.json()
        except ValueError:
            feed_payload = {"raw_body": feed_response.text}

        if not feed_response.ok:
            return PublishResult(
                success=False,
                status="failed",
                error_message=feed_payload.get("error", {}).get("message", feed_response.reason),
                raw_response={"photo_upload": upload_payload, "feed_publish": feed_payload},
            )

        external_post_id = feed_payload.get("id", "")
        return PublishResult(
            success=True,
            status="published",
            external_post_id=external_post_id,
            external_url=f"https://www.facebook.com/{external_post_id}" if external_post_id else "",
            raw_response={
                "photo_upload": upload_payload,
                "feed_publish": feed_payload,
                "publish_kind": "photo_attached_feed",
            },
        )

    def publish_video(self, post_draft, message):
        media_path = Path(self.media_path(post_draft))
        endpoint = f"https://graph.facebook.com/{self.graph_version}/{self.page_id}/videos"
        with media_path.open("rb") as video_file:
            response = requests.post(
                endpoint,
                data={
                    "description": message,
                    "access_token": self.access_token,
                },
                files={"source": (media_path.name, video_file, self.media_content_type(post_draft))},
                timeout=120,
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

        external_post_id = str(payload.get("id") or "")
        return PublishResult(
            success=True,
            status="published",
            external_post_id=external_post_id,
            external_url=f"https://www.facebook.com/{external_post_id}" if external_post_id else "",
            raw_response={**payload, "publish_kind": "video"},
        )

    def should_publish_photo(self, post_draft):
        media_path = self.media_path(post_draft)
        return (
            self.media_content_type(post_draft).startswith("image/")
            and bool(media_path)
            and Path(media_path).exists()
        )

    def should_publish_video(self, post_draft):
        media_path = self.media_path(post_draft)
        return (
            self.media_content_type(post_draft).startswith("video/")
            and bool(media_path)
            and Path(media_path).exists()
        )

    def publish_kind(self, post_draft):
        if self.should_publish_photo(post_draft):
            return "photo"
        if self.should_publish_video(post_draft):
            return "video"
        return "feed"

    def should_fallback_to_attached_media(self, error_message):
        normalized = str(error_message or "").lower()
        return "reduce the amount of data" in normalized

    def media_path(self, post_draft):
        artifact = getattr(post_draft, "artifact", None)
        return getattr(artifact, "media_path", "") or ""

    def media_content_type(self, post_draft):
        artifact = getattr(post_draft, "artifact", None)
        return getattr(artifact, "media_content_type", "") or ""

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
            "insights.metric(post_clicks)"
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
