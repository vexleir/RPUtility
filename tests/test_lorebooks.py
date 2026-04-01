"""
Unit tests for lorebook loading and retrieval.
"""

import pytest
import json
from pathlib import Path

from app.lorebooks.loader import parse_lorebook, load_lorebook_from_file
from app.lorebooks.retriever import retrieve_entries, _entry_matches
from app.core.models import Lorebook, LorebookEntry


# ── Fixtures ──────────────────────────────────────────────────────────────────

SIMPLE_LOREBOOK = {
    "name": "Test Lore",
    "entries": [
        {
            "keys": ["dragon", "wyrm"],
            "content": "Dragons are ancient beings of fire and wisdom.",
            "priority": 5,
        },
        {
            "keys": ["castle", "keep", "fortress"],
            "content": "The castle looms over the valley.",
            "priority": 3,
        },
        {
            "keys": ["elf"],
            "content": "Elves are long-lived and reclusive.",
            "priority": 2,
        },
    ],
}

ST_WORLD_INFO_FORMAT = {
    "entries": {
        "0": {
            "key": ["knight", "paladin"],
            "content": "The knights of the realm are bound by the Seven Vows.",
            "disable": False,
            "priority": 4,
        },
        "1": {
            "key": "wizard,mage,sorcerer",
            "content": "Magic users are required to register with the Arcane Council.",
            "disable": True,   # disabled entry
        },
        "2": {
            "key": ["shadow guild"],
            "content": "The Shadow Guild controls the underground information trade.",
            "disable": False,
        },
    }
}


# ── Lorebook loading tests ────────────────────────────────────────────────────

class TestParseLorebook:
    def test_simple_format(self):
        book = parse_lorebook(SIMPLE_LOREBOOK)
        assert book.name == "Test Lore"
        assert len(book.entries) == 3

    def test_st_world_info_format(self):
        """Dict-keyed entries (SillyTavern format) should be handled."""
        book = parse_lorebook(ST_WORLD_INFO_FORMAT, name="World Info")
        # disabled entry should still be present but marked disabled
        assert any(not e.enabled for e in book.entries)
        enabled = [e for e in book.entries if e.enabled]
        assert len(enabled) == 2

    def test_comma_separated_keys(self):
        """String keys like 'wizard,mage,sorcerer' should be split."""
        book = parse_lorebook(ST_WORLD_INFO_FORMAT, name="World Info")
        wizard_entry = next(
            (e for e in book.entries if "wizard" in e.keys), None
        )
        assert wizard_entry is not None
        assert "mage" in wizard_entry.keys
        assert "sorcerer" in wizard_entry.keys

    def test_empty_content_skipped(self):
        """Entries with no content should be skipped."""
        raw = {
            "name": "Sparse",
            "entries": [
                {"keys": ["trigger"], "content": ""},        # empty → skip
                {"keys": ["trigger2"], "content": "Valid."},  # keep
            ],
        }
        book = parse_lorebook(raw)
        assert len(book.entries) == 1

    def test_no_keys_skipped(self):
        """Entries with no keys should be skipped."""
        raw = {
            "entries": [
                {"keys": [], "content": "No trigger."},
                {"keys": ["valid"], "content": "Has trigger."},
            ]
        }
        book = parse_lorebook(raw)
        assert len(book.entries) == 1

    def test_load_from_file(self, tmp_path: Path):
        path = tmp_path / "test_lorebook.json"
        path.write_text(json.dumps(SIMPLE_LOREBOOK), encoding="utf-8")
        book = load_lorebook_from_file(path)
        assert book.name == "Test Lore"
        assert len(book.entries) == 3


# ── Retrieval tests ───────────────────────────────────────────────────────────

class TestRetrieveEntries:
    def setup_method(self):
        self.book = parse_lorebook(SIMPLE_LOREBOOK)

    def test_single_keyword_match(self):
        entries = retrieve_entries(self.book, "I saw a dragon in the sky.")
        assert len(entries) == 1
        assert "dragon" in entries[0].keys

    def test_multiple_keyword_match(self):
        entries = retrieve_entries(self.book, "The dragon circled the castle.")
        assert len(entries) == 2

    def test_alternate_keyword_match(self):
        """Either key in a key list should trigger the entry."""
        entries = retrieve_entries(self.book, "I heard a wyrm lives nearby.")
        assert len(entries) == 1
        assert "wyrm" in entries[0].keys

    def test_no_match(self):
        entries = retrieve_entries(self.book, "The sun was bright today.")
        assert len(entries) == 0

    def test_word_boundary(self):
        """'elf' should not match 'elfish' or 'yourself'."""
        entries = retrieve_entries(self.book, "She was rather elfish in manner.")
        assert len(entries) == 0

        entries = retrieve_entries(self.book, "The elf stepped forward.")
        assert len(entries) == 1

    def test_priority_ordering(self):
        """Higher priority entries should appear first."""
        entries = retrieve_entries(
            self.book, "The dragon fought near the castle."
        )
        assert entries[0].priority >= entries[-1].priority

    def test_max_entries_respected(self):
        entries = retrieve_entries(
            self.book,
            "The dragon and the castle and the elf",
            max_entries=2,
        )
        assert len(entries) == 2

    def test_disabled_entries_skipped(self):
        book = parse_lorebook(ST_WORLD_INFO_FORMAT, name="WI")
        # wizard entry is disabled
        entries = retrieve_entries(book, "the wizard cast a spell")
        assert not any("wizard" in e.keys for e in entries)

    def test_case_insensitive(self):
        entries = retrieve_entries(self.book, "THE DRAGON ROARED.")
        assert len(entries) == 1
