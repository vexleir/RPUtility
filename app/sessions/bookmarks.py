"""
Bookmark store.
Manages starred conversation moments for a session.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from app.core.database import get_connection
from app.core.models import Bookmark


class BookmarkStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save(self, bookmark: Bookmark) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO bookmarks
                     (id, session_id, turn_id, turn_number, role,
                      content_preview, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bookmark.id,
                    bookmark.session_id,
                    bookmark.turn_id,
                    bookmark.turn_number,
                    bookmark.role,
                    bookmark.content_preview,
                    bookmark.note,
                    bookmark.created_at.isoformat(),
                ),
            )

    def get(self, bookmark_id: str) -> Optional[Bookmark]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)
            ).fetchone()
        return _row_to_bookmark(row) if row else None

    def get_by_turn(self, session_id: str, turn_id: str) -> Optional[Bookmark]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM bookmarks WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
        return _row_to_bookmark(row) if row else None

    def get_all(self, session_id: str) -> list[Bookmark]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM bookmarks
                   WHERE session_id = ?
                   ORDER BY turn_number ASC""",
                (session_id,),
            ).fetchall()
        return [_row_to_bookmark(r) for r in rows]

    def update_note(self, bookmark_id: str, note: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE bookmarks SET note = ? WHERE id = ?",
                (note, bookmark_id),
            )

    def delete(self, bookmark_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))

    def delete_by_turn(self, session_id: str, turn_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM bookmarks WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            )

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM bookmarks WHERE session_id = ?", (session_id,)
            )


def _row_to_bookmark(row: sqlite3.Row) -> Bookmark:
    return Bookmark(
        id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        turn_number=row["turn_number"],
        role=row["role"],
        content_preview=row["content_preview"],
        note=row["note"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
