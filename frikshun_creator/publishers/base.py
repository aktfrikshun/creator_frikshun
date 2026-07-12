from dataclasses import dataclass, field


@dataclass
class PublishResult:
    success: bool
    status: str
    external_post_id: str = ""
    external_url: str = ""
    error_message: str = ""
    raw_response: dict = field(default_factory=dict)


class PublisherAdapter:
    platform = "base"

    def validate(self, post_draft):
        if not post_draft.caption.strip():
            return PublishResult(
                success=False,
                status="failed",
                error_message="Draft caption cannot be blank.",
            )
        return PublishResult(success=True, status="validated")

    def prepare(self, post_draft):
        hashtag_text = " ".join(f"#{tag.lstrip('#')}" for tag in post_draft.hashtags)
        parts = [post_draft.caption.strip()]

        if post_draft.call_to_action:
            parts.append(post_draft.call_to_action.strip())
        if hashtag_text:
            parts.append(hashtag_text)

        return "\n\n".join(parts)

    def publish(self, post_draft):
        raise NotImplementedError
