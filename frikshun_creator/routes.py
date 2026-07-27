from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from threading import Thread
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import requests

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session as flask_session, url_for
from werkzeug.utils import secure_filename
from sqlalchemy import String, cast, or_

from .db import get_session
from .models import (
    ContentMetricSnapshot,
    EngagementSenderPolicy,
    Artifact,
    CanonEntry,
    MetricsPollRun,
    PlatformAccount,
    PostDraft,
    PostInteraction,
    PostMetricSnapshot,
    PostPublication,
    RemoteContent,
)
from .publishers import FacebookAdapter, InstagramAdapter, ThreadsAdapter, XAdapter, FanvueAdapter
from .services.canon_importer import CanonImporter
from .services.custom_post_curator import CUSTOM_POST_PLATFORMS, CustomPostCurator
from .services.analytics_accounts import synchronize_account_registry
from .services.account_analytics_runner import AccountAnalyticsRunner
from .services.draft_generator import ArtifactDraftGenerator, PLATFORMS
from .services.daily_fragment_generator import DailyFragmentGenerator
from .services.generation_context import load_generation_context
from .services.google_oauth import GoogleOAuth
from .services.fanvue_oauth import FanvueOAuth
from .services.media_analyzer import MediaAnalyzer
from .services.metadata_generator import ArtifactMetadataGenerator
from .services.post_metrics import PostMetricsPoller, latest_snapshot_by_publication
from .services.post_media import artifact_media_items
from .services.post_preview import apply_review_form, platform_summary
from .services.sample_artifact_importer import SampleArtifactImporter
from .services.s3_media_storage import S3MediaStorage
from .services.social_post_importer import SocialPostImporter
from .services.text import split_tags
from .services.threads_oauth import ThreadsOAuth
from .services.tiktok_oauth import TikTokOAuth
from .services.youtube_oauth import YouTubeOAuth
from .services.uploads import archive_media_filename, next_fragment_code, save_artifact_file

bp = Blueprint("creator", __name__)
EASTERN_TIME = ZoneInfo("America/New_York")


def eastern_time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(EASTERN_TIME)

DAILY_POST_FAMILIES = {
    "reconstruction": ("Recovered fragment", "recovered-fragment", "Recovered Fragment"),
    "philosophy": ("Philosophy", "philosophy", "Chloe Thinking"),
    "lifestyle": ("Lifestyle", "lifestyle", "Chloe Living"),
    "music": ("Music", "music", "Studio Note"),
    "travel": ("Travel", "travel", "Field Note"),
    "craft": ("Creator craft", "craft", "Creator Note"),
    "fantasy_art": ("Beautiful fantasy art", "fantasy-art", "Art du Jour"),
}

PUBLIC_ENDPOINTS = {
    "creator.terms",
    "creator.privacy",
    "creator.acceptable_use",
    "creator.google_login",
    "creator.google_callback",
    "creator.google_logout",
    "creator.youtube_oauth_callback",
    "creator.tiktok_oauth_callback",
    "creator.fanvue_oauth_callback",
    "creator.threads_oauth_callback",
}


def google_oauth():
    return GoogleOAuth(
        client_id=current_app.config.get("GOOGLE_OAUTH_CLIENT_ID"),
        client_secret=current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET"),
        redirect_uri=current_app.config.get("GOOGLE_OAUTH_REDIRECT_URI"),
    )


def allowed_google_emails():
    return {
        email.strip().lower()
        for email in current_app.config.get("GOOGLE_ALLOWED_EMAILS", "").split(",")
        if email.strip()
    }


