"""
Narrative Arc store — persists the high-level story structure for a session.
One arc per session; upserted on every save.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import NarrativeArc


class NarrativeArcStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, arc: NarrativeArc) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO narrative_arc
                    (session_id, current_act, act_label, tension, pacing,
                     themes, arc_notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    current_act=excluded.current_act,
                    act_label=excluded.act_label,
                    tension=excluded.tension,
                    pacing=excluded.pacing,
                    themes=excluded.themes,
                    arc_notes=excluded.arc_notes,
                    updated_at=excluded.updated_at
            """, (
                arc.session_id,
                arc.current_act,
                arc.act_label,
                max(0.0, min(1.0, arc.tension)),  # clamp 0–1
                arc.pacing,
                json_encode(arc.themes),
                arc.arc_notes,
                arc.updated_at.isoformat(),
            ))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "DELETE FROM narrative_arc WHERE session_id=?", (session_id,)
            )

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> NarrativeArc | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM narrative_arc WHERE session_id=?", (session_id,)
            ).fetchone()
        return _row_to_arc(row) if row else None

    def get_or_default(self, session_id: str) -> NarrativeArc:
        arc = self.get(session_id)
        if arc is None:
            arc = NarrativeArc(session_id=session_id)
        return arc


def _row_to_arc(row) -> NarrativeArc:
    return NarrativeArc(
        session_id=row["session_id"],
        current_act=row["current_act"],
        act_label=row["act_label"] or "Opening",
        tension=float(row["tension"]),
        pacing=row["pacing"] or "building",
        themes=json_decode(row["themes"]),
        arc_notes=row["arc_notes"] or "",
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
