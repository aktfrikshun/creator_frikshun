import base64
import os
import re
from pathlib import Path
from uuid import uuid4

import requests
from requests_oauthlib import OAuth1

from .base import PostMetrics, PublishResult, PublisherAdapter


class XAdapter(PublisherAdapter):
    """Publish an image post and collect engagement metrics through X API v2."""

    platform = "x"
    max_text_length = 280

    def prepare(self, post_draft):
        """Produce compact, link-free X copy with a profile/music direction."""
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
        cleaned.append("Links are in my bio. Search Chloe Katastrophe on major streaming platforms.")
        cleaned.extend(hashtags)
        return "\n\n".join(cleaned)

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
        media_path = self.media_path(post_draft)
        if not media_path or not media_path.is_file():
            return PublishResult(
                success=False,
                status="failed",
                error_message="X image publishing requires a readable local artifact file.",
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
        media_path = self.media_path(post_draft)
        if self.dry_run:
            post_id = f"dry-run-x-{uuid4()}"
            return PublishResult(
                success=True,
                status="published",
                external_post_id=post_id,
                external_url=f"dry-run://x/{post_id}",
                raw_response={"dry_run": True, "text": text, "media_path": str(media_path)},
            )
        try:
            media = self.request(
                "POST",
                "/2/media/upload",
                json={
                    "media": base64.b64encode(media_path.read_bytes()).decode("ascii"),
                    "media_category": "tweet_image",
                    "media_type": self.media_type(post_draft),
                    "shared": False,
                },
            )
            media_id = str((media.get("data") or {}).get("id") or "")
            if not media_id:
                return self.failed_result("X did not return a media id.", media)
            published = self.request(
                "POST", "/2/tweets", json={"text": text, "media": {"media_ids": [media_id]}}
            )
            post_id = str((published.get("data") or {}).get("id") or "")
            if not post_id:
                return self.failed_result("X did not return a post id.", published)
        except (OSError, requests.RequestException, ValueError) as error:
            return self.failed_result(str(error), {})
        username = self.username.strip().lstrip("@")
        url = f"https://x.com/{username}/status/{post_id}" if username else f"https://x.com/i/status/{post_id}"
        return PublishResult(
            success=True,
            status="published",
            external_post_id=post_id,
            external_url=url,
            raw_response={"media": media, "published": published},
        )

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
            detail = payload.get("detail") or payload.get("title") or response.reason
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
