from flask import Flask
from pathlib import Path

from .routes import bp


def create_app():
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(project_root / "templates"))
    app.config.from_prefixed_env()
    app.register_blueprint(bp)
    return app
