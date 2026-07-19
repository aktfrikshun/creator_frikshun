from urllib.parse import urlencode
import secrets

import requests


class GoogleOAuth:
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.redirect_uri = redirect_uri or ""

    def configured(self):
        return all((self.client_id, self.client_secret, self.redirect_uri))

    def begin(self):
        if not self.configured():
            raise ValueError("Google SSO is not configured.")
        state = secrets.token_urlsafe(32)
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{self.AUTHORIZATION_URL}?{query}", state

    def exchange(self, code):
        if not self.configured():
            raise ValueError("Google SSO is not configured.")
        response = requests.post(
            self.TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        access_token = response.json().get("access_token")
        if not access_token:
            raise ValueError("Google did not return an access token.")
        user_response = requests.get(
            self.USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        user_response.raise_for_status()
        user = user_response.json()
        if not user.get("email") or not user.get("email_verified"):
            raise ValueError("Google did not return a verified email address.")
        return user
