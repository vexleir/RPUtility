"""
Integration tests for the RP Utility engine.

These tests exercise the full persistence layer (SQLite) but mock the model
provider so they run without a live Ollama/LM Studio instance.

Tests verify:
  - Memory persists across sessions
  - Relationships evolve and persist
  - World-building state persists through restart
  - Session restart recovers all state
"""

import sqlite3

import pytest
from pathlib import Path
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from app.core.config import Config
from app.core.database import ensure_db
from app.core.engine import RoleplayEngine
from app.core.models import (
    MemoryEntry,
    MemoryType,
    ImportanceLevel,
    SceneState,
    RelationshipState,
)
from app.memory.store import MemoryStore
from app.scene.state import SceneManager
from app.relationships.tracker import RelationshipTracker
from app.sessions.manager import SessionManager
from app.cards.loader import parse_card
from app.lorebooks.loader import parse_lorebook


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _seed_session(db_path: str, session_id: str) -> None:
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
def test_config(tmp_path: Path) -> Config:
    c = Config()
    c.db_path = str(tmp_path / "test.db")
    c.cards_dir = str(tmp_path / "cards")
    c.lorebooks_dir = str(tmp_path / "lorebooks")
    c.memory_extraction_enabled = False   # disable LLM calls in integration tests
    c.debug = False
    ensure_db(c.db_path)
    # Seed bare session rows so subsystem tests can use hardcoded IDs with FK on
    for sid in ("sess1", "sess2", "s"):
        _seed_session(c.db_path, sid)
    return c


@pytest.fixture
def engine(test_config: Config, tmp_path: Path) -> RoleplayEngine:
    """Build an engine with a mock provider and a pre-loaded character card."""
    # Create cards directory and a test card
    cards_dir = Path(test_config.cards_dir)
    cards_dir.mkdir(parents=True, exist_ok=True)
    card_file = cards_dir / "aria.json"
    card_file.write_text(
        '{"name": "Aria", "description": "A ranger.", "first_message": "I watch from the shadows."}',
        encoding="utf-8",
    )

    e = RoleplayEngine(test_config)

    # Replace the real provider with a mock
    mock_provider = MagicMock()
    mock_provider.chat.return_value = "I see you've arrived. Interesting."
    mock_provider.generate.return_value = "[]"  # empty memory extraction
    e.provider = mock_provider
    e.extraction_provider = mock_provider

    return e


# ── Session persistence tests ─────────────────────────────────────────────────

class TestSessionPersistence:
    def test_session_survives_restart(self, test_config: Config, tmp_path: Path):
        """Creating a session and then building a new engine should find it."""
        cards_dir = Path(test_config.cards_dir)
        cards_dir.mkdir(parents=True, exist_ok=True)
        (cards_dir / "aria.json").write_text(
            '{"name": "Aria", "description": "A ranger."}', encoding="utf-8"
        )

        engine1 = RoleplayEngine(test_config)
        session = engine1.new_session("Test Campaign", "Aria")
        session_id = session.id

        # "Restart" by creating a new engine instance pointing at the same db
        engine2 = RoleplayEngine(test_config)
        loaded = engine2.load_session(session_id)

        assert loaded is not None
        assert loaded.name == "Test Campaign"
        assert loaded.character_name == "Aria"

    def test_turn_count_increments(self, engine: RoleplayEngine):
        session = engine.new_session("Campaign", "Aria")
        assert session.turn_count == 0

        engine.chat(session.id, "Hello")
        engine.chat(session.id, "How are you?")

        updated = engine.load_session(session.id)
        assert updated.turn_count == 2

    def test_turns_persist(self, engine: RoleplayEngine):
        session = engine.new_session("Campaign", "Aria")
        engine.chat(session.id, "Tell me about yourself.")
        turns = engine.sessions.get_last_n_turns(session.id)
        assert len(turns) == 2  # one user, one assistant


# ── Memory persistence tests ──────────────────────────────────────────────────

