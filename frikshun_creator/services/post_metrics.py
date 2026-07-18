from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models import PostInteraction, PostMetricSnapshot, PostPublication
from ..publishers import FacebookAdapter, InstagramAdapter, ThreadsAdapter, XAdapter, FanvueAdapter


@dataclass
class PollMetricsResult:
    scanned: int = 0
    snapshots_created: int = 0
    interactions_created: int = 0
    interactions_updated: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)


class PostMetricsPoller:
    def __init__(self, session, adapters=None):
        self.session = session
        self.adapters = adapters or {
            "facebook": FacebookAdapter(),
            "instagram": InstagramAdapter(),
            "threads": ThreadsAdapter(),
            "x": XAdapter(),
            "fanvue": FanvueAdapter(),
        }

    def run(self, platform=None):
        result = PollMetricsResult()
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
                result.errors.append(
                    f"{publication.platform} {publication.external_post_id}: {exc}"
                )

        self.session.commit()
        return result

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
