from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from PIL import Image

from frikshun_creator.services.s3_media_storage import S3MediaStorage


class S3MediaStorageTest(unittest.TestCase):
    def test_converts_uploads_and_signs_image(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://signed.example.test/image.jpg"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGBA", (24, 24), (20, 30, 40, 180)).save(source)
            result = S3MediaStorage(
                bucket="social-bucket",
                prefix="social",
                client=client,
            ).store_instagram_image(
                source,
                "Borrowed Reflections",
                local_day=__import__("datetime").date(2026, 7, 16),
                output_dir=directory,
            )

            self.assertTrue(result.local_path.is_file())
            with Image.open(result.local_path) as uploaded:
                self.assertEqual("JPEG", uploaded.format)
            self.assertEqual(
                "social/2026/07/16/2026-07-16-borrowed-reflections.jpg",
                result.object_key,
            )

        args, kwargs = client.upload_file.call_args
        self.assertEqual("social-bucket", args[1])
        self.assertEqual(result.object_key, args[2])
        self.assertEqual("image/jpeg", kwargs["ExtraArgs"]["ContentType"])
        client.generate_presigned_url.assert_called_once()

    def test_requires_bucket(self):
        with self.assertRaisesRegex(ValueError, "S3_MEDIA_BUCKET"):
            S3MediaStorage(bucket="", client=Mock()).store_instagram_image(
                "/missing.jpg", "Missing"
            )


if __name__ == "__main__":
    unittest.main()
