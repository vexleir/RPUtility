"""
Phase 3 (game design plan) feature tests:
  - Emotional State get/set/stress-label/stress-clamp
  - Inventory CRUD + equip toggle + session isolation
  - Status Effects CRUD + ordering + session isolation
  - CharacterCard voice guide fields
  - NPC extractor JSON parsing (no LLM required)
  - Prompt injection for inventory, status effects, emotional state, voice guide
"""

import pytest
from pathlib import Path

from app.core.database import ensure_db
from app.core.models import (
    EmotionalState, InventoryItem, StatusEffect, EffectType,
    CharacterCard, SceneState,
)
from app.sessions.emotional_state import EmotionalStateStore
from app.sessions.inventory import InventoryStore
from app.sessions.status_effects import StatusEffectStore
from app.sessions.manager import SessionManager
from app.sessions.npc_extractor import _parse_npcs


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test_p4.db")
    ensure_db(path)
    return path


@pytest.fixture
def es_store(db_path):
    return EmotionalStateStore(db_path)


@pytest.fixture
def inv_store(db_path):
    return InventoryStore(db_path)


@pytest.fixture
def fx_store(db_path):
    return StatusEffectStore(db_path)


@pytest.fixture
def session_mgr(db_path):
    return SessionManager(db_path)


@pytest.fixture
def session(session_mgr):
    return session_mgr.create("Test", "Hero")


# ── Emotional State ───────────────────────────────────────────────────────────

class TestEmotionalState:
    def test_get_or_default_neutral(self, es_store, session):
        state = es_store.get_or_default(session.id)
        assert state.mood == "neutral"
        assert state.stress == 0.0

    def test_save_and_get(self, es_store, session):
        state = EmotionalState(
            session_id=session.id,
            mood="grieving",
            stress=0.6,
            motivation="Seeking revenge",
        )
        es_store.save(state)
        retrieved = es_store.get(session.id)
        assert retrieved.mood == "grieving"
        assert retrieved.stress == pytest.approx(0.6)
        assert retrieved.motivation == "Seeking revenge"

    def test_upsert_updates_existing(self, es_store, session):
        s = EmotionalState(session_id=session.id, mood="hopeful", stress=0.2)
        es_store.save(s)
        s.mood = "anxious"
        s.stress = 0.75
        es_store.save(s)
        updated = es_store.get(session.id)
        assert updated.mood == "anxious"
        assert updated.stress == pytest.approx(0.75)

    def test_stress_clamped_above_1(self, es_store, session):
        state = EmotionalState(session_id=session.id, stress=2.5)
        es_store.save(state)
        assert es_store.get(session.id).stress == pytest.approx(1.0)

    def test_stress_clamped_below_0(self, es_store, session):
        state = EmotionalState(session_id=session.id, stress=-0.5)
        es_store.save(state)
        assert es_store.get(session.id).stress == pytest.approx(0.0)

    def test_stress_label_property(self):
        assert EmotionalState(session_id="s", stress=0.1).stress_label == "calm"
        assert EmotionalState(session_id="s", stress=0.3).stress_label == "uneasy"
        assert EmotionalState(session_id="s", stress=0.5).stress_label == "stressed"
        assert EmotionalState(session_id="s", stress=0.7).stress_label == "overwhelmed"
        assert EmotionalState(session_id="s", stress=0.9).stress_label == "breaking point"

    def test_delete_session(self, es_store, session):
        es_store.save(EmotionalState(session_id=session.id, mood="sad"))
        es_store.delete_session(session.id)
        assert es_store.get(session.id) is None


# ── Inventory ─────────────────────────────────────────────────────────────────

