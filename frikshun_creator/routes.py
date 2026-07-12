from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .db import get_session
from .models import Artifact, CanonEntry, PlatformAccount, PostDraft, PostInteraction, PostPublication
from .publishers import FacebookAdapter
from .services.canon_importer import CanonImporter
from .services.draft_generator import ArtifactDraftGenerator, PLATFORMS
from .services.generation_context import load_generation_context
from .services.media_analyzer import MediaAnalyzer
from .services.metadata_generator import ArtifactMetadataGenerator
from .services.post_metrics import PostMetricsPoller, latest_snapshot_by_publication
from .services.post_preview import apply_review_form, platform_summary
from .services.sample_artifact_importer import SampleArtifactImporter
from .services.social_post_importer import SocialPostImporter
from .services.text import split_tags
from .services.uploads import archive_media_filename, next_fragment_code, save_artifact_file

bp = Blueprint("creator", __name__)


def facebook_adapter():
    return FacebookAdapter(
        page_id=current_app.config.get("FACEBOOK_PAGE_ID"),
        access_token=current_app.config.get("FACEBOOK_PAGE_ACCESS_TOKEN"),
        graph_version=current_app.config.get("FACEBOOK_GRAPH_VERSION"),
        dry_run=current_app.config.get("FACEBOOK_DRY_RUN"),
        target_type=current_app.config.get("FACEBOOK_TARGET_TYPE"),
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
    return render_template(
        "index.html",
        artifacts=artifacts,
        drafts=drafts,
        platforms=PLATFORMS,
        canon_count=canon_count,
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

    return render_template(
        "review_draft.html",
        draft=draft,
        preview=platform_summary(draft),
        facebook_adapter=facebook_adapter(),
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
    result = PostMetricsPoller(session, adapters={"facebook": facebook_adapter()}).run()
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


def ensure_platform_accounts(session):
    existing = {
        row.platform
        for row in session.query(PlatformAccount.platform).filter(PlatformAccount.active.is_(True)).all()
    }
    for platform in PLATFORMS:
        if platform not in existing:
            session.add(PlatformAccount(platform=platform, oauth_status="manual", active=True))
    session.commit()
