"""
Memory retrieval system.
Selects the most relevant MemoryEntry objects for the current scene context.

Phase 2 improvements:
  - Configurable scoring weights (from Config)
  - Per-type retrieval caps
  - Certainty penalty (suspicion/lie/myth scored lower than confirmed)
  - Recently-used penalty to reduce repetition of same memories
  - Debug score breakdown logging
  - Archived memories excluded automatically (store already filters these)

Scoring factors:
  1. Importance weight   — CRITICAL=10, HIGH=4, MEDIUM=2, LOW=1
  2. Entity relevance    — +weight per entity/location overlap with scene
  3. Keyword match       — +weight per tag/entity hit in recent conversation
  4. Recency decay       — exp(-age/half_life)
  5. Reference recency   — exp(-days_since_ref/ref_half_life) * weight
  6. Confidence penalty  — multiply by memory.confidence (0.0–1.0)
  7. Certainty penalty   — confirmed=1.0, rumor=0.7, suspicion=0.5, lie=0.1, myth=0.6
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Optional

from app.core.models import MemoryEntry, ImportanceLevel, SceneState, CertaintyLevel

log = logging.getLogger("rp_utility")

# ── Importance base weights ────────────────────────────────────────────────────
_IMPORTANCE_SCORE = {
    ImportanceLevel.LOW: 1.0,
    ImportanceLevel.MEDIUM: 2.0,
    ImportanceLevel.HIGH: 4.0,
    ImportanceLevel.CRITICAL: 10.0,
}

# Certainty multipliers
_CERTAINTY_MULT = {
    CertaintyLevel.CONFIRMED: 1.0,
    CertaintyLevel.RUMOR: 0.7,
    CertaintyLevel.SUSPICION: 0.5,
    CertaintyLevel.LIE: 0.1,
    CertaintyLevel.MYTH: 0.6,
}

# Per-type default caps (0 = no cap) — overridden from Config at call time
_DEFAULT_TYPE_CAPS: dict[str, int] = {
    "event": 6,
    "world_fact": 5,
    "character_detail": 5,
    "relationship_change": 4,
    "world_state": 4,
    "rumor": 2,
    "suspicion": 2,
    "consolidation": 4,
}


@dataclass
class ScoreBreakdown:
    """Debug record of how a memory was scored."""
    memory_id: str
    title: str
    importance_score: float = 0.0
    entity_score: float = 0.0
    keyword_score: float = 0.0
    recency_score: float = 0.0
    reference_score: float = 0.0
    confidence_mult: float = 1.0
    certainty_mult: float = 1.0
    total: float = 0.0
    selected: bool = False
    rejection_reason: str = ""


def retrieve(
    memories: list[MemoryEntry],
    scene: Optional[SceneState],
    recent_text: str = "",
    max_results: int = 10,
    # Scoring weights (use Config values when calling from engine)
    weight_importance: float = 1.0,
    weight_entity: float = 2.0,
    weight_keyword: float = 0.5,
    weight_recency: float = 1.0,
    weight_reference: float = 0.5,
    recency_half_life: float = 30.0,
    reference_half_life: float = 7.0,
    # Per-type caps (None = use defaults)
    type_caps: Optional[dict[str, int]] = None,
    # Recent memory IDs — apply mild penalty to reduce repetition
    recently_used_ids: Optional[set[str]] = None,
    debug: bool = False,
) -> list[MemoryEntry]:
    """
    Select and return the most relevant memories for the current context.

    Returns memories sorted most-relevant-first, up to max_results.
    Critical memories are always included regardless of score.
    """
    if not memories:
        return []

    caps = {**_DEFAULT_TYPE_CAPS, **(type_caps or {})}
    recently_used = recently_used_ids or set()
    breakdowns: list[ScoreBreakdown] = []

    # Partition critical from non-critical
    critical = [m for m in memories if m.importance == ImportanceLevel.CRITICAL]
    non_critical = [m for m in memories if m.importance != ImportanceLevel.CRITICAL]

    # Score non-critical memories
    scored: list[tuple[MemoryEntry, float, ScoreBreakdown]] = []
    for m in non_critical:
        bd = ScoreBreakdown(memory_id=m.id, title=m.title)
        score = _score(
            m, scene, recent_text, recently_used,
            weight_importance, weight_entity, weight_keyword,
            weight_recency, weight_reference, recency_half_life, reference_half_life,
            bd,
        )
        bd.total = score
        scored.append((m, score, bd))
        breakdowns.append(bd)

    scored.sort(key=lambda x: x[1], reverse=True)

    # Build result respecting per-type caps
    type_counts: dict[str, int] = {}
    result: list[MemoryEntry] = []

    # Critical memories are always included — they represent facts that must
    # never be forgotten regardless of who is currently in the scene.
    # (Character-defining facts, key world truths, permanent story outcomes.)
    for m in critical:
        t = m.type.value
        cap = caps.get(t, 0)
        count = type_counts.get(t, 0)
        if cap and count >= cap:
            continue
        type_counts[t] = count + 1
        result.append(m)

    # Fill remaining slots from scored
    remaining = max_results - len(result)
    for m, score, bd in scored:
        if len(result) - len(critical) >= remaining:
            break
        t = m.type.value
        cap = caps.get(t, 0)
        count = type_counts.get(t, 0)
        if cap and count >= cap:
            bd.rejection_reason = f"type cap ({t} >= {cap})"
            continue
        type_counts[t] = count + 1
        bd.selected = True
        result.append(m)

    # Deduplicate
    seen: set[str] = set()
    deduped: list[MemoryEntry] = []
    for m in result:
        if m.id not in seen:
            deduped.append(m)
            seen.add(m.id)

    if debug:
        _log_breakdown(breakdowns, deduped)

    return deduped[:max_results]


def _score(
    memory: MemoryEntry,
    scene: Optional[SceneState],
    recent_text: str,
    recently_used: set[str],
    w_importance: float,
    w_entity: float,
    w_keyword: float,
    w_recency: float,
    w_reference: float,
    recency_half_life: float,
    reference_half_life: float,
    bd: ScoreBreakdown,
) -> float:
    # 1. Importance base
    imp_base = _IMPORTANCE_SCORE.get(memory.importance, 1.0)
    bd.importance_score = imp_base * w_importance
    score = bd.importance_score

    # 2. Entity / location relevance
    if scene:
        scene_entities = {e.lower() for e in scene.active_characters}
        scene_entities.add(scene.location.lower())
        mem_entities = {e.lower() for e in memory.entities}
        if memory.location:
            mem_entities.add(memory.location.lower())
        overlap = scene_entities & mem_entities
        bd.entity_score = w_entity * len(overlap)
        score += bd.entity_score

    # 3. Keyword match in recent conversation
    if recent_text:
        text_lower = recent_text.lower()
        hits = sum(1 for tag in memory.tags if tag.lower() in text_lower)
        hits += sum(1 for ent in memory.entities if ent.lower() in text_lower)
        bd.keyword_score = w_keyword * hits
        score += bd.keyword_score

    # 4. Recency decay
    days_old = _days_since(memory.created_at)
    recency = math.exp(-days_old / max(recency_half_life, 1.0))
    bd.recency_score = w_recency * recency
    score += bd.recency_score

    # 5. Reference recency boost
    if memory.last_referenced_at:
        days_ref = _days_since(memory.last_referenced_at)
        ref_boost = math.exp(-days_ref / max(reference_half_life, 1.0))
        bd.reference_score = w_reference * ref_boost
        score += bd.reference_score

    # 6. Confidence multiplier
    bd.confidence_mult = max(0.0, min(1.0, memory.confidence))
    score *= bd.confidence_mult

    # 7. Certainty multiplier
    bd.certainty_mult = _CERTAINTY_MULT.get(memory.certainty, 1.0)
    score *= bd.certainty_mult

    # 8. Recently-used mild penalty (reduce repetition)
    if memory.id in recently_used:
        score *= 0.7

    return score


def _days_since(dt: datetime) -> float:
    now = datetime.now(UTC).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    delta = now - dt
    return max(0.0, delta.total_seconds() / 86400.0)


def _log_breakdown(breakdowns: list[ScoreBreakdown], selected: list[MemoryEntry]) -> None:
    selected_ids = {m.id for m in selected}
    log.debug("=== Memory retrieval breakdown ===")
    for bd in sorted(breakdowns, key=lambda b: b.total, reverse=True):
        status = "✓ SELECTED" if bd.memory_id in selected_ids else f"✗ rejected ({bd.rejection_reason or 'score'})"
        log.debug(
            "  [%s] '%s' total=%.2f imp=%.2f ent=%.2f kw=%.2f rec=%.2f ref=%.2f conf=%.2f cert=%.2f",
            status, bd.title, bd.total,
            bd.importance_score, bd.entity_score, bd.keyword_score,
            bd.recency_score, bd.reference_score,
            bd.confidence_mult, bd.certainty_mult,
        )
    log.debug("=== End retrieval breakdown ===")
