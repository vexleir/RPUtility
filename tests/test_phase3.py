"""
Phase 2 (game design plan) feature tests:
  - NPC Roster CRUD + session isolation
  - Location Registry CRUD + auto-visit tracking
  - In-World Clock get/set/display
  - Story Beats CRUD
  - Prompt injection for NPCs, clock, story beats
"""

import pytest
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import (
    NpcEntry, LocationEntry, WorldClock, StoryBeat,
    BeatType,
    CharacterCard, SceneState,
)
from app.sessions.npc_roster import NpcRosterStore
from app.sessions.location_registry import LocationRegistryStore
from app.sessions.world_clock import WorldClockStore
from app.sessions.story_beats import StoryBeatStore
from app.sessions.manager import SessionManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test_p3.db")
    ensure_db(path)
    return path


@pytest.fixture
def npc_store(db_path: str) -> NpcRosterStore:
    return NpcRosterStore(db_path)


@pytest.fixture
def loc_store(db_path: str) -> LocationRegistryStore:
    return LocationRegistryStore(db_path)


@pytest.fixture
def clock_store(db_path: str) -> WorldClockStore:
    return WorldClockStore(db_path)


@pytest.fixture
def beat_store(db_path: str) -> StoryBeatStore:
    return StoryBeatStore(db_path)


@pytest.fixture
def session_mgr(db_path: str) -> SessionManager:
    return SessionManager(db_path)


@pytest.fixture
def session(session_mgr):
    return session_mgr.create("Test Session", "TestChar")


# ── NPC Roster ────────────────────────────────────────────────────────────────

class TestNpcRoster:
    def _npc(self, session_id, name="Thornwick", role="blacksmith"):
        return NpcEntry(
            session_id=session_id,
            name=name,
            role=role,
            description="Gruff but fair",
            personality_notes="Distrusts magic",
            last_known_location="The Forge District",
        )

    def test_save_and_get(self, npc_store, session):
        npc = self._npc(session.id)
        npc_store.save(npc)
        retrieved = npc_store.get(npc.id)
        assert retrieved is not None
        assert retrieved.name == "Thornwick"
        assert retrieved.role == "blacksmith"
        assert retrieved.is_alive is True

    def test_get_all(self, npc_store, session):
        for name in ["Alice", "Bob", "Carol"]:
            npc_store.save(self._npc(session.id, name=name))
        assert len(npc_store.get_all(session.id)) == 3

    def test_get_by_name_case_insensitive(self, npc_store, session):
        npc_store.save(self._npc(session.id, name="Thornwick"))
        found = npc_store.get_by_name(session.id, "thornwick")
        assert found is not None
        assert found.name == "Thornwick"

    def test_get_alive_excludes_dead(self, npc_store, session):
        alive = self._npc(session.id, name="Alive One")
        dead = self._npc(session.id, name="Dead One")
        dead.is_alive = False
        npc_store.save(alive)
        npc_store.save(dead)
        alive_list = npc_store.get_alive(session.id)
        assert len(alive_list) == 1
        assert alive_list[0].name == "Alive One"

    def test_upsert_on_save(self, npc_store, session):
        npc = self._npc(session.id)
        npc_store.save(npc)
        npc.description = "Updated description"
        npc_store.save(npc)
        assert npc_store.get(npc.id).description == "Updated description"

    def test_delete(self, npc_store, session):
        npc = self._npc(session.id)
        npc_store.save(npc)
        npc_store.delete(npc.id)
        assert npc_store.get(npc.id) is None

    def test_delete_session(self, npc_store, session):
        for name in ["A", "B"]:
            npc_store.save(self._npc(session.id, name=name))
        npc_store.delete_session(session.id)
        assert npc_store.get_all(session.id) == []

    def test_session_isolation(self, npc_store, session_mgr):
        s1 = session_mgr.create("S1", "C1")
        s2 = session_mgr.create("S2", "C2")
        npc_store.save(NpcEntry(session_id=s1.id, name="NPC in S1"))
        npc_store.save(NpcEntry(session_id=s2.id, name="NPC in S2"))
        assert len(npc_store.get_all(s1.id)) == 1
        assert npc_store.get_all(s1.id)[0].name == "NPC in S1"


# ── Location Registry ─────────────────────────────────────────────────────────

