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
from datetime import datetime, timedelta
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

    cutoff = datetime.utcnow() - timedelta(days=min_age_days)

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

        if debug:
            log.debug("Consolidating %d '%s' memories.", len(group), type_key)

        summary = _consolidate_group(
            provider=provider,
            group=group,
            session_id=session_id,
            mem_type=type_key,
            location=location,
            debug=debug,
        )
        if summary:
            new_summaries.append(summary)
            to_archive.extend(group)

    return new_summaries, to_archive


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
        f"- [{m.importance.value}] {m.title}: {m.content}" for m in group
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

        return MemoryEntry(
            session_id=session_id,
            type=MemoryType.CONSOLIDATION,
            title=str(data.get("title", "Consolidated summary"))[:200],
            content=str(data.get("content", ""))[:2000],
            entities=[str(e) for e in data.get("entities", [])],
            tags=[str(t) for t in data.get("tags", [])],
            importance=importance,
            confidence=1.0,
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
