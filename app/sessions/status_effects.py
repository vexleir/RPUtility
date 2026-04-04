"""
Status Effects store — persists active conditions on the player character.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection
from app.core.models import StatusEffect, EffectType


class StatusEffectStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, effect: StatusEffect) -> None:
        """Insert or replace a status effect (upsert by id)."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO status_effects
                    (id, session_id, name, description, effect_type,
                     severity, duration_turns, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    effect_type=excluded.effect_type,
                    severity=excluded.severity,
                    duration_turns=excluded.duration_turns
            """, (
                effect.id, effect.session_id, effect.name,
                effect.description, effect.effect_type.value,
                effect.severity, effect.duration_turns,
                effect.created_at.isoformat(),
            ))

    def delete(self, effect_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM status_effects WHERE id=?", (effect_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "DELETE FROM status_effects WHERE session_id=?", (session_id,)
            )

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, effect_id: str) -> StatusEffect | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM status_effects WHERE id=?", (effect_id,)
            ).fetchone()
        return _row_to_effect(row) if row else None

    def get_all(self, session_id: str) -> list[StatusEffect]:
        """Return all effects: debuffs first, then buffs, then neutral."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                """SELECT * FROM status_effects WHERE session_id=?
                   ORDER BY
                     CASE effect_type WHEN 'debuff' THEN 0
                                      WHEN 'buff' THEN 1
                                      ELSE 2 END,
                     severity DESC""",
                (session_id,),
            ).fetchall()
        return [_row_to_effect(r) for r in rows]

    def tick(self, session_id: str) -> list[str]:
        """
        Decrement duration_turns by 1 for all timed effects (duration_turns > 0).
        Delete effects that reach 0. Returns names of expired effects.
        Effects with duration_turns == 0 are permanent and are not ticked.
        """
        with get_connection(self._db) as conn:
            # Find effects about to expire (duration = 1 after decrement)
            expiring = conn.execute(
                "SELECT id, name FROM status_effects WHERE session_id=? AND duration_turns=1",
                (session_id,),
            ).fetchall()
            expired_names = [r["name"] for r in expiring]
            expired_ids = [r["id"] for r in expiring]

            # Decrement all timed effects
            conn.execute(
                "UPDATE status_effects SET duration_turns=duration_turns-1 WHERE session_id=? AND duration_turns>0",
                (session_id,),
            )
            # Delete newly-expired ones
            if expired_ids:
                placeholders = ",".join("?" * len(expired_ids))
                conn.execute(
                    f"DELETE FROM status_effects WHERE id IN ({placeholders})",
                    expired_ids,
                )
        return expired_names


def _row_to_effect(row) -> StatusEffect:
    return StatusEffect(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        description=row["description"] or "",
        effect_type=EffectType(row["effect_type"]),
        severity=row["severity"] or "mild",
        duration_turns=row["duration_turns"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
