from dataclasses import dataclass

from ..models import PlatformAccount


@dataclass(frozen=True)
class PlatformCapabilities:
    publishing_mode: str
    account_metrics: bool = True
    content_discovery: bool = True
    content_metrics: bool = True
    interactions: bool = False
    automated_publishing: bool = False
    historical_backfill: bool = True

    def as_dict(self):
        return {
            "account_metrics": self.account_metrics,
            "content_discovery": self.content_discovery,
            "content_metrics": self.content_metrics,
            "interactions": self.interactions,
            "automated_publishing": self.automated_publishing,
            "historical_backfill": self.historical_backfill,
        }


PLATFORM_CAPABILITIES = {
    "facebook": PlatformCapabilities("automatic", interactions=True, automated_publishing=True),
    "instagram": PlatformCapabilities("automatic", interactions=True, automated_publishing=True),
    "threads": PlatformCapabilities("automatic", interactions=True, automated_publishing=True),
    "x": PlatformCapabilities("automatic", interactions=True, automated_publishing=True),
    "fanvue": PlatformCapabilities("automatic", interactions=True, automated_publishing=True),
    "tiktok": PlatformCapabilities("manual"),
    "youtube": PlatformCapabilities("manual", interactions=True),
}


ANALYTICS_CREDENTIALS = {
    "facebook": ("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"),
    "instagram": ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"),
    "threads": ("THREADS_ACCESS_TOKEN",),
    "x": ("X_BEARER_TOKEN",),
    "fanvue": ("FANVUE_CLIENT_ID", "FANVUE_CLIENT_SECRET"),
    "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"),
    "youtube": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI"),
}


def synchronize_account_registry(session, config):
    accounts = {account.platform: account for account in session.query(PlatformAccount).all()}
    for platform, definition in PLATFORM_CAPABILITIES.items():
        account = accounts.get(platform)
        if account is None:
            account = PlatformAccount(platform=platform, active=True)
            session.add(account)
            accounts[platform] = account

        account.publishing_mode = definition.publishing_mode
        account.capabilities = {**definition.as_dict(), **(account.capabilities or {})}
        configured = all(config.get(key) for key in ANALYTICS_CREDENTIALS[platform])
        if account.analytics_status in (None, "not_connected", "credentials_missing"):
            account.analytics_status = "configured" if configured else "credentials_missing"
        if account.oauth_status in (None, "manual") and configured:
            account.oauth_status = "configured"
    session.commit()
    return [accounts[platform] for platform in PLATFORM_CAPABILITIES]