def safe_next_url(value):
    value = (value or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


@bp.before_request
def require_creator_login():
    if not current_app.config.get("CREATOR_AUTH_REQUIRED"):
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    user = flask_session.get("creator_user") or {}
    if user.get("email", "").lower() in allowed_google_emails():
        return None
    destination = request.full_path.rstrip("?") if request.method == "GET" else "/"
    return redirect(url_for("creator.google_login", next=destination), code=303)


@bp.get("/auth/google/login")
def google_login():
    destination = safe_next_url(request.args.get("next"))
    try:
        authorization_url, state = google_oauth().begin()
    except ValueError as error:
        return render_template("auth_unavailable.html", error=str(error)), 503
    flask_session["google_oauth_state"] = state
    flask_session["google_oauth_next"] = destination
    return redirect(authorization_url)


@bp.get("/auth/google/callback")
def google_callback():
    if request.args.get("error"):
        return render_template("auth_unavailable.html", error="Google authorization was cancelled or denied."), 403
    state = request.args.get("state", "")
    expected_state = flask_session.pop("google_oauth_state", "")
    if not state or not secrets_compare(state, expected_state):
        return render_template("auth_unavailable.html", error="Google authorization returned an invalid state."), 400
    code = request.args.get("code", "")
    if not code:
        return render_template("auth_unavailable.html", error="Google authorization did not return a code."), 400
    try:
        user = google_oauth().exchange(code)
    except (requests.RequestException, ValueError) as error:
        current_app.logger.error("Google OAuth failed: %s", error)
        return render_template("auth_unavailable.html", error="Google sign-in could not be completed."), 400
    email = user["email"].lower()
    if email not in allowed_google_emails():
        flask_session.clear()
        return render_template("auth_unavailable.html", error=f"{email} is not authorized for Creator OS."), 403
    destination = safe_next_url(flask_session.pop("google_oauth_next", "/"))
    flask_session["creator_user"] = {
        "email": email,
        "name": user.get("name") or email,
        "picture": user.get("picture") or "",
    }
    flask_session.permanent = True
    return redirect(destination)


@bp.get("/auth/logout")
def google_logout():
    flask_session.clear()
    return redirect(url_for("creator.google_login"))


@bp.get("/terms")
def terms():
    return render_template("legal/terms.html")


@bp.get("/privacy")
def privacy():
    return render_template("legal/privacy.html")


@bp.get("/acceptable-use")
def acceptable_use():
    return render_template("legal/acceptable_use.html")


def daily_post_family(artifact):
    tags = set(artifact.content_tags or [])
    title = str(artifact.title or "")
    for key, (label, tag, prefix) in DAILY_POST_FAMILIES.items():
        if tag in tags or title.startswith(prefix):
            return {"key": key, "label": label}
    return None


def fanvue_oauth():
    return FanvueOAuth(
        client_id=current_app.config.get("FANVUE_CLIENT_ID"),
        client_secret=current_app.config.get("FANVUE_CLIENT_SECRET"),
        redirect_uri=current_app.config.get("FANVUE_REDIRECT_URI"),
        token_path=current_app.config.get("FANVUE_TOKEN_PATH"),
    )


def fanvue_adapter():
    return FanvueAdapter(
        oauth=fanvue_oauth(),
        api_version=current_app.config.get("FANVUE_API_VERSION"),
        audience=current_app.config.get("FANVUE_AUDIENCE"),
        dry_run=current_app.config.get("FANVUE_DRY_RUN"),
    )


def threads_oauth():
    return ThreadsOAuth(
        app_id=current_app.config.get("THREADS_APP_ID"),
        app_secret=current_app.config.get("THREADS_APP_SECRET"),
        redirect_uri=current_app.config.get("THREADS_REDIRECT_URI"),
        token_path=current_app.config.get("THREADS_TOKEN_PATH"),
        auth_url=current_app.config.get("THREADS_AUTH_URL"),
        api_base_url=current_app.config.get("THREADS_API_BASE_URL"),
    )


def tiktok_oauth():
    return TikTokOAuth(
        client_key=current_app.config.get("TIKTOK_CLIENT_KEY"),
        client_secret=current_app.config.get("TIKTOK_CLIENT_SECRET"),
        redirect_uri=current_app.config.get("TIKTOK_REDIRECT_URI"),
        token_path=current_app.config.get("TIKTOK_TOKEN_PATH"),
    )


def youtube_oauth():
    return YouTubeOAuth(
        client_id=current_app.config.get("YOUTUBE_CLIENT_ID"),
        client_secret=current_app.config.get("YOUTUBE_CLIENT_SECRET"),
        redirect_uri=current_app.config.get("YOUTUBE_REDIRECT_URI"),
        token_path=current_app.config.get("YOUTUBE_TOKEN_PATH"),
    )


@bp.get("/oauth/youtube/start")
def youtube_oauth_start():
    try:
        authorization_url, state = youtube_oauth().begin()
    except ValueError as error:
        return str(error), 503
    flask_session["youtube_oauth_state"] = state
    return redirect(authorization_url)


@bp.get("/oauth/youtube/callback")
def youtube_oauth_callback():
    if request.args.get("error"):
        return f"YouTube authorization failed: {request.args.get('error_description') or request.args['error']}", 400
    state = request.args.get("state", "")
    expected_state = flask_session.pop("youtube_oauth_state", "")
    if not state or not secrets_compare(state, expected_state):
        return "YouTube authorization failed: invalid OAuth state.", 400
    code = request.args.get("code", "")
    if not code:
        return "YouTube authorization failed: missing authorization code.", 400
    try:
        youtube_oauth().exchange(code)
    except (requests.RequestException, ValueError) as error:
        return f"YouTube token exchange failed: {error}", 400
    session = get_session()
    account = session.query(PlatformAccount).filter_by(platform="youtube").one_or_none()
    if account:
        account.oauth_status = "connected"
        account.analytics_status = "connected"
        session.commit()
    return "YouTube authorization succeeded. Channel analytics are connected; you may close this tab."


@bp.get("/oauth/tiktok/start")
def tiktok_oauth_start():
    try:
        authorization_url, state = tiktok_oauth().begin()
    except ValueError as error:
        return str(error), 503
    flask_session["tiktok_oauth_state"] = state
    return redirect(authorization_url)


@bp.get("/oauth/tiktok/callback")
def tiktok_oauth_callback():
    if request.args.get("error"):
        return f"TikTok authorization failed: {request.args.get('error_description') or request.args['error']}", 400
    state = request.args.get("state", "")
    expected_state = flask_session.pop("tiktok_oauth_state", "")
    if not state or not secrets_compare(state, expected_state):
        return "TikTok authorization failed: invalid OAuth state.", 400
    code = request.args.get("code", "")
    if not code:
        return "TikTok authorization failed: missing authorization code.", 400
    try:
        saved = tiktok_oauth().exchange(code)
    except (requests.RequestException, ValueError) as error:
        current_app.logger.error("TikTok token exchange failed: %s", error)
        return f"TikTok token exchange failed: {error}", 400
    session = get_session()
    account = session.query(PlatformAccount).filter_by(platform="tiktok").one_or_none()
    if account:
        account.external_account_id = saved.get("open_id")
        account.oauth_status = "connected"
        account.analytics_status = "connected"
        account.account_metadata = {"scope": saved.get("scope", "")}
        session.commit()
    return "TikTok authorization succeeded. Analytics access is connected; you may close this tab."


@bp.get("/oauth/fanvue/start")
def fanvue_oauth_start():
    try:
        authorization_url, state, verifier = fanvue_oauth().begin()
    except ValueError as error:
        return str(error), 503
    flask_session["fanvue_oauth_state"] = state
    flask_session["fanvue_code_verifier"] = verifier
    return redirect(authorization_url)


@bp.get("/oauth/fanvue/callback")
def fanvue_oauth_callback():
    if request.args.get("error"):
        return f"FanVue authorization failed: {request.args.get('error_description') or request.args['error']}", 400
    state = request.args.get("state", "")
    expected_state = flask_session.pop("fanvue_oauth_state", "")
    verifier = flask_session.pop("fanvue_code_verifier", "")
    if not state or not secrets_compare(state, expected_state):
        return "FanVue authorization failed: invalid OAuth state.", 400
    code = request.args.get("code", "")
    if not code or not verifier:
        return "FanVue authorization failed: missing authorization code or verifier.", 400
    try:
        fanvue_oauth().exchange(code, verifier)
    except (requests.RequestException, ValueError) as error:
        current_app.logger.error("FanVue token exchange failed: %s", error)
        return f"FanVue token exchange failed: {error}", 400
    return "FanVue authorization succeeded. You may close this tab."


@bp.get("/oauth/threads/start")
def threads_oauth_start():
    try:
        authorization_url, state = threads_oauth().begin()
    except ValueError as error:
        return str(error), 503
    flask_session["threads_oauth_state"] = state
    return redirect(authorization_url)


@bp.get("/oauth/threads/callback")
def threads_oauth_callback():
    if request.args.get("error"):
        return f"Threads authorization failed: {request.args.get('error_description') or request.args['error']}", 400
    state = request.args.get("state", "")
    expected_state = flask_session.pop("threads_oauth_state", "") or threads_oauth().pop_state()
    if not state or not secrets_compare(state, expected_state):
        return "Threads authorization failed: invalid OAuth state.", 400
    code = request.args.get("code", "")
    if not code:
        return "Threads authorization failed: missing authorization code.", 400
    try:
        saved = threads_oauth().exchange(code)
    except (requests.RequestException, ValueError) as error:
        current_app.logger.error("Threads token exchange failed: %s", error)
        return f"Threads token exchange failed: {error}", 400
    return (
        "Threads authorization succeeded. "
        f"User {saved.get('user_id') or 'unknown'} is connected and the long-lived token was stored. "
        "You may close this tab."
    )


def secrets_compare(left, right):
    import hmac

    return hmac.compare_digest(str(left), str(right))


def facebook_adapter():
    return FacebookAdapter(
        page_id=current_app.config.get("FACEBOOK_PAGE_ID"),
        access_token=current_app.config.get("FACEBOOK_PAGE_ACCESS_TOKEN"),
        graph_version=current_app.config.get("FACEBOOK_GRAPH_VERSION"),
        dry_run=current_app.config.get("FACEBOOK_DRY_RUN"),
        target_type=current_app.config.get("FACEBOOK_TARGET_TYPE"),
    )


def instagram_adapter():
    return InstagramAdapter(
        user_id=current_app.config.get("INSTAGRAM_USER_ID"),
        access_token=current_app.config.get("INSTAGRAM_ACCESS_TOKEN"),
        graph_version=current_app.config.get("INSTAGRAM_GRAPH_VERSION"),
        media_base_url=current_app.config.get("INSTAGRAM_MEDIA_BASE_URL"),
        dry_run=current_app.config.get("INSTAGRAM_DRY_RUN"),
    )


def refresh_meta_media_url(draft):
    """Store or refresh public S3 media URLs before a Meta publish attempt."""
    artifact = draft.artifact
    metadata = dict((artifact.generated_metadata or {}) or {})
    object_key = str(metadata.get("s3_object_key") or "").strip()
    media_path = Path(str(artifact.media_path or "")).expanduser()
    content_type = str(artifact.media_content_type or "").lower()
    existing_url = str(metadata.get("public_media_url") or "").strip()

    if not object_key and not media_path.is_file():
        return existing_url

    storage = S3MediaStorage(
        bucket=current_app.config.get("S3_MEDIA_BUCKET"),
        region=current_app.config.get("S3_MEDIA_REGION"),
        prefix=current_app.config.get("S3_MEDIA_PREFIX"),
        presign_seconds=current_app.config.get("S3_PRESIGN_SECONDS"),
    )
    needs_image_normalization = content_type.startswith("image/") and not metadata.get(
        "meta_feed_geometry_normalized"
    )
    if object_key and not (needs_image_normalization and media_path.is_file()):
        refreshed_url = storage.refresh_signed_url(object_key)
        if object_key.lower().endswith((".jpg", ".jpeg")):
            metadata["public_media_content_type"] = "image/jpeg"
        elif content_type.startswith("video/"):
            metadata["public_media_content_type"] = content_type
    elif content_type.startswith(("image/", "video/")):
        stored = storage.store_social_media(
            media_path,
            artifact.title,
            content_type,
            local_day=(artifact.created_at or datetime.now(timezone.utc)).date(),
            output_dir=current_app.config.get("UPLOAD_FOLDER"),
        )
        object_key = stored.object_key
        refreshed_url = stored.signed_url
        metadata["s3_bucket"] = current_app.config.get("S3_MEDIA_BUCKET")
        metadata["s3_object_key"] = object_key
        metadata["public_media_content_type"] = stored.content_type
        if stored.content_type == "image/jpeg":
            metadata["meta_feed_geometry_normalized"] = True
    else:
        return existing_url

    metadata["public_media_url"] = refreshed_url
    artifact.generated_metadata = metadata
    return refreshed_url


def refresh_custom_media_urls(draft):
    artifact = draft.artifact
    metadata = dict(artifact.generated_metadata or {})
    additional = [dict(item) for item in metadata.get("additional_media") or []]
    storage = S3MediaStorage(
        bucket=current_app.config.get("S3_MEDIA_BUCKET"),
        region=current_app.config.get("S3_MEDIA_REGION"),
        prefix=current_app.config.get("S3_MEDIA_PREFIX"),
        presign_seconds=current_app.config.get("S3_PRESIGN_SECONDS"),
    )
    items = artifact_media_items(artifact)
    refreshed_items = []
    for index, item in enumerate(items):
        object_key = str(item.get("s3_object_key") or "")
        if object_key:
            item["public_media_url"] = storage.refresh_signed_url(object_key)
        else:
            stored = storage.store_social_media(
                item["media_path"],
                f"{artifact.title}-{index + 1}",
                item.get("media_content_type"),
                local_day=(artifact.created_at or datetime.now(timezone.utc)).date(),
                output_dir=current_app.config.get("UPLOAD_FOLDER"),
            )
            item.update(
                {
                    "media_path": str(stored.local_path.resolve()),
                    "media_content_type": stored.content_type,
                    "s3_object_key": stored.object_key,
                    "public_media_url": stored.signed_url,
                }
            )
        refreshed_items.append(item)

    primary = refreshed_items[0]
    artifact.media_path = primary["media_path"]
    artifact.media_content_type = primary["media_content_type"]
    metadata["s3_object_key"] = primary["s3_object_key"]
    metadata["public_media_url"] = primary["public_media_url"]
    metadata["additional_media"] = [dict(item) for item in refreshed_items[1:]]
    artifact.generated_metadata = metadata
    return refreshed_items


def x_adapter():
    return XAdapter(
        consumer_key=current_app.config.get("X_CONSUMER_KEY"),
        consumer_secret=current_app.config.get("X_SECRET_KEY"),
        access_token=current_app.config.get("X_ACCESS_TOKEN"),
        access_token_secret=current_app.config.get("X_ACCESS_TOKEN_SECRET"),
        bearer_token=current_app.config.get("X_BEARER_TOKEN"),
        username=current_app.config.get("X_USERNAME"),
        dry_run=current_app.config.get("X_DRY_RUN"),
    )


def threads_adapter():
    return ThreadsAdapter(
        access_token=current_app.config.get("THREADS_ACCESS_TOKEN"),
        oauth=threads_oauth(),
        api_version=current_app.config.get("THREADS_API_VERSION"),
        base_url=current_app.config.get("THREADS_API_BASE_URL"),
        media_base_url=current_app.config.get("THREADS_MEDIA_BASE_URL"),
        dry_run=current_app.config.get("THREADS_DRY_RUN"),
    )


@bp.get("/")
def index():
    session = get_session()
    analytics_accounts = ensure_platform_accounts(session)
    search = request.args.get("q", "").strip()
    family = request.args.get("family", "").strip().lower()
    platform = request.args.get("platform", "").strip().lower()
    status = request.args.get("status", "").strip().lower()
    posts_query = (
        session.query(Artifact)
        .filter(Artifact.archived.is_(False))
        .filter(Artifact.post_drafts.any(PostDraft.archived.is_(False)))
    )
    if search:
        pattern = f"%{search}%"
        posts_query = posts_query.filter(
            or_(
                Artifact.title.ilike(pattern),
                Artifact.summary.ilike(pattern),
                Artifact.lore_text.ilike(pattern),
                Artifact.post_drafts.any(PostDraft.caption.ilike(pattern)),
            )
        )
    if family in DAILY_POST_FAMILIES:
        _, family_tag, title_prefix = DAILY_POST_FAMILIES[family]
        posts_query = posts_query.filter(
            or_(
                cast(Artifact.content_tags, String).ilike(f'%"{family_tag}"%'),
                Artifact.title.ilike(f"{title_prefix}%"),
            )
        )
    if platform:
        posts_query = posts_query.filter(
            Artifact.post_drafts.any(
                (PostDraft.platform == platform) & (PostDraft.archived.is_(False))
            )
        )
    if status:
        posts_query = posts_query.filter(
            Artifact.post_drafts.any(
                (PostDraft.status == status) & (PostDraft.archived.is_(False))
            )
        )
    post_count = posts_query.count()
    posts = posts_query.order_by(Artifact.created_at.desc()).limit(60).all()
    for post in posts:
        post.daily_post_family = daily_post_family(post)
        published_platforms = {
            publication.platform
            for draft in post.post_drafts
            for publication in draft.publications
            if publication.status == "published" and publication.external_post_id
        }
        post.auto_publish_complete = {"x", "fanvue"}.issubset(published_platforms)
    canon_count = session.query(CanonEntry).count()
    x_publisher = x_adapter()
    fanvue = fanvue_adapter()
    return render_template(
        "index.html",
        posts=posts,
        post_count=post_count,
        search=search,
        selected_family=family,
        daily_post_families=DAILY_POST_FAMILIES,
        selected_platform=platform,
        selected_status=status,
        platforms=PLATFORMS,
        canon_count=canon_count,
        analytics_accounts=analytics_accounts,
        publishing_status={
            "facebook": "dry run" if current_app.config.get("FACEBOOK_DRY_RUN") else "live",
            "instagram": "dry run" if current_app.config.get("INSTAGRAM_DRY_RUN") else "live",
            "threads": "dry run" if current_app.config.get("THREADS_DRY_RUN") else "live",
            "x": (
                "dry run"
                if x_publisher.dry_run
                else (
                    "live"
                    if all(
                        (
                            x_publisher.consumer_key,
                            x_publisher.consumer_secret,
                            x_publisher.access_token,
                            x_publisher.access_token_secret,
                        )
                    )
                    else "credentials missing"
                )
            ),
            "fanvue": "dry run" if fanvue.dry_run else "live",
        },
    )


@bp.get("/custom-posts/new")
def new_custom_post():
    return render_template("custom_post_new.html")


@bp.post("/custom-posts")
def create_custom_post():
    uploads = [
        upload
        for upload in request.files.getlist("media")
        if upload and upload.filename
    ]
    if not uploads:
        legacy_image = request.files.get("image")
        if legacy_image and legacy_image.filename:
            uploads = [legacy_image]
    source_text = request.form.get("source_text", "").strip()
    invalid = [
        upload.filename
        for upload in uploads
        if not str(upload.mimetype or "").startswith(("image/", "video/"))
    ]
    if not uploads or invalid:
        flash("Choose one or more photo or video files for the post.", "error")
        return render_template(
            "custom_post_new.html",
            source_text=source_text,
            title=request.form.get("title", ""),
            tags=request.form.get("tags", ""),
        ), 400
    if len(uploads) > 10:
        flash("A custom post can contain at most 10 photos and videos.", "error")
        return render_template(
            "custom_post_new.html",
            source_text=source_text,
            title=request.form.get("title", ""),
            tags=request.form.get("tags", ""),
        ), 400
    if not source_text:
        flash("Enter the core text you want Creator OS to curate.", "error")
        return render_template(
            "custom_post_new.html",
            source_text=source_text,
            title=request.form.get("title", ""),
            tags=request.form.get("tags", ""),
        ), 400

    session = get_session()
    saved_media = [
        save_artifact_file(upload, current_app.config["UPLOAD_FOLDER"])
        for upload in uploads
    ]
    upload_info = saved_media[0]
    title = request.form.get("title", "").strip() or custom_post_title(source_text)
    tags = split_tags(request.form.get("tags", ""))
    artifact = Artifact(
        title=title,
        artifact_type="image",
        summary=source_text,
        lore_text="",
        visibility="private",
        canonical_status="draft",
        content_tags=tags,
        mood_tags=[],
        source_notes="Creator-supplied custom social post.",
        generated_metadata={
            "workflow": "custom_post_v1",
            "source_text": source_text,
            "curation": "platform length and hashtag adaptation; creator review required",
            "additional_media": saved_media[1:],
        },
        **upload_info,
    )
    session.add(artifact)
    session.flush()
    for draft_data in CustomPostCurator(source_text, tags).curate():
        session.add(PostDraft(artifact_id=artifact.id, **draft_data))
    session.commit()
    flash("Five platform drafts were curated. Review them before publishing.", "success")
    return redirect(url_for("creator.review_custom_post", artifact_id=artifact.id))


@bp.get("/custom-posts/<int:artifact_id>")
def review_custom_post(artifact_id):
    session = get_session()
    artifact = session.get(Artifact, artifact_id)
    if not artifact or (artifact.generated_metadata or {}).get("workflow") != "custom_post_v1":
        flash("Custom post not found.", "error")
        return redirect(url_for("creator.index"))
    drafts = {
        draft.platform: draft
        for draft in artifact.post_drafts
        if draft.platform in CUSTOM_POST_PLATFORMS and not draft.archived
    }
    return render_template(
        "custom_post_review.html",
        artifact=artifact,
        drafts=drafts,
        platforms=CUSTOM_POST_PLATFORMS,
        media_items=artifact_media_items(artifact),
    )


@bp.get("/custom-posts/<int:artifact_id>/media")
@bp.get("/custom-posts/<int:artifact_id>/media/<int:item_index>")
def custom_post_media(artifact_id, item_index=0):
    artifact = get_session().get(Artifact, artifact_id)
    if not artifact or (artifact.generated_metadata or {}).get("workflow") != "custom_post_v1":
        abort(404)
    items = artifact_media_items(artifact)
    if item_index < 0 or item_index >= len(items):
        abort(404)
    item = items[item_index]
    path = Path(str(item.get("media_path") or ""))
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype=item.get("media_content_type") or "application/octet-stream",
    )


