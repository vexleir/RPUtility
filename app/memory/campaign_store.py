"""
Campaign memory store.

Stores MemoryEntry objects extracted from campaign scene transcripts.
Uses the `campaign_memories` table (same schema as `memories`) with
campaign_id in the session_id column.

Provides only the subset of MemoryStore operations used by the campaign
pipeline: save, retrieve active, archive, and contradiction flags.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Optional

import sqlite3

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import (
    MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel, ContradictonFlag
)
from app.memory.embedder import encode_embedding, decode_embedding


class CampaignMemoryStore:
    """SQLite-backed store for campaign-scoped MemoryEntry objects."""

    _TABLE = "campaign_memories"

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Write ─────────────────────────────────────────────────────────────

    def save(self, entry: MemoryEntry) -> None:
        embedding_blob = encode_embedding(entry.embedding) if entry.embedding else None
        with self._conn() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._TABLE}
                    (id, session_id, created_at, updated_at, type, title, content,
                     entities, location, tags, importance, last_referenced_at,
                     source_turn_ids, source_turn_number, confidence,
                     certainty, consolidated_from, contradiction_of, archived, embedding)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_turn_number  = excluded.source_turn_number,
                    confidence          = excluded.confidence,
                    certainty           = excluded.certainty,
                    consolidated_from   = excluded.consolidated_from,
                    contradiction_of    = excluded.contradiction_of,
                    archived            = excluded.archived,
                    embedding           = excluded.embedding
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
                    entry.source_turn_number,
                    entry.confidence,
                    entry.certainty.value,
                    json_encode(entry.consolidated_from),
                    entry.contradiction_of,
                    int(entry.archived),
                    embedding_blob,
                ),
            )

    def save_many(self, entries: list[MemoryEntry]) -> None:
        for entry in entries:
            self.save(entry)

    def archive(self, memory_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                f"UPDATE {self._TABLE} SET archived = 1, updated_at = ? WHERE id = ?",
                (datetime.now(UTC).replace(tzinfo=None).isoformat(), memory_id),
            )

    def archive_many(self, memory_ids: list[str]) -> None:
        for mid in memory_ids:
            self.archive(mid)

    # ── Read ──────────────────────────────────────────────────────────────

    def get_active(self, campaign_id: str) -> list[MemoryEntry]:
        """Return all non-archived memories for a campaign, most recent first."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._TABLE} WHERE session_id = ? AND archived = 0"
                " ORDER BY created_at DESC",
                (campaign_id,),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_active_for_scene(
        self,
        campaign_id: str,
        npc_names: list[str],
        location: Optional[str] = None,
        max_results: int = 20,
    ) -> list[MemoryEntry]:
        """
        Return active memories relevant to the current scene.
        Prioritises memories whose entities overlap with npc_names or whose
        location matches.  Falls back to all active memories if few match.
        """
        all_active = self.get_active(campaign_id)
        if not all_active:
            return []

        npc_lower = {n.lower() for n in npc_names}
        loc_lower = location.lower() if location else ""

        priority: list[MemoryEntry] = []
        rest: list[MemoryEntry] = []
        for m in all_active:
            mem_entities = {e.lower() for e in m.entities}
            mem_loc = (m.location or "").lower()
            if npc_lower & mem_entities or (loc_lower and mem_loc == loc_lower):
                priority.append(m)
            else:
                rest.append(m)

        combined = priority + rest
        return combined[:max_results]

    def count(self, campaign_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {self._TABLE} WHERE session_id = ? AND archived = 0",
                (campaign_id,),
            ).fetchone()
        return row[0] if row else 0

    def delete_campaign(self, campaign_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                f"DELETE FROM {self._TABLE} WHERE session_id = ?", (campaign_id,)
            )


# ── Row → model helper ────────────────────────────────────────────────────────

def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
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
    try:
        source_turn_number = int(row["source_turn_number"])
    except Exception:
        source_turn_number = 0
    try:
        blob = row["embedding"]
        embedding = decode_embedding(blob) if blob else None
    except Exception:
        embedding = None

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
        source_turn_number=source_turn_number,
        confidence=row["confidence"],
        certainty=certainty,
        consolidated_from=consolidated_from,
        contradiction_of=contradiction_of,
        archived=archived,
        embedding=embedding,
    )
