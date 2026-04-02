"""
Memory extraction pipeline.
After each roleplay turn, this module asks the LLM to identify important facts
worth remembering and stores them as MemoryEntry objects.

Phase 2 improvements:
  - Extended type vocabulary: world_state, suspicion added
  - Certainty field extracted from LLM response
  - Tighter prompt with clearer store/skip guidance
  - Input truncated to _MAX_INPUT_CHARS to prevent token bloat
  - Confidence clamped universally to [0.0, 1.0]
"""

from __future__ import annotations

import json
import re
from datetime import datetime, UTC
from typing import Optional

from app.core.models import (
    MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel, SceneState
)
from app.providers.base import BaseProvider

# Max characters for user/assistant messages sent to extraction model.
_MAX_INPUT_CHARS = 1500

# ── Extraction prompt ──────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction assistant for a roleplay system.
Read the conversation exchange and identify facts worth storing long-term.

STORE:
- Major events with lasting consequences (injuries, deaths, betrayals, alliances)
- Player-created world facts accepted into the fiction
- New factions, places, laws, landmarks, secrets, customs
- Permanent status changes (cursed, exiled, promoted, wanted)
- Promises, debts, oaths, alliances, betrayals
- Important character reveals or backstory confirmed in scene
- Relationship changes that alter future interactions
- World-state shifts (faction control, city damage, political change)
- Confirmed secrets or sensitive information
- Unresolved tensions likely to matter later
- Suspicions or rumors heard from NPCs (mark certainty accordingly)

DO NOT STORE:
- Trivial per-turn actions with no lasting effect
- Decorative prose and atmosphere
- Exact repetition of already-known facts
- Weak speculation not grounded in scene events
- Dialogue that reveals nothing new

Memory types:
  event             — something that happened with lasting impact
  world_fact        — confirmed fact about the world or setting
  character_detail  — trait, history, or status of a specific character
  relationship_change — how two entities now relate differently
  world_state       — durable shift in faction/political/environmental state
  rumor             — heard second-hand, not yet confirmed
  suspicion         — gut feeling or indirect evidence, not verified

Certainty levels:
  confirmed  — witnessed directly or established as true
  rumor      — heard from someone else, unverified
  suspicion  — inferred, not witnessed
  lie        — known to be false but worth tracking
  myth       — ancient/legendary, may be distorted

ENTITY RULES — very important:
- The "entities" field MUST only contain names from the "Active characters" list provided below.
- Do NOT add entity names from dialogue, backstory mentions, or characters not physically present.
- If a memory concerns the whole scene, use only the names of characters who directly participated.

Output ONLY a JSON array. Each object:
{
  "type": "event|world_fact|character_detail|relationship_change|world_state|rumor|suspicion",
  "title": "Short title (max 10 words)",
  "content": "Clear 1-3 sentence description",
  "entities": ["name1", "name2"],
  "location": "place name or null",
  "tags": ["tag1", "tag2"],
  "importance": "low|medium|high|critical",
  "confidence": 0.0-1.0,
  "certainty": "confirmed|rumor|suspicion|lie|myth"
}

If nothing is worth storing: []
Output ONLY the JSON array, no other text."""

EXTRACTION_USER_TEMPLATE = """Session context:
- Location: {location}
- Active characters (the ONLY valid entity names): {characters}

Recent exchange:
USER: {user_message}

A: {assistant_message}

Extract memorable facts as a JSON array. Remember: only use entity names from the active characters list above."""


def extract_memories(
    provider: BaseProvider,
    session_id: str,
    user_message: str,
    assistant_message: str,
    scene: Optional[SceneState],
    source_turn_ids: list[str],
    debug: bool = False,
) -> list[MemoryEntry]:
    """
    Run memory extraction for one conversation exchange.
    Returns a (possibly empty) list of MemoryEntry objects.
    Never raises — all failures return an empty list.
    """
    location = scene.location if scene else "Unknown"
    active_characters: list[str] = scene.active_characters if scene and scene.active_characters else []
    characters = ", ".join(active_characters) if active_characters else "Unknown"

    prompt = EXTRACTION_USER_TEMPLATE.format(
        location=location,
        characters=characters,
        user_message=user_message[:_MAX_INPUT_CHARS],
        assistant_message=assistant_message[:_MAX_INPUT_CHARS],
    )

    if debug:
        import logging
        logging.getLogger("rp_utility").debug("Memory extraction prompt:\n%s", prompt)

    try:
        raw = provider.generate(
            prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=1024,
        )
        if debug:
            import logging
            logging.getLogger("rp_utility").debug("Extraction response:\n%s", raw)

        items = _parse_json_response(raw)
        return _build_entries(items, session_id, source_turn_ids, active_characters)

    except Exception as e:
        if debug:
            import logging
            logging.getLogger("rp_utility").debug("Memory extraction failed (non-fatal): %s", e)
        return []


def _parse_json_response(raw: str) -> list[dict]:
    """Extract and parse the JSON array from the model response."""
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


def _build_entries(
    items: list[dict],
    session_id: str,
    source_turn_ids: list[str],
    active_characters: list[str] | None = None,
) -> list[MemoryEntry]:
    """Convert raw dicts from the model into validated MemoryEntry objects."""
    now = datetime.now(UTC).replace(tzinfo=None)
    entries: list[MemoryEntry] = []
    # Build a case-insensitive allowlist for entity validation
    allowed_lower = {c.lower() for c in active_characters} if active_characters else None

    for item in items:
        try:
            mem_type = MemoryType(item.get("type", "event"))
            importance = ImportanceLevel(item.get("importance", "medium"))
            confidence = max(0.0, min(1.0, float(item.get("confidence", 1.0))))

            # Map type to certainty if not explicitly provided
            certainty_raw = item.get("certainty", "")
            if certainty_raw:
                try:
                    certainty = CertaintyLevel(certainty_raw)
                except ValueError:
                    certainty = _default_certainty(mem_type)
            else:
                certainty = _default_certainty(mem_type)

            # Rumors and suspicions are inherently uncertain — cap confidence
            if certainty in (CertaintyLevel.RUMOR, CertaintyLevel.SUSPICION):
                confidence = min(confidence, 0.6)
            if certainty == CertaintyLevel.LIE:
                confidence = min(confidence, 0.2)

            # Strip entity names the LLM hallucinated outside the active character list
            raw_entities = [str(e) for e in item.get("entities", [])]
            if allowed_lower:
                raw_entities = [e for e in raw_entities if e.lower() in allowed_lower]

            entry = MemoryEntry(
                session_id=session_id,
                created_at=now,
                updated_at=now,
                type=mem_type,
                title=str(item.get("title", "Unnamed memory"))[:200],
                content=str(item.get("content", ""))[:2000],
                entities=raw_entities,
                location=item.get("location") or None,
                tags=[str(t) for t in item.get("tags", [])],
                importance=importance,
                source_turn_ids=source_turn_ids,
                confidence=confidence,
                certainty=certainty,
            )
            entries.append(entry)
        except (ValueError, TypeError):
            continue  # skip malformed entries

    return entries


def _default_certainty(mem_type: MemoryType) -> CertaintyLevel:
    """Derive a sensible default certainty from memory type."""
    if mem_type == MemoryType.RUMOR:
        return CertaintyLevel.RUMOR
    if mem_type == MemoryType.SUSPICION:
        return CertaintyLevel.SUSPICION
    return CertaintyLevel.CONFIRMED
