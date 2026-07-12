import os

from flask import current_app, g
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://frikshun:frikshun_dev@localhost:54329/"
    "frikshun_content_development"
)

engine = None
SessionLocal = None


def configure_database(database_url=None):
    global engine, SessionLocal

    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    options = {"future": True}

    if url == "sqlite+pysqlite:///:memory:":
        options["connect_args"] = {"check_same_thread": False}
        options["poolclass"] = StaticPool

    engine = create_engine(url, **options)
    SessionLocal = scoped_session(sessionmaker(bind=engine, future=True))
    return engine


def init_db():
    if engine is None:
        configure_database(current_app.config.get("DATABASE_URL"))
    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()


def ensure_runtime_columns():
    inspector = inspect(engine)
    if not inspector.has_table("creator_artifacts"):
        return

    columns = {column["name"] for column in inspector.get_columns("creator_artifacts")}
    artifact_columns = {
        "original_filename": "VARCHAR(500)",
        "media_path": "VARCHAR(1000)",
        "media_content_type": "VARCHAR(160)",
        "media_size": "INTEGER",
        "generated_metadata": "JSON",
        "archived": "BOOLEAN",
    }
    canon_columns = {
        "source_path": "VARCHAR(1000)",
        "source_hash": "VARCHAR(80)",
        "source_mtime": "VARCHAR(80)",
        "canon_category": "VARCHAR(120)",
        "usable_in_generation": "BOOLEAN",
        "imported_at": "TIMESTAMP",
    }
    draft_columns = {
        "archived": "BOOLEAN",
    }

    with engine.begin() as connection:
        for name, column_type in artifact_columns.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE creator_artifacts ADD COLUMN {name} {column_type}"))

        if inspector.has_table("creator_canon_entries"):
            canon_existing = {
                column["name"] for column in inspector.get_columns("creator_canon_entries")
            }
            for name, column_type in canon_columns.items():
                if name not in canon_existing:
                    connection.execute(
                        text(f"ALTER TABLE creator_canon_entries ADD COLUMN {name} {column_type}")
                    )

        if inspector.has_table("creator_post_drafts"):
            draft_existing = {
                column["name"] for column in inspector.get_columns("creator_post_drafts")
            }
            for name, column_type in draft_columns.items():
                if name not in draft_existing:
                    connection.execute(
                        text(f"ALTER TABLE creator_post_drafts ADD COLUMN {name} {column_type}")
                    )


def get_session():
    if SessionLocal is None:
        configure_database(current_app.config.get("DATABASE_URL"))
    if "db_session" not in g:
        g.db_session = SessionLocal()
    return g.db_session


def close_session(_error=None):
    session = g.pop("db_session", None)
    if session is not None:
        session.close()
    if SessionLocal is not None:
        SessionLocal.remove()
