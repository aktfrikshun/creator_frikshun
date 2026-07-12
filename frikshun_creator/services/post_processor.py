import re


class ChloePostProcessor:
    """Final copy pass for generated public posts.

    The generator is allowed to be factual and mechanical. This layer makes the
    result readable, first-person, and closer to Chloe's canon voice.
    """

    PARAGRAPH_STARTERS = (
        "I wanted the image",
        "We built the look",
        "In the moment,",
        "I keep my own counsel",
        "The archive is not asking",
        "What do you think",
        "Archive links",
    )

    DEFAULT_CHARACTER_LIMITS = {
        "facebook": 63206,
        "instagram": 2200,
        "youtube": 5000,
        "tiktok": 2200,
        "x": 280,
        "fanvue": 2000,
        "chlokat_archive": None,
    }

    def __init__(self, generation_context=None):
        self.context = generation_context

    def process_draft(self, draft, character_limit=None):
        processed = dict(draft)
        if processed.get("caption"):
            processed["caption"] = self.process_caption(
                processed["caption"],
                processed.get("platform"),
                character_limit=character_limit,
            )
        return processed

    def process_caption(self, caption, platform=None, character_limit=None):
        text = self._normalize_whitespace(caption)
        text = self._fix_raw_vision_insertions(text)
        text = self._convert_observer_language(text)
        text = self._enforce_voice_signature(text, platform)
        text = self._add_paragraph_breaks(text)
        text = self._normalize_punctuation(text)
        text = self._apply_character_limit(text, character_limit or self._platform_limit(platform))
        return text.strip()

    def _platform_limit(self, platform):
        return self.DEFAULT_CHARACTER_LIMITS.get(platform)

    def _normalize_whitespace(self, text):
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(text).splitlines()]
        normalized = "\n".join(lines)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _fix_raw_vision_insertions(self, text):
        fixed = text
        fixed = re.sub(r"\bfrom a\s+(A|An|The)\s+", "from a ", fixed)
        fixed = re.sub(r"\bfrom an\s+(A|An|The)\s+", "from an ", fixed)
        fixed = re.sub(r"\bin\s+(A|An|The)\s+", lambda match: f"in {match.group(1).lower()} ", fixed)
        fixed = re.sub(r"\bhold\s+(Perhaps|Maybe|Possibly|Likely)\s+", "hold ", fixed)
        fixed = re.sub(r"\babout\s+(Perhaps|Maybe|Possibly|Likely)\s+", "about ", fixed)
        fixed = fixed.replace("hold to show", "show")
        fixed = fixed.replace("thinking about to show", "thinking about what it means to show")
        fixed = fixed.replace("my into", "me into")
        fixed = fixed.replace("my as", "me as")
        return fixed

    def _convert_observer_language(self, text):
        replacements = (
            (r"\bA lone woman\b", "I"),
            (r"\ba lone woman\b", "me"),
            (r"\bA young woman\b", "I"),
            (r"\ba young woman\b", "me"),
            (r"\bA woman\b", "I"),
            (r"\ba woman\b", "me"),
            (r"\bThe woman\b", "I"),
            (r"\bthe woman\b", "me"),
        )
        rewritten = text
        for pattern, replacement in replacements:
            rewritten = re.sub(pattern, replacement, rewritten)
        return rewritten

    def _enforce_voice_signature(self, text, platform):
        if not self._has_voice_guidance() or platform not in ("facebook", "youtube"):
            return text
        signature = "I keep my own counsel"
        if signature in text:
            return text
        return (
            f"{text}\n\n"
            "I keep my own counsel: intelligent, wounded, skeptical of simple stories, "
            "and still drawn toward truth and beauty inside the dark."
        )

    def _has_voice_guidance(self):
        return bool(self.context and self.context.has_chloe_voice_guidance)

    def _add_paragraph_breaks(self, text):
        formatted = text
        for starter in self.PARAGRAPH_STARTERS:
            formatted = re.sub(rf"(?<!\n\n) (?={re.escape(starter)})", "\n\n", formatted)
        return formatted

    def _normalize_punctuation(self, text):
        normalized = re.sub(r"\.{2,}", ".", text)
        normalized = re.sub(r"\s+([,.;:?!])", r"\1", normalized)
        normalized = re.sub(r"([.!?])([A-Z])", r"\1 \2", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    def _apply_character_limit(self, text, limit):
        if not limit or len(text) <= limit:
            return text
        if limit <= 3:
            return "." * limit

        paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        kept = []
        for paragraph in paragraphs:
            candidate = "\n\n".join(kept + [paragraph])
            if len(candidate) <= limit:
                kept.append(paragraph)
                continue
            break

        if kept:
            candidate = "\n\n".join(kept)
            if len(candidate) <= limit:
                return candidate

        return self._truncate_text(text, limit)

    def _truncate_text(self, text, limit):
        target = max(0, limit - 3)
        fragment = text[:target].rstrip()
        sentence_end = max(fragment.rfind("."), fragment.rfind("!"), fragment.rfind("?"))
        if sentence_end >= max(0, target // 2):
            fragment = fragment[: sentence_end + 1].rstrip()
            return fragment if len(fragment) <= limit else fragment[:limit]

        word_break = fragment.rfind(" ")
        if word_break >= max(0, target // 2):
            fragment = fragment[:word_break].rstrip()

        return f"{fragment}..."[:limit]
