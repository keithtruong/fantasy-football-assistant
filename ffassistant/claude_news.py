"""Uses Claude to interpret scraped player-news content — this project's first
LLM usage, and deliberately scoped: Claude only ever interprets *external,
unstructured* content (turning a scraped page into clean fields, and
synthesizing a summary). Resolving a name to this project's own canonical
player_id stays entirely in the deterministic ffassistant.name_matching
pipeline, same as everywhere else in this codebase — see CLAUDE.md.

Requires ANTHROPIC_API_KEY in the local .env (see ffassistant.config) — a
separate cost/credential from anything Claude Code itself uses.
"""

from typing import Optional

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5"


class NewsItem(BaseModel):
    raw_name: str
    team: Optional[str] = None
    position: Optional[str] = None
    headline: str
    analysis: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None
    source: Optional[str] = None
    link: Optional[str] = None


class _ExtractedNews(BaseModel):
    items: list[NewsItem]


class _PlayerDigest(BaseModel):
    player_id: int
    digest: str


class _DigestBatch(BaseModel):
    digests: list[_PlayerDigest]


def extract_news_items(cleaned_pages: list[str]) -> list[NewsItem]:
    """Extracts every distinct player-news item found across `cleaned_pages`
    (already-fetched, generically size-reduced HTML — see
    ffassistant.connectors.nbc_news). Faithful extraction only: Claude is
    instructed not to invent fields it can't find in the source.
    """
    if not cleaned_pages:
        return []

    client = anthropic.Anthropic()
    content = "\n\n=== PAGE BREAK ===\n\n".join(cleaned_pages)

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=(
            "You extract individual player-news items from scraped fantasy football news "
            "page content (HTML with most non-content markup already stripped). Each item "
            "concerns one NFL player. Extract every distinct item you find. Be faithful to "
            "the source text — never invent a fact that isn't present. Leave a field empty "
            "rather than guessing when it isn't clearly present. published_at should be an "
            "ISO-8601 UTC timestamp when one is determinable from the content."
        ),
        messages=[{"role": "user", "content": content}],
        output_format=_ExtractedNews,
    )
    return response.parsed_output.items


def generate_digests(player_items: dict[int, dict]) -> dict[int, str]:
    """player_items: {player_id: {"full_name": str, "items": list[NewsItem]}}.
    Returns {player_id: digest_text} — one short digest per player, batched
    into a single call rather than one call per player. Claude echoes back the
    exact player_id it was given, so matching to our records needs no further
    name-based lookup.
    """
    if not player_items:
        return {}

    client = anthropic.Anthropic()
    lines = []
    for player_id, info in player_items.items():
        lines.append(f"Player ID {player_id}: {info['full_name']}")
        for item in info["items"]:
            detail = item.headline
            if item.analysis:
                detail += f" {item.analysis}"
            lines.append(f"  - [{item.published_at or 'date unknown'}] {detail}")

    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=(
            "You write short fantasy football recap digests. For each player listed below, "
            "given their news items from the past few days, write a 1-3 sentence summary of "
            "what's happened, in plain conversational language a fantasy manager would want "
            "to skim. Always echo back the exact numeric Player ID given for each player — "
            "never a name — in your response, so results can be matched to internal records."
        ),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_format=_DigestBatch,
    )
    return {d.player_id: d.digest for d in response.parsed_output.digests}
