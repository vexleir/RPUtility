"""
Unit tests for memory storage, retrieval, and extraction parsing.
"""

import sqlite3

import pytest
import tempfile
from datetime import datetime, timedelta, UTC
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import MemoryEntry, MemoryType, ImportanceLevel, SceneState
from app.memory.store import MemoryStore
from app.memory.retriever import retrieve, _score
from app.memory.extractor import _parse_json_response, _build_entries


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


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    ensure_db(path)
    _seed_session(path, "sess1")
    _seed_session(path, "sess2")
    return path


@pytest.fixture
def store(db_path: str) -> MemoryStore:
    return MemoryStore(db_path)


def make_memory(
    session_id: str = "sess1",
    title: str = "Test Memory",
    content: str = "Something happened.",
    mem_type: MemoryType = MemoryType.EVENT,
    importance: ImportanceLevel = ImportanceLevel.MEDIUM,
    entities: list[str] | None = None,
    tags: list[str] | None = None,
    confidence: float = 1.0,
    days_ago: float = 0,
) -> MemoryEntry:
    now = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)
    return MemoryEntry(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        type=mem_type,
        title=title,
        content=content,
        entities=entities or [],
        tags=tags or [],
        importance=importance,
        confidence=confidence,
    )


# ── Memory store tests ────────────────────────────────────────────────────────

class TestMemoryStore:
    def test_save_and_get(self, store: MemoryStore):
        mem = make_memory(title="Dragon spotted")
        store.save(mem)
        retrieved = store.get(mem.id)
        assert retrieved is not None
        assert retrieved.title == "Dragon spotted"
        assert retrieved.type == MemoryType.EVENT

    def test_get_all(self, store: MemoryStore):
        for i in range(3):
            store.save(make_memory(title=f"Memory {i}"))
        all_mems = store.get_all("sess1")
        assert len(all_mems) == 3

    def test_get_all_session_isolation(self, store: MemoryStore):
        store.save(make_memory(session_id="sess1", title="Sess1 memory"))
        store.save(make_memory(session_id="sess2", title="Sess2 memory"))
        sess1_mems = store.get_all("sess1")
        assert len(sess1_mems) == 1
        assert sess1_mems[0].title == "Sess1 memory"

    def test_upsert_on_duplicate_id(self, store: MemoryStore):
        mem = make_memory(title="Original")
        store.save(mem)
        mem.title = "Updated"
        store.save(mem)
        retrieved = store.get(mem.id)
        assert retrieved.title == "Updated"

    def test_mark_referenced(self, store: MemoryStore):
        mem = make_memory()
        store.save(mem)
        store.mark_referenced(mem.id)
        retrieved = store.get(mem.id)
        assert retrieved.last_referenced_at is not None

    def test_delete(self, store: MemoryStore):
        mem = make_memory()
        store.save(mem)
        store.delete(mem.id)
        assert store.get(mem.id) is None

    def test_count(self, store: MemoryStore):
        for _ in range(5):
            store.save(make_memory())
        assert store.count("sess1") == 5

    def test_json_fields_roundtrip(self, store: MemoryStore):
        mem = make_memory(entities=["Alice", "Bob"], tags=["combat", "forest"])
        store.save(mem)
        retrieved = store.get(mem.id)
        assert retrieved.entities == ["Alice", "Bob"]
        assert "combat" in retrieved.tags

    def test_get_by_importance(self, store: MemoryStore):
        store.save(make_memory(title="low", importance=ImportanceLevel.LOW))
        store.save(make_memory(title="medium", importance=ImportanceLevel.MEDIUM))
        store.save(make_memory(title="high", importance=ImportanceLevel.HIGH))
        store.save(make_memory(title="critical", importance=ImportanceLevel.CRITICAL))

        high_and_above = store.get_by_importance("sess1", ImportanceLevel.HIGH)
        titles = {m.title for m in high_and_above}
        assert "high" in titles
        assert "critical" in titles
        assert "low" not in titles
        assert "medium" not in titles


# ── Memory retriever tests ────────────────────────────────────────────────────

