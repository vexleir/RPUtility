"""
Contradiction detection.
Checks newly extracted memories against existing ones for likely conflicts.

Detection strategy (lightweight, no embeddings required):
  1. Entity + type overlap: if a new memory and an existing memory share the
     same entities and are of the same type, they may contradict each other.
  2. Keyword opposition: scan for opposing signal words (alive/dead, open/closed,
     present/gone, etc.) in the content of overlapping memories.
  3. Confidence asymmetry: new rumor vs existing confirmed fact is always flagged.

Resolution modes (configured via config.contradiction_mode):
  - "mark_uncertain": lower confidence of new memory to 0.4, set certainty=suspicion
  - "reject":        drop the new memory entirely (returns it removed from list)
  - "downgrade":     set new memory type to RUMOR
  - "warn":          log a warning, store anyway unchanged

All results are returned as (kept_memories, contradiction_flags).
Never raises — failures return inputs unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.core.models import (
    MemoryEntry, MemoryType, CertaintyLevel, ImportanceLevel, ContradictonFlag
)

log = logging.getLogger("rp_utility")

# Word pairs that suggest contradiction when found in overlapping memories
_OPPOSITION_PAIRS: list[tuple[str, str]] = [
    ("alive", "dead"), ("alive", "killed"), ("alive", "died"),
    ("living", "dead"), ("living", "killed"),
    ("open", "closed"), ("open", "destroyed"), ("open", "burned"),
    ("standing", "destroyed"), ("standing", "collapsed"), ("standing", "burned"),
    ("present", "gone"), ("present", "left"), ("present", "fled"),
    ("intact", "destroyed"), ("intact", "burned"), ("intact", "ruined"),
    ("healthy", "injured"), ("healthy", "wounded"), ("healthy", "dead"),
    ("allied", "betrayed"), ("allied", "hostile"), ("trusted", "betrayed"),
    ("secret", "revealed"), ("secret", "exposed"), ("hidden", "discovered"),
    ("king", "dead"), ("queen", "dead"), ("leader", "killed"),
    ("friend", "enemy"), ("ally", "enemy"), ("ally", "traitor"),
]


def check_contradictions(
    new_memories: list[MemoryEntry],
    existing_memories: list[MemoryEntry],
    session_id: str,
    mode: str = "mark_uncertain",
    similarity_threshold: float = 0.65,
    debug: bool = False,
) -> tuple[list[MemoryEntry], list[ContradictonFlag]]:
    """
    Check new memories against existing ones for contradictions.

    Returns:
        (kept_memories, contradiction_flags)
        kept_memories may have confidence/certainty lowered depending on mode.
    """
    if not new_memories or not existing_memories:
        return new_memories, []

    # Only check against confirmed/high-importance existing memories —
    # we don't protect rumors from being contradicted
    protected = [
        m for m in existing_memories
        if m.certainty in (CertaintyLevel.CONFIRMED,) or m.importance == ImportanceLevel.CRITICAL
    ]

    kept: list[MemoryEntry] = []
    flags: list[ContradictonFlag] = []

    for new_mem in new_memories:
        contradiction, existing_match, description = _find_contradiction(
            new_mem, protected, similarity_threshold
        )
        if contradiction and existing_match:
            flag = ContradictonFlag(
                session_id=session_id,
                new_memory_id=new_mem.id,
                existing_memory_id=existing_match.id,
                description=description,
                resolution=mode,
            )
            flags.append(flag)
            if debug:
                log.debug(
                    "Contradiction detected: '%s' vs existing '%s' — %s",
                    new_mem.title, existing_match.title, description
                )

            if mode == "reject":
                log.info("Contradiction: rejected '%s'", new_mem.title)
                continue  # skip — don't add to kept
            elif mode == "downgrade":
                new_mem.type = MemoryType.RUMOR
                new_mem.certainty = CertaintyLevel.RUMOR
                new_mem.confidence = min(new_mem.confidence, 0.4)
                new_mem.contradiction_of = existing_match.id
                log.info("Contradiction: downgraded '%s' to rumor", new_mem.title)
            elif mode == "mark_uncertain":
                new_mem.certainty = CertaintyLevel.SUSPICION
                new_mem.confidence = min(new_mem.confidence, 0.4)
                new_mem.contradiction_of = existing_match.id
                log.info("Contradiction: marked '%s' as uncertain", new_mem.title)
            else:  # "warn"
                log.warning(
                    "Contradiction (warn mode): new='%s' vs existing='%s': %s",
                    new_mem.title, existing_match.title, description
                )

        kept.append(new_mem)

    return kept, flags


def _find_contradiction(
    new_mem: MemoryEntry,
    protected: list[MemoryEntry],
    threshold: float,
) -> tuple[bool, Optional[MemoryEntry], str]:
    """
    Check new_mem against protected memories.
    Returns (is_contradiction, conflicting_memory, description).
    """
    new_entities = {e.lower() for e in new_mem.entities}
    new_words = set(_words(new_mem.content))

    for existing in protected:
        ex_entities = {e.lower() for e in existing.entities}

        # Entity overlap check
        shared_entities = new_entities & ex_entities
        if not shared_entities:
            continue  # No shared entities — unlikely to contradict

        # Check for opposing signal words in content
        ex_words = set(_words(existing.content))
        for word_a, word_b in _OPPOSITION_PAIRS:
            a_in_new = word_a in new_words
            b_in_new = word_b in new_words
            a_in_ex = word_a in ex_words
            b_in_ex = word_b in ex_words

            # Contradiction: new says A, existing says B (or vice versa)
            if (a_in_new and b_in_ex) or (b_in_new and a_in_ex):
                desc = (
                    f"New memory says '{word_a if a_in_new else word_b}' but existing "
                    f"memory '{existing.title}' says '{word_b if b_in_ex else word_a}' "
                    f"(shared entities: {', '.join(shared_entities)})"
                )
                return True, existing, desc

        # Confidence asymmetry: new rumor contradicting confirmed critical fact
        if (
            new_mem.certainty in (CertaintyLevel.RUMOR, CertaintyLevel.SUSPICION)
            and existing.importance == ImportanceLevel.CRITICAL
            and existing.certainty == CertaintyLevel.CONFIRMED
            and existing.type == new_mem.type
        ):
            # Same type, shared entities, conflicting certainty levels
            entity_overlap = len(shared_entities) / max(len(new_entities | ex_entities), 1)
            if entity_overlap >= threshold:
                desc = (
                    f"New {new_mem.certainty.value} about {', '.join(shared_entities)} "
                    f"conflicts with confirmed critical fact '{existing.title}'"
                )
                return True, existing, desc

    return False, None, ""


def _words(text: str) -> list[str]:
    """Lowercase word tokens, stripping punctuation."""
    import re
    return re.findall(r"[a-z]+", text.lower())
