"""
Relationship extraction pipeline.
After each roleplay turn, asks the LLM to identify changes in how
characters feel toward each other and returns them as axis deltas.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.core.models import SceneState
from app.providers.base import BaseProvider

log = logging.getLogger("rp_utility")

# ── Prompts ────────────────────────────────────────────────────────────────────

RELATIONSHIP_SYSTEM_PROMPT = """You are a relationship tracker for a roleplay system.
Read the conversation exchange and identify meaningful changes in how characters feel toward each other.

For each directional relationship that changed, output one JSON object:
{
  "source": "entity who has this feeling",
  "target": "entity the feeling is directed at",
  "trust": delta float -0.3 to 0.3,
  "fear": delta float 0.0 to 0.3,
  "respect": delta float -0.3 to 0.3,
  "affection": delta float -0.3 to 0.3,
  "hostility": delta float -0.3 to 0.3
}

Axis meanings:
- trust / respect / affection: negative = less, positive = more (range -1 to 1 total)
- fear / hostility: 0 = none, higher = more (range 0 to 1 total)
- Omit (or use 0.0) any axis that did not meaningfully change
- Small values 0.05–0.15 for subtle changes; larger 0.15–0.3 for dramatic events
- Only include an entry when something genuinely changed

Output ONLY a JSON array. If nothing changed, output: []
No other text."""

RELATIONSHIP_USER_TEMPLATE = """Location: {location}
Active characters: {characters}

Exchange:
USER: {user_message}

ASSISTANT: {assistant_message}

Identify relationship changes as a JSON array of delta objects."""


# ── Public API ────────────────────────────────────────────────────────────────

def extract_relationship_deltas(
    provider: BaseProvider,
    user_message: str,
    assistant_message: str,
    scene: Optional[SceneState],
    debug: bool = False,
) -> list[dict]:
    """
    Ask the LLM to identify relationship changes in this exchange.
    Returns a list of delta dicts with keys:
        source, target, trust, fear, respect, affection, hostility
    Never raises — all failures return [].
    """
    location = scene.location if scene else "Unknown"
    characters = ", ".join(scene.active_characters) if scene else "Unknown"

    prompt = RELATIONSHIP_USER_TEMPLATE.format(
        location=location,
        characters=characters,
        user_message=user_message,
        assistant_message=assistant_message,
    )

    try:
        raw = provider.generate(
            prompt,
            system=RELATIONSHIP_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=512,
        )
        if debug:
            log.debug("Relationship extraction response: %s", raw)
        return _parse(raw)
    except Exception as e:
        log.warning("Relationship extraction failed (non-fatal): %s", e)
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse(raw: str) -> list[dict]:
    """Extract a JSON array from the model response."""
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return []
