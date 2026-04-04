"""
Session manager.
Creates, loads, and manages roleplay sessions.
Each session ties together: a character card, an optional lorebook,
conversation history, memory, scene state, and relationships.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection
from app.core.models import Session, ConversationTurn


class SessionManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Session CRUD ──────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        character_name: str,
        lorebook_name: Optional[str] = None,
        model_name: Optional[str] = None,
        scenario_text: Optional[str] = None,
    ) -> Session:
        session = Session(
            name=name,
            character_name=character_name,
            lorebook_name=lorebook_name,
            model_name=model_name,
            scenario_text=scenario_text,
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sessions
                     (id, name, character_name, lorebook_name, model_name,
                      created_at, last_active, turn_count, scenario_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.name,
                    session.character_name,
                    session.lorebook_name,
                    session.model_name,
                    session.created_at.isoformat(),
                    session.last_active.isoformat(),
                    session.turn_count,
                    session.scenario_text,
                ),
            )
        return session

    def get(self, session_id: str) -> Optional[Session]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def list_all(self) -> list[Session]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY last_active DESC"
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def touch(self, session_id: str) -> None:
        """Update last_active timestamp."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE id = ?",
                (datetime.now(UTC).replace(tzinfo=None).isoformat(), session_id),
            )

    def increment_turn(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET turn_count = turn_count + 1 WHERE id = ?",
                (session_id,),
            )

    # ── Conversation turns ────────────────────────────────────────────────

    def add_turn(self, turn: ConversationTurn) -> None:
        """Persist a single conversation turn."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO turns
                     (id, session_id, turn_number, role, content, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    turn.id,
                    turn.session_id,
                    turn.turn_number,
                    turn.role,
                    turn.content,
                    turn.timestamp.isoformat(),
                ),
            )

    def get_turns(
        self,
        session_id: str,
        limit: int = 40,
        offset: int = 0,
    ) -> list[ConversationTurn]:
        """Return the most recent `limit` turns for a session."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM turns
                   WHERE session_id = ?
                   ORDER BY turn_number DESC
                   LIMIT ? OFFSET ?""",
                (session_id, limit, offset),
            ).fetchall()
        # Reverse so oldest is first (chronological order)
        turns = [_row_to_turn(r) for r in rows]
        turns.reverse()
        return turns

    def get_last_n_turns(
        self, session_id: str, n: int = 20
    ) -> list[ConversationTurn]:
        """Return the last N turns in chronological order."""
        return self.get_turns(session_id, limit=n)

    def get_turn_count(self, session_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT turn_count FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row["turn_count"] if row else 0

    def get_last_turns_by_role(
        self, session_id: str, role: str, n: int = 1
    ) -> list[ConversationTurn]:
        """Return the last N turns matching the given role, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM turns
                   WHERE session_id = ? AND role = ?
                   ORDER BY turn_number DESC
                   LIMIT ?""",
                (session_id, role, n),
            ).fetchall()
        return [_row_to_turn(r) for r in rows]

    def update_turn_content(self, turn_id: str, content: str) -> bool:
        """Update the content of a single turn. Returns True if a row was found."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE turns SET content=? WHERE id=?",
                (content, turn_id),
            )
        return cur.rowcount > 0

    def get_turn_by_id(self, turn_id: str):
        """Return a single ConversationTurn by its ID, or None."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        return _row_to_turn(row) if row else None

    def delete_turn_by_id(self, turn_id: str) -> bool:
        """Delete a single turn by ID. Returns True if a row was found and deleted."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM turns WHERE id=?", (turn_id,))
        return cur.rowcount > 0

    def delete_turns_from(self, session_id: str, turn_number: int) -> int:
        """Delete all turns with turn_number >= turn_number. Returns count deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM turns WHERE session_id = ? AND turn_number >= ?",
                (session_id, turn_number),
            )
        return cur.rowcount

    def decrement_turn_count(self, session_id: str, by: int = 1) -> None:
        """Decrease turn_count, flooring at 0."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE sessions
                   SET turn_count = MAX(0, turn_count - ?)
                   WHERE id = ?""",
                (by, session_id),
            )

    def search_turns(
        self, session_id: str, query: str, limit: int = 200
    ) -> list[ConversationTurn]:
        """Return turns whose content contains query (case-insensitive)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM turns
                   WHERE session_id = ?
                     AND LOWER(content) LIKE LOWER(?)
                   ORDER BY turn_number ASC
                   LIMIT ?""",
                (session_id, f"%{query}%", limit),
            ).fetchall()
        return [_row_to_turn(r) for r in rows]

    def delete(self, session_id: str) -> None:
        """Delete a session and all its associated data."""
        with self._conn() as conn:
            conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM scene_state WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM relationships WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM player_objectives WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM bookmarks WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# ── Row → model helpers ───────────────────────────────────────────────────────

def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        name=row["name"],
        character_name=row["character_name"],
        lorebook_name=row["lorebook_name"],
        model_name=row["model_name"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_active=datetime.fromisoformat(row["last_active"]),
        turn_count=row["turn_count"],
        scenario_text=row["scenario_text"] if "scenario_text" in row.keys() else None,
    )


def _row_to_turn(row: sqlite3.Row) -> ConversationTurn:
    return ConversationTurn(
        id=row["id"],
        session_id=row["session_id"],
        turn_number=row["turn_number"],
        role=row["role"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )
