from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import requests

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session as flask_session, url_for
from werkzeug.utils import secure_filename
from sqlalchemy import String, cast, or_

from .db import get_session
from .models import (
    ContentMetricSnapshot,
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
    """Refresh expiring S3 media URLs before a saved draft is retried."""
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
    if object_key:
        refreshed_url = storage.refresh_signed_url(object_key)
    elif content_type.startswith("image/"):
        stored = storage.store_instagram_image(
            media_path,
            artifact.title,
            local_day=(artifact.created_at or datetime.now(timezone.utc)).date(),
            output_dir=current_app.config.get("UPLOAD_FOLDER"),
        )
        object_key = stored.object_key
        refreshed_url = stored.signed_url
        metadata["s3_bucket"] = current_app.config.get("S3_MEDIA_BUCKET")
        metadata["s3_object_key"] = object_key
    else:
        return existing_url

    metadata["public_media_url"] = refreshed_url
    artifact.generated_metadata = metadata
    return refreshed_url


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

    adapters = {
        "facebook": facebook_adapter,
        "instagram": instagram_adapter,
        "threads": threads_adapter,
        "x": x_adapter,
        "fanvue": fanvue_adapter,
    }
    adapter_factory = adapters.get(draft.platform)
    if adapter_factory is None:
        flash(f"Automatic publishing is not configured for {draft.platform.title()}.", "error")
        return redirect(url_for("creator.index"))

    if draft.platform in {"instagram", "threads"}:
        try:
            refresh_meta_media_url(draft)
        except (OSError, ValueError) as error:
            flash(f"{draft.platform.title()} media refresh failed: {error}", "error")
            return redirect(url_for("creator.index"))

    draft.updated_at = datetime.now(timezone.utc)
    result = adapter_factory().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    session.add(
        PostPublication(
            post_draft_id=draft.id,
            platform=draft.platform,
            status=result.status,
            external_post_id=result.external_post_id,
            external_url=result.external_url,
            error_message=result.error_message,
            raw_response=result.raw_response,
        )
    )
    session.commit()
    label = "FanVue" if draft.platform == "fanvue" else draft.platform.title()
    flash(
        f"{label} {result.status}." if result.success else (result.error_message or f"{label} publish failed."),
        "success" if result.success else "error",
    )
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
            row["replyStatus"] == "pending_review" for row in interaction_rows
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
    try:
        refresh_meta_media_url(draft)
    except (OSError, ValueError) as error:
        flash(f"Instagram media refresh failed: {error}", "error")
        return redirect(url_for("creator.review_draft", draft_id=draft.id))
    result = instagram_adapter().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    session.add(
        PostPublication(
            post_draft_id=draft.id,
            platform="instagram",
            status=result.status,
            external_post_id=result.external_post_id,
            external_url=result.external_url,
            error_message=result.error_message,
            raw_response=result.raw_response,
        )
    )
    session.commit()
    if result.success:
        flash(f"Instagram {result.status}.", "success")
    else:
        flash(result.error_message or "Instagram publish failed.", "error")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


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
    try:
        refresh_meta_media_url(draft)
    except (OSError, ValueError) as error:
        flash(f"Threads media refresh failed: {error}", "error")
        return redirect(url_for("creator.review_draft", draft_id=draft.id))
    result = threads_adapter().publish(draft)
    draft.status = result.status
    if result.success:
        draft.approved_at = datetime.now(timezone.utc)
    session.add(PostPublication(
        post_draft_id=draft.id, platform="threads", status=result.status,
        external_post_id=result.external_post_id, external_url=result.external_url,
        error_message=result.error_message, raw_response=result.raw_response,
    ))
    session.commit()
    flash(f"Threads {result.status}." if result.success else (result.error_message or "Threads publish failed."),
          "success" if result.success else "error")
    return redirect(url_for("creator.review_draft", draft_id=draft.id))


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
