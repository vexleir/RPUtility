"""
Unit tests for relationship tracking.
"""

import sqlite3

import pytest
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import RelationshipState
from app.relationships.tracker import RelationshipTracker, _clamp


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
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    ensure_db(path)
    _seed_session(path, "sess1")
    _seed_session(path, "sess2")
    _seed_session(path, "s")
    _seed_session(path, "other")
    return path


@pytest.fixture
def tracker(db_path: str) -> RelationshipTracker:
    return RelationshipTracker(db_path)


class TestRelationshipTracker:
    def test_get_default_neutral(self, tracker: RelationshipTracker):
        """Getting a relationship that doesn't exist returns neutral values."""
        rel = tracker.get("sess1", "Alice", "Bob")
        assert rel.trust == 0.0
        assert rel.fear == 0.0
        assert rel.affection == 0.0

    def test_save_and_get(self, tracker: RelationshipTracker):
        rel = RelationshipState(
            session_id="sess1",
            source_entity="Alice",
            target_entity="Bob",
            trust=0.7,
            affection=0.5,
        )
        tracker.save(rel)
        retrieved = tracker.get("sess1", "Alice", "Bob")
        assert abs(retrieved.trust - 0.7) < 0.001
        assert abs(retrieved.affection - 0.5) < 0.001

    def test_upsert(self, tracker: RelationshipTracker):
        rel = RelationshipState(
            session_id="sess1",
            source_entity="Alice",
            target_entity="Bob",
            trust=0.3,
        )
        tracker.save(rel)
        rel.trust = 0.8
        tracker.save(rel)
        retrieved = tracker.get("sess1", "Alice", "Bob")
        assert abs(retrieved.trust - 0.8) < 0.001

    def test_directional(self, tracker: RelationshipTracker):
        """Alice→Bob and Bob→Alice are separate entries."""
        tracker.save(RelationshipState(
            session_id="s", source_entity="Alice", target_entity="Bob", trust=0.9
        ))
        tracker.save(RelationshipState(
            session_id="s", source_entity="Bob", target_entity="Alice", trust=-0.5
        ))
        a_to_b = tracker.get("s", "Alice", "Bob")
        b_to_a = tracker.get("s", "Bob", "Alice")
        assert a_to_b.trust > 0
        assert b_to_a.trust < 0

    def test_adjust_delta(self, tracker: RelationshipTracker):
        tracker.save(RelationshipState(
            session_id="s", source_entity="Hero", target_entity="Villain",
            trust=0.0, hostility=0.2
        ))
        tracker.adjust("s", "Hero", "Villain", trust=-0.3, hostility=0.4)
        rel = tracker.get("s", "Hero", "Villain")
        assert abs(rel.trust - (-0.3)) < 0.001
        assert abs(rel.hostility - 0.6) < 0.001

    def test_clamp_on_save(self, tracker: RelationshipTracker):
        """Values exceeding valid range should be clamped."""
        rel = RelationshipState(
            session_id="s", source_entity="A", target_entity="B",
            trust=2.0,       # should clamp to 1.0
            fear=-0.5,       # should clamp to 0.0
            hostility=999.0, # should clamp to 1.0
        )
        tracker.save(rel)
        retrieved = tracker.get("s", "A", "B")
        assert retrieved.trust == 1.0
        assert retrieved.fear == 0.0
        assert retrieved.hostility == 1.0

    def test_get_all(self, tracker: RelationshipTracker):
        tracker.save(RelationshipState(session_id="s", source_entity="A", target_entity="B"))
        tracker.save(RelationshipState(session_id="s", source_entity="C", target_entity="D"))
        tracker.save(RelationshipState(session_id="other", source_entity="X", target_entity="Y"))
        all_rels = tracker.get_all("s")
        assert len(all_rels) == 2

    def test_get_involving(self, tracker: RelationshipTracker):
        tracker.save(RelationshipState(session_id="s", source_entity="Alice", target_entity="Bob"))
        tracker.save(RelationshipState(session_id="s", source_entity="Charlie", target_entity="Alice"))
        tracker.save(RelationshipState(session_id="s", source_entity="Dave", target_entity="Eve"))
        rels = tracker.get_involving("s", "Alice")
        entities = {r.source_entity for r in rels} | {r.target_entity for r in rels}
        assert "Alice" in entities
        assert "Dave" not in entities

    def test_set_relationship(self, tracker: RelationshipTracker):
        tracker.set_relationship("s", "A", "B", trust=0.5)
        rel = tracker.get("s", "A", "B")
        assert abs(rel.trust - 0.5) < 0.001
        # Other axes should remain default
        assert rel.fear == 0.0

    def test_session_isolation(self, tracker: RelationshipTracker):
        tracker.save(RelationshipState(
            session_id="sess1", source_entity="A", target_entity="B", trust=0.9
        ))
        rel_other = tracker.get("sess2", "A", "B")
        assert rel_other.trust == 0.0  # default, not sess1's value


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5, -1.0, 1.0) == 0.5

    def test_above_max(self):
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_below_min(self):
        assert _clamp(-0.5, 0.0, 1.0) == 0.0
