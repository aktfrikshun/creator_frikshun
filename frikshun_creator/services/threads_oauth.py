import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests


THREADS_SCOPES = (
    "threads_basic,threads_content_publish,threads_read_replies,"
    "threads_manage_replies,threads_manage_insights"
)


class ThreadsOAuth:
    def __init__(
        self,
        app_id=None,
        app_secret=None,
        redirect_uri=None,
        token_path=None,
        auth_url=None,
        api_base_url=None,
        scopes=None,
    ):
        self.app_id = app_id or os.getenv("THREADS_APP_ID", "") or os.getenv("THREADS_CLIENT_ID", "")
        self.app_secret = app_secret or os.getenv("THREADS_APP_SECRET", "") or os.getenv("THREADS_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("THREADS_REDIRECT_URI", "")
        self.token_path = Path(token_path or os.getenv("THREADS_TOKEN_PATH", "instance/threads_oauth.json"))
        self.auth_url = auth_url or os.getenv("THREADS_AUTH_URL", "https://threads.net/oauth/authorize")
        self.api_base_url = (api_base_url or os.getenv("THREADS_API_BASE_URL", "https://graph.threads.net")).rstrip("/")
        self.scopes = scopes or os.getenv("THREADS_SCOPES", THREADS_SCOPES)

    def begin(self, persist_state=False):
        if not all((self.app_id, self.app_secret, self.redirect_uri)):
            raise ValueError("Threads app ID, secret, and redirect URI are required.")
        state = secrets.token_urlsafe(32)
        if persist_state:
            self.save_state(state)
        query = urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.scopes,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{self.auth_url}?{query}", state

    @property
    def state_path(self):
        return self.token_path.with_suffix(f"{self.token_path.suffix}.state")

    def save_state(self, state):
        payload = {"state": state, "created_at": datetime.now(timezone.utc).isoformat()}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(self.state_path, 0o600)

    def pop_state(self):
        if not self.state_path.exists():
            return ""
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        finally:
            self.state_path.unlink(missing_ok=True)
        return str(payload.get("state") or "")

    def exchange(self, code):
        response = requests.post(
            f"{self.api_base_url}/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        payload = self.response_payload(response)
        payload["short_lived_access_token"] = payload.get("access_token", "")
        long_lived = self.exchange_long_lived_token(payload["short_lived_access_token"])
        payload.update(
            {
                "access_token": long_lived.get("access_token", payload.get("access_token", "")),
                "long_lived_access_token": long_lived.get("access_token", ""),
                "token_type": long_lived.get("token_type", payload.get("token_type", "bearer")),
                "expires_in": long_lived.get("expires_in", payload.get("expires_in", 0)),
            }
        )
        return self.save_tokens(payload)

    def exchange_long_lived_token(self, short_lived_token):
        if not short_lived_token:
            raise ValueError("Threads short-lived access token is missing; authorize the app first.")
        response = requests.get(
            f"{self.api_base_url}/access_token",
            params={
                "grant_type": "th_exchange_token",
                "client_secret": self.app_secret,
                "access_token": short_lived_token,
            },
            timeout=30,
        )
        return self.response_payload(response)

    def refresh(self, access_token=None):
        tokens = self.load_tokens()
        token = access_token or tokens.get("long_lived_access_token") or tokens.get("access_token")
        if not token:
            raise ValueError("Threads long-lived access token is missing; authorize the app first.")
        response = requests.get(
            f"{self.api_base_url}/refresh_access_token",
            params={
                "grant_type": "th_refresh_token",
                "access_token": token,
            },
            timeout=30,
        )
        payload = self.response_payload(response)
        if not payload.get("access_token"):
            payload["access_token"] = token
        payload.setdefault("long_lived_access_token", payload["access_token"])
        payload.setdefault("token_type", tokens.get("token_type", "bearer"))
        payload.setdefault("user_id", tokens.get("user_id", ""))
        payload.setdefault("short_lived_access_token", tokens.get("short_lived_access_token", ""))
        return self.save_tokens(payload)

    def save_tokens(self, payload):
        saved = dict(payload)
        expires_in = int(saved.get("expires_in") or 0)
        if expires_in > 0:
            saved["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
        else:
            saved["expires_at"] = ""
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
            if expiry <= datetime.now(timezone.utc) + timedelta(days=7):
                tokens = self.refresh(tokens.get("long_lived_access_token") or tokens.get("access_token"))
        token = str(tokens.get("long_lived_access_token") or tokens.get("access_token") or "")
        if not token:
            raise ValueError("Threads access token is missing; authorize the app first.")
        return token

    def response_payload(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}
        if not response.ok:
            message = payload.get("error", {}).get("message") or payload.get("error_description") or response.reason
            raise ValueError(str(message))
        return payload