class TestInventory:
    def _item(self, session_id, name="Iron Sword", equipped=False):
        return InventoryItem(
            session_id=session_id,
            name=name,
            description="A trusty blade",
            condition="good",
            quantity=1,
            is_equipped=equipped,
        )

    def test_save_and_get(self, inv_store, session):
        item = self._item(session.id)
        inv_store.save(item)
        retrieved = inv_store.get(item.id)
        assert retrieved.name == "Iron Sword"
        assert retrieved.is_equipped is False

    def test_get_all_equipped_first(self, inv_store, session):
        inv_store.save(self._item(session.id, name="Shield", equipped=False))
        inv_store.save(self._item(session.id, name="Sword", equipped=True))
        inv_store.save(self._item(session.id, name="Potion", equipped=False))
        items = inv_store.get_all(session.id)
        assert items[0].is_equipped is True
        assert items[0].name == "Sword"

    def test_get_equipped(self, inv_store, session):
        inv_store.save(self._item(session.id, name="Helmet", equipped=True))
        inv_store.save(self._item(session.id, name="Boots", equipped=False))
        equipped = inv_store.get_equipped(session.id)
        assert len(equipped) == 1
        assert equipped[0].name == "Helmet"

    def test_upsert_updates_condition(self, inv_store, session):
        item = self._item(session.id)
        inv_store.save(item)
        item.condition = "damaged"
        inv_store.save(item)
        assert inv_store.get(item.id).condition == "damaged"

    def test_delete(self, inv_store, session):
        item = self._item(session.id)
        inv_store.save(item)
        inv_store.delete(item.id)
        assert inv_store.get(item.id) is None

    def test_delete_session(self, inv_store, session):
        for name in ["A", "B", "C"]:
            inv_store.save(self._item(session.id, name=name))
        inv_store.delete_session(session.id)
        assert inv_store.get_all(session.id) == []

    def test_session_isolation(self, inv_store, session_mgr):
        s1 = session_mgr.create("S1", "C1")
        s2 = session_mgr.create("S2", "C2")
        inv_store.save(self._item(s1.id, name="S1 Item"))
        inv_store.save(self._item(s2.id, name="S2 Item"))
        assert len(inv_store.get_all(s1.id)) == 1
        assert inv_store.get_all(s1.id)[0].name == "S1 Item"

    def test_quantity_stored(self, inv_store, session):
        item = InventoryItem(session_id=session.id, name="Arrows", quantity=20)
        inv_store.save(item)
        assert inv_store.get(item.id).quantity == 20


# ── Status Effects ─────────────────────────────────────────────────────────────

class TestStatusEffects:
    def _effect(self, session_id, name="Bleeding", etype=EffectType.DEBUFF, sev="moderate"):
        return StatusEffect(
            session_id=session_id,
            name=name,
            description="Losing health each round",
            effect_type=etype,
            severity=sev,
            duration_turns=3,
        )

    def test_save_and_get(self, fx_store, session):
        fx = self._effect(session.id)
        fx_store.save(fx)
        retrieved = fx_store.get(fx.id)
        assert retrieved.name == "Bleeding"
        assert retrieved.effect_type == EffectType.DEBUFF
        assert retrieved.duration_turns == 3

    def test_get_all_debuffs_first(self, fx_store, session):
        fx_store.save(self._effect(session.id, name="Haste", etype=EffectType.BUFF))
        fx_store.save(self._effect(session.id, name="Poison", etype=EffectType.DEBUFF))
        fx_store.save(self._effect(session.id, name="Neutral", etype=EffectType.NEUTRAL))
        effects = fx_store.get_all(session.id)
        assert effects[0].effect_type == EffectType.DEBUFF

    def test_all_effect_types_roundtrip(self, fx_store, session):
        for etype in EffectType:
            fx = StatusEffect(session_id=session.id, name=f"Effect {etype.value}", effect_type=etype)
            fx_store.save(fx)
            assert fx_store.get(fx.id).effect_type == etype

    def test_delete(self, fx_store, session):
        fx = self._effect(session.id)
        fx_store.save(fx)
        fx_store.delete(fx.id)
        assert fx_store.get(fx.id) is None

    def test_delete_session(self, fx_store, session):
        for name in ["X", "Y", "Z"]:
            fx_store.save(self._effect(session.id, name=name))
        fx_store.delete_session(session.id)
        assert fx_store.get_all(session.id) == []

    def test_session_isolation(self, fx_store, session_mgr):
        s1 = session_mgr.create("S1", "C1")
        s2 = session_mgr.create("S2", "C2")
        fx_store.save(self._effect(s1.id, name="S1 Effect"))
        fx_store.save(self._effect(s2.id, name="S2 Effect"))
        names = [e.name for e in fx_store.get_all(s1.id)]
        assert names == ["S1 Effect"]

    def test_permanent_duration(self, fx_store, session):
        fx = StatusEffect(session_id=session.id, name="Cursed", duration_turns=0)
        fx_store.save(fx)
        assert fx_store.get(fx.id).duration_turns == 0


