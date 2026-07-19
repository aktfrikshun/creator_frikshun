from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Artifact(Base):
    __tablename__ = "creator_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(80), default="image")
    summary: Mapped[str] = mapped_column(Text, default="")
    lore_text: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    fragment_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    canonical_status: Mapped[str] = mapped_column(String(80), default="draft")
    source_notes: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(500), default="")
    media_path: Mapped[str] = mapped_column(String(1000), default="")
    media_content_type: Mapped[str] = mapped_column(String(160), default="")
    media_size: Mapped[int] = mapped_column(Integer, default=0)
    generated_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    usable_in_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    mood_tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    content_tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    platform_tags: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    post_drafts: Mapped[List["PostDraft"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class Release(Base):
    __tablename__ = "creator_releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    release_type: Mapped[str] = mapped_column(String(80), default="single")
    distro_status: Mapped[str] = mapped_column(String(80), default="draft")
    distro_url: Mapped[str] = mapped_column(String(500), default="")
    spotify_url: Mapped[str] = mapped_column(String(500), default="")
    apple_music_url: Mapped[str] = mapped_column(String(500), default="")
    youtube_music_url: Mapped[str] = mapped_column(String(500), default="")
    amazon_music_url: Mapped[str] = mapped_column(String(500), default="")


class PlatformAccount(Base):
    __tablename__ = "creator_platform_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    handle: Mapped[str] = mapped_column(String(160), default="")
    profile_url: Mapped[str] = mapped_column(String(500), default="")
    oauth_status: Mapped[str] = mapped_column(String(80), default="manual")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    external_account_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    analytics_status: Mapped[Optional[str]] = mapped_column(String(80), default="not_connected")
    publishing_mode: Mapped[Optional[str]] = mapped_column(String(80), default="manual")
    capabilities: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    account_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    remote_content: Mapped[List["RemoteContent"]] = relationship(
        back_populates="platform_account", cascade="all, delete-orphan"
    )
    metric_snapshots: Mapped[List["AccountMetricSnapshot"]] = relationship(
        back_populates="platform_account", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[List["AnalyticsSyncRun"]] = relationship(
        back_populates="platform_account", cascade="all, delete-orphan"
    )


class RemoteContent(Base):
    __tablename__ = "creator_remote_content"
    __table_args__ = (
        UniqueConstraint("platform_account_id", "external_content_id", name="uq_remote_content"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("creator_platform_accounts.id"), nullable=False
    )
    post_publication_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("creator_post_publications.id"), nullable=True, unique=True
    )
    external_content_id: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), default="post")
    title: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    permalink: Mapped[str] = mapped_column(String(1000), default="")
    thumbnail_url: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(80), default="available")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    content_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    platform_account: Mapped[PlatformAccount] = relationship(back_populates="remote_content")
    post_publication: Mapped[Optional["PostPublication"]] = relationship()
    metric_snapshots: Mapped[List["ContentMetricSnapshot"]] = relationship(
        back_populates="remote_content", cascade="all, delete-orphan"
    )


class AccountMetricSnapshot(Base):
    __tablename__ = "creator_account_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("creator_platform_accounts.id"), nullable=False
    )
    followers: Mapped[int] = mapped_column(Integer, default=0)
    following: Mapped[int] = mapped_column(Integer, default=0)
    content_count: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    engagements: Mapped[int] = mapped_column(Integer, default=0)
    profile_views: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    platform_account: Mapped[PlatformAccount] = relationship(back_populates="metric_snapshots")


class ContentMetricSnapshot(Base):
    __tablename__ = "creator_content_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remote_content_id: Mapped[int] = mapped_column(
        ForeignKey("creator_remote_content.id"), nullable=False
    )
    views: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    watch_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    average_view_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    remote_content: Mapped[RemoteContent] = relationship(back_populates="metric_snapshots")


