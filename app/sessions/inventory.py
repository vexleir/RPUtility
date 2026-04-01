"""
Inventory store — persists the player character's carried items for a session.
"""

from __future__ import annotations

from datetime import datetime

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import InventoryItem


class InventoryStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, item: InventoryItem) -> None:
        """Insert or replace an inventory item (upsert by id)."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO inventory
                    (id, session_id, name, description, condition,
                     quantity, tags, is_equipped, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    condition=excluded.condition,
                    quantity=excluded.quantity,
                    tags=excluded.tags,
                    is_equipped=excluded.is_equipped,
                    updated_at=excluded.updated_at
            """, (
                item.id, item.session_id, item.name,
                item.description, item.condition,
                item.quantity,
                json_encode(item.tags),
                int(item.is_equipped),
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ))

    def delete(self, item_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM inventory WHERE id=?", (item_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM inventory WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, item_id: str) -> InventoryItem | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM inventory WHERE id=?", (item_id,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def get_all(self, session_id: str) -> list[InventoryItem]:
        """Return all items, equipped items first, then alphabetical."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                """SELECT * FROM inventory WHERE session_id=?
                   ORDER BY is_equipped DESC, name""",
                (session_id,),
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_equipped(self, session_id: str) -> list[InventoryItem]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM inventory WHERE session_id=? AND is_equipped=1 ORDER BY name",
                (session_id,),
            ).fetchall()
        return [_row_to_item(r) for r in rows]


def _row_to_item(row) -> InventoryItem:
    return InventoryItem(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        description=row["description"] or "",
        condition=row["condition"] or "good",
        quantity=row["quantity"],
        tags=json_decode(row["tags"]),
        is_equipped=bool(row["is_equipped"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