# ── CharacterCard Voice Guide ─────────────────────────────────────────────────

class TestVoiceGuide:
    def test_voice_fields_default_empty(self):
        card = CharacterCard(name="Lyra")
        assert card.voice_tone == ""
        assert card.speech_patterns == ""
        assert card.verbal_tics == ""
        assert card.vocabulary_level == ""
        assert card.accent_notes == ""

    def test_voice_fields_roundtrip(self):
        card = CharacterCard(
            name="Lyra",
            voice_tone="gravelly",
            speech_patterns="short declarative sentences",
            verbal_tics="trails off when nervous",
            vocabulary_level="sophisticated",
            accent_notes="faint northern brogue",
        )
        assert card.voice_tone == "gravelly"
        assert card.accent_notes == "faint northern brogue"

    def test_voice_guide_in_prompt(self):
        from app.prompting.builder import build_messages
        from app.core.config import Config
        card = CharacterCard(
            name="Lyra",
            voice_tone="gravelly",
            speech_patterns="uses archaic thee/thy",
            vocabulary_level="archaic",
        )
        messages = build_messages(
            card=card, lorebook_entries=[], memories=[],
            scene=SceneState(session_id="s"), relationships=[],
            history=[], user_message="hello", config=Config(),
        )
        system = messages[0]["content"]
        assert "Voice guide" in system
        assert "gravelly" in system
        assert "archaic" in system

    def test_no_voice_guide_section_when_empty(self):
        from app.prompting.builder import build_messages
        from app.core.config import Config
        card = CharacterCard(name="Lyra")
        messages = build_messages(
            card=card, lorebook_entries=[], memories=[],
            scene=SceneState(session_id="s"), relationships=[],
            history=[], user_message="hello", config=Config(),
        )
        system = messages[0]["content"]
        assert "Voice guide" not in system


# ── NPC extractor parser ──────────────────────────────────────────────────────

class TestNpcExtractorParser:
    def test_valid_json_parsed(self):
        raw = '[{"name": "Thornwick", "role": "blacksmith", "description": "Gruff", "last_known_location": "The Forge"}]'
        npcs = _parse_npcs(raw, "sess1", "Player")
        assert len(npcs) == 1
        assert npcs[0].name == "Thornwick"
        assert npcs[0].role == "blacksmith"
        assert npcs[0].last_known_location == "The Forge"

    def test_player_character_excluded(self):
        raw = '[{"name": "Player", "role": "hero"}, {"name": "Seraphina", "role": "innkeeper"}]'
        npcs = _parse_npcs(raw, "sess1", "Player")
        assert len(npcs) == 1
        assert npcs[0].name == "Seraphina"

    def test_empty_array_returns_empty(self):
        assert _parse_npcs("[]", "sess1", "Player") == []

    def test_markdown_fences_stripped(self):
        raw = "```json\n[{\"name\": \"Grix\", \"role\": \"guard\", \"description\": \"\", \"last_known_location\": \"\"}]\n```"
        npcs = _parse_npcs(raw, "sess1", "Hero")
        assert len(npcs) == 1
        assert npcs[0].name == "Grix"

    def test_invalid_json_returns_empty(self):
        assert _parse_npcs("not json at all", "sess1", "Player") == []

    def test_missing_name_skipped(self):
        raw = '[{"role": "guard", "description": "A guard"}]'
        npcs = _parse_npcs(raw, "sess1", "Player")
        assert npcs == []

    def test_player_substring_excluded(self):
        raw = '[{"name": "Player Character", "role": "hero"}]'
        npcs = _parse_npcs(raw, "sess1", "Player")
        assert npcs == []

    def test_is_alive_defaults_true(self):
        raw = '[{"name": "Viktor", "role": "merchant"}]'
        npcs = _parse_npcs(raw, "sess1", "Hero")
        assert npcs[0].is_alive is True