@bp.post("/custom-posts/<int:artifact_id>/save")
def save_custom_post(artifact_id):
    session = get_session()
    artifact = session.get(Artifact, artifact_id)
    if not artifact or (artifact.generated_metadata or {}).get("workflow") != "custom_post_v1":
        flash("Custom post not found.", "error")
        return redirect(url_for("creator.index"))
    update_custom_post_drafts(artifact, request.form)
    session.commit()
    flash("Platform drafts saved.", "success")
    return redirect(url_for("creator.review_custom_post", artifact_id=artifact.id))


@bp.post("/custom-posts/<int:artifact_id>/publish")
def publish_custom_post(artifact_id):
    session = get_session()
    artifact = session.get(Artifact, artifact_id)
    if not artifact or (artifact.generated_metadata or {}).get("workflow") != "custom_post_v1":
        flash("Custom post not found.", "error")
        return redirect(url_for("creator.index"))

    existing_job = dict((artifact.generated_metadata or {}).get("custom_publish_job") or {})
    if existing_job.get("status") in {"queued", "running"}:
        flash("This post already has a publication job in progress.", "error")
        return redirect(url_for("creator.review_custom_post", artifact_id=artifact.id))

    update_custom_post_drafts(artifact, request.form)
    selected = {
        platform
        for platform in request.form.getlist("platforms")
        if platform in CUSTOM_POST_PLATFORMS
    }
    if not selected:
        flash("Choose at least one platform to publish.", "error")
        return redirect(url_for("creator.review_custom_post", artifact_id=artifact.id))

    saved_artifact_id = artifact.id
    start_custom_post_publish_job(artifact, selected)
    flash(
        "Publishing started in the background. Refresh this page for platform progress.",
        "success",
    )
    return redirect(url_for("creator.review_custom_post", artifact_id=saved_artifact_id))


