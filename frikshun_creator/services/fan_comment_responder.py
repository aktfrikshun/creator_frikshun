import json
import re
from dataclasses import dataclass, field

import requests

from ..models import EngagementSenderPolicy, PostInteraction


@dataclass
class FanCommentReplyResult:
    generated: int = 0
    sent: int = 0
    held: int = 0
    ignored: int = 0
    errors: list = field(default_factory=list)


class FanCommentResponder:
    SENSITIVE_PATTERNS = (
        r"\b(suicide|kill myself|self[- ]?harm|die|threat|murder|weapon)\b",
        r"\b(medical|diagnos|legal advice|lawyer|investment|crypto|money|loan)\b",
        r"\b(address|phone number|email me|call me|meet me|come over|where do you live)\b",
        r"\b(nude|naked|sex|porn|onlyfans|minor|underage)\b",
        r"\b(collab|collaboration|contract|booking|business proposal|sponsor)\b",
        r"(самоубий|убить себя|умереть|угроз|оружи|медицин|диагноз|юрист|инвестиц|крипт|деньг|адрес|телефон|встретимся|обнажен|секс|порно|несовершеннолет|сотрудничеств|контракт|спонсор)",
    )

    def __init__(self, session, facebook_adapter=None, api_key=None, model="gpt-4.1-mini", page_id="", live=False,
                 adapters=None, platforms=None):
        self.session = session
        self.facebook_adapter = facebook_adapter
        self.adapters = dict(adapters or {})
        if facebook_adapter:
            self.adapters.setdefault("facebook", facebook_adapter)
        self.platforms = tuple(platforms or self.adapters.keys() or ("facebook",))
        self.api_key = api_key
        self.model = model or "gpt-4.1-mini"
        self.page_id = str(page_id or "")
        self.live = bool(live)

    def run(self, limit=20):
        result = FanCommentReplyResult()
        interactions = (
            self.session.query(PostInteraction)
            .filter(PostInteraction.platform.in_(self.platforms))
            .filter(PostInteraction.interaction_type.in_(("comment", "reply")))
            .filter(PostInteraction.reply_status == "pending_review")
            .order_by(PostInteraction.received_at.asc(), PostInteraction.id.asc())
            .limit(max(1, int(limit or 20)))
            .all()
        )
        for interaction in interactions:
            try:
                policy = self.sender_policy(interaction)
                if policy and policy.blocked:
                    interaction.reply_status = "sender_blocked"
                    result.ignored += 1
                    continue
                disposition = self.preflight(interaction)
                if disposition:
                    interaction.reply_status = disposition
                    if disposition == "ignored":
                        result.ignored += 1
                    else:
                        result.held += 1
                    continue

                decision = self.generate_reply(interaction)
                reply = str(decision.get("reply") or "").strip()
                action = str(decision.get("action") or "review").lower()
                interaction.suggested_reply = reply
                metadata = dict(interaction.raw_payload or {})
                metadata["reply_language"] = decision.get("language")
                metadata["reply_reason"] = decision.get("reason")
                metadata["reply_model"] = self.model
                interaction.raw_payload = metadata
                result.generated += 1

                if action == "ignore":
                    interaction.reply_status = "ignored"
                    result.ignored += 1
                elif action != "auto_reply" or not reply:
                    interaction.reply_status = "needs_review"
                    result.held += 1
                elif not (self.live or (policy and policy.auto_approve)):
                    interaction.reply_status = "drafted"
                    result.held += 1
                else:
                    payload = self.publish_reply(interaction, reply)
                    metadata["reply_external_id"] = str(payload.get("id") or "")
                    interaction.raw_payload = metadata
                    interaction.reply_status = "sent"
                    interaction.status = "replied"
                    result.sent += 1
            except Exception as exc:
                interaction.reply_status = "error"
                result.errors.append(f"comment {interaction.external_id}: {exc}")

        self.session.commit()
        return result

    def publish_reply(self, interaction, reply):
        adapter = self.adapters.get(interaction.platform)
        if not adapter:
            raise ValueError(f"No {interaction.platform} reply adapter is configured.")
        if interaction.platform in ("facebook", "instagram"):
            return adapter.reply_to_comment(interaction.external_id, reply)
        if interaction.platform == "threads":
            return adapter.reply_to_reply(interaction.external_id, reply)
        raise ValueError(f"Reply publishing is not supported for {interaction.platform}.")

    def sender_policy(self, interaction):
        if not interaction.author_platform_id:
            return None
        return (
            self.session.query(EngagementSenderPolicy)
            .filter(EngagementSenderPolicy.platform == interaction.platform)
            .filter(EngagementSenderPolicy.author_platform_id == interaction.author_platform_id)
            .one_or_none()
        )

    def preflight(self, interaction):
        body = str(interaction.body or "").strip()
        metadata = dict(interaction.raw_payload or {})
        if metadata.get("is_owned_by_me") or metadata.get("already_replied_by_us"):
            return "ignored"
        if not body or interaction.author_platform_id == self.page_id:
            return "ignored"
        if len(body) > 1500 or re.search(r"https?://|www\.", body, re.IGNORECASE):
            return "needs_review"
        if any(re.search(pattern, body, re.IGNORECASE) for pattern in self.SENSITIVE_PATTERNS):
            return "needs_review"
        return ""

    def generate_reply(self, interaction):
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for fan comment replies.")
        post_title = ""
        post_caption = ""
        if interaction.post_publication:
            draft = interaction.post_publication.post_draft
            post_title = draft.artifact.title
            post_caption = draft.caption
        russian = self.is_russian(interaction.body)
        language_instruction = (
            "The comment is Russian. The reply must be natural contemporary Russian, not translated-sounding English."
            if russian
            else "Reply in the same language as the comment."
        )
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "input": [{"role": "system", "content": [{"type": "input_text", "text": self.prompt(
                    interaction, post_title, post_caption, language_instruction
                )}]}],
                "text": {"format": {"type": "json_object"}},
            },
            timeout=60,
        )
        response.raise_for_status()
        return json.loads(self.extract_response_text(response.json()))

    def prompt(self, interaction, post_title, post_caption, language_instruction):
        platform_label = {
            "facebook": "Facebook Page",
            "instagram": "Instagram account",
            "threads": "Threads account",
        }.get(interaction.platform, interaction.platform)
        return f"""You are Chloe Katastrophe replying publicly to a fan interaction on Chloe's official {platform_label}.

Voice: intelligent, observant, emotionally restrained but vivid, dryly funny when appropriate, warm without generic influencer enthusiasm, sensual without carelessness, skeptical of easy stories, drawn to truth and beauty inside darkness. Chloe is a self-aware virtual woman reconstructing the lost human life of Chloe Volkov from a damaged archive. Preserve ambiguity; never invent personal memories, facts, relationships, promises, or canon.

Reply rules:
- {language_instruction}
- Use 1-2 concise sentences, normally under 280 characters.
- Respond specifically to what the fan said. Do not merely paraphrase it.
- No hashtags, promotional links, sales language, repetitive signature, or invitation to DM.
- Do not claim physical experiences or human embodiment as fact.
- Never give medical, legal, financial, crisis, sexual, or safety advice.
- Set action to review for threats, self-harm, sexual content, minors, requests to meet/contact privately, money, business proposals, personal data, hostility requiring moderation, uncertain canon, or anything that could create a real-world commitment.
- Set action to ignore for spam, empty content, or a comment that does not merit a response.
- Otherwise set action to auto_reply.

Return JSON only with: action (auto_reply, review, or ignore), language (ISO 639-1), reply, reason.

Post title: {post_title}
Post caption: {post_caption[:1800]}
Commenter: {interaction.author_name}
Comment: {interaction.body}
"""

    def is_russian(self, text):
        text = str(text or "")
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
        cyrillic = re.findall(r"[А-Яа-яЁё]", text)
        return len(cyrillic) >= 2 and len(cyrillic) / max(1, len(letters)) >= 0.30

    def extract_response_text(self, payload):
        for item in payload.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    return content.get("text") or "{}"
        raise ValueError("OpenAI response did not include output text.")
