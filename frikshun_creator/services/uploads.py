from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename


def save_artifact_file(file_storage, upload_root):
    if not file_storage or not file_storage.filename:
        return {
            "original_filename": "",
            "media_path": "",
            "media_content_type": "",
            "media_size": 0,
        }

    original_filename = file_storage.filename
    safe_name = secure_filename(original_filename) or "artifact"
    stored_name = f"{uuid4()}-{safe_name}"
    target_dir = Path(upload_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / stored_name
    file_storage.save(target_path)

    return {
        "original_filename": original_filename,
        "media_path": str(target_path),
        "media_content_type": file_storage.mimetype or "",
        "media_size": target_path.stat().st_size,
    }


def archive_media_filename(media_path, title, fragment_code):
    if not media_path:
        return {
            "media_path": "",
            "stored_filename": "",
        }

    path = Path(media_path)
    if not path.exists():
        return {
            "media_path": media_path,
            "stored_filename": path.name,
        }

    slug = secure_filename(title.lower().replace(" ", "-")) or "artifact"
    stored_name = f"{fragment_code.lower()}-{slug}{path.suffix.lower()}"
    target_path = path.with_name(stored_name)
    if target_path != path:
        counter = 2
        while target_path.exists():
            target_path = path.with_name(f"{fragment_code.lower()}-{slug}-{counter}{path.suffix.lower()}")
            counter += 1
        path.rename(target_path)

    return {
        "media_path": str(target_path),
        "stored_filename": target_path.name,
    }


def next_fragment_code(session, artifact_model):
    last_id = session.query(artifact_model.id).order_by(artifact_model.id.desc()).limit(1).scalar()
    return f"CK-{(last_id or 0) + 1:06d}"
