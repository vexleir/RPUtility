"""
Relationship tracker.
Stores and updates directional relationship axes between entities.
Each (session, source, target) triple has its own RelationshipState row.

Relationship axes: trust, fear, respect, affection, hostility
All values are floats; trust/respect/affection range -1.0 to 1.0;
fear/hostility range 0.0 to 1.0.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection
from app.core.models import RelationshipState


class RelationshipTracker:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Get / list ────────────────────────────────────────────────────────

    def get(
        self, session_id: str, source: str, target: str
    ) -> RelationshipState:
        """Return relationship, creating a neutral default if absent."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM relationships
                   WHERE session_id = ? AND source_entity = ? AND target_entity = ?""",
                (session_id, source, target),
            ).fetchone()

        if row:
            return _row_to_rel(row)
        return RelationshipState(
            session_id=session_id,
            source_entity=source,
            target_entity=target,
        )

    def get_all(self, session_id: str) -> list[RelationshipState]:
        """Return all relationships for a session."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE session_id = ? ORDER BY source_entity",
                (session_id,),
            ).fetchall()
        return [_row_to_rel(r) for r in rows]

    def get_involving(
        self, session_id: str, entity: str
    ) -> list[RelationshipState]:
        """Return all relationships where entity is source or target."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM relationships
                   WHERE session_id = ?
                     AND (source_entity = ? OR target_entity = ?)
                   ORDER BY source_entity""",
                (session_id, entity, entity),
            ).fetchall()
        return [_row_to_rel(r) for r in rows]

    # ── Save ──────────────────────────────────────────────────────────────

    def save(self, rel: RelationshipState) -> None:
        """Upsert a relationship state."""
        rel.last_updated = datetime.now(UTC).replace(tzinfo=None)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO relationships
                    (session_id, source_entity, target_entity,
                     trust, fear, respect, affection, hostility, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, source_entity, target_entity) DO UPDATE SET
                    trust        = excluded.trust,
                    fear         = excluded.fear,
                    respect      = excluded.respect,
                    affection    = excluded.affection,
                    hostility    = excluded.hostility,
                    last_updated = excluded.last_updated
                """,
                (
                    rel.session_id,
                    rel.source_entity,
                    rel.target_entity,
                    _clamp(rel.trust, -1.0, 1.0),
                    _clamp(rel.fear, 0.0, 1.0),
                    _clamp(rel.respect, -1.0, 1.0),
                    _clamp(rel.affection, -1.0, 1.0),
                    _clamp(rel.hostility, 0.0, 1.0),
                    rel.last_updated.isoformat(),
                ),
            )

    # ── Convenience mutators ──────────────────────────────────────────────

    def adjust(
        self,
        session_id: str,
        source: str,
        target: str,
        *,
        trust: float = 0.0,
        fear: float = 0.0,
        respect: float = 0.0,
        affection: float = 0.0,
        hostility: float = 0.0,
    ) -> RelationshipState:
        """
        Apply deltas to a relationship and save.
        Clamps all values to their legal ranges after adjustment.
        """
        rel = self.get(session_id, source, target)
        rel.trust = _clamp(rel.trust + trust, -1.0, 1.0)
        rel.fear = _clamp(rel.fear + fear, 0.0, 1.0)
        rel.respect = _clamp(rel.respect + respect, -1.0, 1.0)
        rel.affection = _clamp(rel.affection + affection, -1.0, 1.0)
        rel.hostility = _clamp(rel.hostility + hostility, 0.0, 1.0)
        self.save(rel)
        return rel

    def set_relationship(
        self,
        session_id: str,
        source: str,
        target: str,
        *,
        trust: Optional[float] = None,
        fear: Optional[float] = None,
        respect: Optional[float] = None,
        affection: Optional[float] = None,
        hostility: Optional[float] = None,
    ) -> RelationshipState:
        """Overwrite specific axes and save."""
        rel = self.get(session_id, source, target)
        if trust is not None:
            rel.trust = _clamp(trust, -1.0, 1.0)
        if fear is not None:
            rel.fear = _clamp(fear, 0.0, 1.0)
        if respect is not None:
            rel.respect = _clamp(respect, -1.0, 1.0)
        if affection is not None:
            rel.affection = _clamp(affection, -1.0, 1.0)
        if hostility is not None:
            rel.hostility = _clamp(hostility, 0.0, 1.0)
        self.save(rel)
        return rel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _row_to_rel(row: sqlite3.Row) -> RelationshipState:
    return RelationshipState(
        session_id=row["session_id"],
        source_entity=row["source_entity"],
        target_entity=row["target_entity"],
        trust=row["trust"],
        fear=row["fear"],
        respect=row["respect"],
        affection=row["affection"],
        hostility=row["hostility"],
        last_updated=datetime.fromisoformat(row["last_updated"]),
    )
