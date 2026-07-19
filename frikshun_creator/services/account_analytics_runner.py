from dataclasses import dataclass, field
from pathlib import Path

from ..publishers import TikTokAnalyticsAdapter, YouTubeAnalyticsAdapter
from .account_analytics import AccountAnalyticsSync, AccountSyncResult
from .analytics_accounts import synchronize_account_registry
from .tiktok_oauth import TikTokOAuth
from .youtube_oauth import YouTubeOAuth


@dataclass
class AccountAnalyticsRunResult:
    platform_results: dict[str, AccountSyncResult] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def errors(self):
        return [
            f"{platform}: {error}"
            for platform, result in self.platform_results.items()
            for error in result.errors
        ]


class AccountAnalyticsRunner:
    """Run account-wide analytics for OAuth platforms with stored grants."""

    def __init__(self, session, config, now=None):
        self.session = session
        self.config = config
        self.now = now

    def run(self, platforms=None):
        requested = set(platforms or ("youtube", "tiktok"))
        accounts = {
            account.platform: account
            for account in synchronize_account_registry(self.session, self.config)
        }
        result = AccountAnalyticsRunResult()
        for platform in ("youtube", "tiktok"):
            if platform not in requested:
                continue
            token_path = Path(self.config.get(f"{platform.upper()}_TOKEN_PATH", ""))
            if not token_path.is_file():
                result.skipped[platform] = "OAuth authorization has not been completed"
                continue
            adapter = self.adapter_for(platform)
            result.platform_results[platform] = AccountAnalyticsSync(
                self.session,
                accounts[platform],
                adapter,
                now=self.now,
            ).run()
        return result

    def adapter_for(self, platform):
        if platform == "youtube":
            oauth = YouTubeOAuth(
                client_id=self.config.get("YOUTUBE_CLIENT_ID"),
                client_secret=self.config.get("YOUTUBE_CLIENT_SECRET"),
                redirect_uri=self.config.get("YOUTUBE_REDIRECT_URI"),
                token_path=self.config.get("YOUTUBE_TOKEN_PATH"),
            )
            return YouTubeAnalyticsAdapter(oauth)
        if platform == "tiktok":
            oauth = TikTokOAuth(
                client_key=self.config.get("TIKTOK_CLIENT_KEY"),
                client_secret=self.config.get("TIKTOK_CLIENT_SECRET"),
                redirect_uri=self.config.get("TIKTOK_REDIRECT_URI"),
                token_path=self.config.get("TIKTOK_TOKEN_PATH"),
            )
            return TikTokAnalyticsAdapter(oauth)
        raise ValueError(f"Unsupported account analytics platform: {platform}")
