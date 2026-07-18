from datetime import datetime, timezone

import requests

from flask import Blueprint, current_app, flash, redirect, render_template, request, session as flask_session, url_for

from .db import get_session
from .models import Artifact, CanonEntry, PlatformAccount, PostDraft, PostInteraction, PostPublication
from .publishers import FacebookAdapter, InstagramAdapter, ThreadsAdapter, XAdapter, FanvueAdapter
from .services.canon_importer import CanonImporter
from .services.draft_generator import ArtifactDraftGenerator, PLATFORMS
from .services.generation_context import load_generation_context
from .services.fanvue_oauth import FanvueOAuth
from .services.media_analyzer import MediaAnalyzer
from .services.metadata_generator import ArtifactMetadataGenerator
from .services.post_metrics import PostMetricsPoller, latest_snapshot_by_publication
from .services.post_preview import apply_review_form, platform_summary
from .services.sample_artifact_importer import SampleArtifactImporter
from .services.social_post_importer import SocialPostImporter
from .services.text import split_tags
from .services.threads_oauth import ThreadsOAuth
from .services.uploads import archive_media_filename, next_fragment_code, save_artifact_file

bp = Blueprint("creator", __name__)


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
    ensure_platform_accounts(session)
    artifacts = (
        session.query(Artifact)
        .filter(Artifact.archived.is_(False))
        .order_by(Artifact.created_at.desc())
        .limit(20)
        .all()
    )
    drafts = (
        session.query(PostDraft)
        .filter(PostDraft.archived.is_(False))
        .order_by(PostDraft.created_at.desc())
        .limit(20)
        .all()
    )
    canon_count = session.query(CanonEntry).count()
    facebook = facebook_adapter()
    instagram = instagram_adapter()
    threads = threads_adapter()
    x_publisher = x_adapter()
    fanvue = fanvue_adapter()
    return render_template(
        "index.html",
        artifacts=artifacts,
        drafts=drafts,
        platforms=PLATFORMS,
        canon_count=canon_count,
        publishing_status={
            "facebook": "dry run" if facebook.dry_run else "live",
            "instagram": (
                "dry run"
                if instagram.dry_run
                else ("live" if instagram.user_id and instagram.access_token else "credentials missing")
            ),
            "threads": (
                "dry run"
                if threads.dry_run
                else ("live" if threads.current_access_token() else "credentials missing")
            ),
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
            "s3": "ready" if current_app.config.get("S3_MEDIA_BUCKET") else "not configured",
        },
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
    publications = (
        session.query(PostPublication)
        .filter(PostPublication.status == "published")
        .order_by(PostPublication.created_at.desc())
        .limit(50)
        .all()
    )
    interactions = (
        session.query(PostInteraction)
        .order_by(PostInteraction.fetched_at.desc())
        .limit(50)
        .all()
    )
    return render_template(
        "metrics.html",
        publications=publications,
        latest_snapshots=latest_snapshot_by_publication(publications),
        interactions=interactions,
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
    ).run()
    message = (
        f"Metrics poll complete: {result.snapshots_created} snapshots, "
        f"{result.interactions_created} new interactions, "
        f"{result.interactions_updated} updated interactions, "
        f"{result.skipped} skipped."
    )
    flash(message, "success" if not result.errors else "error")
    for error in result.errors[:3]:
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
    existing = {
        row.platform
        for row in session.query(PlatformAccount.platform).filter(PlatformAccount.active.is_(True)).all()
    }
    for platform in PLATFORMS:
        if platform not in existing:
            session.add(PlatformAccount(platform=platform, oauth_status="manual", active=True))
    session.commit()