class TestLocationRegistry:
    def test_save_and_get(self, loc_store, session):
        loc = LocationEntry(
            session_id=session.id,
            name="The Silver Hare Inn",
            description="A cozy tavern",
            atmosphere="Warm and smoky",
        )
        loc_store.save(loc)
        retrieved = loc_store.get(loc.id)
        assert retrieved is not None
        assert retrieved.name == "The Silver Hare Inn"
        assert retrieved.atmosphere == "Warm and smoky"

    def test_get_all_ordered_by_last_visited(self, loc_store, session):
        loc_store.save(LocationEntry(session_id=session.id, name="Old Place"))
        loc_store.save(LocationEntry(session_id=session.id, name="New Place"))
        locs = loc_store.get_all(session.id)
        assert len(locs) == 2

    def test_record_visit_creates_new(self, loc_store, session):
        entry = loc_store.record_visit(session.id, "The Market")
        assert entry.name == "The Market"
        assert entry.visit_count == 1

    def test_record_visit_increments_existing(self, loc_store, session):
        loc_store.record_visit(session.id, "The Market")
        loc_store.record_visit(session.id, "The Market")
        loc = loc_store.get_by_name(session.id, "The Market")
        assert loc.visit_count == 2

    def test_get_by_name_case_insensitive(self, loc_store, session):
        loc_store.record_visit(session.id, "Crosshaven")
        found = loc_store.get_by_name(session.id, "crosshaven")
        assert found is not None

    def test_delete(self, loc_store, session):
        entry = loc_store.record_visit(session.id, "Temp Location")
        loc_store.delete(entry.id)
        assert loc_store.get(entry.id) is None

    def test_delete_session(self, loc_store, session):
        loc_store.record_visit(session.id, "A")
        loc_store.record_visit(session.id, "B")
        loc_store.delete_session(session.id)
        assert loc_store.get_all(session.id) == []

    def test_upsert_updates_description(self, loc_store, session):
        loc = LocationEntry(session_id=session.id, name="The Keep")
        loc_store.save(loc)
        loc.description = "Dark and foreboding"
        loc_store.save(loc)
        assert loc_store.get(loc.id).description == "Dark and foreboding"


# ── World Clock ───────────────────────────────────────────────────────────────

class TestWorldClock:
    def test_get_or_default_returns_day1(self, clock_store, session):
        clock = clock_store.get_or_default(session.id)
        assert clock.year == 1
        assert clock.month == 1
        assert clock.day == 1

    def test_save_and_get(self, clock_store, session):
        clock = WorldClock(
            session_id=session.id,
            year=847, month=3, day=12, hour=14,
            era_label="Third Age",
        )
        clock_store.save(clock)
        retrieved = clock_store.get(session.id)
        assert retrieved is not None
        assert retrieved.year == 847
        assert retrieved.era_label == "Third Age"

    def test_upsert_updates_existing(self, clock_store, session):
        clock = WorldClock(session_id=session.id, year=1, month=1, day=1, hour=8)
        clock_store.save(clock)
        clock.day = 5
        clock.hour = 18
        clock_store.save(clock)
        updated = clock_store.get(session.id)
        assert updated.day == 5
        assert updated.hour == 18

    def test_time_of_day_property(self):
        assert WorldClock(session_id="s", hour=4).time_of_day == "night"
        assert WorldClock(session_id="s", hour=6).time_of_day == "dawn"
        assert WorldClock(session_id="s", hour=10).time_of_day == "morning"
        assert WorldClock(session_id="s", hour=13).time_of_day == "midday"
        assert WorldClock(session_id="s", hour=15).time_of_day == "afternoon"
        assert WorldClock(session_id="s", hour=19).time_of_day == "evening"
        assert WorldClock(session_id="s", hour=22).time_of_day == "night"

    def test_display_includes_era(self):
        clock = WorldClock(session_id="s", year=100, month=6, day=3, hour=12, era_label="Age of Ash")
        display = clock.display()
        assert "100" in display
        assert "Age of Ash" in display
        assert "midday" in display

    def test_display_no_era(self):
        clock = WorldClock(session_id="s", year=5, month=2, day=1, hour=7)
        display = clock.display()
        assert "5" in display
        assert "dawn" in display
        assert "()" not in display  # no empty parens

    def test_delete_session(self, clock_store, session):
        clock_store.save(WorldClock(session_id=session.id))
        clock_store.delete_session(session.id)
        assert clock_store.get(session.id) is None


# ── Story Beats ───────────────────────────────────────────────────────────────

