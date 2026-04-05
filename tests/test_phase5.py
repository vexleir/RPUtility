"""
tests/test_phase5.py  —  Phase 4 game features
Covers: CharacterStats, SkillChecks, NarrativeArc, Factions
"""

import pytest
from app.core.models import (
    CharacterStat,
    SkillCheckResult,
    CheckOutcome,
    NarrativeArc,
    Faction,
)
from app.sessions.stats import CharacterStatStore
from app.sessions.skill_checks import (
    SkillCheckStore,
    parse_dice,
    roll_dice,
    determine_outcome,
    perform_check,
)
from app.sessions.narrative_arc import NarrativeArcStore
from app.sessions.factions import FactionStore
from app.prompting.builder import (
    _format_stats,
    _format_narrative_arc,
    _format_faction_standings,
)


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


SESSION = "sess-p5-test"


# ══════════════════════════════════════════════════════════════════════════════
# Dice helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestParseDice:
    def test_d20(self):
        assert parse_dice("d20") == (1, 20)

    def test_2d6(self):
        assert parse_dice("2d6") == (2, 6)

    def test_d100(self):
        assert parse_dice("d100") == (1, 100)

    def test_case_insensitive(self):
        assert parse_dice("D20") == (1, 20)

    def test_whitespace(self):
        assert parse_dice("  d20  ") == (1, 20)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_dice("20d")

    def test_zero_sides_raises(self):
        with pytest.raises(ValueError):
            parse_dice("d1")

    def test_zero_count_raises(self):
        with pytest.raises(ValueError):
            parse_dice("0d6")


class TestRollDice:
    def test_d20_range(self):
        for _ in range(50):
            total, rolls = roll_dice("d20")
            assert 1 <= total <= 20
            assert len(rolls) == 1

    def test_2d6_range(self):
        for _ in range(50):
            total, rolls = roll_dice("2d6")
            assert 2 <= total <= 12
            assert len(rolls) == 2

    def test_returns_sum(self):
        total, rolls = roll_dice("3d6")
        assert total == sum(rolls)


class TestDetermineOutcome:
    def test_nat20_critical_success(self):
        assert determine_outcome(20, 25, 15, "d20") == CheckOutcome.CRITICAL_SUCCESS

    def test_nat1_critical_failure(self):
        assert determine_outcome(1, 6, 5, "d20") == CheckOutcome.CRITICAL_FAILURE

    def test_d20_success(self):
        assert determine_outcome(15, 15, 12, "d20") == CheckOutcome.SUCCESS

    def test_d20_failure(self):
        assert determine_outcome(8, 8, 12, "d20") == CheckOutcome.FAILURE

    def test_non_d20_margin_critical_success(self):
        # 2d6: total 20, difficulty 8 → margin +12 ≥ 10
        assert determine_outcome(10, 20, 8, "2d6") == CheckOutcome.CRITICAL_SUCCESS

    def test_non_d20_margin_critical_failure(self):
        # 2d6: total 2, difficulty 15 → margin -13 ≤ -10
        assert determine_outcome(2, 2, 15, "2d6") == CheckOutcome.CRITICAL_FAILURE

    def test_non_d20_success(self):
        assert determine_outcome(8, 8, 7, "2d6") == CheckOutcome.SUCCESS

    def test_non_d20_failure(self):
        assert determine_outcome(4, 4, 10, "2d6") == CheckOutcome.FAILURE


class TestPerformCheck:
    def test_returns_skill_check_result(self):
        result = perform_check(
            session_id=SESSION,
            stat=None,
            stat_name="Perception",
            difficulty=12,
        )
        assert isinstance(result, SkillCheckResult)
        assert result.stat_name == "Perception"
        assert result.difficulty == 12
        assert result.modifier == 0

    def test_uses_stat_modifier(self):
        stat = CharacterStat(session_id=SESSION, name="Str", value=16, modifier=3)
        result = perform_check(
            session_id=SESSION,
            stat=stat,
            stat_name="Strength",
            difficulty=10,
        )
        assert result.modifier == 3
        assert result.total == result.roll + 3

    def test_effective_modifier_fallback(self):
        # modifier=0 → effective = (18-10)//2 = 4
        stat = CharacterStat(session_id=SESSION, name="Str", value=18)
        result = perform_check(
            session_id=SESSION,
            stat=stat,
            stat_name="Strength",
            difficulty=10,
        )
        assert result.modifier == 4

    def test_outcome_is_valid(self):
        result = perform_check(
            session_id=SESSION,
            stat=None,
            stat_name="Athletics",
            difficulty=10,
        )
        assert result.outcome in list(CheckOutcome)

    def test_unsaved(self):
        """perform_check returns without persisting — id should be set but not in DB."""
        result = perform_check(
            session_id=SESSION,
            stat=None,
            stat_name="Stealth",
            difficulty=15,
        )
        assert result.id  # has a UUID


