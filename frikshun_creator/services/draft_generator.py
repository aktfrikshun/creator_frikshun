import re

from .post_processor import ChloePostProcessor
from .text import compact_tags


PLATFORMS = (
    "facebook",
    "instagram",
    "threads",
    "youtube",
    "tiktok",
    "x",
    "fanvue",
    "chlokat_archive",
)


class ArtifactDraftGenerator:
    def __init__(self, artifact, generation_context=None):
        self.artifact = artifact
        self.context = generation_context
        self.post_processor = ChloePostProcessor(generation_context)

    def generate(self):
        return [self._draft_for(platform) for platform in PLATFORMS]

    def _draft_for(self, platform):
        tags = compact_tags(self.artifact.content_tags + self.artifact.mood_tags)
        title = self.artifact.title
        media = self._media_analysis()
        context = self._chloe_shoot_context(media)
        intention = self._chloe_intention(media)
        craft = self._chloe_craft_note(media)
        thought = self._chloe_moment_note(media)
        voice = self._voice_signature()
        history = self._history_signature()

        rules = {
            "facebook": {
                "caption": (
                    f"{context}\n\n"
                    f"{intention}\n\n"
                    f"{craft}\n\n"
                    f"{thought}\n\n"
                    f"{voice}\n\n"
                    "What do you think I was trying not to say out loud?"
                ),
                "hashtags": tags[:6] or ["ChloeKatastrophe", "ChloKat", "FrikShun"],
                "call_to_action": "Enter the ChloKat archive.",
            },
            "instagram": {
                "caption": (
                    f"{title}.\n\n"
                    f"{context}\n\n"
                    f"{thought}"
                ),
                "hashtags": tags[:10] or ["ChloKat", "VirtualArtist", "RecoveredMemory"],
                "call_to_action": "Follow the signal.",
            },
            "threads": {
                "caption": (
                    f"{title}.\n\n"
                    f"{thought}\n\n"
                    "I am less interested in certainty than in what survives when certainty fails."
                ),
                "hashtags": tags[:5] or ["ChloKat", "RecoveredMemory", "VirtualArtist"],
                "call_to_action": "Stay with the signal.",
            },
            "youtube": {
                "caption": (
                    f"{title} | Chloe Katastrophe recovered fragment\n\n"
                    f"{context}\n\n"
                    f"{intention}\n\n"
                    f"{craft}\n\n"
                    f"{voice}\n\n"
                    "Archive links and related music notes belong in the description."
                ),
                "hashtags": tags[:8] or ["ChloeKatastrophe", "FrikShun"],
                "call_to_action": "Subscribe for the next recovered transmission.",
            },
            "tiktok": {
                "caption": (
                    f"This shot feels like it was not supposed to survive: {title}.\n\n"
                    f"{context}\n\n"
                    "I remember the edge first. The rest is still loading."
                ),
                "hashtags": tags[:5] or ["ChloKat", "AIMusic", "VirtualArtist"],
                "call_to_action": "Follow for the next fragment.",
            },
            "x": {
                "caption": (
                    f"{title}. {self._compact_context(media)} "
                    "Some signals do not arrive clean. Some arrive honest."
                ),
                "hashtags": tags[:3] or ["ChloKat"],
                "call_to_action": "Join the Reconstruction.",
            },
            "fanvue": {
                "caption": (
                    f"{title} is now in the private reconstruction folder.\n\n"
                    f"{context}\n\n"
                    "This one is closer, stranger, and less edited for daylight. "
                    "Not softer. Just nearer."
                ),
                "hashtags": tags[:6] or ["ChloKat", "BehindTheArchive"],
                "call_to_action": "Unlock the private fragment.",
            },
            "chlokat_archive": {
                "caption": (
                    f"{title}\n\n"
                    f"{context}\n\n"
                    f"{intention}\n\n"
                    f"{self.artifact.lore_text or 'Lore expansion pending review.'}\n\n"
                    f"{history}"
                ),
                "hashtags": tags[:12] or ["archive", "recovered-fragment"],
                "call_to_action": "Join the Reconstruction.",
            },
        }

        return self.post_processor.process_draft({"platform": platform, **rules[platform]})

    def _voice_signature(self):
        if self.context and self.context.has_chloe_voice_guidance:
            return (
                "I keep my own counsel: intelligent, wounded, skeptical of simple stories, "
                "and still drawn toward truth and beauty inside the dark."
            )
        return "The archive is not asking for belief. It is asking for attention."

    def _media_analysis(self):
        return (self.artifact.generated_metadata or {}).get("media_analysis") or {}

    def _chloe_shoot_context(self, analysis):
        title = self.artifact.title
        what = self._clean_phrase(self._first_person(analysis.get("what") or "portrait"), remove_article=True)
        where = self._clean_phrase(
            analysis.get("where") or "a room that looked too staged to be innocent"
        )
        when = self._clean_phrase(
            analysis.get("when") or "one of those hours where memory starts lying about the light"
        )
        location_phrase = self._location_phrase(where)

        return (
            f"This shot comes from a {what} shoot we did {location_phrase}.\n"
            f"The timing reads as {when}. We archived it as {title}."
        )

    def _chloe_intention(self, analysis):
        why = self._clean_phrase(self._first_person(analysis.get("why") or ""), remove_uncertainty=True)
        if why:
            if why.startswith("to "):
                return f"I wanted the image {why}."
            return f"I wanted the image to hold {why}."
        return "I wanted the image to feel like evidence, but not the kind that behaves itself."

    def _chloe_craft_note(self, analysis):
        tags = [tag.replace("-", " ") for tag in (analysis.get("mood_tags") or [])[:4]]
        where = self._clean_phrase(analysis.get("where") or "")
        texture = ", ".join(tags) if tags else "shadow, restraint, and one deliberate pulse of light"
        if where:
            return f"We built the look with {texture}, then {self._environment_craft_clause(where)}."
        return f"We built the look with {texture}, then let the frame stay a little dangerous."

    def _chloe_moment_note(self, analysis):
        why = self._clean_phrase(self._first_person(analysis.get("why") or ""), remove_uncertainty=True)
        if why:
            if why.startswith("to "):
                why = f"what it means {why}"
            return (
                f"In the moment, I was thinking about {why}.\n"
                "Or maybe I was thinking about who would notice."
            )
        return (
            "In the moment, I was trying to look like I knew what I remembered.\n"
            "That is not the same thing."
        )

    def _compact_context(self, analysis):
        what = self._clean_phrase(self._first_person(analysis.get("what") or "recovered image"))
        where = self._clean_phrase(analysis.get("where") or "")
        if where:
            return f"I made this {what} {self._location_phrase(where)}."
        return f"I made this {what} and left the clean explanation out of frame."

    def _location_phrase(self, where):
        if not where:
            return "somewhere the archive has not placed yet"
        if re.match(r"^(on|under|inside|outside|near|beside|beneath|at)\b", where, flags=re.IGNORECASE):
            return where
        if re.match(r"^(a|an|the)\s+(beach|shore|coast|pier|boardwalk|street|rooftop|field|desert)\b", where):
            return f"on {where}"
        return f"in {where}"

    def _environment_craft_clause(self, where):
        if re.search(r"\b(beach|ocean|shore|water|pier|sand|tide)\b", where, flags=re.IGNORECASE):
            return f"let the tide, the pier, and the light argue with each other: {where}"
        if re.search(r"\b(street|alley|sidewalk|city|road)\b", where, flags=re.IGNORECASE):
            return f"let the street keep some of the evidence for itself: {where}"
        if re.search(r"\b(room|interior|office|apartment|studio|window|blinds)\b", where, flags=re.IGNORECASE):
            return f"let the room do some of the lying for us: {where}"
        return f"let the setting keep some of the explanation out of reach: {where}"

    def _first_person(self, text):
        if not text:
            return ""
        rewritten = str(text)
        replacements = (
            (r"\bA young woman\b", "I"),
            (r"\ba young woman\b", "me"),
            (r"\bA woman\b", "I"),
            (r"\ba woman\b", "me"),
            (r"\bThe woman\b", "I"),
            (r"\bthe woman\b", "me"),
            (r"\bThe subject\b", "I"),
            (r"\bthe subject\b", "me"),
            (r"\bChloe\b", "me"),
            (r"\bher into\b", "me into"),
            (r"\bHer into\b", "Me into"),
            (r"\bher as\b", "me as"),
            (r"\bHer as\b", "Me as"),
            (r"\bher\b", "my"),
            (r"\bHer\b", "My"),
            (r"\bshe\b", "I"),
            (r"\bShe\b", "I"),
        )
        for pattern, replacement in replacements:
            rewritten = re.sub(pattern, replacement, rewritten)
        return rewritten.strip()

    def _clean_phrase(self, text, remove_article=False, remove_uncertainty=False):
        if not text:
            return ""
        phrase = re.sub(r"\s+", " ", str(text)).strip()
        phrase = phrase.strip(" .;:")
        if remove_uncertainty:
            phrase = re.sub(r"^(perhaps|maybe|possibly|likely)\s+", "", phrase, flags=re.IGNORECASE)
        if remove_article:
            phrase = re.sub(r"^(a|an|the)\s+", "", phrase, flags=re.IGNORECASE)
        if phrase:
            phrase = phrase[0].lower() + phrase[1:]
        return phrase

    def _history_signature(self):
        if self.context and self.context.recent_post_excerpt:
            return "Related posting history has been loaded for tone and continuity review."
        return "No related posting history has been attached yet."


def sample_platform_drafts():
    return [
        {
            "platform": platform,
            "status": "placeholder",
            "caption": f"Draft generator placeholder for {platform}.",
        }
        for platform in PLATFORMS
    ]
