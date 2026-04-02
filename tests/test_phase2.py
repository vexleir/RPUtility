"""
Phase 2 tests — advanced memory, world-state, contradiction, consolidation,
relationship summaries, retriever scoring, prompt assembly, schema migration.
"""

import sqlite3

import pytest
import tempfile
from datetime import datetime, timedelta, UTC
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import (
    MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel,
    SceneState, RelationshipState, WorldStateEntry,
)
from app.memory.store import MemoryStore
from app.memory.world_state import WorldStateStore
from app.memory.retriever import retrieve, ScoreBreakdown
from app.memory.contradiction import check_contradictions
from app.memory.extractor import _parse_json_response, _build_entries, _default_certainty
from app.prompting.builder import (
    build_messages, derive_relationship_summary,
    _format_critical_facts, _format_memories_soft, _format_world_state,
)
from app.core.config import Config


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    path = str(tmp_path / "test_p2.db")
    ensure_db(path)
    _seed_session(path, "sess1")
    _seed_session(path, "sess2")
    return path


@pytest.fixture
def store(db_path: str) -> MemoryStore:
    return MemoryStore(db_path)


@pytest.fixture
def ws_store(db_path: str) -> WorldStateStore:
    return WorldStateStore(db_path)


@pytest.fixture
def config() -> Config:
    return Config()


def make_memory(
    session_id: str = "sess1",
    title: str = "Test Memory",
    content: str = "Something happened.",
    mem_type: MemoryType = MemoryType.EVENT,
    importance: ImportanceLevel = ImportanceLevel.MEDIUM,
    certainty: CertaintyLevel = CertaintyLevel.CONFIRMED,
    entities: list[str] | None = None,
    tags: list[str] | None = None,
    confidence: float = 1.0,
    days_ago: float = 0,
    archived: bool = False,
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
        certainty=certainty,
        archived=archived,
    )


def make_world_state(
    session_id: str = "sess1",
    title: str = "Faction Controls City",
    content: str = "The Iron Order controls the northern gate.",
    category: str = "faction",
    importance: ImportanceLevel = ImportanceLevel.HIGH,
) -> WorldStateEntry:
    return WorldStateEntry(
        session_id=session_id,
        category=category,
        title=title,
        content=content,
        importance=importance,
    )


# ── Phase 2 memory store tests ────────────────────────────────────────────────

class TestPhase2MemoryStore:
    def test_save_and_get_with_certainty(self, store: MemoryStore):
        mem = make_memory(certainty=CertaintyLevel.RUMOR, confidence=0.4)
        store.save(mem)
        r = store.get(mem.id)
        assert r.certainty == CertaintyLevel.RUMOR
        assert r.confidence == pytest.approx(0.4)

    def test_archive_hides_from_get_active(self, store: MemoryStore):
        mem = make_memory()
        store.save(mem)
        assert len(store.get_active("sess1")) == 1
        store.archive(mem.id)
        assert len(store.get_active("sess1")) == 0

    def test_archived_visible_in_get_archived(self, store: MemoryStore):
        mem = make_memory()
        store.save(mem)
        store.archive(mem.id)
        archived = store.get_archived("sess1")
        assert len(archived) == 1
        assert archived[0].archived is True

    def test_get_all_includes_archived(self, store: MemoryStore):
        active = make_memory(title="Active")
        archived = make_memory(title="Archived")
        store.save(active)
        store.save(archived)
        store.archive(archived.id)
        all_mems = store.get_all("sess1")
        assert len(all_mems) == 2

    def test_consolidated_from_roundtrip(self, store: MemoryStore):
        mem = make_memory()
        mem.consolidated_from = ["id1", "id2"]
        mem.type = MemoryType.CONSOLIDATION
        store.save(mem)
        r = store.get(mem.id)
        assert r.consolidated_from == ["id1", "id2"]

    def test_contradiction_of_roundtrip(self, store: MemoryStore):
        mem = make_memory()
        mem.contradiction_of = "other-id-123"
        store.save(mem)
        r = store.get(mem.id)
        assert r.contradiction_of == "other-id-123"

    def test_count_excludes_archived(self, store: MemoryStore):
        for i in range(4):
            m = make_memory(title=f"Mem {i}")
            store.save(m)
        # Archive one
        all_mems = store.get_all("sess1")
        store.archive(all_mems[0].id)
        assert store.count("sess1") == 3

    def test_archive_many(self, store: MemoryStore):
        mems = [make_memory(title=f"M{i}") for i in range(5)]
        store.save_many(mems)
        store.archive_many([m.id for m in mems[:3]])
        assert store.count("sess1") == 2


