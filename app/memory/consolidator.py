"""
Memory consolidation pipeline.
Merges groups of aging, lower-importance memories of the same type into
compact summaries, reducing prompt bloat while preserving key facts.

Strategy:
  - Triggered when a session accumulates >= threshold memories of one type
  - Only consolidates non-critical memories older than min_age_days
  - Calls the LLM once per type group to produce a summary MemoryEntry
  - Archives (soft-deletes) the source memories so they remain inspectable
  - Critical memories and fresh memories are never touched

The consolidation summary is stored as type=CONSOLIDATION with
consolidated_from listing the source memory IDs.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, UTC
from typing import Optional

from app.core.models import (
    MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel
)
from app.providers.base import BaseProvider

log = logging.getLogger("rp_utility")

# ── Prompts ────────────────────────────────────────────────────────────────────

_CONSOLIDATION_SYSTEM = """You are a memory summarizer for a roleplay system.
You will receive a list of related memories and must produce ONE compact summary.

Rules:
- Preserve all critical facts, names, outcomes, and consequences
- Keep permanent injuries, deaths, betrayals, alliances, and world changes
- Discard trivial details, repeated phrasing, and filler
- Write in 2-4 sentences, present-tense narrative style
- IMPORTANT: Each memory includes a "(characters: ...)" label. Only include a character name in "entities" if they appear in at least one source memory's character list. Do NOT invent or merge character names.
- The summary content must accurately attribute events to the correct characters — do not conflate who did what.
- Output ONLY a JSON object:
{
  "title": "Short descriptive title (max 10 words)",
  "content": "The consolidated summary text",
  "entities": ["name1", "name2"],
  "tags": ["tag1", "tag2"],
  "importance": "medium" | "high" | "critical"
}
No other text."""

_CONSOLIDATION_USER = """Memory type: {mem_type}
Location context: {location}

Memories to consolidate:
{memory_list}

Produce one compact summary JSON."""


def consolidate_memories(
    provider: BaseProvider,
    memories: list[MemoryEntry],
    session_id: str,
    threshold: int = 10,
    min_age_days: float = 1.0,
    location: str = "Unknown",
    debug: bool = False,
) -> tuple[list[MemoryEntry], list[MemoryEntry]]:
    """
    Consolidate memories that exceed the per-type threshold.

    Args:
        provider:      LLM provider to use for summarization.
        memories:      All non-archived memories for the session.
        session_id:    Current session ID.
        threshold:     Minimum count per type to trigger consolidation.
        min_age_days:  Minimum memory age (days) to be eligible.
        location:      Current scene location for context.
        debug:         Log detailed consolidation info.

    Returns:
        (new_summaries, memories_to_archive)
        Caller is responsible for saving new_summaries and archiving the others.
    """
    from collections import defaultdict

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=min_age_days)

    # Group eligible memories by type (exclude critical and fresh)
    groups: dict[str, list[MemoryEntry]] = defaultdict(list)
    for m in memories:
        if m.importance == ImportanceLevel.CRITICAL:
            continue
        if m.created_at > cutoff:
            continue
        if m.type == MemoryType.CONSOLIDATION:
            continue  # don't re-consolidate summaries
        groups[m.type.value].append(m)

    new_summaries: list[MemoryEntry] = []
    to_archive: list[MemoryEntry] = []

    for type_key, group in groups.items():
        if len(group) < threshold:
            continue

        # Split group into entity-coherent sub-groups so memories about
        # different characters are never merged into the same summary.
        subgroups = _split_by_entity_overlap(group, max_gap=threshold)

        for subgroup in subgroups:
            if len(subgroup) < threshold:
                continue

            if debug:
                log.debug("Consolidating %d '%s' memories (entity subgroup).", len(subgroup), type_key)

            summary = _consolidate_group(
                provider=provider,
                group=subgroup,
                session_id=session_id,
                mem_type=type_key,
                location=location,
                debug=debug,
            )
            if summary:
                new_summaries.append(summary)
                to_archive.extend(subgroup)

    return new_summaries, to_archive


def _split_by_entity_overlap(
    memories: list[MemoryEntry],
    max_gap: int,
) -> list[list[MemoryEntry]]:
    """
    Split a flat list of memories into sub-groups where each group shares
    at least one entity with at least one other member. Memories with no
    entities are placed in their own singleton group.
    Uses a simple union-find approach so transitively related memories stay together.
    Sub-groups smaller than max_gap are merged with the largest group to avoid
    producing too many tiny consolidations.
    """
    if not memories:
        return []

    n = len(memories)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    # Build entity → memory index map
    entity_to_indices: dict[str, list[int]] = {}
    for i, m in enumerate(memories):
        for e in m.entities:
            entity_to_indices.setdefault(e.lower(), []).append(i)

    # Union memories that share any entity
    for indices in entity_to_indices.values():
        for j in range(1, len(indices)):
            union(indices[0], indices[j])

    # Collect groups
    groups_map: dict[int, list[MemoryEntry]] = {}
    for i, m in enumerate(memories):
        root = find(i)
        groups_map.setdefault(root, []).append(m)

    subgroups = list(groups_map.values())

    # Merge tiny sub-groups into the largest one to avoid micro-consolidations
    large = [g for g in subgroups if len(g) >= max_gap]
    small = [g for g in subgroups if len(g) < max_gap]
    if small and large:
        biggest = max(large, key=len)
        for sg in small:
            biggest.extend(sg)
    elif small and not large:
        # All sub-groups are small — merge them all into one
        merged: list[MemoryEntry] = []
        for sg in small:
            merged.extend(sg)
        return [merged]

    return large if large else subgroups


def _consolidate_group(
    provider: BaseProvider,
    group: list[MemoryEntry],
    session_id: str,
    mem_type: str,
    location: str,
    debug: bool,
) -> Optional[MemoryEntry]:
    """Call the LLM to produce one summary for a group of memories."""
    memory_list = "\n".join(
        f"- [{m.importance.value}] {m.title} (characters: {', '.join(m.entities) or 'unknown'}): {m.content}"
        for m in group
    )
    prompt = _CONSOLIDATION_USER.format(
        mem_type=mem_type,
        location=location,
        memory_list=memory_list,
    )
    try:
        raw = provider.generate(
            prompt,
            system=_CONSOLIDATION_SYSTEM,
            temperature=0.2,
            max_tokens=400,
        )
        if debug:
            log.debug("Consolidation response: %s", raw)

        data = _parse(raw)
        if not data:
            return None

        importance_raw = data.get("importance", "medium")
        try:
            importance = ImportanceLevel(importance_raw)
        except ValueError:
            importance = ImportanceLevel.MEDIUM

        # Carry forward the average confidence of the source memories so that
        # uncertainty is not silently inflated to 1.0 by consolidation.
        avg_confidence = sum(m.confidence for m in group) / len(group)

        return MemoryEntry(
            session_id=session_id,
            type=MemoryType.CONSOLIDATION,
            title=str(data.get("title", "Consolidated summary"))[:200],
            content=str(data.get("content", ""))[:2000],
            entities=[str(e) for e in data.get("entities", [])],
            tags=[str(t) for t in data.get("tags", [])],
            importance=importance,
            confidence=round(avg_confidence, 3),
            certainty=CertaintyLevel.CONFIRMED,
            consolidated_from=[m.id for m in group],
        )
    except Exception as e:
        log.warning("Consolidation failed for type '%s' (non-fatal): %s", mem_type, e)
        return None


def _parse(raw: str) -> dict:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}
