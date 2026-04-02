"""
Unit tests for scene state management.
"""

import sqlite3

import pytest
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import SceneState
from app.scene.state import SceneManager


def _seed_session(db_path: str, session_id: str) -> None:
    """Insert a minimal sessions row so FK constraints are satisfied."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT OR IGNORE INTO sessions(id, name, character_name, created_at, last_active)"
        " VALUES (?, ?, '', datetime('now'), datetime('now'))",
        (session_id, session_id),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    ensure_db(path)
    _seed_session(path, "sess1")
    _seed_session(path, "sess2")
    _seed_session(path, "new_session")
    return path


@pytest.fixture
def manager(db_path: str) -> SceneManager:
    return SceneManager(db_path)


class TestSceneManager:
    def test_get_default_scene(self, manager: SceneManager):
        """Getting a scene that doesn't exist should return a default."""
        scene = manager.get("new_session")
        assert scene.session_id == "new_session"
        assert scene.location == "Unknown"
        assert scene.active_characters == []

    def test_save_and_get(self, manager: SceneManager):
        scene = SceneState(
            session_id="sess1",
            location="Crosshaven",
            active_characters=["Lyra", "Player"],
            summary="They met at the tavern.",
        )
        manager.save(scene)
        retrieved = manager.get("sess1")
        assert retrieved.location == "Crosshaven"
        assert "Lyra" in retrieved.active_characters
        assert retrieved.summary == "They met at the tavern."

    def test_upsert(self, manager: SceneManager):
        """Saving twice should update, not create a duplicate."""
        scene = SceneState(session_id="sess1", location="Forest")
        manager.save(scene)
        scene.location = "Mountain"
        manager.save(scene)
        retrieved = manager.get("sess1")
        assert retrieved.location == "Mountain"

    def test_update_location(self, manager: SceneManager):
        scene = SceneState(session_id="sess1", location="Tavern")
        manager.save(scene)
        manager.update_location("sess1", "Castle")
        assert manager.get("sess1").location == "Castle"

    def test_add_character(self, manager: SceneManager):
        scene = SceneState(session_id="sess1", active_characters=["Lyra"])
        manager.save(scene)
        manager.add_character("sess1", "Baron")
        chars = manager.get("sess1").active_characters
        assert "Lyra" in chars
        assert "Baron" in chars

    def test_add_character_no_duplicate(self, manager: SceneManager):
        scene = SceneState(session_id="sess1", active_characters=["Lyra"])
        manager.save(scene)
        manager.add_character("sess1", "Lyra")  # already present
        chars = manager.get("sess1").active_characters
        assert chars.count("Lyra") == 1

    def test_remove_character(self, manager: SceneManager):
        scene = SceneState(session_id="sess1", active_characters=["Lyra", "Baron"])
        manager.save(scene)
        manager.remove_character("sess1", "Baron")
        chars = manager.get("sess1").active_characters
        assert "Baron" not in chars
        assert "Lyra" in chars

    def test_update_summary(self, manager: SceneManager):
        scene = SceneState(session_id="sess1")
        manager.save(scene)
        manager.update_summary("sess1", "A tense standoff occurred.")
        assert manager.get("sess1").summary == "A tense standoff occurred."

    def test_update_multiple(self, manager: SceneManager):
        scene = SceneState(session_id="sess1", location="Town")
        manager.save(scene)
        manager.update(
            "sess1",
            location="Dungeon",
            active_characters=["Hero", "Rogue"],
            summary="Descended into darkness.",
        )
        s = manager.get("sess1")
        assert s.location == "Dungeon"
        assert "Rogue" in s.active_characters
        assert s.summary == "Descended into darkness."

    def test_json_roundtrip_active_characters(self, manager: SceneManager):
        """List of characters must survive SQLite JSON serialization."""
        chars = ["Alice", "Bob", "Charlie D'Arcy"]
        scene = SceneState(session_id="sess1", active_characters=chars)
        manager.save(scene)
        retrieved = manager.get("sess1")
        assert retrieved.active_characters == chars