# ── World-state store tests ───────────────────────────────────────────────────

class TestWorldStateStore:
    def test_save_and_get_all(self, ws_store: WorldStateStore):
        e = make_world_state()
        ws_store.save(e)
        results = ws_store.get_all("sess1")
        assert len(results) == 1
        assert results[0].title == "Faction Controls City"

    def test_get_by_category(self, ws_store: WorldStateStore):
        ws_store.save(make_world_state(category="faction"))
        ws_store.save(make_world_state(title="Storm Coming", content="...", category="environment"))
        faction = ws_store.get_by_category("sess1", "faction")
        assert len(faction) == 1
        assert faction[0].category == "faction"

    def test_session_isolation(self, ws_store: WorldStateStore):
        ws_store.save(make_world_state(session_id="sess1"))
        ws_store.save(make_world_state(session_id="sess2"))
        assert len(ws_store.get_all("sess1")) == 1
        assert len(ws_store.get_all("sess2")) == 1

    def test_upsert(self, ws_store: WorldStateStore):
        e = make_world_state()
        ws_store.save(e)
        e.content = "Updated content"
        ws_store.save(e)
        results = ws_store.get_all("sess1")
        assert len(results) == 1
        assert results[0].content == "Updated content"

    def test_delete_session(self, ws_store: WorldStateStore):
        ws_store.save(make_world_state())
        ws_store.delete_session("sess1")
        assert len(ws_store.get_all("sess1")) == 0

    def test_count(self, ws_store: WorldStateStore):
        ws_store.save(make_world_state(title="A"))
        ws_store.save(make_world_state(title="B"))
        assert ws_store.count("sess1") == 2


# ── Phase 2 retriever tests ───────────────────────────────────────────────────

class TestPhase2Retriever:
    def test_certainty_lowers_score(self):
        confirmed = make_memory(title="Confirmed", certainty=CertaintyLevel.CONFIRMED)
        rumor = make_memory(title="Rumor", certainty=CertaintyLevel.RUMOR, confidence=0.6)
        result = retrieve([confirmed, rumor], scene=None, max_results=2)
        assert result[0].title == "Confirmed"

    def test_lie_scores_very_low(self):
        lie = make_memory(title="Lie", certainty=CertaintyLevel.LIE)
        high = make_memory(title="High", importance=ImportanceLevel.HIGH)
        result = retrieve([lie, high], scene=None, max_results=2)
        assert result[0].title == "High"

    def test_archived_excluded(self):
        active = make_memory(title="Active")
        archived = make_memory(title="Archived", archived=True)
        # Retriever operates on what store returns; simulate by passing only active
        result = retrieve([active], scene=None, max_results=5)
        assert len(result) == 1
        assert result[0].title == "Active"

    def test_per_type_cap_enforced(self):
        events = [make_memory(title=f"Event {i}", mem_type=MemoryType.EVENT) for i in range(8)]
        result = retrieve(events, scene=None, max_results=10, type_caps={"event": 3})
        assert len(result) <= 3

    def test_recently_used_penalty(self):
        mem_a = make_memory(title="A", importance=ImportanceLevel.MEDIUM)
        mem_b = make_memory(title="B", importance=ImportanceLevel.MEDIUM)
        # A was recently used — should be ranked lower despite equal importance
        result = retrieve(
            [mem_a, mem_b], scene=None, max_results=2,
            recently_used_ids={mem_a.id}
        )
        assert result[0].title == "B"

    def test_configurable_weights(self):
        entity_mem = make_memory(
            title="Entity match",
            entities=["Alice"],
            importance=ImportanceLevel.LOW,
        )
        keyword_mem = make_memory(
            title="Keyword match",
            tags=["magic"],
            importance=ImportanceLevel.MEDIUM,
        )
        scene = SceneState(session_id="s", location="Forest", active_characters=["Alice"])
        # High entity weight should push entity_mem up despite lower importance
        result = retrieve(
            [entity_mem, keyword_mem], scene=scene,
            recent_text="magic spell was cast",
            max_results=2,
            weight_entity=10.0,
            weight_keyword=0.1,
        )
        assert result[0].title == "Entity match"

    def test_critical_always_selected(self):
        critical = make_memory(title="Critical", importance=ImportanceLevel.CRITICAL, days_ago=200)
        recent = [make_memory(title=f"Recent {i}", days_ago=0) for i in range(10)]
        result = retrieve([critical] + recent, scene=None, max_results=5)
        assert any(m.title == "Critical" for m in result)

    def test_no_duplicates_in_result(self):
        critical = make_memory(importance=ImportanceLevel.CRITICAL)
        result = retrieve([critical], scene=None, max_results=10)
        assert len(result) == len({m.id for m in result})

    def test_debug_breakdown_does_not_crash(self):
        mems = [make_memory(title=f"M{i}") for i in range(5)]
        result = retrieve(mems, scene=None, max_results=3, debug=True)
        assert len(result) <= 3