class AnalyticsSyncRun(Base):
    __tablename__ = "creator_analytics_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("creator_platform_accounts.id"), nullable=False
    )
    sync_type: Mapped[str] = mapped_column(String(80), default="daily")
    status: Mapped[str] = mapped_column(String(80), default="running")
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    cursor: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    platform_account: Mapped[PlatformAccount] = relationship(back_populates="sync_runs")


class PostDraft(Base):
    __tablename__ = "creator_post_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("creator_artifacts.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[List[str]] = mapped_column(JSON, default=list)
    call_to_action: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(80), default="draft")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    artifact: Mapped[Artifact] = relationship(back_populates="post_drafts")
    publications: Mapped[List["PostPublication"]] = relationship(
        back_populates="post_draft", cascade="all, delete-orphan"
    )


class PostPublication(Base):
    __tablename__ = "creator_post_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_draft_id: Mapped[int] = mapped_column(ForeignKey("creator_post_drafts.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(240), default="")
    external_url: Mapped[str] = mapped_column(String(500), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    post_draft: Mapped[PostDraft] = relationship(back_populates="publications")
    metric_snapshots: Mapped[List["PostMetricSnapshot"]] = relationship(
        back_populates="post_publication", cascade="all, delete-orphan"
    )
    interactions: Mapped[List["PostInteraction"]] = relationship(
        back_populates="post_publication", cascade="all, delete-orphan"
    )


class PostMetricSnapshot(Base):
    __tablename__ = "creator_post_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_publication_id: Mapped[int] = mapped_column(
        ForeignKey("creator_post_publications.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(240), default="")
    external_url: Mapped[str] = mapped_column(String(500), default="")
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    raw_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    post_publication: Mapped[PostPublication] = relationship(back_populates="metric_snapshots")


class MetricsPollRun(Base):
    __tablename__ = "creator_metrics_poll_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), default="scheduler")
    status: Mapped[str] = mapped_column(String(80), default="running")
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0)
    interactions_created: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PostInteraction(Base):
    __tablename__ = "creator_post_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_publication_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("creator_post_publications.id"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(80), default="comment")
    external_id: Mapped[str] = mapped_column(String(240), default="")
    external_post_id: Mapped[str] = mapped_column(String(240), default="")
    author_name: Mapped[str] = mapped_column(String(240), default="")
    author_platform_id: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="new")
    reply_status: Mapped[str] = mapped_column(String(80), default="pending_review")
    suggested_reply: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    post_publication: Mapped[Optional[PostPublication]] = relationship(back_populates="interactions")


class Campaign(Base):
    __tablename__ = "creator_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    campaign_type: Mapped[str] = mapped_column(String(80), default="general_weekly_content")
    status: Mapped[str] = mapped_column(String(80), default="draft")
    theme: Mapped[str] = mapped_column(String(240), default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class CanonEntry(Base):
    __tablename__ = "creator_canon_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    source_path: Mapped[str] = mapped_column(String(1000), default="")
    source_hash: Mapped[str] = mapped_column(String(80), default="")
    source_mtime: Mapped[str] = mapped_column(String(80), default="")
    canon_category: Mapped[str] = mapped_column(String(120), default="")
    canonical_status: Mapped[str] = mapped_column(String(80), default="approved")
    usable_in_generation: Mapped[bool] = mapped_column(Boolean, default=True)
    usable_in_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Fan(Base):
    __tablename__ = "creator_fans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(240), default="")
    display_name: Mapped[str] = mapped_column(String(160), default="")


class FanEvent(Base):
    __tablename__ = "creator_fan_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(160), default="")
    platform: Mapped[str] = mapped_column(String(80), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Transmission(Base):
    __tablename__ = "creator_transmissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="draft")


class ChloeChatConversation(Base):
    __tablename__ = "creator_chloe_chat_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChloeChatMessage(Base):
    __tablename__ = "creator_chloe_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("creator_chloe_chat_conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
