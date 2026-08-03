from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app
from werkzeug.utils import secure_filename

from ..models import FanFragmentIngestion, FanFragmentMedia


SOURCE_ID_PATTERN = re.compile(r"^FSUB-[A-Z0-9-]{6,64}$")
MEDIA_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
CHECKSUM_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_CLASSIFICATIONS = {
    "cultural_correction",
    "personal_testimony",
    "fan_interpretation",
    "proposed_artifact",
    "artwork_or_music",
    "timeline_or_location_clue",
    "canon_contradiction",
    "collaboration_proposal",
    "other",
}
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 250 * 1024 * 1024
MAX_ATTACHMENTS = 10
MAX_ENVELOPE_BYTES = 256 * 1024
ALLOWED_ENVELOPE_KEYS = {
    "schema_version",
    "source_submission_id",
    "classification",
    "title",
    "candidate_text",
    "provenance_summary",
    "source_urls",
    "attribution",
    "attachments",
}


class EnvelopeError(ValueError):
    pass


def configured_token():
    return current_app.config.get("FAN_FRAGMENT_INGEST_TOKEN") or os.getenv(
        "FAN_FRAGMENT_INGEST_TOKEN", ""
    )


def authorized_request(auth_header):
    expected = configured_token()
    supplied = str(auth_header or "")
    if not expected or not supplied.startswith("Bearer "):
        return False
    return hmac.compare_digest(supplied.removeprefix("Bearer ").strip(), expected)


def validate_envelope(payload):
    if not isinstance(payload, dict):
        raise EnvelopeError("The request body must be a JSON object.")
    unknown = set(payload) - ALLOWED_ENVELOPE_KEYS
    if unknown:
        raise EnvelopeError(f"Unsupported fields: {', '.join(sorted(unknown))}.")
    if payload.get("schema_version") != 1:
        raise EnvelopeError("schema_version must be 1.")
    source_id = str(payload.get("source_submission_id") or "").strip()
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise EnvelopeError("source_submission_id is invalid.")
    classification = str(payload.get("classification") or "").strip()
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise EnvelopeError("classification is invalid.")
    title = str(payload.get("title") or "").strip()
    if not title or len(title) > 240:
        raise EnvelopeError("title is required and must not exceed 240 characters.")
    candidate_text = str(payload.get("candidate_text") or "").strip()
    provenance = str(payload.get("provenance_summary") or "").strip()
    if len(candidate_text) > 50_000 or len(provenance) > 20_000:
        raise EnvelopeError("Text fields exceed the supported size.")
    source_urls = payload.get("source_urls") or []
    if not isinstance(source_urls, list) or len(source_urls) > 10:
        raise EnvelopeError("source_urls must be a list of at most 10 URLs.")
    for source_url in source_urls:
        parsed = urlparse(str(source_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise EnvelopeError("source_urls contains an invalid URL.")
    attribution = payload.get("attribution") or {}
    if not isinstance(attribution, dict) or set(attribution) - {"display_name", "preference"}:
        raise EnvelopeError("attribution contains unsupported fields.")
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
        raise EnvelopeError(f"attachments must contain at most {MAX_ATTACHMENTS} items.")
    seen_media_ids = set()
    validated_attachments = []
    for item in attachments:
        if not isinstance(item, dict) or set(item) - {
            "media_id",
            "filename",
            "content_type",
            "byte_size",
            "checksum_sha256",
        }:
            raise EnvelopeError("An attachment contains unsupported fields.")
        media_id = str(item.get("media_id") or "").strip()
        filename = secure_filename(str(item.get("filename") or ""))
        content_type = str(item.get("content_type") or "").lower().strip()
        checksum = str(item.get("checksum_sha256") or "").lower().strip()
        try:
            byte_size = int(item.get("byte_size"))
        except (TypeError, ValueError) as error:
            raise EnvelopeError("Attachment byte_size is invalid.") from error
        if not MEDIA_ID_PATTERN.fullmatch(media_id) or media_id in seen_media_ids:
            raise EnvelopeError("Attachment media_id is missing or duplicated.")
        if not filename or content_type not in ALLOWED_CONTENT_TYPES:
            raise EnvelopeError("Attachment filename or content type is invalid.")
        limit = MAX_IMAGE_BYTES if content_type.startswith("image/") else MAX_VIDEO_BYTES
        if byte_size < 1 or byte_size > limit or not CHECKSUM_PATTERN.fullmatch(checksum):
            raise EnvelopeError("Attachment size or checksum is invalid.")
        seen_media_ids.add(media_id)
        validated_attachments.append(
            {
                "media_id": media_id,
                "filename": filename,
                "content_type": content_type,
                "byte_size": byte_size,
                "checksum_sha256": checksum,
            }
        )
    if not candidate_text and not source_urls and not validated_attachments:
        raise EnvelopeError("At least one text, link, or media fragment is required.")
    return {
        "schema_version": 1,
        "source_submission_id": source_id,
        "classification": classification,
        "title": title,
        "candidate_text": candidate_text,
        "provenance_summary": provenance,
        "source_urls": [str(value) for value in source_urls],
        "attribution": {
            "display_name": str(attribution.get("display_name") or "").strip()[:240],
            "preference": str(attribution.get("preference") or "anonymous").strip()[:40],
        },
        "attachments": validated_attachments,
    }


def build_ingestion(validated, idempotency_key):
    return FanFragmentIngestion(
        ingestion_id=f"CFI-{secrets.token_hex(8).upper()}",
        source_submission_id=validated["source_submission_id"],
        idempotency_key=idempotency_key,
        schema_version=validated["schema_version"],
        classification=validated["classification"],
        title=validated["title"],
        candidate_text=validated["candidate_text"],
        provenance_summary=validated["provenance_summary"],
        source_urls=validated["source_urls"],
        attribution=validated["attribution"],
        attachment_manifest=validated["attachments"],
        status="awaiting_media" if validated["attachments"] else "staged",
    )


def store_uploaded_media(session, ingestion, expected, uploaded):
    if uploaded is None or not uploaded.filename:
        raise EnvelopeError("A media file is required.")
    if str(uploaded.mimetype or "").lower() != expected["content_type"]:
        raise EnvelopeError("Uploaded media content type does not match its manifest.")
    data = uploaded.read(expected["byte_size"] + 1)
    if len(data) != expected["byte_size"]:
        raise EnvelopeError("Uploaded media size does not match its manifest.")
    checksum = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(checksum, expected["checksum_sha256"]):
        raise EnvelopeError("Uploaded media checksum does not match its manifest.")
    existing = next((item for item in ingestion.media if item.media_id == expected["media_id"]), None)
    if existing:
        if hmac.compare_digest(existing.checksum_sha256, checksum):
            return existing, False
        raise EnvelopeError("This media identifier was already uploaded with different content.")
    directory = (
        Path(current_app.config["UPLOAD_FOLDER"])
        / "fan_fragment_inbox"
        / ingestion.ingestion_id
    )
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{expected['media_id']}-{expected['filename']}"
    destination = directory / filename
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(destination)
    media = FanFragmentMedia(
        media_id=expected["media_id"],
        filename=expected["filename"],
        content_type=expected["content_type"],
        byte_size=expected["byte_size"],
        checksum_sha256=checksum,
        storage_path=str(destination.resolve()),
    )
    ingestion.media.append(media)
    if len(ingestion.media) == len(ingestion.attachment_manifest or []):
        ingestion.status = "staged"
    session.add(ingestion)
    return media, True
