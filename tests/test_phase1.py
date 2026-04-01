"""
Phase 1 feature tests:
  1.1 - Regenerate / delete last exchange
  1.2 - Player objectives CRUD + prompt injection
  1.3 - Session recap (mocked provider)
  1.4 - Message search
  1.5 - Bookmarks CRUD
"""

import pytest
from datetime import datetime
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import (
    PlayerObjective, ObjectiveStatus,
    Bookmark, ConversationTurn, Session,
)
from app.sessions.manager import SessionManager
from app.sessions.objectives import ObjectivesStore
from app.sessions.bookmarks import BookmarkStore


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    ensure_db(path)
    return path


@pytest.fixture
def session_mgr(db_path: str) -> SessionManager:
    return SessionManager(db_path)


@pytest.fixture
def session(session_mgr: SessionManager) -> Session:
    return session_mgr.create("Test Session", "TestChar")


@pytest.fixture
def objectives_store(db_path: str) -> ObjectivesStore:
    return ObjectivesStore(db_path)


@pytest.fixture
def bookmark_store(db_path: str) -> BookmarkStore:
    return BookmarkStore(db_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_turn(session_id: str, role: str, turn_number: int, content: str) -> ConversationTurn:
    return ConversationTurn(
        session_id=session_id,
        turn_number=turn_number,
        role=role,
        content=content,
    )


# ── 1.1 Regenerate — delete last exchange ─────────────────────────────────────

class TestDeleteLastExchange:
    def test_delete_removes_last_two_turns(self, session_mgr, session):
        sid = session.id
        for i, (role, content) in enumerate([
            ("user", "Hello"),
            ("assistant", "Hi there"),
            ("user", "How are you?"),
            ("assistant", "Fine thanks"),
        ]):
            session_mgr.add_turn(make_turn(sid, role, i, content))
        session_mgr.increment_turn(sid)
        session_mgr.increment_turn(sid)

        # Delete from turn_number 2 onwards (last exchange)
        deleted = session_mgr.delete_turns_from(sid, 2)
        assert deleted == 2
        remaining = session_mgr.get_turns(sid, limit=10)
        assert len(remaining) == 2
        assert remaining[0].content == "Hello"
        assert remaining[1].content == "Hi there"

    def test_decrement_turn_count(self, session_mgr, session):
        sid = session.id
        session_mgr.increment_turn(sid)
        session_mgr.increment_turn(sid)
        assert session_mgr.get_turn_count(sid) == 2
        session_mgr.decrement_turn_count(sid, by=1)
        assert session_mgr.get_turn_count(sid) == 1

    def test_decrement_floors_at_zero(self, session_mgr, session):
        session_mgr.decrement_turn_count(session.id, by=10)
        assert session_mgr.get_turn_count(session.id) == 0

    def test_get_last_turns_by_role(self, session_mgr, session):
        sid = session.id
        for i, (role, content) in enumerate([
            ("user", "First user"),
            ("assistant", "First reply"),
            ("user", "Second user"),
            ("assistant", "Second reply"),
        ]):
            session_mgr.add_turn(make_turn(sid, role, i, content))
        last_asst = session_mgr.get_last_turns_by_role(sid, "assistant", n=1)
        assert len(last_asst) == 1
        assert last_asst[0].content == "Second reply"


# ── 1.2 Player Objectives ─────────────────────────────────────────────────────

class TestObjectivesStore:
    def test_save_and_get(self, objectives_store, session):
        obj = PlayerObjective(session_id=session.id, title="Find the key")
        objectives_store.save(obj)
        retrieved = objectives_store.get(obj.id)
        assert retrieved is not None
        assert retrieved.title == "Find the key"
        assert retrieved.status == ObjectiveStatus.ACTIVE

    def test_get_all(self, objectives_store, session):
        for t in ["Objective A", "Objective B", "Objective C"]:
            objectives_store.save(PlayerObjective(session_id=session.id, title=t))
        all_objs = objectives_store.get_all(session.id)
        assert len(all_objs) == 3

    def test_get_active_excludes_completed(self, objectives_store, session):
        obj_a = PlayerObjective(session_id=session.id, title="Active one")
        obj_b = PlayerObjective(session_id=session.id, title="Done one", status=ObjectiveStatus.COMPLETED)
        objectives_store.save(obj_a)
        objectives_store.save(obj_b)
        active = objectives_store.get_active(session.id)
        assert len(active) == 1
        assert active[0].title == "Active one"

    def test_update_status(self, objectives_store, session):
        obj = PlayerObjective(session_id=session.id, title="Mission")
        objectives_store.save(obj)
        objectives_store.update_status(obj.id, ObjectiveStatus.COMPLETED)
        retrieved = objectives_store.get(obj.id)
        assert retrieved.status == ObjectiveStatus.COMPLETED

    def test_delete(self, objectives_store, session):
        obj = PlayerObjective(session_id=session.id, title="Doomed objective")
        objectives_store.save(obj)
        objectives_store.delete(obj.id)
        assert objectives_store.get(obj.id) is None

    def test_delete_session(self, objectives_store, session):
        for t in ["A", "B"]:
            objectives_store.save(PlayerObjective(session_id=session.id, title=t))
        objectives_store.delete_session(session.id)
        assert objectives_store.get_all(session.id) == []

    def test_session_isolation(self, objectives_store, session_mgr):
        s1 = session_mgr.create("S1", "Char1")
        s2 = session_mgr.create("S2", "Char2")
        objectives_store.save(PlayerObjective(session_id=s1.id, title="S1 goal"))
        objectives_store.save(PlayerObjective(session_id=s2.id, title="S2 goal"))
        assert len(objectives_store.get_all(s1.id)) == 1
        assert objectives_store.get_all(s1.id)[0].title == "S1 goal"

    def test_upsert_on_save(self, objectives_store, session):
        obj = PlayerObjective(session_id=session.id, title="Original")
        objectives_store.save(obj)
        obj.title = "Updated"
        objectives_store.save(obj)
        assert objectives_store.get(obj.id).title == "Updated"


# ── 1.3 Recap ─────────────────────────────────────────────────────────────────

class TestRecapGeneration:
    def test_recap_returns_string_on_success(self):
        from app.sessions.recap import generate_recap
        from app.core.models import SceneState

        class MockProvider:
            def generate(self, prompt, system="", temperature=0.4, max_tokens=300):
                return "The adventurer arrived at the tavern and met a mysterious stranger."

        recap = generate_recap(
            provider=MockProvider(),
            memories=[],
            scene=SceneState(session_id="s", location="Tallow & Ink"),
            relationships=[],
            max_sentences=3,
        )
        assert isinstance(recap, str)
        assert len(recap) > 0

    def test_recap_returns_empty_on_provider_failure(self):
        from app.sessions.recap import generate_recap
        from app.core.models import SceneState

        class FailingProvider:
            def generate(self, *a, **kw):
                raise RuntimeError("Provider offline")

        recap = generate_recap(
            provider=FailingProvider(),
            memories=[],
            scene=SceneState(session_id="s", location="Unknown"),
            relationships=[],
        )
        assert recap == ""


# ── 1.4 Message Search ────────────────────────────────────────────────────────

class TestMessageSearch:
    def test_search_finds_matching_turns(self, session_mgr, session):
        sid = session.id
        for i, content in enumerate(["The dragon appeared", "We fled to the forest", "Dragon attacks again"]):
            session_mgr.add_turn(make_turn(sid, "assistant", i, content))
        results = session_mgr.search_turns(sid, "dragon")
        assert len(results) == 2
        titles = {r.content for r in results}
        assert "The dragon appeared" in titles
        assert "Dragon attacks again" in titles

    def test_search_is_case_insensitive(self, session_mgr, session):
        session_mgr.add_turn(make_turn(session.id, "user", 0, "Hello WORLD"))
        assert len(session_mgr.search_turns(session.id, "world")) == 1
        assert len(session_mgr.search_turns(session.id, "HELLO")) == 1

    def test_search_returns_empty_for_no_match(self, session_mgr, session):
        session_mgr.add_turn(make_turn(session.id, "assistant", 0, "Nothing relevant here"))
        assert session_mgr.search_turns(session.id, "xyzzy") == []

    def test_search_respects_session_isolation(self, session_mgr):
        s1 = session_mgr.create("S1", "C1")
        s2 = session_mgr.create("S2", "C2")
        session_mgr.add_turn(make_turn(s1.id, "user", 0, "secret word"))
        assert session_mgr.search_turns(s2.id, "secret") == []


# ── 1.5 Bookmarks ─────────────────────────────────────────────────────────────

class TestBookmarkStore:
    def _make_turn_and_add(self, session_mgr, session, role="assistant", content="test"):
        turn = make_turn(session.id, role, 0, content)
        session_mgr.add_turn(turn)
        return turn

    def test_save_and_get(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(
            session_id=session.id,
            turn_id=turn.id,
            turn_number=0,
            role="assistant",
            content_preview=turn.content[:200],
        )
        bookmark_store.save(bm)
        retrieved = bookmark_store.get(bm.id)
        assert retrieved is not None
        assert retrieved.turn_id == turn.id

    def test_get_by_turn(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(session_id=session.id, turn_id=turn.id, turn_number=0, role="assistant")
        bookmark_store.save(bm)
        found = bookmark_store.get_by_turn(session.id, turn.id)
        assert found is not None
        assert found.id == bm.id

    def test_get_all(self, bookmark_store, session_mgr, session):
        for i in range(3):
            turn = make_turn(session.id, "assistant", i, f"Turn {i}")
            session_mgr.add_turn(turn)
            bookmark_store.save(Bookmark(
                session_id=session.id, turn_id=turn.id,
                turn_number=i, role="assistant",
            ))
        assert len(bookmark_store.get_all(session.id)) == 3

    def test_duplicate_ignored(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(session_id=session.id, turn_id=turn.id, turn_number=0, role="assistant")
        bookmark_store.save(bm)
        bookmark_store.save(bm)  # second save should be ignored (INSERT OR IGNORE)
        assert len(bookmark_store.get_all(session.id)) == 1

    def test_delete(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(session_id=session.id, turn_id=turn.id, turn_number=0, role="assistant")
        bookmark_store.save(bm)
        bookmark_store.delete(bm.id)
        assert bookmark_store.get(bm.id) is None

    def test_delete_by_turn(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(session_id=session.id, turn_id=turn.id, turn_number=0, role="assistant")
        bookmark_store.save(bm)
        bookmark_store.delete_by_turn(session.id, turn.id)
        assert bookmark_store.get_by_turn(session.id, turn.id) is None

    def test_delete_session(self, bookmark_store, session_mgr, session):
        for i in range(2):
            turn = make_turn(session.id, "user", i, f"msg {i}")
            session_mgr.add_turn(turn)
            bookmark_store.save(Bookmark(
                session_id=session.id, turn_id=turn.id,
                turn_number=i, role="user",
            ))
        bookmark_store.delete_session(session.id)
        assert bookmark_store.get_all(session.id) == []

    def test_update_note(self, bookmark_store, session_mgr, session):
        turn = self._make_turn_and_add(session_mgr, session)
        bm = Bookmark(session_id=session.id, turn_id=turn.id, turn_number=0, role="assistant")
        bookmark_store.save(bm)
        bookmark_store.update_note(bm.id, "Important scene")
        assert bookmark_store.get(bm.id).note == "Important scene"


# ── Prompt injection for objectives ───────────────────────────────────────────

class TestObjectivesPromptInjection:
    def test_active_objectives_appear_in_prompt(self):
        from app.prompting.builder import build_messages, _format_objectives
        from app.core.models import PlayerObjective, ObjectiveStatus

        active = [
            PlayerObjective(session_id="s", title="Find the missing merchant"),
            PlayerObjective(session_id="s", title="Discover who burned the archive"),
        ]
        result = _format_objectives(active)
        assert "PLAYER GOALS" in result
        assert "Find the missing merchant" in result
        assert "Discover who burned the archive" in result

    def test_completed_objectives_not_injected(self):
        from app.prompting.builder import build_messages
        from app.core.models import (
            PlayerObjective, ObjectiveStatus,
            CharacterCard, SceneState,
        )
        from app.core.config import Config

        completed = PlayerObjective(
            session_id="s", title="Already done",
            status=ObjectiveStatus.COMPLETED,
        )
        messages = build_messages(
            card=CharacterCard(name="Test"),
            lorebook_entries=[],
            memories=[],
            scene=SceneState(session_id="s"),
            relationships=[],
            history=[],
            user_message="hello",
            config=Config(),
            objectives=[completed],
        )
        system = messages[0]["content"]
        assert "Already done" not in system
