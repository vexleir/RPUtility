"""
Story Beats store — persists major narrative milestones for a session.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import StoryBeat, BeatType, ImportanceLevel


class StoryBeatStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, beat: StoryBeat) -> None:
        """Insert or replace a story beat (upsert by id)."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO story_beats
                    (id, session_id, title, description, beat_type,
                     turn_number, importance, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    beat_type=excluded.beat_type,
                    turn_number=excluded.turn_number,
                    importance=excluded.importance,
                    tags=excluded.tags
            """, (
                beat.id, beat.session_id, beat.title, beat.description,
                beat.beat_type.value, beat.turn_number,
                beat.importance.value,
                json_encode(beat.tags),
                beat.created_at.isoformat(),
            ))

    def delete(self, beat_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM story_beats WHERE id=?", (beat_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM story_beats WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, beat_id: str) -> StoryBeat | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM story_beats WHERE id=?", (beat_id,)
            ).fetchone()
        return _row_to_beat(row) if row else None

    def get_all(self, session_id: str) -> list[StoryBeat]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM story_beats WHERE session_id=? ORDER BY turn_number, created_at",
                (session_id,),
            ).fetchall()
        return [_row_to_beat(r) for r in rows]

    def get_recent(self, session_id: str, n: int = 5) -> list[StoryBeat]:
        """Return the n most recent beats."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                """SELECT * FROM story_beats WHERE session_id=?
                   ORDER BY turn_number DESC, created_at DESC LIMIT ?""",
                (session_id, n),
            ).fetchall()
        return [_row_to_beat(r) for r in rows]


def _row_to_beat(row) -> StoryBeat:
    return StoryBeat(
        id=row["id"],
        session_id=row["session_id"],
        title=row["title"],
        description=row["description"] or "",
        beat_type=BeatType(row["beat_type"]),
        turn_number=row["turn_number"],
        importance=ImportanceLevel(row["importance"]),
        tags=json_decode(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
