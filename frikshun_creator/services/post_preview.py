from .text import split_tags


PLATFORM_LABELS = {
    "facebook": "Facebook Page",
    "instagram": "Instagram",
    "threads": "Threads",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "x": "X",
    "fanvue": "FanVue",
    "chlokat_archive": "ChloKat Archive",
}


def platform_label(platform):
    return PLATFORM_LABELS.get(platform, platform.replace("_", " ").title())


def post_text(draft):
    hashtag_text = " ".join(f"#{tag.lstrip('#')}" for tag in draft.hashtags)
    parts = [draft.caption.strip()]

    if draft.call_to_action:
        parts.append(draft.call_to_action.strip())
    if hashtag_text:
        parts.append(hashtag_text)

    return "\n\n".join(part for part in parts if part)


def platform_summary(draft):
    artifact = draft.artifact
    base = artifact.summary or "No artifact summary has been entered yet."

    summaries = {
        "facebook": (
            "Facebook draft: lore-forward, conversational, and built for a Page post. "
            "It should invite discussion while pointing people back toward the archive."
        ),
        "instagram": (
            "Instagram draft: visual, concise, and atmospheric. It should feel native to "
            "a post or carousel caption without overexplaining the canon."
        ),
        "threads": (
            "Threads draft: conversational and idea-forward, with enough atmosphere to feel "
            "personal without collapsing into a generic status update."
        ),
        "youtube": (
            "YouTube draft: search-friendly and context-rich, suitable for Shorts, "
            "Community posts, or a video description."
        ),
        "tiktok": (
            "TikTok draft: hook-first, brief, and curiosity-driven. It should make the "
            "fragment feel immediate."
        ),
        "x": (
            "X draft: compact and standalone, with a strong hook and minimal hashtags."
        ),
        "fanvue": (
            "FanVue draft: more intimate and exclusive, while keeping Chloe self-possessed "
            "and character-specific."
        ),
        "chlokat_archive": (
            "Archive draft: durable public context for search, discovery, and canon-safe "
            "fan exploration."
        ),
    }

    return {
        "platform": platform_label(draft.platform),
        "intent": summaries.get(draft.platform, "Platform-specific draft ready for review."),
        "artifact": base,
        "post_text": post_text(draft),
        "hashtags_csv": ", ".join(draft.hashtags),
    }


def apply_review_form(draft, form):
    draft.caption = form.get("caption", "").strip()
    draft.call_to_action = form.get("call_to_action", "").strip()
    draft.hashtags = split_tags(form.get("hashtags", ""))
    return draft
