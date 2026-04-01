"""
Lorebook retriever.
Scans recent conversation text for lorebook trigger keywords and returns
matching entries sorted by priority (descending).
"""

from __future__ import annotations

import re

from app.core.models import Lorebook, LorebookEntry


def retrieve_entries(
    lorebook: Lorebook,
    text: str,
    max_entries: int = 5,
) -> list[LorebookEntry]:
    """
    Return lorebook entries whose keys appear in `text`.

    Args:
        lorebook:    The lorebook to search.
        text:        Combined text to scan (e.g. recent conversation turns).
        max_entries: Maximum number of entries to return.

    Returns:
        List of matching LorebookEntry objects sorted by priority (highest first).
    """
    text_lower = text.lower()
    matched: list[LorebookEntry] = []

    for entry in lorebook.entries:
        if not entry.enabled:
            continue
        if _entry_matches(entry, text_lower):
            matched.append(entry)

    # Sort by priority descending, then stable order
    matched.sort(key=lambda e: e.priority, reverse=True)
    return matched[:max_entries]


def _entry_matches(entry: LorebookEntry, text_lower: str) -> bool:
    """Return True if any of the entry's keys appear in the text."""
    for key in entry.keys:
        # Use word-boundary matching to avoid false positives
        # e.g. "elf" should not trigger "elfish"
        pattern = r"\b" + re.escape(key.lower()) + r"\b"
        if re.search(pattern, text_lower):
            return True
    return False


def retrieve_entries_for_messages(
    lorebook: Lorebook,
    messages: list[dict],
    max_entries: int = 5,
) -> list[LorebookEntry]:
    """
    Convenience helper: extract text from message dicts and retrieve entries.

    Args:
        lorebook:  The lorebook to search.
        messages:  List of {"role": ..., "content": ...} dicts.
        max_entries: Max entries to return.
    """
    combined = " ".join(m.get("content", "") for m in messages)
    return retrieve_entries(lorebook, combined, max_entries=max_entries)
