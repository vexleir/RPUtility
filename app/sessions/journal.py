"""
Session journal store.
Timestamped free-form player notes; immutable once written (no update, only delete).
Ordered newest-first.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import JournalEntry


class JournalStore:
    def __init__(self, db_path: str):
        self._db = db_path

    def save(self, entry: JournalEntry) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO journal_entries
                    (id, session_id, title, content, turn_number, tags, created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    entry.id,
                    entry.session_id,
                    entry.title,
                    entry.content,
                    entry.turn_number,
                    json_encode(entry.tags),
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, entry_id: str) -> JournalEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def get_all(self, session_id: str) -> list[JournalEntry]:
        """Return all entries newest-first."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM journal_entries WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_recent(self, session_id: str, n: int = 10) -> list[JournalEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM journal_entries WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, n),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def delete(self, entry_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            conn.commit()

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM journal_entries WHERE session_id = ?", (session_id,))
            conn.commit()


def _row_to_entry(row) -> JournalEntry:
    return JournalEntry(
        id=row["id"],
        session_id=row["session_id"],
        title=row["title"],
        content=row["content"],
        turn_number=row["turn_number"],
        tags=json_decode(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
