from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PublishResult:
    success: bool
    status: str
    external_post_id: str = ""
    external_url: str = ""
    error_message: str = ""
    raw_response: dict = field(default_factory=dict)


@dataclass
class PostMetrics:
    platform: str
    external_post_id: str
    external_url: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    clicks: int = 0
    reach: int = 0
    raw_metrics: dict = field(default_factory=dict)


@dataclass
class PostInteractionData:
    platform: str
    interaction_type: str
    external_id: str
    external_post_id: str
    author_name: str = ""
    author_platform_id: str = ""
    body: str = ""
    received_at: Optional[datetime] = None
    raw_payload: dict = field(default_factory=dict)


@dataclass
class RemoteContentData:
    external_content_id: str
    content_type: str = "post"
    title: str = ""
    body: str = ""
    permalink: str = ""
    thumbnail_url: str = ""
    published_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ContentDiscoveryPage:
    items: list[RemoteContentData] = field(default_factory=list)
    next_cursor: str = ""


@dataclass
class AccountMetricsData:
    followers: int = 0
    following: int = 0
    content_count: int = 0
    views: int = 0
    reach: int = 0
    engagements: int = 0
    profile_views: int = 0
    metrics: dict = field(default_factory=dict)


class PublisherAdapter:
    platform = "base"

    def validate(self, post_draft):
        if not post_draft.caption.strip():
            return PublishResult(
                success=False,
                status="failed",
                error_message="Draft caption cannot be blank.",
            )
        return PublishResult(success=True, status="validated")

    def prepare(self, post_draft):
        hashtag_text = " ".join(f"#{tag.lstrip('#')}" for tag in post_draft.hashtags)
        parts = [post_draft.caption.strip()]

        if post_draft.call_to_action:
            parts.append(post_draft.call_to_action.strip())
        if hashtag_text:
            parts.append(hashtag_text)

        return "\n\n".join(parts)

    def publish(self, post_draft):
        raise NotImplementedError

    def fetch_post_metrics(self, post_publication):
        raise NotImplementedError

    def fetch_post_interactions(self, post_publication):
        return []

    def discover_account_content(self, cursor="", limit=100):
        raise NotImplementedError

    def fetch_account_metrics(self):
        raise NotImplementedError

    def fetch_remote_content_metrics(self, remote_content):
        raise NotImplementedError