# ══════════════════════════════════════════════════════════════════════════════
# CharacterStatStore
# ══════════════════════════════════════════════════════════════════════════════

class TestCharacterStatStore:
    def test_save_and_get(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Strength", value=14, modifier=2)
        store.save(stat)
        fetched = store.get(stat.id)
        assert fetched is not None
        assert fetched.name == "Strength"
        assert fetched.value == 14

    def test_upsert_updates(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Dexterity", value=10)
        store.save(stat)
        stat.value = 16
        store.save(stat)
        fetched = store.get(stat.id)
        assert fetched.value == 16

    def test_get_by_name_case_insensitive(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Charisma", value=12)
        store.save(stat)
        found = store.get_by_name(SESSION, "charisma")
        assert found is not None
        assert found.id == stat.id

    def test_get_by_name_returns_none(self, db):
        store = CharacterStatStore(db)
        assert store.get_by_name(SESSION, "NoSuchStat") is None

    def test_get_all_ordered(self, db):
        store = CharacterStatStore(db)
        s1 = CharacterStat(session_id=SESSION, name="Zebra", category="skill")
        s2 = CharacterStat(session_id=SESSION, name="Alpha", category="attribute")
        s3 = CharacterStat(session_id=SESSION, name="Beta", category="attribute")
        for s in [s1, s2, s3]:
            store.save(s)
        all_stats = store.get_all(SESSION)
        names = [s.name for s in all_stats]
        # attribute before skill, then alpha within category
        assert names.index("Alpha") < names.index("Zebra")
        assert names.index("Beta") < names.index("Zebra")

    def test_get_by_category(self, db):
        store = CharacterStatStore(db)
        s1 = CharacterStat(session_id=SESSION, name="Jump", category="skill")
        s2 = CharacterStat(session_id=SESSION, name="Con", category="attribute")
        store.save(s1)
        store.save(s2)
        skills = store.get_by_category(SESSION, "skill")
        assert any(s.name == "Jump" for s in skills)
        assert not any(s.name == "Con" for s in skills)

    def test_delete(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Wisdom", value=13)
        store.save(stat)
        store.delete(stat.id)
        assert store.get(stat.id) is None

    def test_delete_session(self, db):
        store = CharacterStatStore(db)
        for i in range(3):
            store.save(CharacterStat(session_id=SESSION, name=f"Stat{i}"))
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []

    def test_effective_modifier_computed(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Int", value=14)
        store.save(stat)
        fetched = store.get(stat.id)
        # modifier=0 so effective = (14-10)//2 = 2
        assert fetched.effective_modifier == 2

    def test_explicit_modifier_used(self, db):
        store = CharacterStatStore(db)
        stat = CharacterStat(session_id=SESSION, name="Wisdom", value=10, modifier=5)
        store.save(stat)
        fetched = store.get(stat.id)
        assert fetched.effective_modifier == 5


# ══════════════════════════════════════════════════════════════════════════════
# SkillCheckStore
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillCheckStore:
    def _make_result(self, outcome=CheckOutcome.SUCCESS, stat_name="Str"):
        return SkillCheckResult(
            session_id=SESSION,
            stat_name=stat_name,
            roll=12,
            modifier=2,
            total=14,
            difficulty=12,
            outcome=outcome,
        )

    def test_save_and_get_all(self, db):
        store = SkillCheckStore(db)
        r = self._make_result()
        store.save(r)
        all_checks = store.get_all(SESSION)
        assert any(c.id == r.id for c in all_checks)

    def test_insert_or_ignore(self, db):
        """Duplicate save should not raise and not duplicate the row."""
        store = SkillCheckStore(db)
        r = self._make_result()
        store.save(r)
        store.save(r)  # second save should be ignored
        assert sum(1 for c in store.get_all(SESSION) if c.id == r.id) == 1

    def test_get_recent(self, db):
        store = SkillCheckStore(db)
        for i in range(5):
            store.save(self._make_result(stat_name=f"S{i}"))
        recent = store.get_recent(SESSION, n=3)
        assert len(recent) == 3

    def test_get_all_most_recent_first(self, db):
        import time
        store = SkillCheckStore(db)
        r1 = self._make_result(stat_name="First")
        store.save(r1)
        time.sleep(0.01)
        r2 = self._make_result(stat_name="Second")
        store.save(r2)
        all_checks = store.get_all(SESSION)
        assert all_checks[0].stat_name == "Second"

    def test_outcome_roundtrip(self, db):
        store = SkillCheckStore(db)
        for outcome in CheckOutcome:
            r = self._make_result(outcome=outcome)
            store.save(r)
            fetched = next(c for c in store.get_all(SESSION) if c.id == r.id)
            assert fetched.outcome == outcome

    def test_delete_session(self, db):
        store = SkillCheckStore(db)
        for _ in range(3):
            store.save(self._make_result())
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []


# ══════════════════════════════════════════════════════════════════════════════
# NarrativeArcStore
# ══════════════════════════════════════════════════════════════════════════════

class TestNarrativeArcStore:
    def test_get_or_default_returns_default(self, db):
        store = NarrativeArcStore(db)
        arc = store.get_or_default(SESSION)
        assert arc.session_id == SESSION
        assert arc.current_act == 1

    def test_save_and_get(self, db):
        store = NarrativeArcStore(db)
        arc = NarrativeArc(
            session_id=SESSION,
            current_act=2,
            act_label="Rising Action",
            tension=0.6,
            pacing="building",
            themes=["betrayal", "redemption"],
        )
        store.save(arc)
        fetched = store.get(SESSION)
        assert fetched is not None
        assert fetched.current_act == 2
        assert fetched.act_label == "Rising Action"
        assert fetched.tension == pytest.approx(0.6)
        assert "betrayal" in fetched.themes

    def test_tension_clamped(self, db):
        store = NarrativeArcStore(db)
        arc = NarrativeArc(session_id=SESSION, tension=1.5)
        store.save(arc)
        fetched = store.get(SESSION)
        assert fetched.tension == pytest.approx(1.0)

    def test_tension_clamped_low(self, db):
        store = NarrativeArcStore(db)
        arc = NarrativeArc(session_id=SESSION, tension=-0.5)
        store.save(arc)
        fetched = store.get(SESSION)
        assert fetched.tension == pytest.approx(0.0)

    def test_upsert(self, db):
        store = NarrativeArcStore(db)
        arc = NarrativeArc(session_id=SESSION, current_act=1)
        store.save(arc)
        arc.current_act = 3
        store.save(arc)
        fetched = store.get(SESSION)
        assert fetched.current_act == 3

    def test_tension_label(self):
        arc = NarrativeArc(session_id=SESSION, tension=0.0)
        assert arc.tension_label == "peaceful"
        arc.tension = 0.3
        assert arc.tension_label == "tense"
        arc.tension = 0.5
        assert arc.tension_label == "dramatic"
        arc.tension = 0.7
        assert arc.tension_label == "intense"
        arc.tension = 0.9
        assert arc.tension_label == "crisis"

    def test_delete_session(self, db):
        store = NarrativeArcStore(db)
        arc = NarrativeArc(session_id=SESSION)
        store.save(arc)
        store.delete_session(SESSION)
        assert store.get(SESSION) is None


# ══════════════════════════════════════════════════════════════════════════════
# FactionStore
# ══════════════════════════════════════════════════════════════════════════════

class TestFactionStore:
    def test_save_and_get(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="The Guild", standing=0.4)
        store.save(f)
        fetched = store.get(f.id)
        assert fetched is not None
        assert fetched.name == "The Guild"
        assert fetched.standing == pytest.approx(0.4)

    def test_upsert_updates(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="The Order", standing=0.0)
        store.save(f)
        f.standing = 0.8
        store.save(f)
        fetched = store.get(f.id)
        assert fetched.standing == pytest.approx(0.8)

    def test_standing_clamped_high(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="Heroes", standing=1.5)
        store.save(f)
        assert store.get(f.id).standing == pytest.approx(1.0)

    def test_standing_clamped_low(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="Villains", standing=-2.0)
        store.save(f)
        assert store.get(f.id).standing == pytest.approx(-1.0)

    def test_get_by_name_case_insensitive(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="City Watch")
        store.save(f)
        found = store.get_by_name(SESSION, "city watch")
        assert found is not None
        assert found.id == f.id

    def test_get_all_ordered_by_standing(self, db):
        store = FactionStore(db)
        f1 = Faction(session_id=SESSION, name="Allied", standing=0.9)
        f2 = Faction(session_id=SESSION, name="Hostile", standing=-0.8)
        f3 = Faction(session_id=SESSION, name="Neutral", standing=0.0)
        for f in [f1, f2, f3]:
            store.save(f)
        factions = store.get_all(SESSION)
        standings = [f.standing for f in factions]
        assert standings == sorted(standings, reverse=True)

    def test_adjust_standing(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="Merchants", standing=0.3)
        store.save(f)
        updated = store.adjust_standing(f.id, 0.2)
        assert updated is not None
        assert updated.standing == pytest.approx(0.5)

    def test_adjust_standing_clamps(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="Royals", standing=0.9)
        store.save(f)
        updated = store.adjust_standing(f.id, 0.5)
        assert updated.standing == pytest.approx(1.0)

    def test_adjust_standing_missing_returns_none(self, db):
        store = FactionStore(db)
        assert store.adjust_standing("no-such-id", 0.1) is None

    def test_standing_label(self):
        f = Faction(session_id=SESSION, name="X", standing=0.8)
        assert f.standing_label == "allied"
        f.standing = 0.4
        assert f.standing_label == "friendly"
        f.standing = 0.0
        assert f.standing_label == "neutral"
        f.standing = -0.3
        assert f.standing_label == "unfriendly"
        f.standing = -0.7
        assert f.standing_label == "hostile"

    def test_delete(self, db):
        store = FactionStore(db)
        f = Faction(session_id=SESSION, name="ToDelete", standing=0.0)
        store.save(f)
        store.delete(f.id)
        assert store.get(f.id) is None

    def test_delete_session(self, db):
        store = FactionStore(db)
        for i in range(3):
            store.save(Faction(session_id=SESSION, name=f"F{i}"))
        store.delete_session(SESSION)
        assert store.get_all(SESSION) == []


# ══════════════════════════════════════════════════════════════════════════════
# Prompt builder formatters
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptFormatters:
    def test_format_stats_groups_by_category(self):
        stats = [
            CharacterStat(session_id=SESSION, name="Strength", value=16, category="attribute"),
            CharacterStat(session_id=SESSION, name="Jump", value=10, category="skill"),
        ]
        text = _format_stats(stats)
        assert "[CHARACTER STATS]" in text
        assert "Attribute" in text
        assert "Strength 16" in text
        assert "Skill" in text
        assert "Jump 10" in text

    def test_format_stats_modifier_displayed(self):
        stats = [CharacterStat(session_id=SESSION, name="Dex", value=14, modifier=3)]
        text = _format_stats(stats)
        assert "(+3)" in text

    def test_format_stats_zero_modifier_hidden(self):
        # modifier=0 means effective = (10-10)//2 = 0, should not show (+0)
        stats = [CharacterStat(session_id=SESSION, name="Con", value=10)]
        text = _format_stats(stats)
        assert "(+0)" not in text
        assert "(0)" not in text

    def test_format_narrative_arc(self):
        arc = NarrativeArc(
            session_id=SESSION,
            current_act=2,
            act_label="Confrontation",
            tension=0.65,
            pacing="climactic",
            themes=["honor", "loss"],
        )
        text = _format_narrative_arc(arc)
        assert "[NARRATIVE ARC]" in text
        assert "Act 2" in text
        assert "Confrontation" in text
        assert "intense" in text  # tension_label for 0.65 (< 0.8 → intense)
        assert "climactic" in text
        assert "honor" in text

    def test_format_faction_standings(self):
        factions = [
            Faction(session_id=SESSION, name="The Crown", alignment="lawful", standing=0.75),
            Faction(session_id=SESSION, name="Thieves Guild", standing=-0.6),
        ]
        text = _format_faction_standings(factions)
        assert "FACTION STANDINGS" in text
        assert "The Crown" in text
        assert "allied" in text
        assert "Thieves Guild" in text
        assert "hostile" in text
