"""
tests/test_phase6.py  —  Phase 5 game features
Covers: Quest Log, Session Journal, Lore Notes
"""

import pytest

from app.core.models import (
    Quest,
    QuestStage,
    QuestStatus,
    JournalEntry,
    LoreNote,
    ImportanceLevel,
)
from app.sessions.quests import QuestStore
from app.sessions.journal import JournalStore
from app.sessions.lore_notes import LoreNoteStore
from app.prompting.builder import _format_quests


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    from app.core.database import ensure_db, get_connection
    ensure_db(path)
    # Insert a stub session row so FK constraints on session_id are satisfied
    with get_connection(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, name, character_name, created_at, last_active)"
            " VALUES (?, 'Test', 'Test', datetime('now'), datetime('now'))",
            (SESSION,),
        )
        conn.commit()
    return path


SESSION = "sess-p6-test"


# ══════════════════════════════════════════════════════════════════════════════
# Quest model
# ══════════════════════════════════════════════════════════════════════════════

class TestQuestModel:
    def test_default_status(self):
        q = Quest(session_id=SESSION, title="Find the key")
        assert q.status == QuestStatus.ACTIVE

    def test_stages_done_count(self):
        q = Quest(
            session_id=SESSION,
            title="Test",
            stages=[
                QuestStage(description="Step 1", completed=True, order=0),
                QuestStage(description="Step 2", completed=False, order=1),
                QuestStage(description="Step 3", completed=True, order=2),
            ],
        )
        assert q.stages_done == 2

    def test_progress_label(self):
        q = Quest(
            session_id=SESSION,
            title="Test",
            stages=[
                QuestStage(description="Step 1", completed=True, order=0),
                QuestStage(description="Step 2", completed=False, order=1),
            ],
        )
        assert q.progress_label == "1/2 stages"

    def test_progress_label_empty_stages(self):
        q = Quest(session_id=SESSION, title="Test")
        assert q.progress_label == ""

    def test_stages_done_all_complete(self):
        q = Quest(
            session_id=SESSION,
            title="Test",
            stages=[QuestStage(description="A", completed=True, order=0)],
        )
        assert q.stages_done == 1


# ══════════════════════════════════════════════════════════════════════════════
# QuestStore
# ══════════════════════════════════════════════════════════════════════════════

class TestQuestStore:
    def _make_quest(self, title="Recover the Artifact", status=QuestStatus.ACTIVE):
        return Quest(
            session_id=SESSION,
            title=title,
            description="A dangerous mission.",
            status=status,
            giver_npc_name="Elder Maren",
            location_name="The Vault",
            reward_notes="500 gold",
            stages=[
                QuestStage(description="Find the vault entrance", order=0),
                QuestStage(description="Retrieve the artifact", order=1),
            ],
        )

    def test_save_and_get(self, db):
        store = QuestStore(db)
        q = self._make_quest()
        store.save(q)
        fetched = store.get(q.id)
        assert fetched is not None
        assert fetched.title == "Recover the Artifact"
        assert fetched.giver_npc_name == "Elder Maren"
        assert fetched.reward_notes == "500 gold"

    def test_stages_roundtrip(self, db):
        store = QuestStore(db)
        q = self._make_quest()
        store.save(q)
        fetched = store.get(q.id)
        assert len(fetched.stages) == 2
        assert fetched.stages[0].description == "Find the vault entrance"
        assert fetched.stages[1].description == "Retrieve the artifact"

    def test_stage_completed_roundtrip(self, db):
        store = QuestStore(db)
        q = self._make_quest()
        q.stages[0].completed = True
        store.save(q)
        fetched = store.get(q.id)
        assert fetched.stages[0].completed is True
        assert fetched.stages[1].completed is False

    def test_upsert_updates_status(self, db):
        store = QuestStore(db)
        q = self._make_quest()
        store.save(q)
        q.status = QuestStatus.COMPLETED
        store.save(q)
        fetched = store.get(q.id)
        assert fetched.status == QuestStatus.COMPLETED

    def test_get_active_filters(self, db):
        store = QuestStore(db)
        active = self._make_quest("Active Quest", QuestStatus.ACTIVE)
        done = self._make_quest("Done Quest", QuestStatus.COMPLETED)
        hidden = self._make_quest("Hidden Quest", QuestStatus.HIDDEN)
        for q in [active, done, hidden]:
            store.save(q)
        result = store.get_active(SESSION)
        titles = [q.title for q in result]
        assert "Active Quest" in titles
        assert "Done Quest" not in titles
        assert "Hidden Quest" not in titles

    def test_get_all_returns_all_statuses(self, db):
        store = QuestStore(db)
        for i, status in enumerate(QuestStatus):
            store.save(Quest(session_id=SESSION, title=f"Q{i}", status=status))
        all_quests = store.get_all(SESSION)
        assert len(all_quests) == len(QuestStatus)

    def test_delete(self, db):
        store = QuestStore(db)
        q = self._make_quest()
        store.save(q)
        store.delete(q.id)
        assert store.get(q.id) is None

    def test_delete_session(self, db):
        store = QuestStore(db)
        for i in range(3):
            store.save(Quest(session_id=SESSION, title=f"Q{i}"))
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []

    def test_importance_roundtrip(self, db):
        store = QuestStore(db)
        q = Quest(session_id=SESSION, title="Critical Quest", importance=ImportanceLevel.CRITICAL)
        store.save(q)
        fetched = store.get(q.id)
        assert fetched.importance == ImportanceLevel.CRITICAL

    def test_tags_roundtrip(self, db):
        store = QuestStore(db)
        q = Quest(session_id=SESSION, title="Tagged Quest", tags=["main", "dungeon"])
        store.save(q)
        fetched = store.get(q.id)
        assert "main" in fetched.tags
        assert "dungeon" in fetched.tags

    def test_get_all_ordered_by_created_at(self, db):
        import time
        store = QuestStore(db)
        q1 = Quest(session_id=SESSION, title="First")
        store.save(q1)
        time.sleep(0.01)
        q2 = Quest(session_id=SESSION, title="Second")
        store.save(q2)
        all_quests = store.get_all(SESSION)
        assert all_quests[0].title == "First"
        assert all_quests[1].title == "Second"


