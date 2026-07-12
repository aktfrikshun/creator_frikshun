from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
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
