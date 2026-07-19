from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..models import (
    AccountMetricSnapshot,
    AnalyticsSyncRun,
    ContentMetricSnapshot,
    PostPublication,
    RemoteContent,
)


@dataclass
class AccountSyncResult:
    discovered: int = 0
    updated: int = 0
    reconciled: int = 0
    account_snapshots: int = 0
    content_snapshots: int = 0
    unavailable: int = 0
    errors: list[str] = field(default_factory=list)


class AccountAnalyticsSync:
    def __init__(self, session, account, adapter, now=None):
        self.session = session
        self.account = account
        self.adapter = adapter
        self.now = now or datetime.now(timezone.utc)

    def run(self, max_pages=25, page_size=100):
        result = AccountSyncResult()
        previous_run = (
            self.session.query(AnalyticsSyncRun)
            .filter(AnalyticsSyncRun.platform_account_id == self.account.id)
            .filter(AnalyticsSyncRun.status.in_(("failed", "partial")))
            .order_by(AnalyticsSyncRun.started_at.desc())
            .first()
        )
        sync_run = AnalyticsSyncRun(
            platform_account=self.account,
            sync_type="daily",
            status="running",
            started_at=self.now,
            cursor=previous_run.cursor if previous_run and previous_run.cursor else "",
        )
        self.session.add(sync_run)
        self.session.flush()
        try:
            self.collect_account_metrics(result)
            self.discover_content(sync_run, result, max_pages=max_pages, page_size=page_size)
            self.collect_content_metrics(result)
            sync_run.status = "succeeded" if not result.errors else "partial"
        except Exception as error:
            result.errors.append(str(error))
            sync_run.status = "failed"
        sync_run.discovered_count = result.discovered
        sync_run.updated_count = result.updated + result.content_snapshots
        sync_run.error_count = len(result.errors)
        sync_run.error_message = "\n".join(result.errors[:10])
        sync_run.details = {
            "reconciled": result.reconciled,
            "account_snapshots": result.account_snapshots,
            "content_snapshots": result.content_snapshots,
            "unavailable": result.unavailable,
        }
        sync_run.completed_at = self.now
        self.account.last_synced_at = self.now
        self.account.analytics_status = "connected" if sync_run.status == "succeeded" else sync_run.status
        self.session.commit()
        return result

    def collect_account_metrics(self, result):
        try:
            metrics = self.adapter.fetch_account_metrics()
        except NotImplementedError:
            return
        snapshot, created = self.daily_account_snapshot()
        for name in (
            "followers", "following", "content_count", "views", "reach",
            "engagements", "profile_views", "metrics",
        ):
            setattr(snapshot, name, getattr(metrics, name))
        result.account_snapshots += int(created)

    def discover_content(self, sync_run, result, max_pages, page_size):
        cursor = sync_run.cursor or ""
        for _page_number in range(max_pages):
            try:
                page = self.adapter.discover_account_content(cursor=cursor, limit=page_size)
            except NotImplementedError:
                return
            for item in page.items:
                content = self.upsert_remote_content(item, result)
                self.reconcile_publication(content, result)
            cursor = page.next_cursor or ""
            sync_run.cursor = cursor
            self.session.flush()
            if not cursor:
                break

    def upsert_remote_content(self, item, result):
        content = (
            self.session.query(RemoteContent)
            .filter(RemoteContent.platform_account_id == self.account.id)
            .filter(RemoteContent.external_content_id == item.external_content_id)
            .one_or_none()
        )
        if content is None:
            content = RemoteContent(
                platform_account=self.account,
                external_content_id=item.external_content_id,
                discovered_at=self.now,
            )
            self.session.add(content)
            result.discovered += 1
        else:
            result.updated += 1
        content.content_type = item.content_type
        content.title = item.title
        content.body = item.body
        content.permalink = item.permalink
        content.thumbnail_url = item.thumbnail_url
        content.published_at = item.published_at
        content.content_metadata = item.metadata
        content.status = "available"
        content.last_seen_at = self.now
        self.session.flush()
        return content

    def reconcile_publication(self, content, result):
        if content.post_publication_id:
            return
        publication = (
            self.session.query(PostPublication)
            .filter(PostPublication.platform == self.account.platform)
            .filter(PostPublication.external_post_id == content.external_content_id)
            .order_by(PostPublication.created_at.desc())
            .first()
        )
        if publication:
            content.post_publication = publication
            result.reconciled += 1

    def collect_content_metrics(self, result):
        content_rows = (
            self.session.query(RemoteContent)
            .filter(RemoteContent.platform_account_id == self.account.id)
            .filter(RemoteContent.status == "available")
            .all()
        )
        for content in content_rows:
            try:
                metrics = self.adapter.fetch_remote_content_metrics(content)
            except NotImplementedError:
                return
            except Exception as error:
                if self.is_not_found(error):
                    content.status = "unavailable"
                    result.unavailable += 1
                else:
                    result.errors.append(f"{content.external_content_id}: {error}")
                continue
            snapshot, created = self.daily_content_snapshot(content)
            for name in (
                "views", "reach", "likes", "comments", "shares", "saves", "clicks",
                "watch_time_seconds", "average_view_duration_seconds", "metrics",
            ):
                setattr(snapshot, name, getattr(metrics, name, 0 if name != "metrics" else {}))
            result.content_snapshots += int(created)

    def daily_account_snapshot(self):
        start = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        snapshot = (
            self.session.query(AccountMetricSnapshot)
            .filter(AccountMetricSnapshot.platform_account_id == self.account.id)
            .filter(AccountMetricSnapshot.fetched_at >= start)
            .filter(AccountMetricSnapshot.fetched_at < start + timedelta(days=1))
            .one_or_none()
        )
        if snapshot:
            return snapshot, False
        snapshot = AccountMetricSnapshot(platform_account=self.account, fetched_at=self.now)
        self.session.add(snapshot)
        return snapshot, True

    def daily_content_snapshot(self, content):
        start = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        snapshot = (
            self.session.query(ContentMetricSnapshot)
            .filter(ContentMetricSnapshot.remote_content_id == content.id)
            .filter(ContentMetricSnapshot.fetched_at >= start)
            .filter(ContentMetricSnapshot.fetched_at < start + timedelta(days=1))
            .one_or_none()
        )
        if snapshot:
            return snapshot, False
        snapshot = ContentMetricSnapshot(remote_content=content, fetched_at=self.now)
        self.session.add(snapshot)
        return snapshot, True

    @staticmethod
    def is_not_found(error):
        message = str(error).lower()
        return any(marker in message for marker in ("not found", "does not exist", "cannot be found"))
