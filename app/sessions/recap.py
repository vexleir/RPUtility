"""
Session recap generator.
Produces a short 'previously on...' narrative summary using the LLM.
Used when resuming a session or for the status page overview.
"""

from __future__ import annotations

import logging

from app.core.models import MemoryEntry, SceneState, RelationshipState
from app.prompting.builder import derive_relationship_summary

log = logging.getLogger("rp_utility")

_RECAP_SYSTEM = (
    "You are a narrator summarising a collaborative roleplay story. "
    "Write a single concise paragraph in past tense describing what has happened. "
    "Focus on the most important events, discoveries, and relationship developments. "
    "Do not list facts — weave them into flowing narrative prose. "
    "Do not include meta-commentary. Respond with the paragraph only."
)

_MAX_MEMORIES = 12
_MAX_RELS = 6


def generate_recap(
    provider,
    memories: list[MemoryEntry],
    scene: SceneState,
    relationships: list[RelationshipState],
    max_sentences: int = 5,
) -> str:
    """
    Call the LLM to produce a short narrative recap.
    Returns empty string on failure (non-fatal).
    """
    try:
        prompt = _build_recap_prompt(memories, scene, relationships, max_sentences)
        result = provider.generate(
            prompt,
            system=_RECAP_SYSTEM,
            temperature=0.4,
            max_tokens=300,
        )
        return result.strip()
    except Exception as e:
        log.warning("Recap generation failed (non-fatal): %s", e)
        return ""


def _build_recap_prompt(
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
        # Sort by importance then recency — take most important first
        from app.core.models import ImportanceLevel
        order = {ImportanceLevel.CRITICAL: 0, ImportanceLevel.HIGH: 1,
                 ImportanceLevel.MEDIUM: 2, ImportanceLevel.LOW: 3}
        sorted_mems = sorted(memories, key=lambda m: order.get(m.importance, 4))
        shown = sorted_mems[:_MAX_MEMORIES]
        parts.append("\nKey events and facts:")
        for m in shown:
            parts.append(f"  - {m.title}: {m.content}")

    if relationships:
        shown_rels = relationships[:_MAX_RELS]
        parts.append("\nRelationships:")
        for r in shown_rels:
            summary = derive_relationship_summary(r)
            parts.append(f"  - {r.source_entity} → {r.target_entity}: {summary}")

    parts.append(
        f"\nWrite a recap paragraph of at most {max_sentences} sentences "
        f"covering the most important story developments."
    )

    return "\n".join(parts)
