from flask import Flask
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
import json
import click
import os

from .db import close_session, configure_database, init_db
from .models import Artifact, PostDraft, PostPublication
from .publishers.facebook import FacebookAdapter
from .publishers.instagram import InstagramAdapter
from .publishers.x import XAdapter
from .publishers.fanvue import FanvueAdapter
from .routes import bp
from .services.canon_importer import CanonImporter
from .services.daily_fragment_generator import DailyFragmentGenerator
from .services.daily_fragment_readiness import DailyFragmentReadinessChecker
from .services.daily_fragment_workflow import DailyFragmentPackage, publish_daily_fragment_package
from .services.post_metrics import PostMetricsPoller
from .services.sample_artifact_importer import SampleArtifactImporter
from .services.social_post_importer import SocialPostImporter


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
    x_dry_run_overridden = (config_overrides or {}).get("X_DRY_RUN") is False
    fanvue_dry_run_overridden = (config_overrides or {}).get("FANVUE_DRY_RUN") is False
    if app.config.get("TESTING") and not facebook_dry_run_overridden:
        app.config["FACEBOOK_DRY_RUN"] = True
    if app.config.get("TESTING") and not instagram_dry_run_overridden:
        app.config["INSTAGRAM_DRY_RUN"] = True
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
        required=True,
        help="Separate beautiful, artsy, intimate image for FanVue.",
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
            fanvue_image_path=fanvue_image,
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
    @click.option("--allow-dry-run", is_flag=True, help="Record a dry run instead of refusing it.")
    def run_daily_fragment_autopilot_command(local_date, run_id, allow_dry_run):
        """Generate one Chloe daily fragment package and publish it to all live platforms."""
        from .db import get_session
        from .services.generation_context import load_generation_context

        session = get_session()
        local_date = local_date.date() if local_date else datetime.now().astimezone().date()
        CanonImporter(session).run()
        generator = DailyFragmentGenerator(app.config.get("UPLOAD_FOLDER"))
        package = generator.generate(local_date, load_generation_context(session))
        _, run_id, urls, errors = publish_daily_fragment_package(
            session, app.config, package, local_date, run_id=run_id, allow_dry_run=allow_dry_run
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

    return app
