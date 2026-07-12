from flask import Flask
from pathlib import Path
from dotenv import load_dotenv
import click
import os

from .db import close_session, configure_database, init_db
from .routes import bp
from .services.canon_importer import CanonImporter
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
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "creator-frikshun-local-dev"

    if config_overrides:
        app.config.update(config_overrides)

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

    return app