def start_custom_post_publish_job(artifact, selected):
    metadata = dict(artifact.generated_metadata or {})
    existing_job = dict(metadata.get("custom_publish_job") or {})
    if existing_job.get("status") in {"queued", "running"}:
        return False
    metadata["custom_publish_job"] = {
        "status": "queued",
        "platforms": sorted(selected),
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "results": {},
    }
    artifact.generated_metadata = metadata
    get_session().commit()

    app = current_app._get_current_object()
    artifact_id = artifact.id
    if current_app.config.get("CUSTOM_POST_PUBLISH_SYNC"):
        run_custom_post_publish(app, artifact_id, selected)
    else:
        Thread(
            target=run_custom_post_publish,
            args=(app, artifact_id, selected),
            name=f"post-{artifact_id}-publisher",
            daemon=True,
        ).start()
    return True


def flash_individual_publish_status(draft_id, label):
    session = get_session()
    if current_app.config.get("CUSTOM_POST_PUBLISH_SYNC"):
        session.expire_all()
        saved = session.get(PostDraft, draft_id)
        latest = max(saved.publications, key=lambda publication: publication.id, default=None)
        flash(
            f"{label} {saved.status}."
            if saved.status == "published"
            else ((latest.error_message if latest else "") or f"{label} publish failed."),
            "success" if saved.status == "published" else "error",
        )
    else:
        flash(
            f"{label} publishing started in the background. Refresh for status.",
            "success",
        )


def run_custom_post_publish(app, artifact_id, selected):
    with app.app_context():
        session = get_session()
        artifact = session.get(Artifact, artifact_id)
        if not artifact:
            return
        metadata = dict(artifact.generated_metadata or {})
        job = dict(metadata.get("custom_publish_job") or {})
        job.update(
            {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "results": dict(job.get("results") or {}),
            }
        )
        metadata["custom_publish_job"] = job
        artifact.generated_metadata = metadata
        session.commit()

        adapters = {
            "facebook": facebook_adapter,
            "instagram": instagram_adapter,
            "threads": threads_adapter,
            "x": x_adapter,
            "fanvue": fanvue_adapter,
        }
        drafts = {draft.platform: draft for draft in artifact.post_drafts}
        failed = False
        for platform in CUSTOM_POST_PLATFORMS:
            if platform not in selected:
                continue
            draft = drafts.get(platform)
            if draft is None:
                update_custom_publish_progress(
                    artifact,
                    platform,
                    "failed",
                    "Platform draft is missing.",
                )
                session.commit()
                failed = True
                continue
            if any(
                publication.status == "published" and publication.external_post_id
                for publication in draft.publications
            ):
                update_custom_publish_progress(artifact, platform, "skipped", "Already published.")
                session.commit()
                continue
            try:
                if platform in ("instagram", "threads"):
                    if len(artifact_media_items(artifact)) > 1:
                        refresh_custom_media_urls(draft)
                    else:
                        refresh_meta_media_url(draft)
                result = adapters[platform]().publish(draft)
            except Exception as error:
                result = None
                message = f"{type(error).__name__}: {error}"
                draft.status = "failed"
                update_custom_publish_progress(artifact, platform, "failed", message)
                session.commit()
                failed = True
                continue

            draft.status = result.status
            draft.updated_at = datetime.now(timezone.utc)
            if result.success:
                draft.approved_at = datetime.now(timezone.utc)
            else:
                failed = True
            session.add(
                PostPublication(
                    post_draft=draft,
                    platform=platform,
                    status=result.status,
                    external_post_id=result.external_post_id,
                    external_url=result.external_url,
                    error_message=result.error_message,
                    raw_response=result.raw_response,
                )
            )
            update_custom_publish_progress(
                artifact,
                platform,
                result.status,
                result.error_message,
                result.external_url,
            )
            session.commit()

        metadata = dict(artifact.generated_metadata or {})
        job = dict(metadata.get("custom_publish_job") or {})
        job["status"] = "partial" if failed else "completed"
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        metadata["custom_publish_job"] = job
        artifact.generated_metadata = metadata
        session.commit()


def update_custom_publish_progress(artifact, platform, status, message="", external_url=""):
    metadata = dict(artifact.generated_metadata or {})
    job = dict(metadata.get("custom_publish_job") or {})
    results = dict(job.get("results") or {})
    results[platform] = {
        "status": status,
        "message": str(message or ""),
        "external_url": str(external_url or ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    job["results"] = results
    metadata["custom_publish_job"] = job
    artifact.generated_metadata = metadata


def update_custom_post_drafts(artifact, form):
    for draft in artifact.post_drafts:
        if draft.platform not in CUSTOM_POST_PLATFORMS:
            continue
        draft.caption = form.get(f"caption_{draft.platform}", draft.caption).strip()
        draft.hashtags = split_tags(form.get(f"hashtags_{draft.platform}", ""))
        draft.call_to_action = form.get(
            f"call_to_action_{draft.platform}",
            draft.call_to_action,
        ).strip()
        if draft.status != "published":
            draft.status = "draft"
        draft.updated_at = datetime.now(timezone.utc)


def custom_post_title(source_text):
    first_line = next((line.strip() for line in source_text.splitlines() if line.strip()), "")
    first_sentence = first_line.split(".", 1)[0].strip()
    if len(first_sentence) > 80:
        first_sentence = first_sentence[:77].rstrip() + "..."
    return first_sentence or "Custom post"


@bp.post("/daily-fragments/generate")
def generate_daily_fragment():
    family = request.form.get("family", "").strip().lower()
    if family and family not in DAILY_POST_FAMILIES:
        abort(400)
    project_root = Path(current_app.root_path).parent
    log_path = Path(current_app.instance_path) / "daily-fragment-adhoc.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "flask", "--app", "app", "run-daily-fragment-autopilot"]
    if family:
        command.extend(("--family", family))
    with log_path.open("ab") as log_file:
        subprocess.Popen(
            command,
            cwd=project_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    family_label = DAILY_POST_FAMILIES[family][0] if family else "Automatically selected"
    flash(
        f"Today’s {family_label.lower()} post run has started. Refresh the library in a few minutes to see it.",
        "success",
    )
    return redirect(url_for("creator.index"))


@bp.post("/daily-fragments/<int:artifact_id>/publish")
def publish_daily_fragment(artifact_id):
    artifact = daily_fragment_or_404(get_session(), artifact_id)
    metadata = dict((artifact.generated_metadata or {}) or {})
    run_id = str(metadata.get("run_id") or artifact.fragment_code.removeprefix("daily-fragment-run-")).strip()
    if not run_id:
        abort(400)
    project_root = Path(current_app.root_path).parent
    log_path = Path(current_app.instance_path) / "daily-fragment-adhoc.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_file:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "flask",
                "--app",
                "app",
                "publish-daily-fragment-run",
                "--run-id",
                run_id,
            ],
            cwd=project_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    flash(
        "Publishing to all connected platforms has started. Existing successful publications will be skipped.",
        "success",
    )
    return redirect(url_for("creator.index"))


def publishing_adapters():
    return {
        "facebook": facebook_adapter,
        "instagram": instagram_adapter,
        "threads": threads_adapter,
        "x": x_adapter,
        "fanvue": fanvue_adapter,
    }


@bp.post("/daily-fragments/<int:artifact_id>/unpublish")
def unpublish_daily_fragment(artifact_id):
    session = get_session()
    artifact = daily_fragment_or_404(session, artifact_id)
    active = [
        publication
        for draft in artifact.post_drafts
        for publication in draft.publications
        if publication.status == "published" and publication.external_post_id
    ]
    failures = []
    for publication in active:
        factory = publishing_adapters().get(publication.platform)
        if factory is None:
            failures.append(f"{publication.platform}: deletion is not configured")
            continue
        result = factory().unpublish(publication)
        if result.success:
            publication.status = "unpublished"
            publication.raw_response = {
                **dict(publication.raw_response or {}),
                "unpublish": result.raw_response,
                "unpublished_at": datetime.now(timezone.utc).isoformat(),
            }
            publication.post_draft.status = "approved"
            publication.post_draft.updated_at = datetime.now(timezone.utc)
        else:
            failures.append(f"{publication.platform}: {result.error_message or 'delete failed'}")
    session.commit()
    if failures:
        flash("Some live posts could not be removed: " + "; ".join(failures), "error")
    elif active:
        flash("The live platform posts were removed. This Creator OS post is ready to edit and republish.", "success")
    else:
        flash("This post was already unpublished and is ready to edit.", "success")
    return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))


