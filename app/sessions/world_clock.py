"""
In-world clock store — persists the in-game date/time for a session.
One clock per session; upserted on every save.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection
from app.core.models import WorldClock


class WorldClockStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, clock: WorldClock) -> None:
        """Upsert the clock for the session."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO world_clock
                    (session_id, year, month, day, hour, era_label, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    year=excluded.year,
                    month=excluded.month,
                    day=excluded.day,
                    hour=excluded.hour,
                    era_label=excluded.era_label,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
            """, (
                clock.session_id,
                clock.year, clock.month, clock.day, clock.hour,
                clock.era_label, clock.notes,
                clock.updated_at.isoformat(),
            ))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM world_clock WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> WorldClock | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM world_clock WHERE session_id=?", (session_id,)
            ).fetchone()
        return _row_to_clock(row) if row else None

    def get_or_default(self, session_id: str) -> WorldClock:
        """Return the clock, or a default Day 1/Month 1/Year 1 if none set."""
        clock = self.get(session_id)
        if clock is None:
            clock = WorldClock(session_id=session_id)
        return clock


def _row_to_clock(row) -> WorldClock:
    return WorldClock(
        session_id=row["session_id"],
        year=row["year"],
        month=row["month"],
        day=row["day"],
        hour=row["hour"],
        era_label=row["era_label"] or "",
        notes=row["notes"] or "",
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
