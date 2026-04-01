"""
NPC Roster store — persists known NPCs for a session.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import NpcEntry


class NpcRosterStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, npc: NpcEntry) -> None:
        """Insert or replace an NPC entry (upsert by id)."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO npc_roster
                    (id, session_id, name, role, description, personality_notes,
                     last_known_location, is_alive, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    role=excluded.role,
                    description=excluded.description,
                    personality_notes=excluded.personality_notes,
                    last_known_location=excluded.last_known_location,
                    is_alive=excluded.is_alive,
                    tags=excluded.tags,
                    updated_at=excluded.updated_at
            """, (
                npc.id, npc.session_id, npc.name, npc.role,
                npc.description, npc.personality_notes,
                npc.last_known_location, int(npc.is_alive),
                json_encode(npc.tags),
                npc.created_at.isoformat(), npc.updated_at.isoformat(),
            ))

    def delete(self, npc_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_roster WHERE id=?", (npc_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_roster WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, npc_id: str) -> NpcEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM npc_roster WHERE id=?", (npc_id,)
            ).fetchone()
        return _row_to_npc(row) if row else None

    def get_by_name(self, session_id: str, name: str) -> NpcEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM npc_roster WHERE session_id=? AND LOWER(name)=LOWER(?)",
                (session_id, name),
            ).fetchone()
        return _row_to_npc(row) if row else None

    def get_all(self, session_id: str) -> list[NpcEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM npc_roster WHERE session_id=? ORDER BY name",
                (session_id,),
            ).fetchall()
        return [_row_to_npc(r) for r in rows]

    def get_alive(self, session_id: str) -> list[NpcEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM npc_roster WHERE session_id=? AND is_alive=1 ORDER BY name",
                (session_id,),
            ).fetchall()
        return [_row_to_npc(r) for r in rows]


def _row_to_npc(row) -> NpcEntry:
    return NpcEntry(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        role=row["role"] or "",
        description=row["description"] or "",
        personality_notes=row["personality_notes"] or "",
        last_known_location=row["last_known_location"] or "",
        is_alive=bool(row["is_alive"]),
        tags=json_decode(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