# ── Prompt injection ──────────────────────────────────────────────────────────

class TestPhase3PromptInjection:
    def _build(self, **kwargs):
        from app.prompting.builder import build_messages
        from app.core.config import Config
        defaults = dict(
            card=CharacterCard(name="Test"),
            lorebook_entries=[], memories=[],
            scene=SceneState(session_id="s"),
            relationships=[], history=[],
            user_message="hello", config=Config(),
        )
        defaults.update(kwargs)
        return build_messages(**defaults)

    def test_inventory_section_injected(self):
        items = [
            InventoryItem(session_id="s", name="Iron Sword", is_equipped=True, condition="good"),
            InventoryItem(session_id="s", name="Healing Potion", quantity=3),
        ]
        system = self._build(inventory=items)[0]["content"]
        assert "INVENTORY" in system
        assert "Iron Sword" in system
        assert "equipped" in system
        assert "Healing Potion" in system
        assert "×3" in system

    def test_no_inventory_section_when_empty(self):
        system = self._build(inventory=[])[0]["content"]
        assert "INVENTORY" not in system

    def test_status_effects_injected(self):
        effects = [
            StatusEffect(session_id="s", name="Bleeding", effect_type=EffectType.DEBUFF,
                         severity="moderate", description="Losing health"),
            StatusEffect(session_id="s", name="Haste", effect_type=EffectType.BUFF,
                         severity="mild"),
        ]
        system = self._build(status_effects=effects)[0]["content"]
        assert "STATUS EFFECTS" in system
        assert "Bleeding" in system
        assert "debuff" in system
        assert "Haste" in system
        assert "buff" in system

    def test_no_effects_section_when_empty(self):
        system = self._build(status_effects=[])[0]["content"]
        assert "STATUS EFFECTS" not in system

    def test_emotional_state_injected_when_non_neutral(self):
        state = EmotionalState(session_id="s", mood="grieving", stress=0.7,
                               motivation="Revenge for fallen comrades")
        system = self._build(emotional_state=state)[0]["content"]
        assert "PLAYER CHARACTER STATE" in system
        assert "grieving" in system
        assert "overwhelmed" in system
        assert "Revenge" in system

    def test_no_state_section_when_neutral(self):
        state = EmotionalState(session_id="s", mood="neutral", stress=0.0)
        system = self._build(emotional_state=state)[0]["content"]
        assert "PLAYER CHARACTER STATE" not in system

    def test_damaged_condition_shown(self):
        items = [InventoryItem(session_id="s", name="Shield", condition="damaged")]
        system = self._build(inventory=items)[0]["content"]
        assert "damaged" in system

    def test_good_condition_not_shown(self):
        items = [InventoryItem(session_id="s", name="Dagger", condition="good")]
        system = self._build(inventory=items)[0]["content"]
        # "good" condition is suppressed to reduce noise
        system_lines = [l for l in system.split("\n") if "Dagger" in l]
        assert all("[good]" not in l for l in system_lines)
