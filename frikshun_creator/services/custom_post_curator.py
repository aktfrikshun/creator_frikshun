import re

from .text import compact_tags


CUSTOM_POST_PLATFORMS = ("facebook", "instagram", "threads", "x", "fanvue")


class CustomPostCurator:
    """Adapt creator-supplied copy without inventing new facts or changing its meaning."""

    LIMITS = {
        "facebook": 6000,
        "instagram": 2100,
        "threads": 450,
        "x": 250,
        "fanvue": 1900,
    }

    HASHTAG_COUNTS = {
        "facebook": 4,
        "instagram": 10,
        "threads": 4,
        "x": 2,
        "fanvue": 5,
    }

    DEFAULT_TAGS = ("ChloeKatastrophe", "ChloKat", "FrikShun")

    def __init__(self, source_text, tags=None):
        self.source_text = self.normalize(source_text)
        supplied_tags = list(tags or [])
        inline_tags = re.findall(r"(?<!\w)#([A-Za-z0-9_]+)", self.source_text)
        self.tags = compact_tags([*supplied_tags, *inline_tags, *self.DEFAULT_TAGS])

    def curate(self):
        return [self.draft_for(platform) for platform in CUSTOM_POST_PLATFORMS]

    def draft_for(self, platform):
        if platform not in CUSTOM_POST_PLATFORMS:
            raise ValueError(f"Unsupported custom-post platform: {platform}")
        hashtags = self.tags[: self.HASHTAG_COUNTS[platform]]
        limit = self.LIMITS[platform]
        if platform == "x" and hashtags:
            hashtag_text = " ".join(f"#{tag}" for tag in hashtags)
            limit = max(0, 280 - len(hashtag_text) - 2)
        return {
            "platform": platform,
            "caption": self.fit(self.source_text, limit),
            "hashtags": hashtags,
            "call_to_action": "",
            "status": "draft",
        }

    @staticmethod
    def normalize(value):
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(value or "").splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    @classmethod
    def fit(cls, value, limit):
        text = cls.normalize(value)
        if len(text) <= limit:
            return text
        target = max(0, limit - 3)
        fragment = text[:target].rstrip()
        sentence_end = max(fragment.rfind("."), fragment.rfind("!"), fragment.rfind("?"))
        if sentence_end >= target // 2:
            return fragment[: sentence_end + 1]
        word_end = fragment.rfind(" ")
        if word_end >= target // 2:
            fragment = fragment[:word_end].rstrip()
        return f"{fragment}..."
