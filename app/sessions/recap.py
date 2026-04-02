"""
Session recap generator.
Produces narrative summaries of the story so far.

generate_recap        — short paragraph (used inline on chat load / export)
generate_full_recap   — rich multi-section recap for the dedicated recap page
"""

from __future__ import annotations

import logging

from app.core.models import MemoryEntry, SceneState, RelationshipState, ImportanceLevel
from app.prompting.builder import derive_relationship_summary

log = logging.getLogger("rp_utility")

_MAX_MEMORIES_SHORT = 12
_MAX_MEMORIES_FULL  = 30
_MAX_RELS = 10

# ── Short recap (existing behaviour) ─────────────────────────────────────────

_RECAP_SYSTEM_SHORT = (
    "You are a narrator summarising a collaborative roleplay story. "
    "Write a single concise paragraph in past tense describing what has happened. "
    "Focus on the most important events, discoveries, and relationship developments. "
    "Do not list facts — weave them into flowing narrative prose. "
    "Do not include meta-commentary. Respond with the paragraph only."
)


def generate_recap(
    provider,
    memories: list[MemoryEntry],
    scene: SceneState,
    relationships: list[RelationshipState],
    max_sentences: int = 5,
) -> str:
    """Short paragraph recap used on chat load and export. Non-fatal."""
    try:
        prompt = _build_short_prompt(memories, scene, relationships, max_sentences)
        result = provider.generate(
            prompt,
            system=_RECAP_SYSTEM_SHORT,
            temperature=0.4,
            max_tokens=300,
        )
        return result.strip()
    except Exception as e:
        log.warning("Recap generation failed (non-fatal): %s", e)
        return ""


def _build_short_prompt(
    memories: list[MemoryEntry],
    scene: SceneState,
    relationships: list[RelationshipState],
    max_sentences: int,
) -> str:
    parts: list[str] = []
    parts.append(f"Current location: {scene.location}")
    if scene.active_characters:
        parts.append(f"Characters present: {', '.join(scene.active_characters)}")
    if scene.summary:
        parts.append(f"Scene summary: {scene.summary}")

    if memories:
        order = {ImportanceLevel.CRITICAL: 0, ImportanceLevel.HIGH: 1,
                 ImportanceLevel.MEDIUM: 2, ImportanceLevel.LOW: 3}
        shown = sorted(memories, key=lambda m: order.get(m.importance, 4))[:_MAX_MEMORIES_SHORT]
        parts.append("\nKey events and facts:")
        for m in shown:
            parts.append(f"  - {m.title}: {m.content}")

    if relationships:
        parts.append("\nRelationships:")
        for r in relationships[:6]:
            parts.append(f"  - {r.source_entity} → {r.target_entity}: {derive_relationship_summary(r)}")

    parts.append(
        f"\nWrite a recap paragraph of at most {max_sentences} sentences "
        "covering the most important story developments."
    )
    return "\n".join(parts)


# ── Full recap (for the dedicated recap page) ─────────────────────────────────

_RECAP_SYSTEM_FULL = """You are a skilled narrator writing a "Previously on…" recap for a returning player in a collaborative roleplay story.

Write an engaging, vivid multi-paragraph narrative recap in past tense that:
1. Opens with a compelling hook that orients the reader ("When we last left our hero...")
2. Describes the major story events in roughly chronological order
3. Highlights key character moments, alliances, betrayals, and discoveries
4. Notes where the story stands right now — what was happening when we paused
5. Ends with a sense of anticipation for what comes next

Style: flowing narrative prose, like a TV show recap or the opening of a novel chapter.
Length: 3–5 paragraphs.
Do NOT use bullet points or headers. Do NOT mention game mechanics. Respond with the narrative only."""


def generate_full_recap(
    provider,
    memories: list[MemoryEntry],
    scene: SceneState,
    relationships: list[RelationshipState],
    clock=None,
    session_name: str = "",
    character_name: str = "",
    turn_count: int = 0,
) -> str:
    """
    Rich multi-paragraph recap for the dedicated recap page.
    Returns empty string on failure.
    """
    try:
        prompt = _build_full_prompt(
            memories, scene, relationships, clock,
            session_name, character_name, turn_count,
        )
        result = provider.generate(
            prompt,
            system=_RECAP_SYSTEM_FULL,
            temperature=0.55,
            max_tokens=900,
        )
        return result.strip()
    except Exception as e:
        log.warning("Full recap generation failed: %s", e)
        return ""


def _build_full_prompt(
    memories: list[MemoryEntry],
    scene: SceneState,
    relationships: list[RelationshipState],
    clock,
    session_name: str,
    character_name: str,
    turn_count: int,
) -> str:
    parts: list[str] = []

    if session_name:
        parts.append(f"Story: {session_name}")
    if character_name:
        parts.append(f"Main character: {character_name}")
    if turn_count:
        parts.append(f"Story length: {turn_count} turns")
    if clock:
        parts.append(f"In-world time: {clock.display()}")

    parts.append(f"\nCurrent scene:")
    parts.append(f"  Location: {scene.location or 'Unknown'}")
    if scene.active_characters:
        parts.append(f"  Characters present: {', '.join(scene.active_characters)}")
    if scene.summary:
        parts.append(f"  What is happening: {scene.summary}")

    # Sort memories by importance then recency
    order = {ImportanceLevel.CRITICAL: 0, ImportanceLevel.HIGH: 1,
             ImportanceLevel.MEDIUM: 2, ImportanceLevel.LOW: 3}
    sorted_mems = sorted(memories, key=lambda m: (order.get(m.importance, 4), m.created_at))
    shown_mems = sorted_mems[:_MAX_MEMORIES_FULL]

    if shown_mems:
        parts.append("\nStory events and facts (oldest to most recent):")
        for m in shown_mems:
            imp = f"[{m.importance.value.upper()}]" if m.importance in (
                ImportanceLevel.CRITICAL, ImportanceLevel.HIGH) else ""
            chars = f" ({', '.join(m.entities)})" if m.entities else ""
            parts.append(f"  - {imp}{m.title}{chars}: {m.content}")

    if relationships:
        parts.append("\nKey relationships:")
        for r in relationships[:_MAX_RELS]:
            summary = derive_relationship_summary(r)
            parts.append(f"  - {r.source_entity} → {r.target_entity}: {summary}")

    parts.append(
        "\nUsing all of the above, write the full narrative recap now. "
        "Make it immersive and engaging — the reader is returning after time away."
    )
    return "\n".join(parts)
