import base64
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import requests
from requests_oauthlib import OAuth1

from .base import PostMetrics, PublishResult, PublisherAdapter
from ..services.post_media import media_kind, post_media_items


class XAdapter(PublisherAdapter):
    """Publish an image post and collect engagement metrics through X API v2."""

    platform = "x"
    max_text_length = 280
    post_verification_attempts = 3
    post_verification_delay = 1

    def prepare(self, post_draft):
        """Produce compact, link-free X copy without a compulsory promo footer."""
        prepared = super().prepare(post_draft)
        paragraphs = [part.strip() for part in prepared.split("\n\n") if part.strip()]
        footer_starts = (
            "Learn more about me in the FrikShun archives:",
            "My music is available on all major streaming platforms.",
            "My modeling work funds the reconstruction of my memory:",
            "Archive:",
            "Music:",
            "Modeling funds",
        )
        kept = [part for part in paragraphs if not part.startswith(footer_starts)]
        cleaned = []
        for part in kept:
            without_urls = re.sub(r"https?://\S+", "", part).strip()
            without_urls = re.sub(r" {2,}", " ", without_urls)
            if without_urls:
                cleaned.append(without_urls)

        hashtags = []
        while cleaned and cleaned[-1].startswith("#"):
            hashtags.insert(0, cleaned.pop())
        suffix = "\n\n".join(hashtags)
        body = "\n\n".join(cleaned)
        available = self.max_text_length - len(suffix) - (2 if body and suffix else 0)
        if available < 0:
            suffix = self.fit_text(suffix, self.max_text_length)
            body = ""
        elif len(body) > available:
            body = self.fit_text(body, available)
        return "\n\n".join(part for part in (body, suffix) if part)

    @staticmethod
    def fit_text(value, limit):
        if len(value) <= limit:
            return value
        if limit <= 3:
            return value[:limit]
        fragment = value[: limit - 3].rstrip()
        word_end = fragment.rfind(" ")
        if word_end >= max(1, (limit - 3) // 2):
            fragment = fragment[:word_end].rstrip()
        return f"{fragment}..."

    def __init__(
        self,
        consumer_key=None,
        consumer_secret=None,
        access_token=None,
        access_token_secret=None,
        bearer_token=None,
        username=None,
        dry_run=None,
    ):
        self.consumer_key = consumer_key or os.getenv("X_CONSUMER_KEY", "")
        self.consumer_secret = consumer_secret or os.getenv("X_SECRET_KEY", "")
        self.access_token = access_token or os.getenv("X_ACCESS_TOKEN", "")
        self.access_token_secret = access_token_secret or os.getenv("X_ACCESS_TOKEN_SECRET", "")
        self.bearer_token = bearer_token or os.getenv("X_BEARER_TOKEN", "")
        self.username = username or os.getenv("X_USERNAME", "")
        if dry_run is None:
            dry_run = os.getenv("X_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run

    def validate(self, post_draft):
        result = super().validate(post_draft)
        if not result.success:
            return result
        text = self.prepare(post_draft)
        if len(text) > self.max_text_length:
            return PublishResult(
                success=False,
                status="failed",
                error_message=(
                    f"X post is {len(text)} characters; the configured limit is "
                    f"{self.max_text_length}. Use the platform-specific X draft."
                ),
            )
        media_paths = self.supported_media(post_draft)
        if not media_paths:
            return PublishResult(
                success=False,
                status="failed",
                error_message="X requires at least one readable photo or video.",
            )
        if not self.dry_run and not all(
            (self.consumer_key, self.consumer_secret, self.access_token, self.access_token_secret)
        ):
            return PublishResult(
                success=False,
                status="failed",
                error_message=(
                    "X_CONSUMER_KEY, X_SECRET_KEY, X_ACCESS_TOKEN, and "
                    "X_ACCESS_TOKEN_SECRET are required when X_DRY_RUN=false."
                ),
            )
        return PublishResult(success=True, status="validated")

    def publish(self, post_draft):
        validation = self.validate(post_draft)
        if not validation.success:
            return validation
        text = self.prepare(post_draft)
        media_paths = self.supported_media(post_draft)
        if self.dry_run:
            post_id = f"dry-run-x-{uuid4()}"
            return PublishResult(
                success=True,
                status="published",
                external_post_id=post_id,
                external_url=f"dry-run://x/{post_id}",
                raw_response={
                    "dry_run": True,
                    "text": text,
                    "media_paths": [str(path) for path, _ in media_paths],
                    "video_policy": "one video or up to four photos",
                },
            )
        try:
            media = []
            media_ids = []
            for media_path, media_type in media_paths:
                uploaded = self.upload_media(media_path, media_type)
                media_id = str((uploaded.get("data") or {}).get("id") or "")
                if not media_id:
                    return self.failed_result("X did not return a media id.", uploaded)
                media.append(uploaded)
                media_ids.append(media_id)
            published = self.request(
                "POST", "/2/tweets", json={"text": text, "media": {"media_ids": media_ids}}
            )
            post_id = str((published.get("data") or {}).get("id") or "")
            if not post_id:
                return self.failed_result("X did not return a post id.", published)
            verification, verification_errors = self.verify_created_post(post_id)
            verified_id = str((verification.get("data") or {}).get("id") or "")
            if verified_id != post_id:
                rollback = self.rollback_unverified_post(post_id)
                return PublishResult(
                    success=False,
                    status="failed",
                    external_post_id=post_id,
                    error_message=(
                        "X returned a post id, but the post could not be retrieved after creation. "
                        "Creator OS attempted to remove the unverified post before allowing a retry."
                    ),
                    raw_response={
                        "media": media,
                        "published": published,
                        "verification": verification,
                        "verification_errors": verification_errors,
                        "rollback": rollback,
                    },
                )
        except (OSError, requests.RequestException, ValueError) as error:
            return self.failed_result(str(error), {})
        username = self.username.strip().lstrip("@")
        url = f"https://x.com/{username}/status/{post_id}" if username else f"https://x.com/i/status/{post_id}"
        return PublishResult(
            success=True,
            status="published",
            external_post_id=post_id,
            external_url=url,
            raw_response={
                "media": media,
                "published": published,
                "verification": verification,
                "verification_errors": verification_errors,
            },
        )

    def verify_created_post(self, post_id):
        """Confirm that a newly-created post is retrievable by its author."""
        errors = []
        for attempt in range(self.post_verification_attempts):
            try:
                payload = self.request(
                    "GET",
                    f"/2/tweets/{post_id}",
                    params={"tweet.fields": "created_at,author_id"},
                )
                if str((payload.get("data") or {}).get("id") or "") == post_id:
                    return payload, errors
                errors.append("X retrieval response did not contain the created post id.")
            except (requests.RequestException, ValueError) as error:
                errors.append(str(error))
            if attempt + 1 < self.post_verification_attempts:
                time.sleep(self.post_verification_delay)
        return {}, errors

    def rollback_unverified_post(self, post_id):
        try:
            return self.request("DELETE", f"/2/tweets/{post_id}")
        except (requests.RequestException, ValueError) as error:
            return {"error": str(error), "deleted": False}

    def upload_media(self, media_path, media_type):
        if not media_type.startswith("video/"):
            return self.request(
                "POST",
                "/2/media/upload",
                json={
                    "media": base64.b64encode(media_path.read_bytes()).decode("ascii"),
                    "media_category": "tweet_image",
                    "media_type": media_type,
                    "shared": False,
                },
            )

        initialized = self.request(
            "POST",
            "/2/media/upload/initialize",
            json={
                "media_type": media_type,
                "total_bytes": media_path.stat().st_size,
                "media_category": "tweet_video",
                "shared": False,
            },
        )
        media_id = str((initialized.get("data") or {}).get("id") or "")
        if not media_id:
            raise ValueError("X did not return a media id when initializing video upload.")

        chunks = []
        with media_path.open("rb") as video:
            segment_index = 0
            while chunk := video.read(4 * 1024 * 1024):
                chunks.append(
                    self.request(
                        "POST",
                        f"/2/media/upload/{media_id}/append",
                        json={
                            "media": base64.b64encode(chunk).decode("ascii"),
                            "segment_index": segment_index,
                        },
                    )
                )
                segment_index += 1

        finalized = self.request(
            "POST",
            f"/2/media/upload/{media_id}/finalize",
        )
        status = finalized
        for _ in range(20):
            processing = (status.get("data") or {}).get("processing_info") or {}
            state = str(processing.get("state") or "succeeded").lower()
            if state == "succeeded":
                break
            if state == "failed":
                detail = processing.get("error") or "X video processing failed."
                raise ValueError(str(detail))
            time.sleep(min(max(float(processing.get("check_after_secs") or 1), 0), 5))
            status = self.request(
                "GET",
                "/2/media/upload",
                params={"media_id": media_id},
            )
        else:
            raise ValueError("X video processing did not finish in time.")

        return {
            "data": {**(finalized.get("data") or {}), "id": media_id},
            "initialized": initialized,
            "chunks": chunks,
            "status": status,
        }

    def unpublish(self, publication):
        if self.dry_run:
            return PublishResult(True, "unpublished", publication.external_post_id,
                                 raw_response={"dry_run": True, "deleted": True})
        try:
            payload = self.request("DELETE", f"/2/tweets/{publication.external_post_id}")
        except (requests.RequestException, ValueError) as error:
            return self.failed_result(str(error), {})
        deleted = bool((payload.get("data") or {}).get("deleted"))
        return PublishResult(deleted, "unpublished" if deleted else "failed",
                             publication.external_post_id,
                             error_message="X did not confirm that the post was deleted." if not deleted else "",
                             raw_response=payload)

    def fetch_post_metrics(self, post_publication):
        if self.dry_run:
            return PostMetrics(
                platform=self.platform,
                external_post_id=post_publication.external_post_id,
                external_url=post_publication.external_url,
                raw_metrics={"dry_run": True},
            )
        payload = self.request(
            "GET",
            f"/2/tweets/{post_publication.external_post_id}",
            params={"tweet.fields": "public_metrics,non_public_metrics,organic_metrics"},
        )
        data = payload.get("data") or {}
        public = data.get("public_metrics") or {}
        private = data.get("non_public_metrics") or data.get("organic_metrics") or {}
        return PostMetrics(
            platform=self.platform,
            external_post_id=post_publication.external_post_id,
            external_url=post_publication.external_url,
            views=int(public.get("impression_count") or private.get("impression_count") or 0),
            likes=int(public.get("like_count") or 0),
            comments=int(public.get("reply_count") or 0),
            shares=int(public.get("retweet_count") or 0) + int(public.get("quote_count") or 0),
            saves=int(public.get("bookmark_count") or 0),
            clicks=int(private.get("url_link_clicks") or 0),
            raw_metrics=payload,
        )

    def request(self, method, path, **kwargs):
        response = requests.request(
            method,
            f"https://api.x.com{path}",
            auth=self.oauth1(),
            timeout=30,
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            nested_errors = payload.get("errors") or []
            nested_detail = "; ".join(
                str(item.get("message") or item.get("detail") or "").strip()
                for item in nested_errors
                if isinstance(item, dict)
                and str(item.get("message") or item.get("detail") or "").strip()
            )
            detail = nested_detail or payload.get("detail") or payload.get("title") or response.reason
            raise ValueError(str(detail))
        return payload

    def verify_identity(self):
        """Return the X user represented by the configured OAuth 1.0a token."""
        return self.request("GET", "/2/users/me", params={"user.fields": "id,name,username"})

    def oauth1(self):
        return OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret,
        )

    def media_path(self, post_draft):
        value = str(getattr(getattr(post_draft, "artifact", None), "media_path", "") or "")
        return Path(value).expanduser() if value else None

    def supported_media(self, post_draft):
        images = []
        videos = []
        items = post_media_items(post_draft)
        for item in items:
            kind = media_kind(item)
            if kind not in {"image", "video"}:
                continue
            path = Path(str(item.get("media_path") or "")).expanduser()
            if path.is_file():
                content_type = str(item.get("media_content_type") or "").lower()
                target = videos if kind == "video" else images
                target.append(
                    (
                        path,
                        content_type
                        if content_type in {
                            "image/jpeg", "image/png", "image/webp", "video/mp4"
                        }
                        else ("video/mp4" if kind == "video" else "image/jpeg"),
                    )
                )
        if items and media_kind(items[0]) == "video" and videos:
            return videos[:1]
        return images[:4] or videos[:1]

    def media_type(self, post_draft):
        value = str(
            getattr(getattr(post_draft, "artifact", None), "media_content_type", "") or ""
        ).lower()
        return value if value in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"

    def failed_result(self, message, payload):
        return PublishResult(
            success=False,
            status="failed",
            error_message=str(message),
            raw_response=payload,
        )
