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

DAILY_POST_FAMILIES = {
    "reconstruction": ("Recovered fragment", "recovered-fragment", "Recovered Fragment"),
    "philosophy": ("Philosophy", "philosophy", "Chloe Thinking"),
    "lifestyle": ("Lifestyle", "lifestyle", "Chloe Living"),
    "music": ("Music", "music", "Studio Note"),
    "travel": ("Travel", "travel", "Field Note"),
    "craft": ("Creator craft", "craft", "Creator Note"),
}


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
        publishing_status={
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
    flash("Publishing to X and FanVue has started. Existing successful publications will be skipped.", "success")
    return redirect(url_for("creator.index"))


def daily_fragment_or_404(session, artifact_id):
    artifact = session.get(Artifact, artifact_id)
    if artifact is None or not str(artifact.fragment_code or "").startswith("daily-fragment-run-"):
        abort(404)
    return artifact


def daily_fragment_media_path(artifact, variant):
    metadata = dict((artifact.generated_metadata or {}) or {})
    value = metadata.get("fanvue_media_path") if variant == "fanvue" else artifact.media_path
    path = Path(str(value or "")).expanduser()
    if not path.is_file():
        abort(404)
    return path


@bp.get("/daily-fragments/<int:artifact_id>/media/<variant>")
def daily_fragment_media(artifact_id, variant):
    if variant not in {"public", "fanvue"}:
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