class TestMemoryPersistence:
    def test_memory_survives_restart(self, test_config: Config, tmp_path: Path):
        """Manually saved memories should persist across engine instantiation."""
        cards_dir = Path(test_config.cards_dir)
        cards_dir.mkdir(parents=True, exist_ok=True)
        (cards_dir / "aria.json").write_text(
            '{"name": "Aria", "description": "A ranger."}', encoding="utf-8"
        )

        engine1 = RoleplayEngine(test_config)
        session = engine1.new_session("Campaign", "Aria")

        # Manually save a memory
        mem = MemoryEntry(
            session_id=session.id,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
            type=MemoryType.EVENT,
            title="Dragon spotted",
            content="A red dragon was spotted flying over the mountains.",
            entities=["Dragon"],
            importance=ImportanceLevel.HIGH,
        )
        engine1.memory_store.save(mem)

        # New engine instance
        engine2 = RoleplayEngine(test_config)
        memories = engine2.get_memories(session.id)
        assert any(m.title == "Dragon spotted" for m in memories)

    def test_memory_included_in_prompt(self, engine: RoleplayEngine):
        """Relevant stored memories should appear in the prompt sent to the model."""
        session = engine.new_session("Campaign", "Aria", initial_location="Forest")

        # Pre-seed a high-importance memory with relevant entity
        mem = MemoryEntry(
            session_id=session.id,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
            type=MemoryType.EVENT,
            title="Found ancient ruin",
            content="An ancient elven ruin was discovered in the forest.",
            entities=["Aria"],
            importance=ImportanceLevel.HIGH,
        )
        engine.memory_store.save(mem)

        # Capture the messages passed to the provider
        captured_messages = []
        original_chat = engine.provider.chat

        def capture_chat(messages, **kwargs):
            captured_messages.extend(messages)
            return "Response."

        engine.provider.chat = capture_chat
        engine.chat(session.id, "What did we find in the forest?")

        # The system message should contain our memory
        system_msgs = [m for m in captured_messages if m["role"] == "system"]
        assert system_msgs, "No system message found"
        assert "ancient elven ruin" in system_msgs[0]["content"]


# ── Relationship persistence tests ────────────────────────────────────────────

class TestRelationshipPersistence:
    def test_relationship_evolves(self, test_config: Config):
        tracker = RelationshipTracker(test_config.db_path)

        tracker.adjust("sess1", "Aria", "Player", trust=0.2)
        tracker.adjust("sess1", "Aria", "Player", trust=0.3)
        rel = tracker.get("sess1", "Aria", "Player")
        assert abs(rel.trust - 0.5) < 0.001

    def test_relationship_survives_restart(self, test_config: Config):
        tracker1 = RelationshipTracker(test_config.db_path)
        tracker1.adjust("sess1", "Aria", "Player", trust=0.6, affection=0.4)

        tracker2 = RelationshipTracker(test_config.db_path)
        rel = tracker2.get("sess1", "Aria", "Player")
        assert abs(rel.trust - 0.6) < 0.001
        assert abs(rel.affection - 0.4) < 0.001

    def test_clamping_on_accumulation(self, test_config: Config):
        tracker = RelationshipTracker(test_config.db_path)
        # Push trust way above 1.0 via repeated adjustments
        for _ in range(10):
            tracker.adjust("s", "A", "B", trust=0.3)
        rel = tracker.get("s", "A", "B")
        assert rel.trust <= 1.0


# ── Scene persistence tests ───────────────────────────────────────────────────

class TestScenePersistence:
    def test_scene_survives_restart(self, test_config: Config):
        mgr1 = SceneManager(test_config.db_path)
        mgr1.update(
            "sess1",
            location="The Old Archive",
            active_characters=["Lyra", "Guard"],
            summary="Lyra forced open the vault door.",
        )

        mgr2 = SceneManager(test_config.db_path)
        scene = mgr2.get("sess1")
        assert scene.location == "The Old Archive"
        assert "Guard" in scene.active_characters
        assert "vault door" in scene.summary

    def test_world_building_accumulates(self, test_config: Config):
        """Verify that scene updates accumulate correctly over time."""
        mgr = SceneManager(test_config.db_path)
        mgr.update("sess1", location="Town Square")
        mgr.add_character("sess1", "Merchant")
        mgr.add_character("sess1", "Guard")
        mgr.update_location("sess1", "Tavern")

        final = mgr.get("sess1")
        assert final.location == "Tavern"
        assert "Merchant" in final.active_characters


# ── Lorebook retrieval integration ────────────────────────────────────────────

class TestLorebookIntegration:
    def test_lorebook_triggers_on_user_input(self, test_config: Config, tmp_path: Path):
        """Lorebook entries should be retrieved when keywords appear in chat."""
        lorebooks_dir = Path(test_config.lorebooks_dir)
        lorebooks_dir.mkdir(parents=True, exist_ok=True)
        cards_dir = Path(test_config.cards_dir)
        cards_dir.mkdir(parents=True, exist_ok=True)

        (cards_dir / "aria.json").write_text(
            '{"name": "Aria"}', encoding="utf-8"
        )
        (lorebooks_dir / "world.json").write_text(
            '{"name": "World", "entries": [{"keys": ["ashfen"], "content": "The Ashfen is a dark swamp.", "priority": 5}]}',
            encoding="utf-8",
        )

        engine = RoleplayEngine(test_config)
        mock = MagicMock()
        mock.chat.return_value = "Yes, the Ashfen is dangerous."
        mock.generate.return_value = "[]"
        engine.provider = mock
        engine.extraction_provider = mock

        session = engine.new_session("Test", "Aria", lorebook_name="World")

        captured = []
        def cap(messages, **kw):
            captured.extend(messages)
            return "Response."
        engine.provider.chat = cap

        engine.chat(session.id, "Tell me about the Ashfen region.")

        system_msgs = [m for m in captured if m["role"] == "system"]
        assert any("dark swamp" in m["content"] for m in system_msgs)