@bp.post(
    "/daily-fragments/<int:artifact_id>/publications/<int:publication_id>/confirm-unpublished"
)
def confirm_publication_unpublished(artifact_id, publication_id):
    """Reconcile a platform post that the user has already removed manually."""
    session = get_session()
    artifact = daily_fragment_or_404(session, artifact_id)
    publication = session.get(PostPublication, publication_id)
    if publication is None or publication.post_draft.artifact_id != artifact.id:
        abort(404)

    if publication.status == "published" and publication.external_post_id:
        now = datetime.now(timezone.utc)
        publication.status = "unpublished"
        publication.error_message = ""
        publication.raw_response = {
            **dict(publication.raw_response or {}),
            "manual_unpublish": {
                "confirmed_at": now.isoformat(),
                "reason": "User confirmed the platform post was deleted manually.",
            },
            "unpublished_at": now.isoformat(),
        }
        publication.post_draft.status = "approved"
        publication.post_draft.updated_at = now
        session.commit()
        flash(
            f"{publication.platform.title()} was recorded as manually deleted. "
            "Creator can now edit and republish once no other platforms remain live.",
            "success",
        )
    else:
        flash(f"{publication.platform.title()} was already recorded as unpublished.", "success")

    return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))


@bp.get("/daily-fragments/<int:artifact_id>/edit")
def edit_daily_fragment(artifact_id):
    artifact = daily_fragment_or_404(get_session(), artifact_id)
    drafts = {draft.platform: draft for draft in artifact.post_drafts if not draft.archived}
    active_publications = [
        publication for draft in drafts.values() for publication in draft.publications
        if publication.status == "published" and publication.external_post_id
    ]
    return render_template(
        "daily_fragment_edit.html",
        artifact=artifact,
        drafts=drafts,
        platforms=("facebook", "instagram", "threads", "x", "fanvue"),
        active_publications=active_publications,
        additional_images=list((artifact.generated_metadata or {}).get("additional_media") or []),
    )


@bp.post("/daily-fragments/<int:artifact_id>/edit")
def update_daily_fragment(artifact_id):
    session = get_session()
    artifact = daily_fragment_or_404(session, artifact_id)
    if any(
        publication.status == "published" and publication.external_post_id
        for draft in artifact.post_drafts for publication in draft.publications
    ):
        flash("Unpublish the live post before changing its text or media.", "error")
        return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))

    metadata = dict(artifact.generated_metadata or {})
    history = list(metadata.get("image_history") or [])
    replacement = request.files.get("primary_image")
    if replacement and replacement.filename:
        if artifact.media_path:
            history.append({"path": artifact.media_path, "replaced_at": datetime.now(timezone.utc).isoformat()})
        uploaded = save_artifact_file(replacement, current_app.config.get("UPLOAD_FOLDER"))
        artifact.original_filename = uploaded["original_filename"]
        artifact.media_path = uploaded["media_path"]
        artifact.media_content_type = uploaded["media_content_type"]
        artifact.media_size = uploaded["media_size"]
        metadata.pop("public_media_url", None)
        metadata.pop("s3_object_key", None)

    additional = list(metadata.get("additional_media") or [])
    for upload in request.files.getlist("additional_images"):
        if not upload or not upload.filename:
            continue
        saved = save_artifact_file(upload, current_app.config.get("UPLOAD_FOLDER"))
        additional.append(saved)
    metadata["additional_media"] = additional
    metadata["image_history"] = history

    drafts = {draft.platform: draft for draft in artifact.post_drafts if not draft.archived}
    for platform in ("facebook", "instagram", "threads", "x", "fanvue"):
        caption = request.form.get(f"caption_{platform}")
        if caption is not None and platform in drafts:
            drafts[platform].caption = caption.strip()
            drafts[platform].status = "approved"
            drafts[platform].approved_at = datetime.now(timezone.utc)
            drafts[platform].updated_at = datetime.now(timezone.utc)
    canonical = drafts.get("facebook")
    if canonical:
        artifact.summary = canonical.caption
        artifact.lore_text = canonical.caption

    review_status = request.form.get("review_status", "accepted").strip()
    reason = request.form.get("feedback_reason", "").strip()
    category = request.form.get("feedback_category", "").strip()
    metadata["review_status"] = review_status
    if review_status == "not_accepted" or reason:
        feedback = list(metadata.get("review_feedback") or [])
        feedback.append({
            "status": review_status,
            "category": category,
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        metadata["review_feedback"] = feedback
    artifact.generated_metadata = metadata
    artifact.updated_at = datetime.now(timezone.utc)
    session.commit()
    flash("Post changes saved. Republish will create fresh platform posts for this same Creator OS entry.", "success")
    return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))


@bp.post("/daily-fragments/<int:artifact_id>/regenerate-image")
def regenerate_daily_fragment_image(artifact_id):
    session = get_session()
    artifact = daily_fragment_or_404(session, artifact_id)
    if any(
        publication.status == "published" and publication.external_post_id
        for draft in artifact.post_drafts for publication in draft.publications
    ):
        flash("Unpublish the live post before regenerating its image.", "error")
        return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))
    metadata = dict(artifact.generated_metadata or {})
    prompt = str(metadata.get("public_image_prompt") or "").strip()
    if not prompt:
        flash("This older post does not have its original image prompt saved, so it cannot be regenerated exactly.", "error")
        return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    destination = Path(current_app.config.get("UPLOAD_FOLDER")) / f"{suffix}-regenerated.png"
    try:
        DailyFragmentGenerator(current_app.config.get("UPLOAD_FOLDER")).generate_image(prompt, destination)
    except (OSError, requests.RequestException, ValueError) as error:
        flash(f"Image regeneration failed: {error}", "error")
        return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))
    history = list(metadata.get("image_history") or [])
    if artifact.media_path:
        history.append({"path": artifact.media_path, "replaced_at": datetime.now(timezone.utc).isoformat()})
    metadata["image_history"] = history
    metadata.pop("public_media_url", None)
    metadata.pop("s3_object_key", None)
    artifact.media_path = str(destination.resolve())
    artifact.original_filename = destination.name
    artifact.media_content_type = "image/png"
    artifact.media_size = destination.stat().st_size
    artifact.generated_metadata = metadata
    artifact.updated_at = datetime.now(timezone.utc)
    session.commit()
    flash("A new image candidate was generated from the original prompt. The prior image remains in history.", "success")
    return redirect(url_for("creator.edit_daily_fragment", artifact_id=artifact.id))


@bp.post("/drafts/<int:draft_id>/publish-from-library")
def publish_draft_from_library(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if draft is None or draft.archived:
        abort(404)
    if draft.status not in {"approved", "failed"}:
        flash(f"{draft.platform.title()} is not waiting to be published.", "error")
        return redirect(url_for("creator.index"))

    already_published = any(
        publication.status == "published" and publication.external_post_id
        for publication in draft.publications
    )
    if already_published:
        draft.status = "published"
        session.commit()
        flash(f"{draft.platform.title()} was already published; no duplicate was created.", "success")
        return redirect(url_for("creator.index"))

    if draft.platform not in CUSTOM_POST_PLATFORMS:
        flash(f"Automatic publishing is not configured for {draft.platform.title()}.", "error")
        return redirect(url_for("creator.index"))

    draft.updated_at = datetime.now(timezone.utc)
    session.commit()
    label = "FanVue" if draft.platform == "fanvue" else draft.platform.title()
    saved_draft_id = draft.id
    if not start_custom_post_publish_job(draft.artifact, {draft.platform}):
        flash("This post already has a publication job in progress.", "error")
        return redirect(url_for("creator.index"))
    flash_individual_publish_status(saved_draft_id, label)
    return redirect(url_for("creator.index"))


def daily_fragment_or_404(session, artifact_id):
    artifact = session.get(Artifact, artifact_id)
    if artifact is None or not str(artifact.fragment_code or "").startswith("daily-fragment-run-"):
        abort(404)
    return artifact


def daily_fragment_media_path(artifact, variant):
    metadata = dict((artifact.generated_metadata or {}) or {})
    if variant.startswith("additional-"):
        try:
            value = (metadata.get("additional_media") or [])[int(variant.removeprefix("additional-"))]["media_path"]
        except (ValueError, IndexError, KeyError, TypeError):
            abort(404)
    else:
        value = metadata.get("fanvue_media_path") if variant == "fanvue" else artifact.media_path
    path = Path(str(value or "")).expanduser()
    if not path.is_file():
        abort(404)
    return path


@bp.get("/daily-fragments/<int:artifact_id>/media/<variant>")
def daily_fragment_media(artifact_id, variant):
    if variant not in {"public", "fanvue"} and not variant.startswith("additional-"):
        abort(404)
    artifact = daily_fragment_or_404(get_session(), artifact_id)
    path = daily_fragment_media_path(artifact, variant)
    return send_file(
        path,
        as_attachment=request.args.get("download") == "1",
        download_name=path.name,
    )


def manual_caption(platform, draft):
    if platform == "instagram":
        return InstagramAdapter(dry_run=True).prepare(draft)
    if platform == "threads":
        return ThreadsAdapter(dry_run=True).prepare(draft)
    if platform == "x":
        return XAdapter(dry_run=True).prepare(draft)
    return draft.caption.strip()


@bp.get("/daily-fragments/<int:artifact_id>/manual-posting-kit")
def daily_fragment_manual_posting_kit(artifact_id):
    artifact = daily_fragment_or_404(get_session(), artifact_id)
    metadata = dict((artifact.generated_metadata or {}) or {})
    run_id = str(metadata.get("run_id") or artifact.fragment_code.removeprefix("daily-fragment-run-"))
    slug = secure_filename(run_id) or f"daily-fragment-{artifact.id}"
    drafts = {draft.platform: draft for draft in artifact.post_drafts}

    sections = [artifact.title, f"Run ID: {run_id}", f"Local date: {metadata.get('local_date') or ''}"]
    for platform in ("facebook", "instagram", "threads", "x", "fanvue"):
        draft = drafts.get(platform)
        if draft is not None:
            sections.extend(("", f"=== {platform.upper()} ===", manual_caption(platform, draft)))
    captions = "\n".join(sections).strip() + "\n"

    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{slug}-captions.txt", captions)
        path = daily_fragment_media_path(artifact, "public")
        archive.write(path, f"{slug}-image{path.suffix.lower()}")
    archive_buffer.seek(0)
    return send_file(
        archive_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}-manual-posting-kit.zip",
    )


