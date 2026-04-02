"""
Faction store — persists named factions and the player's standing with each.
"""

from __future__ import annotations

from datetime import datetime, UTC

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import Faction


class FactionStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, faction: Faction) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO factions
                    (id, session_id, name, description, alignment,
                     standing, tags, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    alignment=excluded.alignment,
                    standing=excluded.standing,
                    tags=excluded.tags,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
            """, (
                faction.id, faction.session_id, faction.name,
                faction.description, faction.alignment,
                max(-1.0, min(1.0, faction.standing)),  # clamp -1 to 1
                json_encode(faction.tags),
                faction.notes,
                faction.created_at.isoformat(),
                faction.updated_at.isoformat(),
            ))

    def delete(self, faction_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM factions WHERE id=?", (faction_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM factions WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, faction_id: str) -> Faction | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM factions WHERE id=?", (faction_id,)
            ).fetchone()
        return _row_to_faction(row) if row else None

    def get_by_name(self, session_id: str, name: str) -> Faction | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM factions WHERE session_id=? AND LOWER(name)=LOWER(?)",
                (session_id, name),
            ).fetchone()
        return _row_to_faction(row) if row else None

    def get_all(self, session_id: str) -> list[Faction]:
        """Return factions ordered by standing descending (allied → hostile)."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM factions WHERE session_id=? ORDER BY standing DESC, name",
                (session_id,),
            ).fetchall()
        return [_row_to_faction(r) for r in rows]

    def adjust_standing(self, faction_id: str, delta: float) -> Faction | None:
        """Add delta to standing, clamped to [-1, 1]. Returns updated faction."""
        faction = self.get(faction_id)
        if not faction:
            return None
        faction.standing = max(-1.0, min(1.0, faction.standing + delta))
        faction.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.save(faction)
        return faction


def _row_to_faction(row) -> Faction:
    return Faction(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        description=row["description"] or "",
        alignment=row["alignment"] or "",
        standing=float(row["standing"]),
        tags=json_decode(row["tags"]),
        notes=row["notes"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
