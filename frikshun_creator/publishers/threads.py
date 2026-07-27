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


class ThreadsAdapter(PublisherAdapter):
    platform = "threads"
    max_text_length = 500

    def __init__(
        self,
        access_token=None,
        oauth=None,
        api_version=None,
        base_url=None,
        media_base_url=None,
        dry_run=None,
        status_attempts=20,
        status_delay=2,
    ):
        self.access_token = access_token or os.getenv("THREADS_ACCESS_TOKEN", "")
        self.oauth = oauth
        self.api_version = api_version or os.getenv("THREADS_API_VERSION", "v1.0")
        self.base_url = (base_url or os.getenv("THREADS_API_BASE_URL", "https://graph.threads.net")).rstrip("/")
        self.media_base_url = (media_base_url or os.getenv("THREADS_MEDIA_BASE_URL", "")).rstrip("/")
        self.status_attempts = status_attempts
        self.status_delay = status_delay
        if dry_run is None:
            dry_run = os.getenv("THREADS_DRY_RUN", "true").lower() != "false"
        self.dry_run = dry_run

    def prepare(self, post_draft):
        prepared = super().prepare(post_draft)
        paragraphs = [paragraph.strip() for paragraph in prepared.split("\n\n") if paragraph.strip()]
        standing_footer_starts = (
            "Learn more about me in the FrikShun archives:",
            "My music is available on all major streaming platforms.",
            "My modeling work funds the reconstruction of my memory:",
        )
        kept = [paragraph for paragraph in paragraphs if not paragraph.startswith(standing_footer_starts)]

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
        footer = ""
        return self.fit_text_with_footer(cleaned, footer, hashtags)

    def validate(self, post_draft):
        base_result = super().validate(post_draft)
        if not base_result.success:
            return base_result
        if not self.dry_run and not self.current_access_token():
            return PublishResult(
                success=False,
                status="failed",
                error_message="THREADS_ACCESS_TOKEN is required when THREADS_DRY_RUN=false.",
            )
        for item in self.media_items(post_draft):
            if media_kind(item) not in {"image", "video"}:
                return PublishResult(False, "failed", error_message="Threads supports photos and videos only.")
            if urlparse(str(item.get("public_media_url") or "")).scheme != "https":
                return PublishResult(
                    success=False,
                    status="failed",
                    error_message="Every Threads attachment requires a public HTTPS URL.",
                )
        return PublishResult(success=True, status="validated")

    def publish(self, post_draft):
        validation = self.validate(post_draft)
        if not validation.success:
            return validation

        text = self.prepare(post_draft)
        media = self.media_items(post_draft)
        media_url = self.media_url(post_draft)
        media_type = "CAROUSEL" if len(media) > 1 else self.media_type(post_draft, media_url)
        if self.dry_run:
            external_post_id = f"dry-run-threads-{uuid4()}"
            return PublishResult(
                success=True,
                status="published",
                external_post_id=external_post_id,
                external_url=f"dry-run://threads/{external_post_id}",
                raw_response={
                    "dry_run": True,
                    "media_type": media_type,
                    "text": text,
                    "media_url": media_url,
                    "media_urls": [item.get("public_media_url") for item in media],
                },
            )

        container = {}
        status = {}
        stage = "create_container"
        try:
            if len(media) > 1:
                container, child_containers = self.create_carousel(text, media)
            else:
                container = self.create_container(text=text, media_url=media_url, media_type=media_type)
                child_containers = []
            creation_id = str(container.get("id") or "")
            if not creation_id:
                return self.failed_result("Threads did not return a creation id.", container)

            if media_type in {"IMAGE", "VIDEO", "CAROUSEL"}:
                stage = "wait_for_container"
                status = self.wait_for_container(
                    creation_id,
                    attempts=max(180, self.status_attempts)
                    if media_type == "CAROUSEL"
                    else None,
                )
                if status.get("status") != "FINISHED":
                    message = status.get("error_message") or status.get("status") or "Threads media processing failed."
                    return self.failed_result(
                        message,
                        {"container": container, "status": status, "media_type": media_type, "stage": stage},
                    )

            stage = "publish_container"
            published = self.publish_container_with_retry(creation_id)
            thread_id = str(published.get("id") or "")
            if not thread_id:
                return self.failed_result("Threads did not return a published post id.", published)
        except (requests.RequestException, ValueError) as error:
            return self.failed_result(
                str(error),
                {"container": container, "status": status, "media_type": media_type, "stage": stage},
            )

        details = {}
        fetch_error = ""
        try:
            details = self.fetch_thread_with_retry(thread_id)
        except (requests.RequestException, ValueError) as error:
            fetch_error = str(error)
        return PublishResult(
            success=True,
            status="published",
            external_post_id=thread_id,
            external_url=str(details.get("permalink") or ""),
            raw_response={
                "container": container,
                "child_containers": child_containers,
                "status": status,
                "published": published,
                "thread": details,
                "thread_fetch_error": fetch_error,
                "media_type": media_type,
            },
        )

    def unpublish(self, publication):
        if self.dry_run:
            return PublishResult(True, "unpublished", publication.external_post_id,
                                 raw_response={"dry_run": True, "deleted": True})
        response = requests.delete(
            f"{self.base_url}/{self.api_version}/{publication.external_post_id}",
            params={"access_token": self.current_access_token()}, timeout=20,
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

    def verify_identity(self):
        return self.graph_get("me", {"fields": "id,username"})

    def create_container(self, text, media_url="", media_type="TEXT", reply_to_id=""):
        payload = {"media_type": media_type, "text": text}
        if reply_to_id:
            payload["reply_to_id"] = reply_to_id
        if media_type == "IMAGE" and media_url:
            payload["image_url"] = media_url
        if media_type == "VIDEO" and media_url:
            payload["video_url"] = media_url
        return self.graph_post("me/threads", payload)

    def create_carousel(self, text, media):
        children = []
        child_containers = []
        for item in media[:20]:
            kind = media_kind(item)
            payload = {
                "media_type": kind.upper(),
                "is_carousel_item": "true",
            }
            payload[f"{kind}_url"] = item["public_media_url"]
            child = self.graph_post("me/threads", payload)
            child_id = str(child.get("id") or "")
            if not child_id:
                raise ValueError("Threads did not return a carousel child id.")
            status = self.wait_for_container(child_id, attempts=max(180, self.status_attempts))
            if status.get("status") != "FINISHED":
                raise ValueError(
                    status.get("error_message")
                    or status.get("status")
                    or "Threads carousel attachment processing failed."
                )
            children.append(child_id)
            child_containers.append({"container": child, "status": status})
        parent = self.graph_post(
            "me/threads",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "text": text,
            },
        )
        return parent, child_containers

    def publish_container(self, creation_id):
        return self.graph_post("me/threads_publish", {"creation_id": creation_id})

    def publish_container_with_retry(self, creation_id, attempts=3):
        last_error = None
        for attempt in range(attempts):
            try:
                return self.publish_container(creation_id)
            except ValueError as error:
                last_error = error
                if "code 24" not in str(error) or attempt + 1 >= attempts:
                    raise
                time.sleep(max(2, self.status_delay))
        raise last_error

    def wait_for_container(self, creation_id, attempts=None):
        attempts = attempts or self.status_attempts
        last_status = {}
        last_error = None
        for attempt in range(attempts):
            try:
                last_status = self.graph_get(creation_id, {"fields": "status,error_message"})
                last_error = None
            except (requests.RequestException, ValueError) as error:
                last_error = error
            else:
                if last_status.get("status") in {"FINISHED", "ERROR", "EXPIRED"}:
                    return last_status
            if attempt + 1 < attempts and self.status_delay:
                time.sleep(self.status_delay)
        if last_error:
            raise last_error
        return last_status

    def fetch_thread(self, thread_id):
        return self.graph_get(thread_id, {"fields": "id,permalink,username,media_type,media_product_type,text,timestamp"})

    def fetch_thread_with_retry(self, thread_id, attempts=3, sleep_seconds=2):
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return self.fetch_thread(thread_id)
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt >= attempts:
                    break
                time.sleep(sleep_seconds)
        if last_error:
            raise last_error
        return {}

    def fetch_post_metrics(self, post_publication):
        if self.dry_run:
            return PostMetrics(
                platform=self.platform,
                external_post_id=post_publication.external_post_id,
                external_url=post_publication.external_url,
                raw_metrics={"dry_run": True},
            )

        try:
            details = self.fetch_thread_with_retry(post_publication.external_post_id)
        except (requests.RequestException, ValueError) as error:
            details = {}
            details_error = str(error)
        else:
            details_error = ""
        try:
            insights_payload = self.graph_get(
                f"{post_publication.external_post_id}/insights",
                {"metric": "views,likes,replies,reposts,quotes"},
            )
            insights = self.parse_insights(insights_payload)
        except (requests.RequestException, ValueError) as error:
            insights_payload = {"error": str(error)}
            insights = {}
        return PostMetrics(
            platform=self.platform,
            external_post_id=post_publication.external_post_id,
            external_url=str(details.get("permalink") or post_publication.external_url),
            views=int(insights.get("views", 0) or 0),
            likes=int(insights.get("likes", 0) or 0),
            comments=int(insights.get("replies", 0) or 0),
            shares=int((insights.get("reposts", 0) or 0) + (insights.get("quotes", 0) or 0)),
            raw_metrics={"thread": details, "thread_error": details_error, "insights": insights_payload},
        )

    def fetch_post_interactions(self, post_publication):
        if self.dry_run:
            return []
        payload = self.graph_get(
            f"{post_publication.external_post_id}/replies",
            {"fields": "id,text,timestamp,username", "reverse": "false"},
        )
        interactions = []
        for item in payload.get("data") or []:
            interactions.append(
                PostInteractionData(
                    platform=self.platform,
                    interaction_type="reply",
                    external_id=str(item.get("id") or ""),
                    external_post_id=post_publication.external_post_id,
                    author_name=str(item.get("username") or ""),
                    author_platform_id=str(item.get("username") or ""),
                    body=str(item.get("text") or ""),
                    received_at=self.parse_threads_time(item.get("timestamp")),
                    raw_payload=item,
                )
            )
        return [interaction for interaction in interactions if interaction.external_id]

    def fetch_account_interactions(self):
        """Fetch replies from every thread on the connected Threads account."""
        if self.dry_run:
            return []
        interactions = []
        identity = self.graph_get("me", {"fields": "id,username"})
        own_username = str(identity.get("username") or "").casefold()
        threads_url = self.graph_url("me/threads")
        params = {
            "fields": "id,text,timestamp,permalink",
            "limit": 100,
            "access_token": self.current_access_token(),
        }
        seen_urls = set()
        while threads_url and threads_url not in seen_urls:
            seen_urls.add(threads_url)
            payload = self.graph_request_url(threads_url, params=params)
            params = None
            for thread in payload.get("data") or []:
                thread_id = str(thread.get("id") or "")
                if not thread_id:
                    continue
                replies_url = self.graph_url(f"{thread_id}/conversation")
                reply_params = {
                    "fields": "id,text,timestamp,username,is_reply_owned_by_me,replied_to{id}",
                    "reverse": "false",
                    "limit": 100,
                    "access_token": self.current_access_token(),
                }
                seen_reply_urls = set()
                conversation_items = []
                while replies_url and replies_url not in seen_reply_urls:
                    seen_reply_urls.add(replies_url)
                    replies = self.graph_request_url(replies_url, params=reply_params)
                    reply_params = None
                    conversation_items.extend(replies.get("data") or [])
                    replies_url = (replies.get("paging") or {}).get("next")
                owned_parent_ids = {
                    str((item.get("replied_to") or {}).get("id") or "")
                    for item in conversation_items
                    if item.get("is_reply_owned_by_me") is True
                    or (own_username and str(item.get("username") or "").casefold() == own_username)
                }
                for item in conversation_items:
                    reply_id = str(item.get("id") or "")
                    if not reply_id:
                        continue
                    raw_payload = dict(item)
                    username = str(item.get("username") or "")
                    owned_by_me = bool(
                        reply_id == thread_id
                        or item.get("is_reply_owned_by_me") is True
                        or (own_username and username.casefold() == own_username)
                    )
                    raw_payload.update({
                        "source_post_message": str(thread.get("text") or ""),
                        "source_post_permalink": str(thread.get("permalink") or ""),
                        "source_post_created_time": str(thread.get("timestamp") or ""),
                        "is_owned_by_me": owned_by_me,
                        "already_replied_by_us": reply_id in owned_parent_ids,
                    })
                    interactions.append(PostInteractionData(
                        platform=self.platform,
                        interaction_type="reply",
                        external_id=reply_id,
                        external_post_id=thread_id,
                        author_name=username,
                        author_platform_id=username,
                        body=str(item.get("text") or ""),
                        received_at=self.parse_threads_time(item.get("timestamp")),
                        raw_payload=raw_payload,
                    ))
            threads_url = (payload.get("paging") or {}).get("next")
        return interactions

    def reply_to_reply(self, reply_id, message):
        reply_id = str(reply_id or "").strip()
        message = str(message or "").strip()
        if not reply_id or not message:
            raise ValueError("Threads reply id and reply message are required.")
        if self.dry_run:
            return {"id": f"dry-run-threads-reply-{reply_id}"}
        container = self.create_container(text=message, media_type="TEXT", reply_to_id=reply_id)
        creation_id = str(container.get("id") or "")
        if not creation_id:
            raise ValueError("Threads did not return a reply creation id.")
        return self.publish_container(creation_id)

    def graph_request_url(self, url, params=None):
        response = requests.get(url, params=params, timeout=30)
        return self.response_payload(response)

    def parse_insights(self, payload):
        parsed = {}
        for item in payload.get("data") or []:
            values = item.get("values") or []
            value = values[0].get("value") if values else 0
            parsed[str(item.get("name") or "")] = value
        return parsed

    def graph_post(self, path, data):
        response = requests.post(
            self.graph_url(path),
            data={**data, "access_token": self.current_access_token()},
            timeout=30,
        )
        return self.response_payload(response)

    def graph_get(self, path, params=None):
        response = requests.get(
            self.graph_url(path),
            params={**(params or {}), "access_token": self.current_access_token()},
            timeout=20,
        )
        return self.response_payload(response)

    def response_payload(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            error = payload.get("error") or {}
            details = str((error.get("error_data") or {}).get("details") or "").strip()
            message = str(
                error.get("error_user_msg")
                or error.get("message")
                or payload.get("error_description")
                or payload.get("raw_body")
                or response.reason
                or "Threads API request failed."
            ).strip()
            if details and details.lower() not in message.lower():
                message = f"{message}: {details}"
            code = error.get("code")
            subcode = error.get("error_subcode")
            identifiers = ", ".join(
                part for part in (f"code {code}" if code else "", f"subcode {subcode}" if subcode else "") if part
            )
            if identifiers:
                message = f"{message} ({identifiers})"
            raise ValueError(message)
        return payload

    def graph_url(self, path):
        return f"{self.base_url}/{self.api_version}/{path.lstrip('/')}"

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
        return items[:20]

    def media_type(self, post_draft, media_url):
        content_type = str(
            getattr(getattr(post_draft, "artifact", None), "media_content_type", "") or ""
        ).lower()
        if media_url and content_type.startswith("video/"):
            return "VIDEO"
        if media_url:
            return "IMAGE"
        return "TEXT"

    def failed_result(self, message, payload=None):
        return PublishResult(
            success=False,
            status="failed",
            error_message=message,
            raw_response=payload or {},
        )

    def parse_threads_time(self, value):
        if not value:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def current_access_token(self):
        if self.oauth:
            try:
                return self.oauth.access_token()
            except ValueError:
                pass
        if self.access_token:
            return self.access_token
        return ""

    def fit_text_with_footer(self, paragraphs, footer, hashtags):
        hashtag_text = " ".join(tag for tag in hashtags if tag).strip()
        body_candidates = []
        normalized = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
        if normalized:
            body_candidates.append("\n\n".join(normalized))
            if len(normalized) > 1:
                body_candidates.append("\n\n".join(normalized[:2]))
            body_candidates.extend(normalized)

        for candidate in body_candidates:
            composed = self.join_parts(candidate, footer, hashtag_text)
            if len(composed) <= self.max_text_length and composed.count("?") == 1:
                return composed

        body = body_candidates[0] if body_candidates else ""
        reserved = len(self.join_parts("", footer, hashtag_text))
        limit = max(80, self.max_text_length - reserved - 2)
        trimmed = self.truncate_preserving_question(body, limit)
        return self.join_parts(trimmed, footer, hashtag_text)

    def join_parts(self, body, footer, hashtag_text):
        return "\n\n".join(part for part in (body.strip(), footer.strip(), hashtag_text.strip()) if part).strip()

    def truncate_preserving_question(self, text, limit):
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= limit:
            return value
        question_index = value.rfind("?")
        if question_index != -1:
            start = max(0, question_index - limit + 1)
            snippet = value[start:question_index + 1].strip()
            if start > 0:
                first_space = snippet.find(" ")
                if first_space != -1:
                    snippet = snippet[first_space + 1:].strip()
            if len(snippet) <= limit and snippet.endswith("?"):
                return snippet
        truncated = value[:limit].rstrip()
        last_space = truncated.rfind(" ")
        if last_space > 40:
            truncated = truncated[:last_space].rstrip()
        if truncated and truncated[-1] not in ".!?":
            truncated = f"{truncated}."
        if "?" not in truncated:
            fallback = "Which version still feels true?"
            available = max(0, limit - len(fallback) - 1)
            prefix = truncated[:available].rstrip()
            if prefix and prefix[-1] not in ".!":
                prefix = f"{prefix[:max(0, available - 1)].rstrip()}."
            truncated = f"{prefix} {fallback}".strip()
        return truncated[:limit]
