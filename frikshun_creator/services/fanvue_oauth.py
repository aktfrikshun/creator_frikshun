import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests


FANVUE_SCOPES = (
    "openid offline_access offline read:self read:post write:post "
    "read:media write:media read:insights"
)


class FanvueOAuth:
    authorization_url = "https://auth.fanvue.com/oauth2/auth"
    token_url = "https://auth.fanvue.com/oauth2/token"

    def __init__(self, client_id=None, client_secret=None, redirect_uri=None, token_path=None):
        self.client_id = client_id or os.getenv("FANVUE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("FANVUE_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("FANVUE_REDIRECT_URI", "")
        self.token_path = Path(token_path or "instance/fanvue_oauth.json")

    def begin(self):
        if not all((self.client_id, self.client_secret, self.redirect_uri)):
            raise ValueError("FanVue client ID, secret, and redirect URI are required.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        state = secrets.token_urlsafe(32)
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": FANVUE_SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.authorization_url}?{query}", state, verifier

    def exchange(self, code, verifier):
        response = requests.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        payload = self.response_payload(response)
        return self.save_tokens(payload)

    def refresh(self, refresh_token=None):
        current = self.load_tokens()
        token = refresh_token or current.get("refresh_token")
        if not token:
            raise ValueError("FanVue refresh token is missing; authorize the app first.")
        response = requests.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": token,
            },
            timeout=30,
        )
        payload = self.response_payload(response)
        if not payload.get("refresh_token"):
            payload["refresh_token"] = token
        return self.save_tokens(payload)

    def save_tokens(self, payload):
        saved = dict(payload)
        saved["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in") or 3600))
        ).isoformat()
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        return saved

    def load_tokens(self):
        if not self.token_path.exists():
            return {}
        return json.loads(self.token_path.read_text(encoding="utf-8"))

    def access_token(self):
        tokens = self.load_tokens()
        expires_at = tokens.get("expires_at")
        if expires_at:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry <= datetime.now(timezone.utc) + timedelta(minutes=5):
                tokens = self.refresh(tokens.get("refresh_token"))
        token = str(tokens.get("access_token") or "")
        if not token:
            raise ValueError("FanVue access token is missing; authorize the app first.")
        return token

    def response_payload(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = payload.get("error_description") or payload.get("error") or response.reason
            raise ValueError(str(message))
        return payload
