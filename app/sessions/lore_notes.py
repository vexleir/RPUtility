"""
Lore notes store.
Player-curated world knowledge, categorized and searchable.
Categories: general, history, magic, faction, character, location, rumor, prophecy
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import LoreNote


class LoreNoteStore:
    def __init__(self, db_path: str):
        self._db = db_path

    def save(self, note: LoreNote) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO lore_notes
                    (id, session_id, title, content, category, source, tags, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title      = excluded.title,
                    content    = excluded.content,
                    category   = excluded.category,
                    source     = excluded.source,
                    tags       = excluded.tags,
                    updated_at = excluded.updated_at
                """,
                (
                    note.id,
                    note.session_id,
                    note.title,
                    note.content,
                    note.category,
                    note.source,
                    json_encode(note.tags),
                    note.created_at.isoformat(),
                    note.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, note_id: str) -> LoreNote | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM lore_notes WHERE id = ?", (note_id,)
            ).fetchone()
        return _row_to_note(row) if row else None

    def get_all(self, session_id: str) -> list[LoreNote]:
        """Return all notes ordered by category then title."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM lore_notes WHERE session_id = ? ORDER BY category ASC, title ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_note(r) for r in rows]

    def get_by_category(self, session_id: str, category: str) -> list[LoreNote]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM lore_notes WHERE session_id = ? AND LOWER(category) = LOWER(?) ORDER BY title ASC",
                (session_id, category),
            ).fetchall()
        return [_row_to_note(r) for r in rows]

    def delete(self, note_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM lore_notes WHERE id = ?", (note_id,))
            conn.commit()

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM lore_notes WHERE session_id = ?", (session_id,))
            conn.commit()


def _row_to_note(row) -> LoreNote:
    return LoreNote(
        id=row["id"],
        session_id=row["session_id"],
        title=row["title"],
        content=row["content"],
        category=row["category"],
        source=row["source"] or "",
        tags=json_decode(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
