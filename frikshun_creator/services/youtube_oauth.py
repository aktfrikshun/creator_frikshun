import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests


YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.readonly"


class YouTubeOAuth:
    def __init__(self, client_id="", client_secret="", redirect_uri="", token_path="", scopes=""):
        self.client_id = client_id or os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("YOUTUBE_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("YOUTUBE_REDIRECT_URI", "")
        self.token_path = Path(token_path or os.getenv("YOUTUBE_TOKEN_PATH", "instance/youtube_oauth.json"))
        self.scopes = scopes or YOUTUBE_SCOPES
        self.token_url = "https://oauth2.googleapis.com/token"

    def begin(self):
        if not all((self.client_id, self.client_secret, self.redirect_uri)):
            raise ValueError("YouTube client ID, client secret, and redirect URI are required.")
        state = secrets.token_urlsafe(32)
        query = urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": self.scopes,
            "access_type": "offline", "prompt": "consent", "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}", state

    def exchange(self, code):
        return self.request_tokens({
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "grant_type": "authorization_code", "redirect_uri": self.redirect_uri,
        })

    def refresh(self, refresh_token):
        saved = self.load_tokens()
        refreshed = self.request_tokens({
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }, merge=False)
        refreshed.setdefault("refresh_token", refresh_token)
        refreshed.setdefault("scope", saved.get("scope", ""))
        return self.save_tokens(refreshed)

    def request_tokens(self, data, merge=True):
        response = requests.post(self.token_url, data=data, timeout=30)
        payload = self.response_payload(response)
        if merge:
            payload = {**self.load_tokens(), **payload}
        payload["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in") or 0))
        ).isoformat()
        return self.save_tokens(payload)

    def save_tokens(self, payload):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        return payload

    def load_tokens(self):
        return json.loads(self.token_path.read_text()) if self.token_path.exists() else {}

    def access_token(self):
        tokens = self.load_tokens()
        if tokens.get("expires_at"):
            expiry = datetime.fromisoformat(tokens["expires_at"].replace("Z", "+00:00"))
            if expiry <= datetime.now(timezone.utc) + timedelta(minutes=10):
                tokens = self.refresh(tokens.get("refresh_token", ""))
        if not tokens.get("access_token"):
            raise ValueError("YouTube access token is missing; authorize the channel first.")
        return tokens["access_token"]

    @staticmethod
    def response_payload(response):
        payload = response.json()
        if not response.ok or payload.get("error"):
            error = payload.get("error_description") or payload.get("error") or response.reason
            raise ValueError(str(error))
        return payload