@bp.post("/artifacts")
def create_artifact():
    session = get_session()
    upload_info = save_artifact_file(
        request.files.get("artifact_file"),
        current_app.config["UPLOAD_FOLDER"],
    )
    generation_context = load_generation_context(session)
    media_analysis = MediaAnalyzer(
        provider=current_app.config.get("MEDIA_ANALYZER_PROVIDER"),
        model=current_app.config.get("OPENAI_VISION_MODEL"),
    ).analyze(upload_info)
    generated = ArtifactMetadataGenerator(
        upload_info=upload_info,
        form_data=request.form,
        generation_context=generation_context,
        media_analysis=media_analysis,
    ).defaults()
    fragment_code = next_fragment_code(session, Artifact)
    archive_info = archive_media_filename(upload_info.get("media_path"), generated["title"], fragment_code)
    upload_info["media_path"] = archive_info.get("media_path", upload_info.get("media_path", ""))
    generated["generated_metadata"]["fragment_code"] = fragment_code
    generated["generated_metadata"]["stored_filename"] = archive_info.get("stored_filename", "")

    artifact = Artifact(
        title=generated["title"],
        artifact_type=generated["artifact_type"],
        summary=generated["summary"],
        lore_text=generated["lore_text"],
        visibility=request.form.get("visibility", "private"),
        canonical_status=request.form.get("canonical_status", "draft"),
        content_tags=generated["content_tags"],
        mood_tags=generated["mood_tags"],
        source_notes=request.form.get("source_notes", "").strip(),
        generated_metadata=generated["generated_metadata"],
        **upload_info,
    )
    session.add(artifact)
    session.flush()

    for draft_data in ArtifactDraftGenerator(artifact, generation_context).generate():
        session.add(PostDraft(artifact_id=artifact.id, **draft_data))

    session.commit()
    return redirect(url_for("creator.index"))


@bp.post("/canon/import")
def import_canon():
    session = get_session()
    result = CanonImporter(session).run()
    flash(
        (
            f"Canon import complete: {result.created} created, {result.updated} updated, "
            f"{result.unchanged} unchanged, {result.skipped} skipped."
        ),
        "success",
    )
    return redirect(url_for("creator.index"))


@bp.post("/social/import")
def import_social_posts():
    session = get_session()
    result = SocialPostImporter(session).run()
    flash(
        (
            f"Social post import complete: {result.created} created, {result.updated} updated, "
            f"{result.skipped} skipped."
        ),
        "success",
    )
    return redirect(url_for("creator.index"))


@bp.post("/samples/import")
def import_sample_artifacts():
    session = get_session()
    result = SampleArtifactImporter(session).run()
    flash(
        (
            f"Sample artifact import complete: {result.created} created, {result.updated} updated, "
            f"{result.skipped} skipped."
        ),
        "success",
    )
    return redirect(url_for("creator.index"))


