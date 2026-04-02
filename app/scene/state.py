"""
Scene state manager.
Tracks current location, active characters, and a rolling scene summary.
Persisted to SQLite; one row per session (upserted on each update).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import SceneState


class SceneManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ── Load ──────────────────────────────────────────────────────────────

    def get(self, session_id: str) -> SceneState:
        """Return the current scene for a session, creating a default if absent."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM scene_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if row:
            return _row_to_scene(row)

        # Return default scene (not yet persisted)
        return SceneState(session_id=session_id)

    # ── Save ──────────────────────────────────────────────────────────────

    def save(self, scene: SceneState) -> None:
        """Upsert the scene state for a session."""
        scene.last_updated = datetime.now(UTC).replace(tzinfo=None)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO scene_state
                    (session_id, location, active_characters, summary, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    location          = excluded.location,
                    active_characters = excluded.active_characters,
                    summary           = excluded.summary,
                    last_updated      = excluded.last_updated
                """,
                (
                    scene.session_id,
                    scene.location,
                    json_encode(scene.active_characters),
                    scene.summary,
                    scene.last_updated.isoformat(),
                ),
            )

    # ── Convenience mutators ──────────────────────────────────────────────

    def update_location(self, session_id: str, location: str) -> SceneState:
        scene = self.get(session_id)
        scene.location = location
        self.save(scene)
        return scene

    def add_character(self, session_id: str, name: str) -> SceneState:
        scene = self.get(session_id)
        if name not in scene.active_characters:
            scene.active_characters.append(name)
        self.save(scene)
        return scene

    def remove_character(self, session_id: str, name: str) -> SceneState:
        scene = self.get(session_id)
        scene.active_characters = [c for c in scene.active_characters if c != name]
        self.save(scene)
        return scene

    def update_summary(self, session_id: str, summary: str) -> SceneState:
        scene = self.get(session_id)
        scene.summary = summary
        self.save(scene)
        return scene

    def update(
        self,
        session_id: str,
        *,
        location: Optional[str] = None,
        active_characters: Optional[list[str]] = None,
        summary: Optional[str] = None,
    ) -> SceneState:
        """Apply multiple updates in one call."""
        scene = self.get(session_id)
        if location is not None:
            scene.location = location
        if active_characters is not None:
            scene.active_characters = active_characters
        if summary is not None:
            scene.summary = summary
        self.save(scene)
        return scene


def _row_to_scene(row: sqlite3.Row) -> SceneState:
    return SceneState(
        session_id=row["session_id"],
        location=row["location"],
        active_characters=json_decode(row["active_characters"]),
        summary=row["summary"],
        last_updated=datetime.fromisoformat(row["last_updated"]),
    )