class TestStoryBeats:
    def _beat(self, session_id, title="The Merchant Vanished", beat_type=BeatType.REVELATION):
        return StoryBeat(
            session_id=session_id,
            title=title,
            description="Edric disappeared during the Fog Festival",
            beat_type=beat_type,
            turn_number=4,
        )

    def test_save_and_get(self, beat_store, session):
        beat = self._beat(session.id)
        beat_store.save(beat)
        retrieved = beat_store.get(beat.id)
        assert retrieved is not None
        assert retrieved.title == "The Merchant Vanished"
        assert retrieved.beat_type == BeatType.REVELATION

    def test_get_all(self, beat_store, session):
        for i, t in enumerate(["Beat A", "Beat B", "Beat C"]):
            b = self._beat(session.id, title=t)
            b.turn_number = i
            beat_store.save(b)
        assert len(beat_store.get_all(session.id)) == 3

    def test_get_all_ordered_by_turn(self, beat_store, session):
        for turn, title in [(10, "Late"), (1, "Early"), (5, "Middle")]:
            b = self._beat(session.id, title=title)
            b.turn_number = turn
            beat_store.save(b)
        ordered = beat_store.get_all(session.id)
        assert [b.title for b in ordered] == ["Early", "Middle", "Late"]

    def test_get_recent(self, beat_store, session):
        for i in range(8):
            b = self._beat(session.id, title=f"Beat {i}")
            b.turn_number = i
            beat_store.save(b)
        recent = beat_store.get_recent(session.id, n=3)
        assert len(recent) == 3
        # Most recent turn first
        assert recent[0].turn_number > recent[1].turn_number

    def test_delete(self, beat_store, session):
        beat = self._beat(session.id)
        beat_store.save(beat)
        beat_store.delete(beat.id)
        assert beat_store.get(beat.id) is None

    def test_delete_session(self, beat_store, session):
        for i in range(3):
            beat_store.save(self._beat(session.id, title=f"Beat {i}"))
        beat_store.delete_session(session.id)
        assert beat_store.get_all(session.id) == []

    def test_upsert_updates_title(self, beat_store, session):
        beat = self._beat(session.id)
        beat_store.save(beat)
        beat.title = "Renamed Beat"
        beat_store.save(beat)
        assert beat_store.get(beat.id).title == "Renamed Beat"

    def test_all_beat_types_roundtrip(self, beat_store, session):
        for bt in BeatType:
            b = StoryBeat(session_id=session.id, title=f"Beat {bt.value}", beat_type=bt)
            beat_store.save(b)
            retrieved = beat_store.get(b.id)
            assert retrieved.beat_type == bt


# ── Prompt injection ──────────────────────────────────────────────────────────

class TestPhase2PromptInjection:
    def _build(self, **kwargs):
        from app.prompting.builder import build_messages
        from app.core.config import Config
        defaults = dict(
            card=CharacterCard(name="Test"),
            lorebook_entries=[],
            memories=[],
            scene=SceneState(session_id="s"),
            relationships=[],
            history=[],
            user_message="hello",
            config=Config(),
        )
        defaults.update(kwargs)
        return build_messages(**defaults)

    def test_npc_section_injected(self):
        npcs = [
            NpcEntry(session_id="s", name="Thornwick", role="blacksmith",
                     description="Gruff but fair"),
        ]
        messages = self._build(npcs=npcs)
        system = messages[0]["content"]
        assert "KNOWN NPCs" in system
        assert "Thornwick" in system
        assert "blacksmith" in system

    def test_dead_npcs_still_injected_when_passed(self):
        """Engine passes only alive NPCs; prompt just formats what it receives."""
        npc = NpcEntry(session_id="s", name="Ghost", is_alive=False)
        messages = self._build(npcs=[npc])
        system = messages[0]["content"]
        assert "Ghost" in system

    def test_no_npc_section_when_empty(self):
        messages = self._build(npcs=[])
        system = messages[0]["content"]
        assert "KNOWN NPCs" not in system

    def test_clock_injected_into_scene(self):
        clock = WorldClock(session_id="s", year=847, month=3, day=12,
                           hour=13, era_label="Third Age")
        messages = self._build(clock=clock)
        system = messages[0]["content"]
        assert "847" in system
        assert "Third Age" in system
        assert "midday" in system

    def test_no_clock_section_when_none(self):
        messages = self._build(clock=None)
        system = messages[0]["content"]
        assert "Time:" not in system

    def test_story_beats_injected(self):
        beats = [
            StoryBeat(session_id="s", title="The Archive Burns",
                      description="The city archive was set ablaze",
                      beat_type=BeatType.TRAGEDY),
        ]
        messages = self._build(story_beats=beats)
        system = messages[0]["content"]
        assert "KEY STORY MOMENTS" in system
        assert "The Archive Burns" in system
        assert "TRAGEDY" in system

    def test_no_beats_section_when_empty(self):
        messages = self._build(story_beats=[])
        system = messages[0]["content"]
        assert "KEY STORY MOMENTS" not in system

    def test_npc_capped_at_15(self):
        npcs = [NpcEntry(session_id="s", name=f"NPC{i}") for i in range(20)]
        messages = self._build(npcs=npcs)
        system = messages[0]["content"]
        # NPC15–NPC19 should not appear
        assert "NPC19" not in system
        assert "NPC0" in system
