"""
Unit tests for character card loading and parsing.
"""

import pytest
import json
import tempfile
from pathlib import Path

from app.cards.loader import parse_card, load_card_from_file
from app.core.models import CharacterCard


# ── Fixtures ──────────────────────────────────────────────────────────────────

SIMPLE_CARD = {
    "name": "Test Character",
    "description": "A test character.",
    "personality": "Curious and bold.",
    "scenario": "Standing in a forest.",
    "first_message": "Hello there.",
    "example_dialogue": "User: Hi\nAssistant: Hello.",
}

ST_V1_CARD = {
    "name": "Aria",
    "description": "An elven ranger.",
    "personality": "Silent and deadly.",
    "scenario": "On patrol in the forest.",
    "first_mes": "I watch you from the shadows.",
    "mes_example": "<START>\nUser: Who are you?\nAria: None of your concern.",
}

ST_V2_CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "Baron",
        "description": "A pompous nobleman.",
        "personality": "Arrogant and cunning.",
        "scenario": "In his grand hall.",
        "first_mes": "You dare enter my hall?",
        "mes_example": "<START>\nUser: My lord.\nBaron: Yes, yes, get on with it.",
        "creator_notes": "Keep him insufferable.",
        "tags": ["noble", "antagonist"],
    }
}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestParseCard:
    def test_simple_card(self):
        card = parse_card(SIMPLE_CARD)
        assert isinstance(card, CharacterCard)
        assert card.name == "Test Character"
        assert card.description == "A test character."
        assert card.personality == "Curious and bold."
        assert card.first_message == "Hello there."

    def test_st_v1_field_mapping(self):
        """first_mes and mes_example should be mapped correctly."""
        card = parse_card(ST_V1_CARD)
        assert card.name == "Aria"
        assert card.first_message == "I watch you from the shadows."
        assert "None of your concern" in card.example_dialogue

    def test_st_v2_unwrapping(self):
        """V2 cards with spec wrapper should be unwrapped."""
        card = parse_card(ST_V2_CARD)
        assert card.name == "Baron"
        assert card.first_message == "You dare enter my hall?"
        assert card.creator_notes == "Keep him insufferable."
        assert "antagonist" in card.tags

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            parse_card({"description": "No name card."})

    def test_unknown_fields_ignored(self):
        """Extra fields that aren't in our model should be silently dropped."""
        raw = {**SIMPLE_CARD, "unknown_field_xyz": "ignored", "another_extra": 42}
        card = parse_card(raw)
        assert card.name == "Test Character"
        assert not hasattr(card, "unknown_field_xyz")

    def test_empty_optional_fields(self):
        """Card with only name should succeed."""
        card = parse_card({"name": "Minimal"})
        assert card.name == "Minimal"
        assert card.description == ""
        assert card.first_message == ""
        assert card.tags == []


class TestLoadCardFromFile:
    def test_load_simple_file(self, tmp_path: Path):
        card_file = tmp_path / "test_card.json"
        card_file.write_text(json.dumps(SIMPLE_CARD), encoding="utf-8")

        card = load_card_from_file(card_file)
        assert card.name == "Test Character"

    def test_load_v2_file(self, tmp_path: Path):
        card_file = tmp_path / "v2_card.json"
        card_file.write_text(json.dumps(ST_V2_CARD), encoding="utf-8")

        card = load_card_from_file(card_file)
        assert card.name == "Baron"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_card_from_file(tmp_path / "nonexistent.json")