# ══════════════════════════════════════════════════════════════════════════════
# JournalStore
# ══════════════════════════════════════════════════════════════════════════════

class TestJournalStore:
    def _make_entry(self, title="Day One", content="We arrived at the ruins."):
        return JournalEntry(
            session_id=SESSION,
            title=title,
            content=content,
            turn_number=5,
            tags=["exploration"],
        )

    def test_save_and_get(self, db):
        store = JournalStore(db)
        e = self._make_entry()
        store.save(e)
        fetched = store.get(e.id)
        assert fetched is not None
        assert fetched.title == "Day One"
        assert fetched.content == "We arrived at the ruins."
        assert fetched.turn_number == 5

    def test_insert_or_ignore(self, db):
        """Duplicate save should not raise and not duplicate the row."""
        store = JournalStore(db)
        e = self._make_entry()
        store.save(e)
        store.save(e)
        assert sum(1 for x in store.get_all(SESSION) if x.id == e.id) == 1

    def test_tags_roundtrip(self, db):
        store = JournalStore(db)
        e = self._make_entry()
        store.save(e)
        fetched = store.get(e.id)
        assert "exploration" in fetched.tags

    def test_get_all_newest_first(self, db):
        import time
        store = JournalStore(db)
        e1 = self._make_entry("First entry")
        store.save(e1)
        time.sleep(0.01)
        e2 = self._make_entry("Second entry")
        store.save(e2)
        all_entries = store.get_all(SESSION)
        assert all_entries[0].title == "Second entry"

    def test_get_recent(self, db):
        store = JournalStore(db)
        for i in range(5):
            store.save(self._make_entry(title=f"Entry {i}"))
        recent = store.get_recent(SESSION, n=3)
        assert len(recent) == 3

    def test_delete(self, db):
        store = JournalStore(db)
        e = self._make_entry()
        store.save(e)
        store.delete(e.id)
        assert store.get(e.id) is None

    def test_delete_session(self, db):
        store = JournalStore(db)
        for i in range(3):
            store.save(self._make_entry(title=f"E{i}"))
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []


# ══════════════════════════════════════════════════════════════════════════════
# LoreNoteStore
# ══════════════════════════════════════════════════════════════════════════════

