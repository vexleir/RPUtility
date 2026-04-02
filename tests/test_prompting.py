"""
Unit tests for prompt assembly.
"""

import pytest
from datetime import datetime, UTC

from app.core.config import Config
from app.core.models import (
    CharacterCard,
    LorebookEntry,
    MemoryEntry,
    MemoryType,
    ImportanceLevel,
    CertaintyLevel,
    RelationshipState,
    SceneState,
    ConversationTurn,
)
from app.prompting.builder import (
    build_messages,
    _format_character_card,
    _format_lorebook,
    _format_memories_raw,
    _format_memories_soft,
    _format_scene,
    _format_relationships,
    derive_relationship_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    c = Config()
    c.memory_injection_mode = "soft"
    return c


@pytest.fixture
def card():
    return CharacterCard(
        name="Lyra",
        description="A wandering scholar.",
        personality="Dry wit, deeply curious.",
        scenario="In a tavern.",
        first_message="Hello.",
        example_dialogue="User: Hi\nLyra: Indeed.",
    )


@pytest.fixture
def lorebook_entries():
    return [
        LorebookEntry(keys=["crosshaven"], content="Crosshaven is a trade city.", priority=5),
        LorebookEntry(keys=["dragon"], content="Dragons are rare here.", priority=3),
    ]


@pytest.fixture
def memories():
    now = datetime.now(UTC).replace(tzinfo=None)
    return [
        MemoryEntry(
            session_id="s",
            created_at=now,
            updated_at=now,
            type=MemoryType.EVENT,
            title="Arrived at tavern",
            content="The player arrived at the Tallow & Ink.",
            entities=["Player", "Lyra"],
            importance=ImportanceLevel.MEDIUM,
        ),
        MemoryEntry(
            session_id="s",
            created_at=now,
            updated_at=now,
            type=MemoryType.RUMOR,
            title="Strange lights",
            content="Someone claims to have seen strange lights in the Ashfen.",
            entities=["Ashfen"],
            importance=ImportanceLevel.LOW,
            confidence=0.4,
            certainty=CertaintyLevel.RUMOR,
        ),
    ]


@pytest.fixture
def scene():
    return SceneState(
        session_id="s",
        location="Tallow & Ink",
        active_characters=["Lyra", "Player"],
        summary="A meeting at the tavern.",
    )


@pytest.fixture
def relationships():
    return [
        RelationshipState(
            session_id="s",
            source_entity="Lyra",
            target_entity="Player",
            trust=0.3,
            respect=0.5,
        )
    ]


@pytest.fixture
def history():
    return [
        ConversationTurn(
            session_id="s", turn_number=0,
            role="user", content="Hello there."
        ),
        ConversationTurn(
            session_id="s", turn_number=1,
            role="assistant", content="Hovering is inefficient."
        ),
    ]


# ── Character card formatting ─────────────────────────────────────────────────

class TestFormatCharacterCard:
    def test_name_appears(self, card):
        result = _format_character_card(card)
        assert "LYRA" in result

    def test_description_appears(self, card):
        result = _format_character_card(card)
        assert "wandering scholar" in result

    def test_personality_appears(self, card):
        result = _format_character_card(card)
        assert "Dry wit" in result

    def test_minimal_card(self):
        card = CharacterCard(name="Bob")
        result = _format_character_card(card)
        assert "BOB" in result


# ── Memory formatting ─────────────────────────────────────────────────────────

class TestFormatMemories:
    def test_raw_mode_shows_bullets(self, memories):
        result = _format_memories_raw(memories)
        assert "•" in result
        assert "Arrived at tavern" in result

    def test_raw_mode_marks_rumors(self, memories):
        result = _format_memories_raw(memories)
        assert "[RUMOR]" in result

    def test_soft_mode_has_sections(self, memories):
        result = _format_memories_soft(memories)
        assert "Events that have occurred" in result
        assert "Unverified rumors" in result

    def test_soft_mode_confidence_shown(self, memories):
        result = _format_memories_soft(memories)
        assert "40%" in result  # 0.4 confidence shown as percentage


# ── Scene formatting ──────────────────────────────────────────────────────────

class TestFormatScene:
    def test_location_appears(self, scene):
        result = _format_scene(scene)
        assert "Tallow & Ink" in result

    def test_characters_appear(self, scene):
        result = _format_scene(scene)
        assert "Lyra" in result
        assert "Player" in result

    def test_summary_appears(self, scene):
        result = _format_scene(scene)
        assert "meeting at the tavern" in result


# ── Relationship formatting ───────────────────────────────────────────────────

class TestFormatRelationships:
    def test_entities_appear(self, relationships):
        result = _format_relationships(relationships)
        assert "Lyra" in result
        assert "Player" in result

    def test_describes_trust(self, relationships):
        result = _format_relationships(relationships)
        assert "trust" in result.lower()


class TestDescribeRelationship:
    def test_close_ally(self):
        r = RelationshipState(session_id="s", source_entity="A", target_entity="B", trust=0.8, affection=0.6)
        desc = derive_relationship_summary(r)
        assert desc == "close ally"

    def test_hostile(self):
        r = RelationshipState(session_id="s", source_entity="A", target_entity="B", hostility=0.7, affection=-0.2)
        desc = derive_relationship_summary(r)
        assert desc == "hostile"

    def test_neutral(self):
        r = RelationshipState(session_id="s", source_entity="A", target_entity="B")
        desc = derive_relationship_summary(r)
        assert desc == "neutral"


# ── Full message assembly ─────────────────────────────────────────────────────

class TestBuildMessages:
    def test_returns_list_of_dicts(self, card, lorebook_entries, memories, scene, relationships, history, config):
        messages = build_messages(
            card=card,
            lorebook_entries=lorebook_entries,
            memories=memories,
            scene=scene,
            relationships=relationships,
            history=history,
            user_message="What do you know about the Ashfen?",
            config=config,
        )
        assert isinstance(messages, list)
        for msg in messages:
            assert "role" in msg
            assert "content" in msg

    def test_first_message_is_system(self, card, lorebook_entries, memories, scene, relationships, history, config):
        messages = build_messages(
            card=card, lorebook_entries=lorebook_entries, memories=memories,
            scene=scene, relationships=relationships, history=history,
            user_message="Test", config=config,
        )
        assert messages[0]["role"] == "system"

    def test_last_message_is_user(self, card, lorebook_entries, memories, scene, relationships, history, config):
        messages = build_messages(
            card=card, lorebook_entries=lorebook_entries, memories=memories,
            scene=scene, relationships=relationships, history=history,
            user_message="My final question", config=config,
        )
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "My final question"

    def test_history_included(self, card, lorebook_entries, memories, scene, relationships, history, config):
        messages = build_messages(
            card=card, lorebook_entries=lorebook_entries, memories=memories,
            scene=scene, relationships=relationships, history=history,
            user_message="Test", config=config,
        )
        contents = [m["content"] for m in messages]
        assert any("Hovering is inefficient" in c for c in contents)

    def test_card_in_system(self, card, config):
        messages = build_messages(
            card=card, lorebook_entries=[], memories=[], scene=None,
            relationships=[], history=[], user_message="Test", config=config,
        )
        system_content = messages[0]["content"]
        assert "LYRA" in system_content

    def test_lorebook_in_system(self, card, lorebook_entries, config):
        messages = build_messages(
            card=card, lorebook_entries=lorebook_entries, memories=[], scene=None,
            relationships=[], history=[], user_message="Test", config=config,
        )
        system_content = messages[0]["content"]
        assert "trade city" in system_content

    def test_empty_lorebook_no_section(self, card, config):
        messages = build_messages(
            card=card, lorebook_entries=[], memories=[], scene=None,
            relationships=[], history=[], user_message="Test", config=config,
        )
        system_content = messages[0]["content"]
        assert "WORLD LORE" not in system_content

    def test_raw_memory_mode(self, card, memories, config):
        config.memory_injection_mode = "raw"
        messages = build_messages(
            card=card, lorebook_entries=[], memories=memories, scene=None,
            relationships=[], history=[], user_message="Test", config=config,
        )
        system_content = messages[0]["content"]
        assert "•" in system_content  # raw mode uses bullet points

    def test_provider_switching(self):
        """Smoke test: config.provider can switch without breaking build_messages."""
        c = Config()
        c.provider = "lmstudio"
        card = CharacterCard(name="Test")
        msgs = build_messages(
            card=card, lorebook_entries=[], memories=[], scene=None,
            relationships=[], history=[], user_message="Hi", config=c,
        )
        assert msgs[-1]["content"] == "Hi"
