from flask import Flask
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
import json
import click
import os
import requests

from .db import close_session, configure_database, init_db
from .models import Artifact, PostDraft, PostPublication
from .publishers.facebook import FacebookAdapter
from .publishers.instagram import InstagramAdapter
from .publishers.threads import ThreadsAdapter
from .publishers.x import XAdapter
from .publishers.fanvue import FanvueAdapter
from .routes import bp
from .services.canon_importer import CanonImporter
from .services.daily_fragment_generator import CONTENT_LANES, DailyFragmentGenerator
from .services.daily_fragment_readiness import DailyFragmentReadinessChecker
from .services.daily_fragment_workflow import (
    DailyFragmentPackage,
    artifact_local_date,
    existing_daily_fragment_artifact,
    package_from_existing_artifact,
    publish_daily_fragment_package,
    store_daily_fragment_package,
)
from .services.post_metrics import PostMetricsPoller
from .services.sample_artifact_importer import SampleArtifactImporter
from .services.social_post_importer import SocialPostImporter
from .services.threads_oauth import ThreadsOAuth
from .services.tiktok_reel_generator import TikTokReelGenerator


def create_app(config_overrides=None):
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")

    app = Flask(__name__, template_folder=str(project_root / "templates"))
    app.config.from_prefixed_env()
    app.config.setdefault("DATABASE_URL", None)
    app.config.setdefault("AUTO_CREATE_TABLES", True)
    app.config.setdefault("UPLOAD_FOLDER", str(project_root / "instance" / "uploads"))
    app.config.setdefault("MEDIA_ANALYZER_PROVIDER", os.getenv("MEDIA_ANALYZER_PROVIDER", "auto"))
    app.config.setdefault("OPENAI_VISION_MODEL", os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"))
    app.config.setdefault("OPENAI_RATE_LIMIT_RETRIES", int(os.getenv("OPENAI_RATE_LIMIT_RETRIES", "8")))
    app.config.setdefault("OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS", int(os.getenv("OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS", "60")))
    app.config.setdefault("TIKTOK_REEL_VIDEO_PROVIDER", os.getenv("TIKTOK_REEL_VIDEO_PROVIDER", "animatic"))
    app.config.setdefault("FFMPEG_BIN", os.getenv("FFMPEG_BIN", "ffmpeg"))
    app.config.setdefault("FACEBOOK_TARGET_TYPE", os.getenv("FACEBOOK_TARGET_TYPE", "page"))
    app.config.setdefault("FACEBOOK_GRAPH_VERSION", os.getenv("FACEBOOK_GRAPH_VERSION", "v20.0"))
    app.config.setdefault("FACEBOOK_DRY_RUN", os.getenv("FACEBOOK_DRY_RUN", "true").lower() != "false")
    app.config.setdefault("FACEBOOK_PAGE_ID", os.getenv("FACEBOOK_PAGE_ID", ""))
    app.config.setdefault("FACEBOOK_PAGE_ACCESS_TOKEN", os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", ""))
    app.config.setdefault("INSTAGRAM_GRAPH_VERSION", os.getenv("INSTAGRAM_GRAPH_VERSION", "v20.0"))
    app.config.setdefault("INSTAGRAM_DRY_RUN", os.getenv("INSTAGRAM_DRY_RUN", "true").lower() != "false")
    app.config.setdefault("INSTAGRAM_USER_ID", os.getenv("INSTAGRAM_USER_ID", ""))
    app.config.setdefault("INSTAGRAM_ACCESS_TOKEN", os.getenv("INSTAGRAM_ACCESS_TOKEN", ""))
    app.config.setdefault("INSTAGRAM_MEDIA_BASE_URL", os.getenv("INSTAGRAM_MEDIA_BASE_URL", ""))
    app.config.setdefault("THREADS_API_VERSION", os.getenv("THREADS_API_VERSION", "v1.0"))
    app.config.setdefault("THREADS_API_BASE_URL", os.getenv("THREADS_API_BASE_URL", "https://graph.threads.net"))
    app.config.setdefault("THREADS_AUTH_URL", os.getenv("THREADS_AUTH_URL", "https://threads.net/oauth/authorize"))
    app.config.setdefault("THREADS_DRY_RUN", os.getenv("THREADS_DRY_RUN", "true").lower() != "false")
    app.config.setdefault("THREADS_APP_ID", os.getenv("THREADS_APP_ID", ""))
    app.config.setdefault("THREADS_APP_SECRET", os.getenv("THREADS_APP_SECRET", ""))
    app.config.setdefault("THREADS_REDIRECT_URI", os.getenv("THREADS_REDIRECT_URI", ""))
    app.config.setdefault("THREADS_TOKEN_PATH", os.getenv("THREADS_TOKEN_PATH", str(project_root / "instance" / "threads_oauth.json")))
    app.config.setdefault("THREADS_ACCESS_TOKEN", os.getenv("THREADS_ACCESS_TOKEN", ""))
    app.config.setdefault("THREADS_LONG_LIVED_ACCESS_TOKEN", os.getenv("THREADS_LONG_LIVED_ACCESS_TOKEN", ""))
    app.config.setdefault("THREADS_MEDIA_BASE_URL", os.getenv("THREADS_MEDIA_BASE_URL", ""))
    app.config.setdefault("X_DRY_RUN", os.getenv("X_DRY_RUN", "true").lower() != "false")
    app.config.setdefault("X_USERNAME", os.getenv("X_USERNAME", ""))
    app.config.setdefault("X_CONSUMER_KEY", os.getenv("X_CONSUMER_KEY", ""))
    app.config.setdefault("X_SECRET_KEY", os.getenv("X_SECRET_KEY", ""))
    app.config.setdefault("X_ACCESS_TOKEN", os.getenv("X_ACCESS_TOKEN", ""))
    app.config.setdefault("X_ACCESS_TOKEN_SECRET", os.getenv("X_ACCESS_TOKEN_SECRET", ""))
    app.config.setdefault("X_BEARER_TOKEN", os.getenv("X_BEARER_TOKEN", ""))
    app.config.setdefault("FANVUE_APP_ID", os.getenv("FANVUE_APP_ID", ""))
    app.config.setdefault("FANVUE_CLIENT_ID", os.getenv("FANVUE_CLIENT_ID", ""))
    app.config.setdefault("FANVUE_CLIENT_SECRET", os.getenv("FANVUE_CLIENT_SECRET", ""))
    app.config.setdefault("FANVUE_REDIRECT_URI", os.getenv("FANVUE_REDIRECT_URI", ""))
    app.config.setdefault(
        "FANVUE_TOKEN_PATH", os.getenv("FANVUE_TOKEN_PATH", str(project_root / "instance" / "fanvue_oauth.json"))
    )
    app.config.setdefault("FANVUE_API_VERSION", os.getenv("FANVUE_API_VERSION", "2025-06-26"))
    app.config.setdefault("FANVUE_AUDIENCE", os.getenv("FANVUE_AUDIENCE", "followers-and-subscribers"))
    app.config.setdefault("FANVUE_DRY_RUN", os.getenv("FANVUE_DRY_RUN", "true").lower() != "false")
    app.config.setdefault("S3_MEDIA_BUCKET", os.getenv("S3_MEDIA_BUCKET", ""))
    app.config.setdefault("S3_MEDIA_REGION", os.getenv("S3_MEDIA_REGION", "us-east-1"))
    app.config.setdefault("S3_MEDIA_PREFIX", os.getenv("S3_MEDIA_PREFIX", "social"))
    app.config.setdefault("S3_PRESIGN_SECONDS", int(os.getenv("S3_PRESIGN_SECONDS", "3600")))
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "creator-frikshun-local-dev"

    if config_overrides:
        app.config.update(config_overrides)
    facebook_dry_run_overridden = (config_overrides or {}).get("FACEBOOK_DRY_RUN") is False
    instagram_dry_run_overridden = (config_overrides or {}).get("INSTAGRAM_DRY_RUN") is False
    threads_dry_run_overridden = (config_overrides or {}).get("THREADS_DRY_RUN") is False
    x_dry_run_overridden = (config_overrides or {}).get("X_DRY_RUN") is False
    fanvue_dry_run_overridden = (config_overrides or {}).get("FANVUE_DRY_RUN") is False
    if app.config.get("TESTING") and not facebook_dry_run_overridden:
        app.config["FACEBOOK_DRY_RUN"] = True
    if app.config.get("TESTING") and not instagram_dry_run_overridden:
        app.config["INSTAGRAM_DRY_RUN"] = True
    if app.config.get("TESTING") and not threads_dry_run_overridden:
        app.config["THREADS_DRY_RUN"] = True
    if app.config.get("TESTING") and not x_dry_run_overridden:
        app.config["X_DRY_RUN"] = True
    if app.config.get("TESTING") and not fanvue_dry_run_overridden:
        app.config["FANVUE_DRY_RUN"] = True

    configure_database(app.config.get("DATABASE_URL"))
    app.teardown_appcontext(close_session)
    app.register_blueprint(bp)

    with app.app_context():
        if app.config["AUTO_CREATE_TABLES"]:
            init_db()

    @app.cli.command("import-canon")
    def import_canon_command():
        from .db import get_session

        result = CanonImporter(get_session()).run()
        click.echo(
            "Canon import complete: "
            f"{result.created} created, {result.updated} updated, "
            f"{result.unchanged} unchanged, {result.skipped} skipped."
        )

    @app.cli.command("import-social-posts")
    def import_social_posts_command():
        from .db import get_session

        result = SocialPostImporter(get_session()).run()
        click.echo(
            "Social post import complete: "
            f"{result.created} created, {result.updated} updated, {result.skipped} skipped."
        )

    @app.cli.command("import-sample-artifacts")
    def import_sample_artifacts_command():
        from .db import get_session

        result = SampleArtifactImporter(get_session()).run()
        click.echo(
            "Sample artifact import complete: "
            f"{result.created} created, {result.updated} updated, {result.skipped} skipped."
        )

    @app.cli.command("poll-post-metrics")
    def poll_post_metrics_command():
        from .db import get_session

        result = PostMetricsPoller(get_session()).run()
        click.echo(
            "Metrics poll complete: "
            f"{result.snapshots_created} snapshots, "
            f"{result.interactions_created} new interactions, "
            f"{result.interactions_updated} updated interactions, "
            f"{result.skipped} skipped, {len(result.errors)} errors."
        )
        for error in result.errors:
            click.echo(f"ERROR: {error}", err=True)

    @app.cli.command("check-daily-fragment-readiness")
    def check_daily_fragment_readiness_command():
        """Validate whether daily fragment generation/publishing is ready to run live."""
        checks = DailyFragmentReadinessChecker(app).run()
        failed = [check for check in checks if not check.ok]
        for check in checks:
            status = "OK" if check.ok else "FAIL"
            click.echo(f"{status} {check.name}: {check.detail}")
        if failed:
            raise click.ClickException(f"{len(failed)} readiness checks failed.")
        click.echo("Daily fragment automation is ready for live generation and publishing.")

    @app.cli.command("start-threads-oauth")
    def start_threads_oauth_command():
        """Print the Threads authorization URL for the configured callback."""
        oauth = ThreadsOAuth(
            app_id=app.config.get("THREADS_APP_ID"),
            app_secret=app.config.get("THREADS_APP_SECRET"),
            redirect_uri=app.config.get("THREADS_REDIRECT_URI"),
            token_path=app.config.get("THREADS_TOKEN_PATH"),
            auth_url=app.config.get("THREADS_AUTH_URL"),
            api_base_url=app.config.get("THREADS_API_BASE_URL"),
        )
        try:
            authorization_url, _ = oauth.begin(persist_state=True)
        except ValueError as error:
            raise click.ClickException(str(error))
        click.echo(authorization_url)

    @app.cli.command("refresh-threads-token")
    def refresh_threads_token_command():
        """Refresh the stored Threads long-lived access token."""
        oauth = ThreadsOAuth(
            app_id=app.config.get("THREADS_APP_ID"),
            app_secret=app.config.get("THREADS_APP_SECRET"),
            redirect_uri=app.config.get("THREADS_REDIRECT_URI"),
            token_path=app.config.get("THREADS_TOKEN_PATH"),
            auth_url=app.config.get("THREADS_AUTH_URL"),
            api_base_url=app.config.get("THREADS_API_BASE_URL"),
        )
        try:
            saved = oauth.refresh()
        except (requests.RequestException, ValueError) as error:
            raise click.ClickException(str(error))
        click.echo(f"threads_user_id: {saved.get('user_id') or ''}")
        click.echo(f"expires_at: {saved.get('expires_at') or ''}")
        click.echo(f"token_path: {oauth.token_path}")

    @app.cli.command("publish-daily-fragment")
    @click.option("--body", required=True, help="The complete text-only post.")
    @click.option("--x-body", default="", help="Optional X-native caption body.")
    @click.option("--fanvue-body", default="", help="Optional intimate FanVue caption body.")
    @click.option("--title", default="Recovered Fragment", show_default=True)
    @click.option(
        "--image",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=True,
        help="Image to publish to Facebook, Instagram, and X.",
    )
    @click.option(
        "--fanvue-image",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=False,
        default=None,
        help="Deprecated optional FanVue-specific image. The public image is used by default.",
    )
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Override the local day used for caption generation and file naming (YYYY-MM-DD).",
    )
    @click.option(
        "--run-id",
        default="",
        help="Optional logical run id. Reuse it only when retrying the same run.",
    )
    @click.option("--allow-dry-run", is_flag=True, help="Record a dry run instead of refusing it.")
    def publish_daily_fragment_command(body, x_body, fanvue_body, title, image, fanvue_image, local_date, run_id, allow_dry_run):
        """Publish one Chloe fragment run to Facebook, Instagram, X, and FanVue."""
        from .db import get_session

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        package = DailyFragmentPackage(
            title=title,
            body=body,
            x_body=x_body or body,
            fanvue_body=fanvue_body or body,
            public_image_path=image,
            fanvue_image_path=fanvue_image or image,
        )
        _, run_id, urls, errors = publish_daily_fragment_package(
            session, app.config, package, local_date, run_id=run_id, allow_dry_run=allow_dry_run
        )
        click.echo(f"run_id: {run_id}")
        for url in urls:
            click.echo(url)
        if errors:
            raise click.ClickException("; ".join(errors))

    @app.cli.command("run-daily-fragment-autopilot")
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Override the local day used for generation and file naming (YYYY-MM-DD).",
    )
    @click.option(
        "--run-id",
        default="",
        help="Optional logical run id. Reuse it only when retrying the same run.",
    )
    @click.option(
        "--family",
        type=click.Choice([name for name, _description in CONTENT_LANES]),
        default=None,
        help="Require a specific editorial family instead of using the automatic rotation.",
    )
    @click.option("--allow-dry-run", is_flag=True, help="Record a dry run instead of refusing it.")
    def run_daily_fragment_autopilot_command(local_date, run_id, family, allow_dry_run):
        """Generate one Chloe daily fragment package and publish it to all live platforms."""
        from .db import get_session
        from .services.generation_context import load_generation_context

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        CanonImporter(session).run()
        artifact = existing_daily_fragment_artifact(session, run_id)
        if artifact is not None:
            package = package_from_existing_artifact(artifact)
        else:
            generator = DailyFragmentGenerator(
                app.config.get("UPLOAD_FOLDER"),
                openai_rate_limit_retries=app.config.get("OPENAI_RATE_LIMIT_RETRIES", 8),
                openai_rate_limit_max_sleep_seconds=app.config.get("OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS", 60),
            )
            try:
                package = generator.generate(
                    local_date,
                    load_generation_context(session),
                    selected_lane=family,
                )
            except requests.HTTPError as error:
                response = getattr(error, "response", None)
                if response is not None and response.status_code == 429:
                    raise click.ClickException(
                        "OpenAI rate limit persisted after retries. "
                        f"Diagnostic: {generator.openai_error_summary(error)}. "
                        "Wait a few minutes and rerun "
                        "`flask --app app run-daily-fragment-autopilot`, or raise "
                        "`OPENAI_RATE_LIMIT_RETRIES` / `OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS` in `.env`."
                    ) from error
                raise
        _, run_id, urls, errors = publish_daily_fragment_package(
            session, app.config, package, local_date, run_id=run_id, allow_dry_run=allow_dry_run
        )
        click.echo(f"run_id: {run_id}")
        click.echo(package.title)
        for url in urls:
            click.echo(url)
        if errors:
            raise click.ClickException("; ".join(errors))

    @app.cli.command("generate-daily-fragment-run")
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Override the local day used for generation and file naming (YYYY-MM-DD).",
    )
    @click.option(
        "--run-id",
        default="",
        help="Optional logical run id. Reuse it only when regenerating or inspecting the same saved run.",
    )
    @click.option(
        "--family",
        type=click.Choice([name for name, _description in CONTENT_LANES]),
        default=None,
        help="Require a specific editorial family instead of using the automatic rotation.",
    )
    def generate_daily_fragment_run_command(local_date, run_id, family):
        """Generate one Chloe daily fragment package and save it locally without publishing."""
        from .db import get_session
        from .services.generation_context import load_generation_context

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        CanonImporter(session).run()
        artifact = existing_daily_fragment_artifact(session, run_id)
        if artifact is not None:
            package = package_from_existing_artifact(artifact)
            saved_local_date = artifact_local_date(artifact)
            click.echo(f"run_id: {run_id}")
            click.echo(package.title)
            click.echo(f"saved_local_date: {saved_local_date or local_date.isoformat()}")
            click.echo(f"public_image: {package.public_image_path}")
            click.echo(f"fanvue_image: {package.fanvue_image_path}")
            return

        generator = DailyFragmentGenerator(
            app.config.get("UPLOAD_FOLDER"),
            openai_rate_limit_retries=app.config.get("OPENAI_RATE_LIMIT_RETRIES", 8),
            openai_rate_limit_max_sleep_seconds=app.config.get("OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS", 60),
        )
        try:
            package = generator.generate(
                local_date,
                load_generation_context(session),
                selected_lane=family,
            )
        except requests.HTTPError as error:
            response = getattr(error, "response", None)
            if response is not None and response.status_code == 429:
                raise click.ClickException(
                    "OpenAI rate limit persisted after retries. "
                    f"Diagnostic: {generator.openai_error_summary(error)}. "
                    "Wait a few minutes and rerun "
                    "`flask --app app generate-daily-fragment-run`, or raise "
                    "`OPENAI_RATE_LIMIT_RETRIES` / `OPENAI_RATE_LIMIT_MAX_SLEEP_SECONDS` in `.env`."
                ) from error
            raise

        artifact, saved_run_id = store_daily_fragment_package(session, package, local_date, run_id=run_id)
        click.echo(f"run_id: {saved_run_id}")
        click.echo(package.title)
        click.echo(f"saved_local_date: {artifact_local_date(artifact)}")
        click.echo(f"public_image: {package.public_image_path}")
        click.echo(f"fanvue_image: {package.fanvue_image_path}")

    @app.cli.command("publish-daily-fragment-run")
    @click.option(
        "--run-id",
        required=True,
        help="Logical run id of a previously generated daily fragment run.",
    )
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Optional override for the local day used during publishing (YYYY-MM-DD).",
    )
    @click.option("--allow-dry-run", is_flag=True, help="Record a dry run instead of refusing it.")
    def publish_daily_fragment_run_command(run_id, local_date, allow_dry_run):
        """Publish a previously generated Chloe fragment run by run id."""
        from .db import get_session

        session = get_session()
        artifact = existing_daily_fragment_artifact(session, run_id)
        if artifact is None:
            raise click.ClickException(f"No generated daily fragment run found for run_id `{run_id}`.")

        package = package_from_existing_artifact(artifact)
        stored_local_date = artifact_local_date(artifact)
        publish_local_date = (
            local_date.date()
            if local_date
            else datetime.fromisoformat(stored_local_date).date()
            if stored_local_date
            else datetime.now().astimezone().date()
        )
        _, run_id, urls, errors = publish_daily_fragment_package(
            session, app.config, package, publish_local_date, run_id=run_id, allow_dry_run=allow_dry_run
        )
        click.echo(f"run_id: {run_id}")
        click.echo(package.title)
        for url in urls:
            click.echo(url)
        if errors:
            raise click.ClickException("; ".join(errors))

    @app.cli.command("preview-daily-fragment-series")
    @click.option("--count", default=10, show_default=True, type=int, help="How many preview posts to generate.")
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Start date for the preview sequence (YYYY-MM-DD).",
    )
    def preview_daily_fragment_series_command(count, local_date):
        """Generate a dry preview series of Chloe daily posts without publishing."""
        from .db import get_session
        from .services.generation_context import load_generation_context

        if count < 1:
            raise click.ClickException("count must be at least 1.")

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        CanonImporter(session).run()
        generator = DailyFragmentGenerator(app.config.get("UPLOAD_FOLDER"))
        previews = generator.preview_series(local_date, load_generation_context(session), count)
        click.echo(json.dumps([preview.__dict__ for preview in previews], indent=2))

    @app.cli.command("generate-tiktok-reel")
    @click.option("--concept", required=True, help="Short concept seed, for example 'dating a virtual girl'.")
    @click.option("--shot-count", default=5, show_default=True, type=int, help="Number of shots to plan and render.")
    @click.option(
        "--local-date",
        type=click.DateTime(formats=["%Y-%m-%d"]),
        default=None,
        help="Override the local day used for generation and export naming (YYYY-MM-DD).",
    )
    def generate_tiktok_reel_command(concept, shot_count, local_date):
        """Generate and export a TikTok-style review reel without publishing it."""
        from .db import get_session
        from .services.generation_context import load_generation_context

        if shot_count < 3 or shot_count > 8:
            raise click.ClickException("shot-count must be between 3 and 8.")

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        CanonImporter(session).run()
        generator = TikTokReelGenerator(
            app.config.get("UPLOAD_FOLDER"),
            video_provider=app.config.get("TIKTOK_REEL_VIDEO_PROVIDER"),
            ffmpeg_bin=app.config.get("FFMPEG_BIN"),
            progress_callback=click.echo,
        )
        export = generator.generate_and_store(
            session,
            local_date,
            load_generation_context(session),
            concept=concept,
            shot_count=shot_count,
        )
        click.echo(f"title: {export.title}")
        click.echo(f"artifact_id: {export.artifact_id}")
        click.echo(f"draft_id: {export.draft_id}")
        click.echo(f"video: {export.video_path}")
        click.echo(f"metadata: {export.metadata_path}")
        click.echo(f"draft: {export.draft_path}")
        click.echo("manual_review_required: true")

    return app
