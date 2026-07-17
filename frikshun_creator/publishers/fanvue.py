import math
import os
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests

from .base import PostInteractionData, PostMetrics, PublishResult, PublisherAdapter
from ..services.fanvue_oauth import FanvueOAuth


class FanvueAdapter(PublisherAdapter):
    platform = "fanvue"

    def __init__(self, oauth=None, api_version=None, audience=None, dry_run=None,
                 status_attempts=20, status_delay=2):
        self.oauth = oauth or FanvueOAuth()
        self.api_version = api_version or os.getenv("FANVUE_API_VERSION", "2025-06-26")
        self.audience = audience or os.getenv("FANVUE_AUDIENCE", "followers-and-subscribers")
        if dry_run is None:
            dry_run = os.getenv("FANVUE_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run
        self.status_attempts = status_attempts
        self.status_delay = status_delay

    def validate(self, post_draft):
        result = super().validate(post_draft)
        if not result.success:
            return result
        path = self.media_path(post_draft)
        if not path or not path.is_file():
            return PublishResult(False, "failed", error_message="FanVue publishing requires a readable local image artifact.")
        if self.audience not in {"subscribers", "followers-and-subscribers"}:
            return PublishResult(False, "failed", error_message="FANVUE_AUDIENCE is invalid.")
        if not self.dry_run:
            try:
                self.oauth.access_token()
            except ValueError as error:
                return PublishResult(False, "failed", error_message=str(error))
        return PublishResult(True, "validated")

    def publish(self, post_draft):
        validation = self.validate(post_draft)
        if not validation.success:
            return validation
        text = self.prepare(post_draft)
        path = self.media_path(post_draft)
        if self.dry_run:
            post_id = f"dry-run-fanvue-{uuid4()}"
            return PublishResult(True, "published", post_id, f"dry-run://fanvue/{post_id}",
                                 raw_response={"dry_run": True, "text": text, "media_path": str(path), "audience": self.audience})
        try:
            upload = self.api("POST", "/media/uploads", json={
                "name": path.stem[:255], "filename": path.name[:255],
                "mediaType": "image", "sizeBytes": path.stat().st_size,
            })
            media_uuid = str(upload.get("mediaUuid") or "")
            upload_id = str(upload.get("uploadId") or "")
            part_size = int(upload.get("partSize") or path.stat().st_size)
            parts = self.upload_parts(path, upload_id, part_size)
            completed = self.api("PATCH", f"/media/uploads/{upload_id}", json={"parts": parts})
            media = self.wait_for_media(media_uuid)
            if media.get("status") != "ready":
                return self.failed_result(f"FanVue media processing ended with status {media.get('status') or 'unknown'}.", {"upload": upload, "completed": completed, "media": media})
            post = self.api("POST", "/posts", json={
                "text": text, "mediaUuids": [media_uuid], "audience": self.audience,
            })
            post_id = str(post.get("uuid") or "")
            if not post_id:
                return self.failed_result("FanVue did not return a post UUID.", post)
        except (OSError, requests.RequestException, ValueError) as error:
            return self.failed_result(str(error), {})
        return PublishResult(True, "published", post_id,
                             f"https://www.fanvue.com/chloekat/post/{post_id}",
                             raw_response={"upload": upload, "completed": completed, "media": media, "post": post})

    def upload_parts(self, path, upload_id, part_size):
        parts = []
        total = int(math.ceil(path.stat().st_size / float(part_size)))
        with path.open("rb") as source:
            for part_number in range(1, total + 1):
                signed_url = self.api("GET", f"/media/uploads/{upload_id}/parts/{part_number}/url", raw=True)
                response = requests.put(signed_url, data=source.read(part_size), timeout=60)
                if not response.ok:
                    raise ValueError(f"FanVue media part {part_number} upload failed: {response.reason}")
                parts.append({"ETag": response.headers.get("ETag", "").strip('"'), "PartNumber": part_number})
        return parts

    def wait_for_media(self, media_uuid):
        last = {}
        for attempt in range(self.status_attempts):
            last = self.api("GET", f"/media/{media_uuid}")
            if last.get("status") in {"ready", "error"}:
                return last
            if attempt + 1 < self.status_attempts and self.status_delay:
                time.sleep(self.status_delay)
        return last

    def fetch_post_metrics(self, publication):
        post = self.api("GET", f"/posts/{publication.external_post_id}")
        return PostMetrics(platform=self.platform, external_post_id=publication.external_post_id,
                           external_url=publication.external_url,
                           likes=int(post.get("likesCount") or 0),
                           comments=int(post.get("commentsCount") or 0),
                           raw_metrics=post)

    def fetch_post_interactions(self, publication):
        payload = self.api("GET", f"/posts/{publication.external_post_id}/comments", params={"page": 1, "size": 50})
        interactions = []
        for comment in payload.get("data") or []:
            user = comment.get("user") or {}
            interactions.append(PostInteractionData(
                platform=self.platform, interaction_type="comment",
                external_id=str(comment.get("uuid") or ""),
                external_post_id=publication.external_post_id,
                author_name=str(user.get("displayName") or user.get("handle") or ""),
                author_platform_id=str(user.get("uuid") or ""), body=str(comment.get("text") or ""),
                received_at=self.parse_time(comment.get("createdAt")), raw_payload=comment,
            ))
        return interactions

    def api(self, method, path, raw=False, **kwargs):
        response = requests.request(method, f"https://api.fanvue.com{path}",
                                    headers={"Authorization": f"Bearer {self.oauth.access_token()}",
                                             "X-Fanvue-API-Version": self.api_version},
                                    timeout=30, **kwargs)
        if raw:
            if not response.ok:
                raise ValueError(response.text or response.reason)
            return response.text.strip()
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = payload.get("message") or payload.get("error") or "; ".join(payload.get("errors") or []) or response.reason
            raise ValueError(str(message))
        return payload

    def media_path(self, draft):
        artifact = getattr(draft, "artifact", None)
        metadata = getattr(artifact, "generated_metadata", None) or {}
        value = str(metadata.get("fanvue_media_path") or getattr(artifact, "media_path", "") or "")
        return Path(value).expanduser() if value else None

    def parse_time(self, value):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
        except ValueError:
            return None

    def failed_result(self, message, payload):
        return PublishResult(False, "failed", error_message=str(message), raw_response=payload)
