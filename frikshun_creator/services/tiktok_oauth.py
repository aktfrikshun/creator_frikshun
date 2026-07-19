import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests


TIKTOK_SCOPES = "user.info.basic,user.info.profile,user.info.stats,video.list"


class TikTokOAuth:
    def __init__(self, client_key="", client_secret="", redirect_uri="", token_path="", scopes=""):
        self.client_key = client_key or os.getenv("TIKTOK_CLIENT_KEY", "")
        self.client_secret = client_secret or os.getenv("TIKTOK_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("TIKTOK_REDIRECT_URI", "")
        self.token_path = Path(token_path or os.getenv("TIKTOK_TOKEN_PATH", "instance/tiktok_oauth.json"))
        self.scopes = scopes or os.getenv("TIKTOK_SCOPES", TIKTOK_SCOPES)
        self.token_url = "https://open.tiktokapis.com/v2/oauth/token/"

    def begin(self):
        if not all((self.client_key, self.client_secret, self.redirect_uri)):
            raise ValueError("TikTok client key, client secret, and redirect URI are required.")
        state = secrets.token_urlsafe(32)
        query = urlencode({
            "client_key": self.client_key,
            "scope": self.scopes,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
        })
        return f"https://www.tiktok.com/v2/auth/authorize/?{query}", state

    def exchange(self, code):
        return self.request_tokens({
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        })

    def refresh(self, refresh_token):
        return self.request_tokens({
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def request_tokens(self, data):
        response = requests.post(self.token_url, data=data, timeout=30)
        payload = self.response_payload(response)
        expires_in = int(payload.get("expires_in") or 0)
        payload["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
        return self.save_tokens(payload)

    def save_tokens(self, payload):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        return payload

    def load_tokens(self):
        if not self.token_path.exists():
            return {}
        return json.loads(self.token_path.read_text(encoding="utf-8"))

    def access_token(self):
        tokens = self.load_tokens()
        expires_at = tokens.get("expires_at")
        if expires_at:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry <= datetime.now(timezone.utc) + timedelta(hours=1):
                refresh_token = tokens.get("refresh_token")
                if not refresh_token:
                    raise ValueError("TikTok refresh token is missing; reconnect the account.")
                tokens = self.refresh(refresh_token)
        token = tokens.get("access_token")
        if not token:
            raise ValueError("TikTok access token is missing; authorize the account first.")
        return token

    @staticmethod
    def response_payload(response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"error_description": response.text}
        if not response.ok or payload.get("error"):
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else error
            raise ValueError(str(message or payload.get("error_description") or response.reason))
        return payload
