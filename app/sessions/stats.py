"""
Character Stats store — persists the player character's attributes and skills.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection
from app.core.models import CharacterStat


class CharacterStatStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, stat: CharacterStat) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO character_stats
                    (id, session_id, name, value, modifier, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    value=excluded.value,
                    modifier=excluded.modifier,
                    category=excluded.category,
                    updated_at=excluded.updated_at
            """, (
                stat.id, stat.session_id, stat.name,
                stat.value, stat.modifier, stat.category,
                stat.created_at.isoformat(), stat.updated_at.isoformat(),
            ))

    def delete(self, stat_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM character_stats WHERE id=?", (stat_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "DELETE FROM character_stats WHERE session_id=?", (session_id,)
            )

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, stat_id: str) -> CharacterStat | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM character_stats WHERE id=?", (stat_id,)
            ).fetchone()
        return _row_to_stat(row) if row else None

    def get_by_name(self, session_id: str, name: str) -> CharacterStat | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM character_stats WHERE session_id=? AND LOWER(name)=LOWER(?)",
                (session_id, name),
            ).fetchone()
        return _row_to_stat(row) if row else None

    def get_all(self, session_id: str) -> list[CharacterStat]:
        """Return stats ordered by category then name."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM character_stats WHERE session_id=? ORDER BY category, name",
                (session_id,),
            ).fetchall()
        return [_row_to_stat(r) for r in rows]

    def get_by_category(self, session_id: str, category: str) -> list[CharacterStat]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM character_stats WHERE session_id=? AND category=? ORDER BY name",
                (session_id, category),
            ).fetchall()
        return [_row_to_stat(r) for r in rows]


def _row_to_stat(row) -> CharacterStat:
    return CharacterStat(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        value=row["value"],
        modifier=row["modifier"],
        category=row["category"] or "attribute",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