class TestMemoryRetriever:
    def test_empty_memories(self):
        result = retrieve([], scene=None)
        assert result == []

    def test_max_results(self):
        mems = [make_memory(title=f"Mem {i}") for i in range(20)]
        result = retrieve(mems, scene=None, max_results=5)
        assert len(result) <= 5

    def test_critical_always_included(self):
        mems = [
            make_memory(
                title="Critical fact",
                importance=ImportanceLevel.CRITICAL,
                days_ago=100,
            )
        ] + [
            make_memory(title=f"Recent {i}", days_ago=0)
            for i in range(15)
        ]
        result = retrieve(mems, scene=None, max_results=5)
        assert any(m.title == "Critical fact" for m in result)

    def test_entity_relevance_boosts_score(self):
        scene = SceneState(
            session_id="s",
            location="Forest",
            active_characters=["Alice"],
        )
        relevant = make_memory(
            title="Alice falls",
            entities=["Alice"],
            importance=ImportanceLevel.LOW,
        )
        irrelevant = make_memory(
            title="Distant event",
            entities=["Bob"],
            importance=ImportanceLevel.MEDIUM,
        )
        result = retrieve([relevant, irrelevant], scene=scene, max_results=2)
        # Alice is in scene — relevant memory should appear
        assert any(m.title == "Alice falls" for m in result)

    def test_recent_text_keyword_boost(self):
        mem_with_tag = make_memory(title="Combat event", tags=["combat"])
        mem_without = make_memory(title="Boring event", tags=["admin"])
        result = retrieve(
            [mem_with_tag, mem_without],
            scene=None,
            recent_text="there was a big combat",
            max_results=2,
        )
        # combat keyword appears in recent_text
        assert result[0].title == "Combat event"

    def test_confidence_affects_ranking(self):
        high_conf = make_memory(title="Confirmed", confidence=1.0, importance=ImportanceLevel.MEDIUM)
        low_conf = make_memory(title="Rumor", confidence=0.3, importance=ImportanceLevel.MEDIUM)
        result = retrieve([high_conf, low_conf], scene=None, max_results=2)
        assert result[0].title == "Confirmed"

    def test_no_duplicates(self):
        mem = make_memory(importance=ImportanceLevel.CRITICAL)
        result = retrieve([mem], scene=None, max_results=10)
        ids = [m.id for m in result]
        assert len(ids) == len(set(ids))


# ── Extraction parser tests ───────────────────────────────────────────────────

class TestExtractionParser:
    def test_valid_json_array(self):
        raw = '[{"type": "event", "title": "Battle", "content": "A battle occurred.", "entities": ["Hero"], "tags": [], "importance": "high", "confidence": 1.0}]'
        items = _parse_json_response(raw)
        assert len(items) == 1
        assert items[0]["title"] == "Battle"

    def test_empty_array(self):
        items = _parse_json_response("[]")
        assert items == []

    def test_json_embedded_in_text(self):
        raw = 'Sure, here are the memories:\n[{"type": "event", "title": "Arrival", "content": "Player arrived.", "entities": [], "tags": [], "importance": "medium", "confidence": 1.0}]\nDone.'
        items = _parse_json_response(raw)
        assert len(items) == 1

    def test_invalid_json_returns_empty(self):
        items = _parse_json_response("this is not json at all")
        assert items == []

    def test_build_entries_valid(self):
        items = [
            {
                "type": "event",
                "title": "Fight at the tavern",
                "content": "A fight broke out.",
                "entities": ["Garrett", "unknown thug"],
                "location": "Tallow & Ink",
                "tags": ["combat", "tavern"],
                "importance": "medium",
                "confidence": 0.9,
            }
        ]
        entries = _build_entries(items, session_id="sess1", source_turn_ids=["t1"])
        assert len(entries) == 1
        e = entries[0]
        assert e.title == "Fight at the tavern"
        assert e.location == "Tallow & Ink"
        assert "combat" in e.tags
        assert e.confidence == 0.9

    def test_build_entries_skips_invalid(self):
        items = [
            {"type": "INVALID_TYPE", "title": "Bad", "content": "x", "entities": [], "tags": [], "importance": "medium", "confidence": 1.0},
            {"type": "event", "title": "Good", "content": "y", "entities": [], "tags": [], "importance": "high", "confidence": 1.0},
        ]
        entries = _build_entries(items, session_id="s", source_turn_ids=[])
        assert len(entries) == 1
        assert entries[0].title == "Good"

    def test_rumor_confidence_clamped(self):
        items = [{
            "type": "rumor",
            "title": "Wild claim",
            "content": "Allegedly...",
            "entities": [],
            "tags": [],
            "importance": "low",
            "confidence": 1.0,   # should be clamped to 0.6 for rumors
        }]
        entries = _build_entries(items, session_id="s", source_turn_ids=[])
        assert entries[0].confidence <= 0.6
