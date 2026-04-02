"""
Player objective store.
Manages the list of player-defined goals for a session.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection
from app.core.models import PlayerObjective, ObjectiveStatus


class ObjectivesStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save(self, obj: PlayerObjective) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO player_objectives
                     (id, session_id, title, description, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title       = excluded.title,
                     description = excluded.description,
                     status      = excluded.status,
                     updated_at  = excluded.updated_at""",
                (
                    obj.id,
                    obj.session_id,
                    obj.title,
                    obj.description,
                    obj.status.value,
                    obj.created_at.isoformat(),
                    obj.updated_at.isoformat(),
                ),
            )

    def get(self, objective_id: str) -> Optional[PlayerObjective]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM player_objectives WHERE id = ?", (objective_id,)
            ).fetchone()
        return _row_to_objective(row) if row else None

    def get_all(self, session_id: str) -> list[PlayerObjective]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM player_objectives WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_objective(r) for r in rows]

    def get_active(self, session_id: str) -> list[PlayerObjective]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM player_objectives
                   WHERE session_id = ? AND status = 'active'
                   ORDER BY created_at ASC""",
                (session_id,),
            ).fetchall()
        return [_row_to_objective(r) for r in rows]

    def update_status(self, objective_id: str, status: ObjectiveStatus) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE player_objectives SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now(UTC).replace(tzinfo=None).isoformat(), objective_id),
            )

    def delete(self, objective_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM player_objectives WHERE id = ?", (objective_id,)
            )

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM player_objectives WHERE session_id = ?", (session_id,)
            )


def _row_to_objective(row: sqlite3.Row) -> PlayerObjective:
    return PlayerObjective(
        id=row["id"],
        session_id=row["session_id"],
        title=row["title"],
        description=row["description"],
        status=ObjectiveStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
