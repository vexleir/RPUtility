"""
NPC auto-extraction pipeline.
After each roleplay turn, this module asks the LLM to identify named NPCs
mentioned in the exchange and adds them to the NPC roster if not already known.

Non-fatal: any failure returns an empty list so chat continues uninterrupted.
"""

from __future__ import annotations

import json
import logging
import re

from app.core.models import NpcEntry, SceneState
from app.providers.base import BaseProvider

log = logging.getLogger("rp_utility")

_MAX_INPUT_CHARS = 1200

_EXTRACTION_SYSTEM = """You are an NPC identification assistant for a roleplay system.
Read the conversation exchange and list every NAMED non-player character (NPC) mentioned.

INCLUDE:
- Named characters who speak, act, or are described (e.g. "Thornwick the blacksmith")
- Characters referenced by name even if not present (e.g. "she mentioned Lord Carew")

EXCLUDE:
- The main player character (provided below)
- Purely generic unnamed figures ("a guard", "the merchant")
- Place names, factions, or objects

For each NPC output a JSON object. If you find none, return [].

Output ONLY a JSON array:
[
  {
    "name": "Full name as used in text",
    "role": "their occupation or role (short, e.g. blacksmith, innkeeper, lord) — or empty string",
    "description": "1 sentence describing their appearance or what happened with them — or empty string",
    "last_known_location": "where they were in this scene — or empty string"
  }
]"""


def extract_npcs(
    *,
    provider: BaseProvider,
    session_id: str,
    character_name: str,
    user_message: str,
    assistant_message: str,
    scene: SceneState | None,
    debug: bool = False,
) -> list[NpcEntry]:
    """
    Ask the LLM to identify named NPCs from the turn exchange.
    Returns a list of NpcEntry objects (may be empty).
    Non-fatal on provider errors.
    """
    try:
        user_text = user_message[:_MAX_INPUT_CHARS]
        asst_text = assistant_message[:_MAX_INPUT_CHARS]
        location = scene.location if scene else "Unknown"

        user_prompt = (
            f"Main player character (EXCLUDE from results): {character_name}\n"
            f"Current location: {location}\n\n"
            f"[USER]: {user_text}\n\n"
            f"[ASSISTANT]: {asst_text}"
        )

        raw = provider.chat(
            [
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=600,
        )

        if debug:
            log.debug("NPC extraction raw response: %s", raw)

        return _parse_npcs(raw, session_id, character_name)

    except Exception as e:
        log.warning("NPC extraction failed (non-fatal): %s", e)
        return []


def _parse_npcs(raw: str, session_id: str, character_name: str) -> list[NpcEntry]:
    """Parse the LLM JSON response into NpcEntry objects."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Extract the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    if not isinstance(items, list):
        return []

    entries: list[NpcEntry] = []
    char_lower = character_name.lower()

    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        # Skip if it's the player character
        if name.lower() == char_lower or char_lower in name.lower():
            continue

        entries.append(NpcEntry(
            session_id=session_id,
            name=name,
            role=str(item.get("role", "")).strip(),
            description=str(item.get("description", "")).strip(),
            last_known_location=str(item.get("last_known_location", "")).strip(),
            is_alive=True,
        ))

    return entries
