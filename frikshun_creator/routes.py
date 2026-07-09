from flask import Blueprint, render_template

from .services.draft_generator import sample_platform_drafts

bp = Blueprint("creator", __name__)


@bp.get("/")
def index():
    return render_template("index.html", drafts=sample_platform_drafts())
