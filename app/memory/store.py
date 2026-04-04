"""
Memory store — SQLite-backed CRUD for MemoryEntry objects.
All reads/writes go through this class.

Phase 2 additions:
  - New columns: certainty, consolidated_from, contradiction_of, archived
  - archive() method for soft-delete during consolidation
  - get_archived() for debug inspection
  - Contradiction flag storage
  - get_active() excludes archived memories (used by retriever and prompt builder)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import (
    MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel, ContradictonFlag
)


class MemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Write ─────────────────────────────────────────────────────────────

    def save(self, entry: MemoryEntry) -> None:
        """Insert or update a memory entry."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO memories
                    (id, session_id, created_at, updated_at, type, title, content,
                     entities, location, tags, importance, last_referenced_at,
                     source_turn_ids, confidence,
                     certainty, consolidated_from, contradiction_of, archived)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    updated_at          = excluded.updated_at,
                    title               = excluded.title,
                    content             = excluded.content,
                    entities            = excluded.entities,
                    location            = excluded.location,
                    tags                = excluded.tags,
                    importance          = excluded.importance,
                    last_referenced_at  = excluded.last_referenced_at,
                    source_turn_ids     = excluded.source_turn_ids,
                    confidence          = excluded.confidence,
                    certainty           = excluded.certainty,
                    consolidated_from   = excluded.consolidated_from,
                    contradiction_of    = excluded.contradiction_of,
                    archived            = excluded.archived
                """,
                (
                    entry.id,
                    entry.session_id,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                    entry.type.value,
                    entry.title,
                    entry.content,
                    json_encode(entry.entities),
                    entry.location,
                    json_encode(entry.tags),
                    entry.importance.value,
                    entry.last_referenced_at.isoformat() if entry.last_referenced_at else None,
                    json_encode(entry.source_turn_ids),
                    entry.confidence,
                    entry.certainty.value,
                    json_encode(entry.consolidated_from),
                    entry.contradiction_of,
                    int(entry.archived),
                ),
            )

    def save_many(self, entries: list[MemoryEntry]) -> None:
        for entry in entries:
            self.save(entry)

    def archive(self, memory_id: str) -> None:
        """Soft-delete a memory (archived=True). Keeps it for debug inspection."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE memories SET archived = 1, updated_at = ? WHERE id = ?",
                (datetime.now(UTC).replace(tzinfo=None).isoformat(), memory_id),
            )

    def archive_many(self, memory_ids: list[str]) -> None:
        for mid in memory_ids:
            self.archive(mid)

    # ── Read ──────────────────────────────────────────────────────────────

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def get_active(self, session_id: str) -> list[MemoryEntry]:
        """Return non-archived memories, most recent first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? AND archived = 0 ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_all(self, session_id: str) -> list[MemoryEntry]:
        """Return all memories including archived (for legacy compat and debug)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_archived(self, session_id: str) -> list[MemoryEntry]:
        """Return only archived (consolidated-away) memories for debug inspection."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? AND archived = 1 ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_by_importance(
        self, session_id: str, min_importance: ImportanceLevel
    ) -> list[MemoryEntry]:
        levels = [ImportanceLevel.LOW, ImportanceLevel.MEDIUM, ImportanceLevel.HIGH, ImportanceLevel.CRITICAL]
        idx = levels.index(min_importance)
        eligible = [l.value for l in levels[idx:]]
        placeholders = ",".join("?" for _ in eligible)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE session_id = ? AND archived = 0 "
                f"AND importance IN ({placeholders}) ORDER BY created_at DESC",
                (session_id, *eligible),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    # ── Reference tracking ────────────────────────────────────────────────

    def mark_referenced(self, memory_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE memories SET last_referenced_at = ? WHERE id = ?",
                (datetime.now(UTC).replace(tzinfo=None).isoformat(), memory_id),
            )

    # ── Delete ────────────────────────────────────────────────────────────

    def delete(self, memory_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))

    # ── Count ─────────────────────────────────────────────────────────────

    def count(self, session_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE session_id = ? AND archived = 0",
                (session_id,),
            ).fetchone()
        return row[0] if row else 0

    # ── Contradiction flags ───────────────────────────────────────────────

    def save_contradiction_flag(self, flag: ContradictonFlag) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO contradiction_flags
                     (id, session_id, detected_at, new_memory_id, existing_memory_id,
                      description, resolution)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    flag.id,
                    flag.session_id,
                    flag.detected_at.isoformat(),
                    flag.new_memory_id,
                    flag.existing_memory_id,
                    flag.description,
                    flag.resolution,
                ),
            )

    def get_contradiction_flags(self, session_id: str) -> list[ContradictonFlag]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM contradiction_flags WHERE session_id = ? ORDER BY detected_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_flag(r) for r in rows]

    def delete_contradiction_flag(self, flag_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM contradiction_flags WHERE id = ?", (flag_id,))
        return cur.rowcount > 0


# ── Row → model helpers ───────────────────────────────────────────────────────

def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    # Handle Phase 2 columns that may not exist in older DB rows
    try:
        certainty = CertaintyLevel(row["certainty"])
    except Exception:
        certainty = CertaintyLevel.CONFIRMED

    try:
        consolidated_from = json_decode(row["consolidated_from"])
    except Exception:
        consolidated_from = []

    try:
        contradiction_of = row["contradiction_of"]
    except Exception:
        contradiction_of = None

    try:
        archived = bool(row["archived"])
    except Exception:
        archived = False

    return MemoryEntry(
        id=row["id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        type=MemoryType(row["type"]),
        title=row["title"],
        content=row["content"],
        entities=json_decode(row["entities"]),
        location=row["location"],
        tags=json_decode(row["tags"]),
        importance=ImportanceLevel(row["importance"]),
        last_referenced_at=(
            datetime.fromisoformat(row["last_referenced_at"])
            if row["last_referenced_at"] else None
        ),
        source_turn_ids=json_decode(row["source_turn_ids"]),
        confidence=row["confidence"],
        certainty=certainty,
        consolidated_from=consolidated_from,
        contradiction_of=contradiction_of,
        archived=archived,
    )


def _row_to_flag(row: sqlite3.Row) -> ContradictonFlag:
    return ContradictonFlag(
        id=row["id"],
        session_id=row["session_id"],
        detected_at=datetime.fromisoformat(row["detected_at"]),
        new_memory_id=row["new_memory_id"],
        existing_memory_id=row["existing_memory_id"],
        description=row["description"],
        resolution=row["resolution"],
    )
