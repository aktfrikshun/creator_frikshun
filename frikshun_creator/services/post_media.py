from pathlib import Path


def artifact_media_items(artifact):
    if artifact is None:
        return []
    metadata = dict(getattr(artifact, "generated_metadata", None) or {})
    published_content_type = str(metadata.get("public_media_content_type") or "").lower()
    items = [
        {
            "media_path": str(getattr(artifact, "media_path", "") or ""),
            "media_content_type": published_content_type or str(
                getattr(artifact, "media_content_type", "") or ""
            ).lower(),
            "original_filename": str(getattr(artifact, "original_filename", "") or ""),
            "public_media_url": str(metadata.get("public_media_url") or ""),
            "s3_object_key": str(metadata.get("s3_object_key") or ""),
            "primary": True,
        }
    ]
    items.extend(dict(item) for item in metadata.get("additional_media") or [])
    return [item for item in items if str(item.get("media_path") or "").strip()]


def post_media_items(post_draft):
    return artifact_media_items(getattr(post_draft, "artifact", None))


def local_media_paths(post_draft):
    return [
        Path(str(item["media_path"])).expanduser()
        for item in post_media_items(post_draft)
    ]


def media_kind(item):
    content_type = str(item.get("media_content_type") or "").lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    return "unknown"
