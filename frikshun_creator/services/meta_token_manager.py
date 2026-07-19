from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile

import requests


class MetaTokenManager:
    def __init__(self, app_id, app_secret, page_id, graph_version="v25.0", env_path=".env"):
        self.app_id = str(app_id or "")
        self.app_secret = str(app_secret or "")
        self.page_id = str(page_id or "")
        self.graph_version = str(graph_version or "v25.0")
        self.env_path = Path(env_path)

    def upgrade(self, short_lived_user_token):
        if not all((self.app_id, self.app_secret, self.page_id, short_lived_user_token)):
            raise ValueError("Meta app ID, app secret, Page ID, and current user token are required.")

        exchange = requests.get(
            f"https://graph.facebook.com/{self.graph_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_lived_user_token,
            },
            timeout=30,
        )
        long_payload = self.response_payload(exchange)
        long_token = str(long_payload.get("access_token") or "")
        if not long_token:
            raise ValueError("Meta did not return a long-lived user token.")

        page_response = requests.get(
            f"https://graph.facebook.com/{self.graph_version}/{self.page_id}",
            params={"fields": "id,name,access_token", "access_token": long_token},
            timeout=30,
        )
        page_payload = self.response_payload(page_response)
        page_token = str(page_payload.get("access_token") or "")
        if not page_token:
            raise ValueError("Meta did not return a Page token from the long-lived user token.")

        self.update_env(
            {
                "META_LONG_LIVED_USER_ACCESS_TOKEN": long_token,
                "INSTAGRAM_ACCESS_TOKEN": long_token,
                "FACEBOOK_PAGE_ACCESS_TOKEN": page_token,
            }
        )
        expires_in = int(long_payload.get("expires_in") or 0)
        return {
            "page_id": str(page_payload.get("id") or self.page_id),
            "page_name": str(page_payload.get("name") or ""),
            "token_type": str(long_payload.get("token_type") or "bearer"),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat() if expires_in else "",
        }

    def update_env(self, updates):
        existing = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        remaining = dict(updates)
        output = []
        for line in existing:
            key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        output.extend(f"{key}={value}" for key, value in remaining.items())
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        mode = self.env_path.stat().st_mode & 0o777 if self.env_path.exists() else 0o600
        descriptor, temporary_name = tempfile.mkstemp(prefix=".meta-token-", dir=str(self.env_path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write("\n".join(output) + "\n")
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, self.env_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def response_payload(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = (payload.get("error") or {}).get("message") or payload.get("error_description") or response.reason
            raise ValueError(str(message))
        return payload
