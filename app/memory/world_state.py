"""
World-state store.
Manages durable, session-level facts about the world that persist beyond
individual episode memories — faction shifts, political changes, environmental
conditions, confirmed secrets, etc.

Separate from lorebooks (static author-defined lore) and episodic memories
(per-event records). World-state entries are promoted from memory by the
consolidation pipeline or extracted directly from the narrative.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import WorldStateEntry, ImportanceLevel


class WorldStateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Write ─────────────────────────────────────────────────────────────

    def save(self, entry: WorldStateEntry) -> None:
        entry.updated_at = datetime.now(UTC).replace(tzinfo=None)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO world_state
                    (id, session_id, created_at, updated_at, category,
                     title, content, entities, tags, importance, source_memory_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at        = excluded.updated_at,
                    category          = excluded.category,
                    title             = excluded.title,
                    content           = excluded.content,
                    entities          = excluded.entities,
                    tags              = excluded.tags,
                    importance        = excluded.importance,
                    source_memory_ids = excluded.source_memory_ids
                """,
                (
                    entry.id,
                    entry.session_id,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                    entry.category,
                    entry.title,
                    entry.content,
                    json_encode(entry.entities),
                    json_encode(entry.tags),
                    entry.importance.value,
                    json_encode(entry.source_memory_ids),
                ),
            )

    def save_many(self, entries: list[WorldStateEntry]) -> None:
        for e in entries:
            self.save(e)

    # ── Read ──────────────────────────────────────────────────────────────

    def get_all(self, session_id: str) -> list[WorldStateEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM world_state WHERE session_id = ? ORDER BY importance DESC, updated_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_by_category(self, session_id: str, category: str) -> list[WorldStateEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM world_state WHERE session_id = ? AND category = ? ORDER BY updated_at DESC",
                (session_id, category),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get(self, entry_id: str) -> Optional[WorldStateEntry]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM world_state WHERE id = ?", (entry_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    # ── Delete ────────────────────────────────────────────────────────────

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM world_state WHERE session_id = ?", (session_id,))

    def count(self, session_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM world_state WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row[0] if row else 0


# ── Row helpers ────────────────────────────────────────────────────────────────

def _row_to_entry(row: sqlite3.Row) -> WorldStateEntry:
    return WorldStateEntry(
        id=row["id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        category=row["category"],
        title=row["title"],
        content=row["content"],
        entities=json_decode(row["entities"]),
        tags=json_decode(row["tags"]),
        importance=ImportanceLevel(row["importance"]),
        source_memory_ids=json_decode(row["source_memory_ids"]),
    )