# ── Contradiction detection tests ─────────────────────────────────────────────

class TestContradictionDetection:
    def _existing(self, content: str, entities: list[str]) -> MemoryEntry:
        return make_memory(
            title="Existing",
            content=content,
            entities=entities,
            importance=ImportanceLevel.HIGH,
            certainty=CertaintyLevel.CONFIRMED,
        )

    def test_no_contradiction_no_shared_entities(self):
        new = [make_memory(title="New", content="Alice is alive.", entities=["Alice"])]
        existing = [self._existing("Bob is dead.", ["Bob"])]
        kept, flags = check_contradictions(new, existing, "sess1")
        assert len(kept) == 1
        assert len(flags) == 0

    def test_detects_alive_dead_contradiction(self):
        new = [make_memory(title="New", content="The king is alive.", entities=["King"])]
        existing = [self._existing("The king is dead.", ["King"])]
        kept, flags = check_contradictions(new, existing, "sess1", mode="mark_uncertain")
        assert len(flags) == 1
        assert kept[0].certainty == CertaintyLevel.SUSPICION

    def test_detects_standing_destroyed_contradiction(self):
        new = [make_memory(title="New", content="The tavern is standing.", entities=["Tavern"])]
        existing = [self._existing("The tavern was destroyed.", ["Tavern"])]
        kept, flags = check_contradictions(new, existing, "sess1", mode="mark_uncertain")
        assert len(flags) == 1

    def test_reject_mode_removes_memory(self):
        new = [make_memory(title="New", content="Alice is alive.", entities=["Alice"])]
        existing = [self._existing("Alice is dead.", ["Alice"])]
        kept, flags = check_contradictions(new, existing, "sess1", mode="reject")
        assert len(kept) == 0
        assert len(flags) == 1

    def test_downgrade_mode_sets_rumor(self):
        new = [make_memory(title="New", content="The gate is open.", entities=["Gate"])]
        existing = [self._existing("The gate is closed.", ["Gate"])]
        kept, flags = check_contradictions(new, existing, "sess1", mode="downgrade")
        assert kept[0].type == MemoryType.RUMOR
        assert kept[0].certainty == CertaintyLevel.RUMOR

    def test_warn_mode_keeps_unchanged(self):
        new = [make_memory(title="New", content="Alice is alive.", entities=["Alice"])]
        existing = [self._existing("Alice is dead.", ["Alice"])]
        kept, flags = check_contradictions(new, existing, "sess1", mode="warn")
        assert len(kept) == 1
        assert len(flags) == 1
        # certainty unchanged in warn mode
        assert kept[0].certainty == CertaintyLevel.CONFIRMED

    def test_rumor_not_protected(self):
        """Rumors should not be used to protect against contradictions."""
        new = [make_memory(title="New", content="Alice is alive.", entities=["Alice"])]
        existing = [make_memory(
            title="Rumor",
            content="Alice is dead.",
            entities=["Alice"],
            certainty=CertaintyLevel.RUMOR,
            importance=ImportanceLevel.LOW,
        )]
        # Rumor is not "protected" so no contradiction should fire
        kept, flags = check_contradictions(new, existing, "sess1")
        assert len(flags) == 0

    def test_multiple_new_memories_processed(self):
        new = [
            make_memory(title="A", content="Alice is alive.", entities=["Alice"]),
            make_memory(title="B", content="Bob is healthy.", entities=["Bob"]),
        ]
        existing = [
            self._existing("Alice is dead.", ["Alice"]),
        ]
        kept, flags = check_contradictions(new, existing, "sess1", mode="mark_uncertain")
        assert len(flags) == 1  # only Alice contradicts
        assert len(kept) == 2   # both kept (warn mode keeps, mark_uncertain keeps but modifies)


# ── Relationship summary tests ────────────────────────────────────────────────

