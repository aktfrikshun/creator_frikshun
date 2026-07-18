from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import requests


class KlingCliError(ValueError):
    pass


class KlingCliClient:
    """Small adapter around the official Kling CLI.

    Generation is deliberately explicit: constructing the client or running the
    test suite never contacts Kling or consumes credits.
    """

    def __init__(
        self,
        executable=None,
        model=None,
        poll_seconds=None,
        enable_audio=None,
        runner=None,
        downloader=None,
    ):
        self.executable = executable or os.getenv("KLING_CLI_BIN", "kling")
        self.model = model or os.getenv("KLING_VIDEO_MODEL", "kling-video-v3_0")
        self.poll_seconds = int(poll_seconds or os.getenv("KLING_POLL_SECONDS", "600"))
        if enable_audio is None:
            enable_audio = os.getenv("KLING_ENABLE_AUDIO", "true")
        self.enable_audio = str(enable_audio).lower() in ("1", "true", "yes", "on")
        self.runner = runner or subprocess.run
        self.downloader = downloader or requests.get

    def generate_clip(self, image_path, prompt, duration_seconds, output_path, tail_image_path=None):
        image_path = Path(image_path)
        output_path = Path(output_path)
        if not image_path.exists():
            raise KlingCliError(f"Kling source frame does not exist: {image_path}")

        duration = max(3, min(15, round(float(duration_seconds))))
        command = [
            self.executable,
            "image_to_video",
            "--model",
            self.model,
            "--image",
            str(image_path),
        ]
        if tail_image_path:
            command.extend(["--tailImage", str(Path(tail_image_path))])
        command.extend(
            [
                prompt,
                "--duration",
                str(duration),
                "--enable_audio",
                str(self.enable_audio).lower(),
                "--prefer_multi_shots",
                "false",
                "--poll",
                str(self.poll_seconds),
                "--quiet",
            ]
        )

        completed = self.runner(command, capture_output=True, text=True)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "unknown Kling CLI error").strip()
            raise KlingCliError(f"Kling clip generation failed: {message}")

        payload = self.parse_json(completed.stdout)
        work = self.find_work(payload)
        url = work.get("url_without_watermark") or work.get("url")
        if not url:
            generation_id = self.find_value(payload, ("generation_id", "generationId"))
            suffix = f" Generation ID: {generation_id}." if generation_id else ""
            raise KlingCliError(f"Kling completed without a downloadable video URL.{suffix}")

        response = self.downloader(url, timeout=180)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return {
            "generation_id": self.find_value(payload, ("generation_id", "generationId")),
            "url": url,
            "work": work,
        }

    def parse_json(self, value):
        try:
            return json.loads(str(value or "").strip())
        except json.JSONDecodeError as error:
            raise KlingCliError(f"Kling CLI returned invalid JSON: {error}") from error

    def find_work(self, value):
        if isinstance(value, dict):
            works = value.get("works")
            if isinstance(works, list) and works:
                return works[0]
            for child in value.values():
                found = self.find_work(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = self.find_work(child)
                if found:
                    return found
        return {}

    def find_value(self, value, keys):
        if isinstance(value, dict):
            for key in keys:
                if value.get(key) is not None:
                    return value[key]
            for child in value.values():
                found = self.find_value(child, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = self.find_value(child, keys)
                if found is not None:
                    return found
        return None
