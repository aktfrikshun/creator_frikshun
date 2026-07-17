from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

import boto3
from PIL import Image, ImageOps


@dataclass
class StoredMedia:
    local_path: Path
    object_key: str
    signed_url: str
    content_type: str = "image/jpeg"


class S3MediaStorage:
    def __init__(
        self,
        bucket,
        region="us-east-1",
        prefix="social",
        presign_seconds=3600,
        client=None,
    ):
        self.bucket = bucket
        self.region = region
        self.prefix = prefix.strip("/")
        self.presign_seconds = int(presign_seconds)
        self.client = client or boto3.client("s3", region_name=region)

    def store_instagram_image(self, source_path, title, local_day=None, output_dir=None):
        if not self.bucket:
            raise ValueError("S3_MEDIA_BUCKET is required for Instagram publishing.")
        source_path = Path(source_path)
        if not source_path.is_file():
            raise ValueError(f"Media file does not exist: {source_path}")

        local_day = local_day or date.today()
        output_dir = Path(output_dir or source_path.parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = self.slug(title) or "recovered-fragment"
        jpeg_path = output_dir / f"{local_day.isoformat()}-{stem}.jpg"
        self.convert_to_jpeg(source_path, jpeg_path)

        object_key = "/".join(
            part
            for part in (
                self.prefix,
                f"{local_day.year:04d}",
                f"{local_day.month:02d}",
                f"{local_day.day:02d}",
                jpeg_path.name,
            )
            if part
        )
        self.client.upload_file(
            str(jpeg_path),
            self.bucket,
            object_key,
            ExtraArgs={
                "ContentType": "image/jpeg",
                "CacheControl": "public, max-age=31536000, immutable",
                "ServerSideEncryption": "AES256",
            },
        )
        signed_url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=self.presign_seconds,
        )
        return StoredMedia(jpeg_path, object_key, signed_url)

    def refresh_signed_url(self, object_key):
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=self.presign_seconds,
        )

    def convert_to_jpeg(self, source_path, destination_path):
        with Image.open(source_path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, "black")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            image.save(destination_path, "JPEG", quality=92, optimize=True, progressive=True)

    def slug(self, value):
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
        return normalized[:80]