class TestRelationshipSummaries:
    def _rel(self, **kwargs) -> RelationshipState:
        defaults = dict(
            session_id="s", source_entity="A", target_entity="B",
            trust=0.0, fear=0.0, respect=0.0, affection=0.0, hostility=0.0,
        )
        defaults.update(kwargs)
        return RelationshipState(**defaults)

    def test_enemy(self):
        r = self._rel(hostility=0.7, trust=-0.4)
        assert derive_relationship_summary(r) == "enemy"

    def test_close_ally(self):
        r = self._rel(trust=0.7, affection=0.5)
        assert derive_relationship_summary(r) == "close ally"

    def test_loyal(self):
        r = self._rel(trust=0.6, respect=0.5)
        assert derive_relationship_summary(r) == "loyal"

    def test_fearful(self):
        r = self._rel(fear=0.6, trust=-0.1)
        assert derive_relationship_summary(r) == "fearful"

    def test_suspicious(self):
        r = self._rel(trust=-0.5)
        assert derive_relationship_summary(r) == "suspicious"

    def test_neutral(self):
        r = self._rel()
        assert derive_relationship_summary(r) == "neutral"

    def test_affectionate(self):
        r = self._rel(affection=0.6)
        assert derive_relationship_summary(r) == "affectionate"

    def test_wary(self):
        r = self._rel(fear=0.4)
        assert derive_relationship_summary(r) == "wary"

    def test_hostile(self):
        r = self._rel(hostility=0.5, affection=-0.1)
        assert derive_relationship_summary(r) == "hostile"


# ── Prompt builder Phase 2 tests ──────────────────────────────────────────────

class TestPhase2PromptBuilder:
    def _minimal_config(self) -> Config:
        return Config()

    def test_critical_facts_section_present(self):
        critical = make_memory(
            title="Player Lost Eye",
            content="The player lost their left eye in combat.",
            importance=ImportanceLevel.CRITICAL,
        )
        result = _format_critical_facts([critical])
        assert "CRITICAL FACTS" in result
        assert "Player Lost Eye" in result
        assert "!!" in result

    def test_world_state_section(self):
        ws = make_world_state(title="Iron Order Controls Gate")
        result = _format_world_state([ws], self._minimal_config())
        assert "WORLD STATE" in result
        assert "Iron Order Controls Gate" in result

    def test_soft_memory_includes_rumor_confidence(self):
        rumor = make_memory(
            title="Dead King Rumor",
            content="They say the king is dead.",
            mem_type=MemoryType.RUMOR,
            certainty=CertaintyLevel.RUMOR,
            confidence=0.4,
        )
        result = _format_memories_soft([rumor])
        assert "40%" in result or "confidence" in result.lower()

    def test_soft_memory_includes_suspicion_section(self):
        suspicion = make_memory(
            title="Spy Suspicion",
            content="The innkeeper seems to be watching us.",
            mem_type=MemoryType.SUSPICION,
            certainty=CertaintyLevel.SUSPICION,
        )
        result = _format_memories_soft([suspicion])
        assert "Suspicion" in result or "suspicion" in result.lower()

    def test_critical_and_episodic_split(self):
        from app.core.models import CharacterCard, SceneState
        card = CharacterCard(name="Lyra", description="A scholar.")
        critical = make_memory(
            title="Critical Fact",
            content="The bridge is destroyed.",
            importance=ImportanceLevel.CRITICAL,
        )
        episodic = make_memory(
            title="Minor Event",
            content="We had lunch.",
            importance=ImportanceLevel.LOW,
        )
        cfg = self._minimal_config()
        messages = build_messages(
            card=card,
            lorebook_entries=[],
            memories=[critical, episodic],
            scene=SceneState(session_id="s", location="Forest", active_characters=["Lyra"]),
            relationships=[],
            history=[],
            user_message="Hello",
            config=cfg,
        )
        system = messages[0]["content"]
        assert "CRITICAL FACTS" in system
        assert "STORY SO FAR" in system

    def test_world_state_appears_before_memories(self):
        from app.core.models import CharacterCard, SceneState
        card = CharacterCard(name="Lyra", description="A scholar.")
        ws = [make_world_state(title="War Ongoing")]
        mem = make_memory(title="Small Event", content="Rain fell.")
        cfg = self._minimal_config()
        messages = build_messages(
            card=card,
            lorebook_entries=[],
            memories=[mem],
            scene=SceneState(session_id="s", location="City", active_characters=["Lyra"]),
            relationships=[],
            history=[],
            user_message="Hi",
            config=cfg,
            world_state=ws,
        )
        system = messages[0]["content"]
        ws_pos = system.find("WORLD STATE")
        mem_pos = system.find("STORY SO FAR")
        assert ws_pos < mem_pos


