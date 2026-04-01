"""
Emotional State store — persists the player character's current emotional
condition for a session. One row per session; upserted on every save.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection
from app.core.models import EmotionalState


class EmotionalStateStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, state: EmotionalState) -> None:
        """Upsert the emotional state for the session."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO emotional_state
                    (session_id, mood, stress, motivation, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    mood=excluded.mood,
                    stress=excluded.stress,
                    motivation=excluded.motivation,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
            """, (
                state.session_id,
                state.mood,
                max(0.0, min(1.0, state.stress)),  # clamp 0–1
                state.motivation,
                state.notes,
                state.updated_at.isoformat(),
            ))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "DELETE FROM emotional_state WHERE session_id=?", (session_id,)
            )

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> EmotionalState | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM emotional_state WHERE session_id=?", (session_id,)
            ).fetchone()
        return _row_to_state(row) if row else None

    def get_or_default(self, session_id: str) -> EmotionalState:
        """Return the state, or a neutral default if none has been set."""
        state = self.get(session_id)
        if state is None:
            state = EmotionalState(session_id=session_id)
        return state


def _row_to_state(row) -> EmotionalState:
    return EmotionalState(
        session_id=row["session_id"],
        mood=row["mood"] or "neutral",
        stress=float(row["stress"]),
        motivation=row["motivation"] or "",
        notes=row["notes"] or "",
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
