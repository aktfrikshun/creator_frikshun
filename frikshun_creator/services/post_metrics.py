from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models import MetricsPollRun, PostInteraction, PostMetricSnapshot, PostPublication
from ..publishers import FacebookAdapter, InstagramAdapter, ThreadsAdapter, XAdapter, FanvueAdapter
from .threads_oauth import ThreadsOAuth


@dataclass
class PollMetricsResult:
    scanned: int = 0
    snapshots_created: int = 0
    interactions_created: int = 0
    interactions_updated: int = 0
    skipped: int = 0
    marked_unpublished: int = 0
    errors: list = field(default_factory=list)


class PostMetricsPoller:
    def __init__(self, session, adapters=None):
        self.session = session
        self.adapters = adapters or {
            "facebook": FacebookAdapter(),
            "instagram": InstagramAdapter(),
            "threads": ThreadsAdapter(oauth=ThreadsOAuth()),
            "x": XAdapter(),
            "fanvue": FanvueAdapter(),
        }

    def run(self, platform=None, source="scheduler"):
        result = PollMetricsResult()
        started_at = datetime.now(timezone.utc)
        poll_run = MetricsPollRun(source=source, status="running", started_at=started_at)
        self.session.add(poll_run)
        blocked_platforms = set()
        query = (
            self.session.query(PostPublication)
            .filter(PostPublication.status == "published")
            .filter(PostPublication.external_post_id != "")
            .order_by(PostPublication.created_at.desc())
        )
        if platform:
            query = query.filter(PostPublication.platform == platform)

        for publication in query.all():
            result.scanned += 1
            if publication.platform in blocked_platforms:
                result.skipped += 1
                continue
            if publication.external_post_id.startswith("dry-run-"):
                result.skipped += 1
                continue
            adapter = self.adapters.get(publication.platform)
            if not adapter:
                result.skipped += 1
                continue

            try:
                metrics = adapter.fetch_post_metrics(publication)
                self.session.add(self.snapshot_for(publication, metrics))
                result.snapshots_created += 1

                for interaction_data in adapter.fetch_post_interactions(publication):
                    created = self.upsert_interaction(publication, interaction_data)
                    if created:
                        result.interactions_created += 1
                    else:
                        result.interactions_updated += 1
            except Exception as exc:
                if self.is_post_not_found(exc):
                    publication.status = "not_found"
                    publication.error_message = str(exc)
                    publication.post_draft.status = "approved"
                    result.marked_unpublished += 1
                else:
                    result.errors.append(
                        f"{publication.platform} {publication.external_post_id}: {exc}"
                    )
                    if self.is_platform_auth_failure(exc):
                        blocked_platforms.add(publication.platform)

        poll_run.status = "partial" if result.errors else "succeeded"
        poll_run.scanned = result.scanned
        poll_run.snapshots_created = result.snapshots_created
        poll_run.interactions_created = result.interactions_created
        poll_run.errors_count = len(result.errors)
        poll_run.error_message = "\n".join(result.errors[:10])
        poll_run.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return result

    def is_post_not_found(self, error):
        message = str(error or "").lower()
        return any(
            marker in message
            for marker in (
                "post not found",
                "media with id",  # Meta's deleted/unavailable media wording.
                "object with id",
                "requested resource does not exist",
                "does not exist, cannot be loaded",
                "could not find",
            )
        ) and not any(
            marker in message
            for marker in (
                "access token",
                "session has expired",
                "api access deactivated",
                "application has been deleted",
                "rate limit",
            )
        )

    def is_platform_auth_failure(self, error):
        message = str(error or "").lower()
        return any(
            marker in message
            for marker in (
                "access token",
                "session has expired",
                "invalid oauth",
                "api access deactivated",
                "application has been deleted",
            )
        )

    def snapshot_for(self, publication, metrics):
        return PostMetricSnapshot(
            post_publication_id=publication.id,
            platform=metrics.platform,
            external_post_id=metrics.external_post_id,
            external_url=metrics.external_url,
            views=metrics.views,
            likes=metrics.likes,
            comments=metrics.comments,
            shares=metrics.shares,
            saves=metrics.saves,
            clicks=metrics.clicks,
            reach=metrics.reach,
            raw_metrics=metrics.raw_metrics,
            fetched_at=datetime.now(timezone.utc),
        )

    def upsert_interaction(self, publication, interaction_data):
        interaction = (
            self.session.query(PostInteraction)
            .filter(PostInteraction.platform == interaction_data.platform)
            .filter(PostInteraction.external_id == interaction_data.external_id)
            .one_or_none()
        )
        created = interaction is None
        if created:
            interaction = PostInteraction(
                platform=interaction_data.platform,
                external_id=interaction_data.external_id,
                reply_status="pending_review",
            )
            self.session.add(interaction)

        interaction.post_publication_id = publication.id
        interaction.interaction_type = interaction_data.interaction_type
        interaction.external_post_id = interaction_data.external_post_id
        interaction.author_name = interaction_data.author_name
        interaction.author_platform_id = interaction_data.author_platform_id
        interaction.body = interaction_data.body
        interaction.raw_payload = interaction_data.raw_payload
        interaction.received_at = interaction_data.received_at
        interaction.fetched_at = datetime.now(timezone.utc)
        return created


def latest_snapshot_by_publication(publications):
    latest = {}
    for publication in publications:
        snapshots = sorted(
            publication.metric_snapshots,
            key=lambda snapshot: snapshot.fetched_at,
            reverse=True,
        )
        latest[publication.id] = snapshots[0] if snapshots else None
    return latest