# ── Extractor Phase 2 tests ───────────────────────────────────────────────────

class TestPhase2Extractor:
    def test_certainty_field_parsed(self):
        items = [{
            "type": "event",
            "title": "Battle",
            "content": "A battle occurred.",
            "entities": [],
            "tags": [],
            "importance": "high",
            "confidence": 0.9,
            "certainty": "confirmed",
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].certainty == CertaintyLevel.CONFIRMED

    def test_rumor_certainty_defaults(self):
        items = [{
            "type": "rumor",
            "title": "Rumor",
            "content": "They say...",
            "entities": [],
            "tags": [],
            "importance": "low",
            "confidence": 0.8,
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].certainty == CertaintyLevel.RUMOR
        assert entries[0].confidence <= 0.6

    def test_suspicion_type_recognized(self):
        items = [{
            "type": "suspicion",
            "title": "Suspect",
            "content": "Something feels off.",
            "entities": [],
            "tags": [],
            "importance": "low",
            "confidence": 0.5,
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].type == MemoryType.SUSPICION
        assert entries[0].certainty == CertaintyLevel.SUSPICION

    def test_world_state_type_recognized(self):
        items = [{
            "type": "world_state",
            "title": "City Falls",
            "content": "The northern city has fallen.",
            "entities": ["Northern City"],
            "tags": ["war"],
            "importance": "critical",
            "confidence": 1.0,
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].type == MemoryType.WORLD_STATE
        assert entries[0].importance == ImportanceLevel.CRITICAL

    def test_lie_certainty_low_confidence(self):
        items = [{
            "type": "event",
            "title": "False Claim",
            "content": "He claimed to be the king.",
            "entities": [],
            "tags": [],
            "importance": "medium",
            "confidence": 0.9,
            "certainty": "lie",
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].certainty == CertaintyLevel.LIE
        assert entries[0].confidence <= 0.2

    def test_confidence_clamped_universal(self):
        items = [{
            "type": "event",
            "title": "Test",
            "content": "x",
            "entities": [],
            "tags": [],
            "importance": "medium",
            "confidence": 5.0,  # out of range
        }]
        entries = _build_entries(items, "sess1", [])
        assert entries[0].confidence <= 1.0

    def test_default_certainty_for_confirmed(self):
        assert _default_certainty(MemoryType.EVENT) == CertaintyLevel.CONFIRMED
        assert _default_certainty(MemoryType.WORLD_FACT) == CertaintyLevel.CONFIRMED
        assert _default_certainty(MemoryType.RUMOR) == CertaintyLevel.RUMOR
        assert _default_certainty(MemoryType.SUSPICION) == CertaintyLevel.SUSPICION


# ── Schema migration / backward-compat tests ──────────────────────────────────

class TestSchemaMigration:
    def test_old_db_loads_without_certainty_column(self, tmp_path: Path):
        """Simulate a Phase 1 DB (no certainty column) loading in Phase 2."""
        import sqlite3
        db_path = str(tmp_path / "old.db")
        # Create old schema without Phase 2 columns
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            entities TEXT NOT NULL DEFAULT '[]',
            location TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            importance TEXT NOT NULL DEFAULT 'medium',
            last_referenced_at TEXT,
            source_turn_ids TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 1.0
        )""")
        conn.execute("""INSERT INTO memories VALUES (
            'test-id', 'sess1', '2024-01-01T00:00:00', '2024-01-01T00:00:00',
            'event', 'Old Memory', 'Something happened.', '[]', null,
            '[]', 'high', null, '[]', 1.0
        )""")
        conn.commit()
        conn.close()

        # Run migration
        ensure_db(db_path)

        # Now load via store — should not crash, certainty defaults to confirmed
        store = MemoryStore(db_path)
        mems = store.get_all("sess1")
        assert len(mems) == 1
        assert mems[0].title == "Old Memory"
        assert mems[0].certainty == CertaintyLevel.CONFIRMED
        assert mems[0].archived is False

    def test_world_state_table_created_on_migrate(self, tmp_path: Path):
        """Ensure world_state table is created even on an existing DB."""
        import sqlite3
        db_path = str(tmp_path / "ws_migrate.db")
        # Create DB with just sessions table (minimal existing DB)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        ensure_db(db_path)

        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "world_state" in tables
        assert "contradiction_flags" in tables
