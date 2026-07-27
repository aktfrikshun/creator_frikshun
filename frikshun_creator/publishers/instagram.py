import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests

from .base import PostInteractionData, PostMetrics, PublishResult, PublisherAdapter
from ..services.post_media import media_kind, post_media_items


class InstagramAdapter(PublisherAdapter):
    """Publish image feed posts and video reels through Instagram's Graph API."""

    platform = "instagram"
    DEFAULT_TAG_USERNAMES = ("allenktaylor",)

    def __init__(
        self,
        user_id=None,
        access_token=None,
        graph_version=None,
        media_base_url=None,
        dry_run=None,
        status_attempts=10,
        status_delay=1,
        tag_usernames=None,
    ):
        self.user_id = user_id or os.getenv("INSTAGRAM_USER_ID", "")
        self.access_token = access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
        self.graph_version = graph_version or os.getenv("INSTAGRAM_GRAPH_VERSION", "v20.0")
        self.media_base_url = (media_base_url or os.getenv("INSTAGRAM_MEDIA_BASE_URL", "")).rstrip("/")
        if dry_run is None:
            dry_run = os.getenv("INSTAGRAM_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run
        self.status_attempts = status_attempts
        self.status_delay = status_delay
        if tag_usernames is None:
            configured = os.getenv("INSTAGRAM_TAG_USERNAMES", "")
            tag_usernames = configured.split(",") if configured.strip() else self.DEFAULT_TAG_USERNAMES
        self.tag_usernames = tuple(
            username.strip().lstrip("@")
            for username in tag_usernames
            if username and username.strip().lstrip("@")
        )
        self.tag_warnings = []

    def prepare(self, post_draft):
        """Produce an Instagram-safe caption with no raw external links."""
        prepared = super().prepare(post_draft)
        paragraphs = [paragraph.strip() for paragraph in prepared.split("\n\n") if paragraph.strip()]
        standing_footer_starts = (
            "Learn more about me in the FrikShun archives:",
            "My music is available on all major streaming platforms.",
            "My modeling work funds the reconstruction of my memory:",
        )
        kept = [
            paragraph
            for paragraph in paragraphs
            if not paragraph.startswith(standing_footer_starts)
        ]
        cleaned = []
        for paragraph in kept:
            without_urls = re.sub(r"https?://\S+", "", paragraph).strip()
            without_urls = re.sub(r"[ \t]+\n", "\n", without_urls)
            without_urls = re.sub(r" {2,}", " ", without_urls)
            if without_urls:
                cleaned.append(without_urls)

        hashtags = []
        while cleaned and cleaned[-1].startswith("#"):
            hashtags.insert(0, cleaned.pop())
        cleaned.extend(hashtags)
        return "\n\n".join(cleaned)

    def validate(self, post_draft):
        base_result = super().validate(post_draft)
        if not base_result.success:
            return base_result

        media = self.media_items(post_draft)
        if not media:
            return PublishResult(False, "failed", error_message="Instagram requires media.")
        for item in media:
            if media_kind(item) == "image" and item["media_content_type"] != "image/jpeg":
                return PublishResult(
                    success=False,
                    status="failed",
                    error_message="Instagram image publishing requires JPEG attachments.",
                )
            if media_kind(item) not in {"image", "video"}:
                return PublishResult(False, "failed", error_message="Instagram supports photos and videos only.")
            if urlparse(str(item.get("public_media_url") or "")).scheme != "https":
                return PublishResult(
                    False,
                    "failed",
                    error_message="Every Instagram attachment requires a public HTTPS media URL.",
                )
        if not self.is_image_post(post_draft) and not self.is_video_post(post_draft):
            return PublishResult(
                success=False,
                status="failed",
                error_message="Instagram publishing currently supports JPEG images and video artifacts only.",
            )

        media_url = self.media_url(post_draft)
        if not media_url:
            return PublishResult(
                success=False,
                status="failed",
                error_message=(
                    "Instagram requires a public HTTPS media URL. Set public_media_url in the "
                    "artifact metadata or configure INSTAGRAM_MEDIA_BASE_URL."
                ),
            )
        if urlparse(media_url).scheme != "https":
            return PublishResult(
                success=False,
                status="failed",
                error_message="Instagram media URLs must use HTTPS.",
            )

        if not self.dry_run and (not self.user_id or not self.access_token):
            return PublishResult(
                success=False,
                status="failed",
                error_message=(
                    "INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN are required when "
                    "INSTAGRAM_DRY_RUN=false."
                ),
            )
        return PublishResult(success=True, status="validated")

    def publish(self, post_draft):
        validation = self.validate(post_draft)
        if not validation.success:
            return validation

        caption = self.prepare(post_draft)
        media_url = self.media_url(post_draft)
        media = self.media_items(post_draft)
        publish_kind = (
            "carousel"
            if len(media) > 1
            else ("reel" if self.is_video_post(post_draft) else "single_image")
        )
        if self.dry_run:
            external_post_id = f"dry-run-instagram-{uuid4()}"
            return PublishResult(
                success=True,
                status="published",
                external_post_id=external_post_id,
                external_url=f"dry-run://instagram/{external_post_id}",
                raw_response={
                    "dry_run": True,
                    "user_id": self.user_id,
                    "media_url": media_url,
                    "media_urls": [item.get("public_media_url") for item in media],
                    "caption": caption,
                    "publish_kind": publish_kind,
                    "user_tags": self.image_user_tags(),
                },
            )

        try:
            if len(media) > 1:
                container, child_containers = self.create_carousel(media, caption)
            else:
                container = self.create_container(post_draft, media_url, caption)
                child_containers = []
            creation_id = str(container.get("id") or "")
            if not creation_id:
                return self.failed_result("Instagram did not return a creation id.", container)

            status = self.wait_for_container(
                creation_id,
                attempts=max(180, self.status_attempts)
                if publish_kind in {"carousel", "reel"}
                else None,
            )
            if status.get("status_code") != "FINISHED":
                message = (
                    status.get("status")
                    or status.get("error_message")
                    or "Instagram media processing failed."
                )
                return self.failed_result(message, {"container": container, "status": status})

            published = self.publish_container(creation_id)
            media_id = str(published.get("id") or "")
            if not media_id:
                return self.failed_result("Instagram did not return a published media id.", published)

            details = self.fetch_media(media_id, fields="permalink")
        except (requests.RequestException, ValueError) as error:
            return self.failed_result(str(error), {"publish_kind": publish_kind})
        return PublishResult(
            success=True,
            status="published",
            external_post_id=media_id,
            external_url=str(details.get("permalink") or ""),
            raw_response={
                "container": container,
                "child_containers": child_containers,
                "status": status,
                "published": published,
                "media": details,
                "publish_kind": publish_kind,
                "tag_warnings": self.tag_warnings,
            },
        )

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

    def create_container(self, post_draft, media_url, caption):
        payload = {"caption": caption}
        if self.is_video_post(post_draft):
            payload["media_type"] = "REELS"
            payload["video_url"] = media_url
        else:
            payload["image_url"] = media_url
            self.add_image_user_tags(payload)
        return self.create_media_container(payload)

    def create_carousel(self, media, caption):
        child_containers = []
        child_ids = []
        for item in media[:10]:
            payload = {"is_carousel_item": "true"}
            if media_kind(item) == "video":
                payload.update(
                    {"media_type": "VIDEO", "video_url": item["public_media_url"]}
                )
            else:
                payload["image_url"] = item["public_media_url"]
                self.add_image_user_tags(payload)
            child = self.create_media_container(payload)
            child_id = str(child.get("id") or "")
            if not child_id:
                raise ValueError("Instagram did not return a carousel child id.")
            status = self.wait_for_container(child_id, attempts=max(180, self.status_attempts))
            if status.get("status_code") != "FINISHED":
                raise ValueError(
                    status.get("status")
                    or status.get("error_message")
                    or "Instagram carousel attachment processing failed."
                )
            child_containers.append({"container": child, "status": status})
            child_ids.append(child_id)
        parent = self.graph_post(
            f"{self.user_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
            },
        )
        return parent, child_containers

    def add_image_user_tags(self, payload):
        user_tags = self.image_user_tags()
        if user_tags:
            payload["user_tags"] = json.dumps(user_tags)

    def create_media_container(self, payload):
        try:
            return self.graph_post(f"{self.user_id}/media", payload)
        except ValueError as error:
            if "user_tags" not in payload or "invalid user id" not in str(error).lower():
                raise
            untagged_payload = dict(payload)
            untagged_payload.pop("user_tags", None)
            self.tag_warnings.append(
                "Instagram rejected the configured photo tag; this media was published without it."
            )
            return self.graph_post(f"{self.user_id}/media", untagged_payload)

    def image_user_tags(self):
        if not self.tag_usernames:
            return []
        count = len(self.tag_usernames)
        return [
            {
                "username": username,
                "x": round((index + 1) / (count + 1), 3),
                "y": 0.5,
            }
            for index, username in enumerate(self.tag_usernames)
        ]

    def publish_container(self, creation_id):
        return self.graph_post(f"{self.user_id}/media_publish", {"creation_id": creation_id})

    def wait_for_container(self, creation_id, attempts=None):
        attempts = attempts or self.status_attempts
        last_status = {}
        for attempt in range(attempts):
            last_status = self.graph_get(creation_id, {"fields": "status_code,status"})
            if last_status.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
                return last_status
            if attempt + 1 < attempts and self.status_delay:
                time.sleep(self.status_delay)
        return last_status

    def graph_post(self, path, data):
        response = requests.post(
            self.graph_url(path),
            data={**data, "access_token": self.access_token},
            timeout=30,
        )
        return self.response_payload(response)

    def graph_get(self, path, params=None):
        response = requests.get(
            self.graph_url(path),
            params={**(params or {}), "access_token": self.access_token},
            timeout=20,
        )
        return self.response_payload(response)

    def response_payload(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = payload.get("error", {}).get("message", response.reason)
            raise ValueError(message)
        return payload

    def graph_url(self, path):
        return f"https://graph.facebook.com/{self.graph_version}/{path.lstrip('/')}"

    def media_url(self, post_draft):
        artifact = getattr(post_draft, "artifact", None)
        metadata = getattr(artifact, "generated_metadata", None) or {}
        explicit_url = str(metadata.get("public_media_url") or "").strip()
        if explicit_url:
            return explicit_url
        media_path = str(getattr(artifact, "media_path", "") or "")
        if media_path.startswith(("https://", "http://")):
            return media_path
        if self.media_base_url and media_path:
            return f"{self.media_base_url}/{quote(Path(media_path).name)}"
        return ""

    def media_items(self, post_draft):
        items = post_media_items(post_draft)
        for index, item in enumerate(items):
            if not item.get("public_media_url") and index == 0:
                item["public_media_url"] = self.media_url(post_draft)
            item["media_content_type"] = str(
                item.get("media_content_type") or ""
            ).lower()
        return items[:10]

    def media_content_type(self, post_draft):
        artifact = getattr(post_draft, "artifact", None)
        return str(getattr(artifact, "media_content_type", "") or "").lower()

    def is_image_post(self, post_draft):
        return self.media_content_type(post_draft).startswith("image/")

    def is_video_post(self, post_draft):
        return self.media_content_type(post_draft).startswith("video/")

    def fetch_media(self, media_id, fields):
        return self.graph_get(media_id, {"fields": fields})

    def fetch_post_metrics(self, post_publication):
        if self.dry_run:
            return PostMetrics(
                platform=self.platform,
                external_post_id=post_publication.external_post_id,
                external_url=post_publication.external_url,
                raw_metrics={"dry_run": True},
            )
        payload = self.fetch_media(
            post_publication.external_post_id,
            fields="permalink,like_count,comments_count",
        )
        try:
            insights_payload = self.graph_get(
                f"{post_publication.external_post_id}/insights",
                {"metric": "views,reach,saved,shares"},
            )
            insights = self.parse_insights(insights_payload)
        except (requests.RequestException, ValueError) as error:
            insights_payload = {"error": str(error)}
            insights = {}
        return PostMetrics(
            platform=self.platform,
            external_post_id=post_publication.external_post_id,
            external_url=str(payload.get("permalink") or post_publication.external_url),
            likes=int(payload.get("like_count") or 0),
            comments=int(payload.get("comments_count") or 0),
            views=insights.get("views", 0),
            reach=insights.get("reach", 0),
            saves=insights.get("saved", 0),
            shares=insights.get("shares", 0),
            raw_metrics={**payload, "insights": insights_payload},
        )

    def fetch_post_interactions(self, post_publication):
        if self.dry_run:
            return []
        payload = self.graph_get(
            f"{post_publication.external_post_id}/comments",
            {"fields": "id,text,timestamp,username", "limit": 25},
        )
        return [
            PostInteractionData(
                platform=self.platform,
                interaction_type="comment",
                external_id=str(comment.get("id") or ""),
                external_post_id=post_publication.external_post_id,
                author_name=str(comment.get("username") or ""),
                author_platform_id=str(comment.get("username") or ""),
                body=str(comment.get("text") or ""),
                received_at=self.parse_time(comment.get("timestamp")),
                raw_payload=comment,
            )
            for comment in payload.get("data") or []
            if comment.get("id")
        ]

    def fetch_account_interactions(self):
        """Fetch comments from every media item on the connected Instagram account."""
        if self.dry_run or not self.user_id:
            return []
        interactions = []
        identity = self.graph_request_url(
            self.graph_url(self.user_id),
            params={"fields": "id,username", "access_token": self.access_token},
        )
        own_id = str(identity.get("id") or self.user_id)
        own_username = str(identity.get("username") or "").casefold()
        media_url = self.graph_url(f"{self.user_id}/media")
        params = {
            "fields": "id,caption,permalink,timestamp",
            "limit": 100,
            "access_token": self.access_token,
        }
        seen_urls = set()
        while media_url and media_url not in seen_urls:
            seen_urls.add(media_url)
            payload = self.graph_request_url(media_url, params=params)
            params = None
            for media in payload.get("data") or []:
                media_id = str(media.get("id") or "")
                if not media_id:
                    continue
                comment_url = self.graph_url(f"{media_id}/comments")
                comment_params = {
                    "fields": "id,text,timestamp,username,from{id,username},replies.limit(100){id,username,from{id,username}}",
                    "limit": 100,
                    "access_token": self.access_token,
                }
                seen_comment_urls = set()
                while comment_url and comment_url not in seen_comment_urls:
                    seen_comment_urls.add(comment_url)
                    comments = self.graph_request_url(comment_url, params=comment_params)
                    comment_params = None
                    for comment in comments.get("data") or []:
                        comment_id = str(comment.get("id") or "")
                        if not comment_id:
                            continue
                        raw_payload = dict(comment)
                        author = comment.get("from") or {}
                        username = str(comment.get("username") or author.get("username") or "")
                        author_id = str(author.get("id") or username)
                        owned_by_me = bool(
                            (own_id and str(author.get("id") or "") == own_id)
                            or (own_username and username.casefold() == own_username)
                        )
                        replies = (comment.get("replies") or {}).get("data") or []
                        already_replied = any(
                            (own_id and str((reply.get("from") or {}).get("id") or "") == own_id)
                            or (
                                own_username
                                and str(reply.get("username") or (reply.get("from") or {}).get("username") or "").casefold()
                                == own_username
                            )
                            for reply in replies
                        )
                        raw_payload.update({
                            "source_post_message": str(media.get("caption") or ""),
                            "source_post_permalink": str(media.get("permalink") or ""),
                            "source_post_created_time": str(media.get("timestamp") or ""),
                            "is_owned_by_me": owned_by_me,
                            "already_replied_by_us": already_replied,
                        })
                        interactions.append(PostInteractionData(
                            platform=self.platform,
                            interaction_type="comment",
                            external_id=comment_id,
                            external_post_id=media_id,
                            author_name=username,
                            author_platform_id=author_id,
                            body=str(comment.get("text") or ""),
                            received_at=self.parse_time(comment.get("timestamp")),
                            raw_payload=raw_payload,
                        ))
                    comment_url = (comments.get("paging") or {}).get("next")
            media_url = (payload.get("paging") or {}).get("next")
        return interactions

    def reply_to_comment(self, comment_id, message):
        comment_id = str(comment_id or "").strip()
        message = str(message or "").strip()
        if not comment_id or not message:
            raise ValueError("Instagram comment id and reply message are required.")
        if self.dry_run:
            return {"id": f"dry-run-instagram-reply-{comment_id}"}
        return self.graph_post(f"{comment_id}/replies", {"message": message})

    def graph_request_url(self, url, params=None):
        response = requests.get(url, params=params, timeout=30)
        return self.response_payload(response)

    def parse_time(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def parse_insights(self, payload):
        parsed = {}
        for item in payload.get("data") or []:
            values = item.get("values") or []
            value = item.get("value")
            if value is None and values:
                value = values[-1].get("value")
            try:
                parsed[str(item.get("name") or "")] = int(value or 0)
            except (TypeError, ValueError):
                parsed[str(item.get("name") or "")] = 0
        return parsed

    def failed_result(self, message, payload):
        return PublishResult(
            success=False,
            status="failed",
            error_message=str(message),
            raw_response=payload,
        )