@bp.post("/drafts/<int:draft_id>/approve")
def approve_draft(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if draft:
        draft.status = "approved"
        draft.approved_at = datetime.now(timezone.utc)
        session.commit()
    return redirect(url_for("creator.index"))


@bp.get("/drafts/<int:draft_id>")
def review_draft(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("creator.index"))

    preview = platform_summary(draft)
    if draft.platform == "x":
        preview["post_text"] = x_adapter().prepare(draft)
    return render_template(
        "review_draft.html",
        draft=draft,
        preview=preview,
        facebook_adapter=facebook_adapter(),
        instagram_adapter=instagram_adapter(),
        threads_adapter=threads_adapter(),
        x_adapter=x_adapter(),
        fanvue_adapter=fanvue_adapter(),
    )


@bp.get("/metrics")
def metrics_dashboard():
    session = get_session()
    latest_poll = session.query(MetricsPollRun).order_by(MetricsPollRun.started_at.desc()).first()
    publications = (
        session.query(PostPublication)
        .filter(PostPublication.status.in_(("published", "not_found")))
        .order_by(PostPublication.created_at.desc())
        .limit(500)
        .all()
    )
    interactions = (
        session.query(PostInteraction)
        .order_by(PostInteraction.fetched_at.desc())
        .limit(500)
        .all()
    )
    latest_snapshots = latest_snapshot_by_publication(publications)
    publication_rows = []
    for publication in publications:
        snapshot = latest_snapshots.get(publication.id)
        publication_rows.append(
            {
                "id": publication.id,
                "source": "publication",
                "title": publication.post_draft.artifact.title,
                "platform": publication.platform,
                "status": publication.status,
                "externalId": publication.external_post_id,
                "externalUrl": publication.external_url,
                "views": snapshot.views if snapshot else 0,
                "reach": snapshot.reach if snapshot else 0,
                "likes": snapshot.likes if snapshot else 0,
                "comments": snapshot.comments if snapshot else 0,
                "shares": snapshot.shares if snapshot else 0,
                "saves": snapshot.saves if snapshot else 0,
                "clicks": snapshot.clicks if snapshot else 0,
                "publishedAt": publication.created_at.isoformat(),
                "fetchedAt": snapshot.fetched_at.isoformat() if snapshot else "",
            }
        )
    remote_content = (
        session.query(RemoteContent)
        .order_by(RemoteContent.published_at.desc())
        .limit(1000)
        .all()
    )
    for content in remote_content:
        if content.post_publication_id:
            continue
        snapshot = (
            session.query(ContentMetricSnapshot)
            .filter(ContentMetricSnapshot.remote_content_id == content.id)
            .order_by(ContentMetricSnapshot.fetched_at.desc())
            .first()
        )
        publication_rows.append(
            {
                "id": f"remote-{content.id}",
                "source": "account",
                "title": content.title or content.body or f"{content.platform_account.platform.title()} post",
                "platform": content.platform_account.platform,
                "status": "published" if content.status == "available" else content.status,
                "externalId": content.external_content_id,
                "externalUrl": content.permalink,
                "views": snapshot.views if snapshot else 0,
                "reach": snapshot.reach if snapshot else 0,
                "likes": snapshot.likes if snapshot else 0,
                "comments": snapshot.comments if snapshot else 0,
                "shares": snapshot.shares if snapshot else 0,
                "saves": snapshot.saves if snapshot else 0,
                "clicks": snapshot.clicks if snapshot else 0,
                "publishedAt": content.published_at.isoformat() if content.published_at else "",
                "fetchedAt": snapshot.fetched_at.isoformat() if snapshot else "",
            }
        )
    interaction_rows = [
        {
            "id": interaction.id,
            "platform": interaction.platform,
            "type": interaction.interaction_type,
            "author": interaction.author_name or "Unknown",
            "body": interaction.body,
            "replyStatus": interaction.reply_status,
            "receivedAt": interaction.received_at.isoformat() if interaction.received_at else "",
            "fetchedAt": interaction.fetched_at.isoformat(),
            "externalId": interaction.external_id,
            "postTitle": (
                interaction.post_publication.post_draft.artifact.title
                if interaction.post_publication
                else ""
            ),
        }
        for interaction in interactions
    ]
    active_rows = [row for row in publication_rows if row["status"] == "published"]
    active_publication_ids = {
        row["id"] for row in active_rows if row.get("source") == "publication"
    }
    snapshot_history = (
        session.query(PostMetricSnapshot)
        .filter(PostMetricSnapshot.post_publication_id.in_(active_publication_ids))
        .order_by(PostMetricSnapshot.fetched_at.asc())
        .all()
        if active_publication_ids
        else []
    )
    history_by_row = {}
    for snapshot in snapshot_history:
        history_by_row.setdefault(snapshot.post_publication_id, []).append(snapshot)
    remote_ids = [content.id for content in remote_content if not content.post_publication_id]
    content_snapshot_history = (
        session.query(ContentMetricSnapshot)
        .filter(ContentMetricSnapshot.remote_content_id.in_(remote_ids))
        .order_by(ContentMetricSnapshot.fetched_at.asc())
        .all()
        if remote_ids
        else []
    )
    for snapshot in content_snapshot_history:
        history_by_row.setdefault(f"remote-{snapshot.remote_content_id}", []).append(snapshot)
    platform_names = sorted({row["platform"] for row in active_rows})
    platform_summaries = []
    for platform in platform_names:
        rows = [row for row in active_rows if row["platform"] == platform]
        engagement = sum(
            row["likes"] + row["comments"] + row["shares"] + row["saves"]
            for row in rows
        )
        previous_engagement = 0
        has_previous_snapshot = False
        for row in rows:
            history = history_by_row.get(row["id"], [])
            previous = history[-2] if len(history) > 1 else None
            if previous:
                has_previous_snapshot = True
                previous_engagement += (
                    previous.likes + previous.comments + previous.shares + previous.saves
                )
        platform_summaries.append(
            {
                "platform": platform,
                "posts": len(rows),
                "engagement": engagement,
                "growth": engagement - previous_engagement if has_previous_snapshot else 0,
                "reach": sum(row["reach"] for row in rows),
                "views": sum(row["views"] for row in rows),
                "comments": sum(row["comments"] for row in rows),
                "engagementRate": round(
                    engagement / max(sum(row["reach"] for row in rows), 1) * 100, 2
                ),
            }
        )
    platform_summaries.sort(key=lambda row: row["engagement"], reverse=True)

    daily_latest = {}
    for row in active_rows:
        for snapshot in history_by_row.get(row["id"], []):
            key = (
                snapshot.fetched_at.date().isoformat(),
                row["platform"],
                row["id"],
            )
            daily_latest[key] = snapshot
    trend_totals = {}
    for (day, platform, _publication_id), snapshot in daily_latest.items():
        trend_totals.setdefault((day, platform), 0)
        trend_totals[(day, platform)] += (
            snapshot.likes + snapshot.comments + snapshot.shares + snapshot.saves
        )
    trend_dates = sorted({day for day, _platform in trend_totals})[-30:]
    platform_trends = [
        {
            "platform": platform,
            "points": [
                {"date": day, "engagement": trend_totals.get((day, platform), 0)}
                for day in trend_dates
            ],
        }
        for platform in platform_names
    ]
    summary = {
        "activePosts": len(active_rows),
        "views": sum(row["views"] for row in active_rows),
        "reach": sum(row["reach"] for row in active_rows),
        "engagements": sum(
            row["likes"] + row["comments"] + row["shares"] + row["saves"]
            for row in active_rows
        ),
        "pendingInteractions": sum(
            row["replyStatus"] in ("pending_review", "needs_review", "drafted")
            for row in interaction_rows
        ),
        "lastFetched": max(
            (row["fetchedAt"] for row in publication_rows if row["fetchedAt"]),
            default="",
        ),
    }
    return render_template(
        "metrics.html",
        publications=publications,
        latest_snapshots=latest_snapshots,
        interactions=interactions,
        publication_rows=publication_rows,
        interaction_rows=interaction_rows,
        platform_summaries=platform_summaries,
        platform_trends=platform_trends,
        summary=summary,
        latest_poll=latest_poll,
    )


def engagement_sender_policy(session, interaction, create=False):
    if not interaction.author_platform_id:
        return None
    policy = (
        session.query(EngagementSenderPolicy)
        .filter(EngagementSenderPolicy.platform == interaction.platform)
        .filter(EngagementSenderPolicy.author_platform_id == interaction.author_platform_id)
        .one_or_none()
    )
    if policy is None and create:
        policy = EngagementSenderPolicy(
            platform=interaction.platform,
            author_platform_id=interaction.author_platform_id,
            author_name=interaction.author_name,
        )
        session.add(policy)
    return policy


@bp.get("/engagement")
def manage_engagement():
    session = get_session()
    supported_platforms = ("facebook", "instagram", "threads")
    latest_engagement_poll = (
        session.query(MetricsPollRun)
        .filter(MetricsPollRun.source == "fan-comment-scheduler")
        .order_by(MetricsPollRun.started_at.desc())
        .first()
    )
    latest_engagement_poll_time = eastern_time(
        latest_engagement_poll.completed_at if latest_engagement_poll else None
    )
    status_filter = str(request.args.get("status") or "open").strip().lower()
    platform_filter = str(request.args.get("platform") or "all").strip().lower()
    if platform_filter not in (*supported_platforms, "all"):
        platform_filter = "all"
    query = (
        session.query(PostInteraction)
        .filter(PostInteraction.platform.in_(supported_platforms))
        .filter(PostInteraction.interaction_type.in_(("comment", "reply")))
        .order_by(PostInteraction.received_at.desc(), PostInteraction.id.desc())
    )
    if platform_filter != "all":
        query = query.filter(PostInteraction.platform == platform_filter)
    if status_filter == "open":
        query = query.filter(PostInteraction.reply_status.in_(("pending_review", "needs_review", "drafted", "error")))
    elif status_filter == "sent":
        query = query.filter(PostInteraction.reply_status == "sent")
    elif status_filter == "blocked":
        query = query.filter(PostInteraction.reply_status == "sender_blocked")
    interactions = query.limit(500).all()

    engagement_records = (
        session.query(
            PostInteraction.external_id,
            PostInteraction.external_post_id,
            PostInteraction.post_publication_id,
            PostInteraction.author_platform_id,
            PostInteraction.author_name,
        )
        .filter(PostInteraction.platform.in_(supported_platforms))
        .filter(PostInteraction.interaction_type.in_(("comment", "reply")))
        .filter(PostInteraction.platform == platform_filter if platform_filter != "all" else True)
        .all()
    )
    post_keys = {
        str(external_post_id or "").strip() or f"publication:{publication_id}"
        for _, external_post_id, publication_id, _, _ in engagement_records
        if str(external_post_id or "").strip() or publication_id
    }
    sender_keys = {
        str(author_platform_id or "").strip()
        or (f"name:{str(author_name).strip().casefold()}" if str(author_name or "").strip() else f"comment:{external_id}")
        for external_id, _, _, author_platform_id, author_name in engagement_records
    }
    engagement_totals = {
        "posts": len(post_keys),
        "senders": len(sender_keys),
        "comments": len(engagement_records),
    }

    policies = {
        (policy.platform, policy.author_platform_id): policy
        for policy in session.query(EngagementSenderPolicy).all()
    }
    rows = []
    for interaction in interactions:
        policy = policies.get((interaction.platform, interaction.author_platform_id))
        metadata = dict(interaction.raw_payload or {})
        rows.append({
            "interaction": interaction,
            "policy": policy,
            "post_title": (
                interaction.post_publication.post_draft.artifact.title
                if interaction.post_publication
                else (str(metadata.get("source_post_message") or "").strip()[:120] or "Facebook Page post")
            ),
            "post_url": (
                interaction.post_publication.external_url
                if interaction.post_publication else str(metadata.get("source_post_permalink") or "")
            ),
            "reply_language": metadata.get("reply_language") or "",
            "reply_reason": metadata.get("reply_reason") or "",
            "reply_external_id": metadata.get("reply_external_id") or "",
            "received_at_eastern": eastern_time(interaction.received_at),
        })
    counts = {
        "open": session.query(PostInteraction).filter(
            PostInteraction.platform.in_(supported_platforms),
            PostInteraction.platform == platform_filter if platform_filter != "all" else True,
            PostInteraction.reply_status.in_(("pending_review", "needs_review", "drafted", "error")),
        ).count(),
        "sent": session.query(PostInteraction).filter(
            PostInteraction.platform.in_(supported_platforms),
            PostInteraction.platform == platform_filter if platform_filter != "all" else True,
            PostInteraction.reply_status == "sent"
        ).count(),
        "blocked": session.query(PostInteraction).filter(
            PostInteraction.platform.in_(supported_platforms),
            PostInteraction.platform == platform_filter if platform_filter != "all" else True,
            PostInteraction.reply_status == "sender_blocked"
        ).count(),
        "whitelisted": session.query(EngagementSenderPolicy).filter(
            EngagementSenderPolicy.platform.in_(supported_platforms),
            EngagementSenderPolicy.platform == platform_filter if platform_filter != "all" else True,
            EngagementSenderPolicy.auto_approve.is_(True)
        ).count(),
    }
    return render_template(
        "manage_engagement.html",
        rows=rows,
        counts=counts,
        status_filter=status_filter,
        latest_engagement_poll=latest_engagement_poll,
        latest_engagement_poll_time=latest_engagement_poll_time,
        engagement_totals=engagement_totals,
        platform_filter=platform_filter,
        supported_platforms=supported_platforms,
    )


@bp.post("/engagement/<int:interaction_id>/save")
def save_engagement_reply(interaction_id):
    session = get_session()
    interaction = session.get(PostInteraction, interaction_id)
    if not interaction or interaction.platform not in ("facebook", "instagram", "threads"):
        abort(404)
    if interaction.reply_status in ("sent", "sender_blocked"):
        flash("That interaction can no longer be edited.", "error")
        return redirect(url_for("creator.manage_engagement"))
    interaction.suggested_reply = str(request.form.get("reply") or "").strip()
    interaction.reply_status = "drafted" if interaction.suggested_reply else "needs_review"
    session.commit()
    flash("Proposed reply saved.", "success")
    return redirect(url_for("creator.manage_engagement", status=request.form.get("status_filter", "open")))


@bp.post("/engagement/<int:interaction_id>/publish")
def publish_engagement_reply(interaction_id):
    session = get_session()
    interaction = session.get(PostInteraction, interaction_id)
    if not interaction or interaction.platform not in ("facebook", "instagram", "threads"):
        abort(404)
    if interaction.reply_status == "sent":
        flash("That reply has already been published.", "error")
        return redirect(url_for("creator.manage_engagement"))
    policy = engagement_sender_policy(session, interaction)
    if policy and policy.blocked:
        flash("Replies cannot be published to a blocked sender.", "error")
        return redirect(url_for("creator.manage_engagement"))
    reply = str(request.form.get("reply") or interaction.suggested_reply or "").strip()
    if not reply:
        flash("Write a reply before publishing.", "error")
        return redirect(url_for("creator.manage_engagement"))
    try:
        if interaction.platform == "facebook":
            payload = facebook_adapter().reply_to_comment(interaction.external_id, reply)
        elif interaction.platform == "instagram":
            payload = instagram_adapter().reply_to_comment(interaction.external_id, reply)
        else:
            payload = threads_adapter().reply_to_reply(interaction.external_id, reply)
    except (requests.RequestException, ValueError) as error:
        interaction.suggested_reply = reply
        interaction.reply_status = "error"
        session.commit()
        flash(f"{interaction.platform.title()} reply failed: {error}", "error")
        return redirect(url_for("creator.manage_engagement"))
    metadata = dict(interaction.raw_payload or {})
    metadata["reply_external_id"] = str(payload.get("id") or "")
    metadata["reply_published_manually"] = True
    interaction.raw_payload = metadata
    interaction.suggested_reply = reply
    interaction.reply_status = "sent"
    interaction.status = "replied"
    session.commit()
    flash(f"Reply published to {interaction.platform.title()}.", "success")
    return redirect(url_for("creator.manage_engagement", status="sent", platform=request.form.get("platform_filter", "all")))


@bp.post("/engagement/<int:interaction_id>/whitelist")
def whitelist_engagement_sender(interaction_id):
    session = get_session()
    interaction = session.get(PostInteraction, interaction_id)
    if not interaction or interaction.platform not in ("facebook", "instagram", "threads"):
        abort(404)
    policy = engagement_sender_policy(session, interaction, create=True)
    if policy is None:
        flash("This comment does not include a sender ID, so it cannot be whitelisted.", "error")
        return redirect(url_for("creator.manage_engagement"))
    enable = str(request.form.get("enable") or "true").lower() == "true"
    policy.auto_approve = enable
    if enable:
        policy.blocked = False
    policy.author_name = interaction.author_name or policy.author_name
    policy.updated_at = datetime.now(timezone.utc)
    session.commit()
    flash(f"{interaction.author_name or 'Sender'} {'added to' if enable else 'removed from'} automatic approval.", "success")
    return redirect(url_for("creator.manage_engagement", status=request.form.get("status_filter", "open"), platform=request.form.get("platform_filter", "all")))


@bp.post("/engagement/<int:interaction_id>/block")
def block_engagement_sender(interaction_id):
    session = get_session()
    interaction = session.get(PostInteraction, interaction_id)
    if not interaction or interaction.platform != "facebook":
        abort(404)
    if not interaction.author_platform_id:
        flash("Facebook did not provide a sender ID for this comment.", "error")
        return redirect(url_for("creator.manage_engagement"))
    try:
        facebook_adapter().block_sender(interaction.author_platform_id)
    except (requests.RequestException, ValueError) as error:
        flash(f"Facebook did not block this sender: {error}", "error")
        return redirect(url_for("creator.manage_engagement"))
    policy = engagement_sender_policy(session, interaction, create=True)
    policy.blocked = True
    policy.auto_approve = False
    policy.author_name = interaction.author_name or policy.author_name
    policy.updated_at = datetime.now(timezone.utc)
    (
        session.query(PostInteraction)
        .filter(PostInteraction.platform == interaction.platform)
        .filter(PostInteraction.author_platform_id == interaction.author_platform_id)
        .filter(PostInteraction.reply_status != "sent")
        .update({PostInteraction.reply_status: "sender_blocked"}, synchronize_session=False)
    )
    session.commit()
    flash(f"{interaction.author_name or 'Sender'} was blocked from the Facebook Page.", "success")
    return redirect(url_for("creator.manage_engagement", status="blocked"))


@bp.post("/metrics/poll")
def poll_metrics():
    session = get_session()
    result = PostMetricsPoller(
        session,
        adapters={
            "facebook": facebook_adapter(),
            "instagram": instagram_adapter(),
            "threads": threads_adapter(),
            "x": x_adapter(),
            "fanvue": fanvue_adapter(),
        },
    ).run(source="manual")
    account_result = AccountAnalyticsRunner(session, current_app.config).run()
    message = (
        f"Metrics poll complete: {result.snapshots_created} snapshots, "
        f"{result.interactions_created} new interactions, "
        f"{result.interactions_updated} updated interactions, "
        f"{result.marked_unpublished} missing posts returned to approved, "
        f"{result.skipped} skipped."
    )
    if account_result.platform_results:
        account_snapshots = sum(
            item.account_snapshots for item in account_result.platform_results.values()
        )
        content_snapshots = sum(
            item.content_snapshots for item in account_result.platform_results.values()
        )
        message += (
            f" Account-wide sync: {account_snapshots} account snapshots and "
            f"{content_snapshots} content snapshots."
        )
    all_errors = [*result.errors, *account_result.errors]
    flash(message, "success" if not all_errors else "error")
    for error in all_errors[:3]:
        flash(error, "error")
    return redirect(url_for("creator.metrics_dashboard"))


@bp.post("/drafts/<int:draft_id>/save")
def save_draft(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("creator.index"))

    apply_review_form(draft, request.form)
    draft.status = "draft"
    draft.updated_at = datetime.now(timezone.utc)
    session.commit()
    flash("Draft saved.", "success")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


@bp.post("/drafts/<int:draft_id>/archive")
def archive_draft(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if draft:
        draft.archived = True
        draft.updated_at = datetime.now(timezone.utc)
        session.commit()
        flash("Draft archived.", "success")
    return redirect(url_for("creator.index"))


@bp.post("/drafts/cleanup-unpublished")
def cleanup_unpublished_drafts():
    session = get_session()
    drafts = (
        session.query(PostDraft)
        .filter(PostDraft.archived.is_(False))
        .filter(PostDraft.status.notin_(["published"]))
        .all()
    )
    for draft in drafts:
        draft.archived = True
        draft.updated_at = datetime.now(timezone.utc)
    session.commit()
    flash(f"Archived {len(drafts)} unpublished drafts.", "success")
    return redirect(url_for("creator.index"))


@bp.post("/drafts/<int:draft_id>/publish/facebook")
def publish_facebook(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        return redirect(url_for("creator.index"))

    apply_review_form(draft, request.form)
    draft.updated_at = datetime.now(timezone.utc)
    result = facebook_adapter().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    publication = PostPublication(
        post_draft_id=draft.id,
        platform="facebook",
        status=result.status,
        external_post_id=result.external_post_id,
        external_url=result.external_url,
        error_message=result.error_message,
        raw_response=result.raw_response,
    )
    session.add(publication)
    session.commit()
    if result.success:
        flash(f"Facebook {result.status}.", "success")
    else:
        flash(result.error_message or "Facebook publish failed.", "error")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


@bp.post("/drafts/<int:draft_id>/publish/instagram")
def publish_instagram(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        return redirect(url_for("creator.index"))

    apply_review_form(draft, request.form)
    draft.updated_at = datetime.now(timezone.utc)
    session.commit()
    saved_draft_id = draft.id
    if not start_custom_post_publish_job(draft.artifact, {"instagram"}):
        flash("This post already has a publication job in progress.", "error")
        return redirect(url_for("creator.review_draft", draft_id=draft.id))
    flash_individual_publish_status(saved_draft_id, "Instagram")
    return redirect(url_for("creator.review_draft", draft_id=saved_draft_id))


@bp.post("/drafts/<int:draft_id>/publish/x")
def publish_x(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        return redirect(url_for("creator.index"))
    apply_review_form(draft, request.form)
    draft.updated_at = datetime.now(timezone.utc)
    result = x_adapter().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    session.add(PostPublication(
        post_draft_id=draft.id, platform="x", status=result.status,
        external_post_id=result.external_post_id, external_url=result.external_url,
        error_message=result.error_message, raw_response=result.raw_response,
    ))
    session.commit()
    flash(f"X {result.status}." if result.success else (result.error_message or "X publish failed."),
          "success" if result.success else "error")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


@bp.post("/drafts/<int:draft_id>/publish/threads")
def publish_threads(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        return redirect(url_for("creator.index"))
    apply_review_form(draft, request.form)
    draft.updated_at = datetime.now(timezone.utc)
    session.commit()
    saved_draft_id = draft.id
    if not start_custom_post_publish_job(draft.artifact, {"threads"}):
        flash("This post already has a publication job in progress.", "error")
        return redirect(url_for("creator.review_draft", draft_id=draft.id))
    flash_individual_publish_status(saved_draft_id, "Threads")
    return redirect(url_for("creator.review_draft", draft_id=saved_draft_id))


@bp.post("/drafts/<int:draft_id>/publish/fanvue")
def publish_fanvue(draft_id):
    session = get_session()
    draft = session.get(PostDraft, draft_id)
    if not draft:
        return redirect(url_for("creator.index"))
    apply_review_form(draft, request.form)
    draft.updated_at = datetime.now(timezone.utc)
    result = fanvue_adapter().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    session.add(PostPublication(
        post_draft_id=draft.id, platform="fanvue", status=result.status,
        external_post_id=result.external_post_id, external_url=result.external_url,
        error_message=result.error_message, raw_response=result.raw_response,
    ))
    session.commit()
    flash(f"FanVue {result.status}." if result.success else (result.error_message or "FanVue publish failed."),
          "success" if result.success else "error")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


def ensure_platform_accounts(session):
    return synchronize_account_registry(session, current_app.config)