class TestLoreNoteStore:
    def _make_note(self, title="The Ancient War", category="history", source="Old tome"):
        return LoreNote(
            session_id=SESSION,
            title=title,
            content="A great war was fought a thousand years ago.",
            category=category,
            source=source,
            tags=["war", "ancient"],
        )

    def test_save_and_get(self, db):
        store = LoreNoteStore(db)
        n = self._make_note()
        store.save(n)
        fetched = store.get(n.id)
        assert fetched is not None
        assert fetched.title == "The Ancient War"
        assert fetched.category == "history"
        assert fetched.source == "Old tome"

    def test_upsert_updates(self, db):
        store = LoreNoteStore(db)
        n = self._make_note()
        store.save(n)
        n.content = "Updated content."
        store.save(n)
        fetched = store.get(n.id)
        assert fetched.content == "Updated content."

    def test_tags_roundtrip(self, db):
        store = LoreNoteStore(db)
        n = self._make_note()
        store.save(n)
        fetched = store.get(n.id)
        assert "war" in fetched.tags
        assert "ancient" in fetched.tags

    def test_get_all_ordered_by_category_then_title(self, db):
        store = LoreNoteStore(db)
        n1 = LoreNote(session_id=SESSION, title="Zebra", content="Z", category="magic")
        n2 = LoreNote(session_id=SESSION, title="Alpha", content="A", category="history")
        n3 = LoreNote(session_id=SESSION, title="Beta", content="B", category="history")
        for n in [n1, n2, n3]:
            store.save(n)
        notes = store.get_all(SESSION)
        titles = [n.title for n in notes]
        # history < magic alphabetically
        assert titles.index("Alpha") < titles.index("Zebra")
        assert titles.index("Beta") < titles.index("Zebra")
        # within history: alpha before beta
        assert titles.index("Alpha") < titles.index("Beta")

    def test_get_by_category(self, db):
        store = LoreNoteStore(db)
        n1 = LoreNote(session_id=SESSION, title="Fireball Spell", content="F", category="magic")
        n2 = LoreNote(session_id=SESSION, title="Old War", content="O", category="history")
        store.save(n1)
        store.save(n2)
        magic = store.get_by_category(SESSION, "magic")
        assert any(n.title == "Fireball Spell" for n in magic)
        assert not any(n.title == "Old War" for n in magic)

    def test_get_by_category_case_insensitive(self, db):
        store = LoreNoteStore(db)
        n = LoreNote(session_id=SESSION, title="X", content="X", category="Magic")
        store.save(n)
        result = store.get_by_category(SESSION, "magic")
        assert any(r.id == n.id for r in result)

    def test_delete(self, db):
        store = LoreNoteStore(db)
        n = self._make_note()
        store.save(n)
        store.delete(n.id)
        assert store.get(n.id) is None

    def test_delete_session(self, db):
        store = LoreNoteStore(db)
        for i in range(3):
            store.save(LoreNote(session_id=SESSION, title=f"N{i}", content="x"))
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []


# ══════════════════════════════════════════════════════════════════════════════
# Prompt builder formatter
# ══════════════════════════════════════════════════════════════════════════════

class TestQuestPromptFormatter:
    def test_format_quests_header(self):
        quests = [Quest(session_id=SESSION, title="Find the Lost Sword")]
        text = _format_quests(quests)
        assert "ACTIVE QUESTS" in text

    def test_format_includes_title(self):
        quests = [Quest(session_id=SESSION, title="Rescue the Hostage")]
        text = _format_quests(quests)
        assert "Rescue the Hostage" in text

    def test_format_includes_giver(self):
        quests = [Quest(session_id=SESSION, title="Quest", giver_npc_name="Lord Valdris")]
        text = _format_quests(quests)
        assert "Lord Valdris" in text

    def test_format_includes_stages(self):
        quests = [Quest(
            session_id=SESSION,
            title="Quest",
            stages=[
                QuestStage(description="Scout the area", completed=False, order=0),
                QuestStage(description="Report back", completed=True, order=1),
            ],
        )]
        text = _format_quests(quests)
        assert "Scout the area" in text
        assert "Report back" in text

    def test_format_stage_checkmarks(self):
        quests = [Quest(
            session_id=SESSION,
            title="Quest",
            stages=[
                QuestStage(description="Done step", completed=True, order=0),
                QuestStage(description="Pending step", completed=False, order=1),
            ],
        )]
        text = _format_quests(quests)
        assert "✓" in text
        assert "○" in text

    def test_format_includes_reward(self):
        quests = [Quest(session_id=SESSION, title="Quest", reward_notes="500 gold")]
        text = _format_quests(quests)
        assert "500 gold" in text

    def test_format_critical_importance_tagged(self):
        quests = [Quest(session_id=SESSION, title="Main Quest", importance=ImportanceLevel.CRITICAL)]
        text = _format_quests(quests)
        assert "CRITICAL" in text

    def test_format_progress_label_shown(self):
        quests = [Quest(
            session_id=SESSION,
            title="Quest",
            stages=[
                QuestStage(description="A", completed=True, order=0),
                QuestStage(description="B", completed=False, order=1),
            ],
        )]
        text = _format_quests(quests)
        assert "1/2 stages" in text

    def test_empty_list_returns_header_only(self):
        text = _format_quests([])
        assert "ACTIVE QUESTS" in text
