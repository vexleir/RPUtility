"""
Lorebook loader.
Supports SillyTavern World Info JSON format and our simplified format.

SillyTavern World Info format:
{
  "entries": {
    "0": {"key": ["keyword1", "keyword2"], "content": "...", ...},
    ...
  }
}

Our simplified format:
{
  "name": "...",
  "entries": [
    {"keys": ["keyword"], "content": "...", "priority": 0},
    ...
  ]
}
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.models import Lorebook, LorebookEntry


def load_lorebook_from_file(path: str | Path) -> Lorebook:
    """Load and parse a lorebook from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Lorebook not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return parse_lorebook(raw, name=path.stem)


def parse_lorebook(raw: dict, name: str = "unnamed") -> Lorebook:
    """Parse a raw dict into a Lorebook, handling both formats."""
    book_name = raw.get("name", name)
    description = raw.get("description", "")

    entries_raw = raw.get("entries", [])

    # SillyTavern format: entries is a dict keyed by index string
    if isinstance(entries_raw, dict):
        entries_raw = list(entries_raw.values())

    entries: list[LorebookEntry] = []
    for item in entries_raw:
        entry = _parse_entry(item)
        if entry is not None:
            entries.append(entry)

    return Lorebook(name=book_name, description=description, entries=entries)


def _parse_entry(item: dict) -> LorebookEntry | None:
    """Parse a single lorebook entry from either format."""
    # SillyTavern uses "key" (list or comma-string); we use "keys"
    keys = item.get("keys") or item.get("key") or []
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(",") if k.strip()]

    content = item.get("content", "").strip()
    if not content or not keys:
        return None   # skip entries with no content or no trigger keys

    # SillyTavern uses "disable" flag; we use "enabled"
    disabled = item.get("disable", False)
    enabled = item.get("enabled", not disabled)

    return LorebookEntry(
        keys=keys,
        content=content,
        enabled=enabled,
        priority=item.get("priority", 0),
        comment=item.get("comment", item.get("name", "")),
    )


def load_lorebook_from_png(path: str | Path) -> Lorebook:
    """
    Extract a lorebook from a SillyTavern PNG file.
    Looks for a character_book embedded in the V2 chara data.
    """
    from app.cards.loader import extract_png_chara
    path = Path(path)
    raw = extract_png_chara(path.read_bytes())

    # Unwrap V2 wrapper
    if raw.get("spec") == "chara_card_v2":
        data = raw.get("data", {})
    else:
        data = raw

    book_data = data.get("character_book")
    if book_data:
        book_data.setdefault("name", data.get("name", path.stem))
        return parse_lorebook(book_data, name=book_data.get("name", path.stem))

    # Fallback: treat the whole payload as a lorebook if it has entries
    if "entries" in data:
        return parse_lorebook(data, name=data.get("name", path.stem))

    raise ValueError(f"No lorebook data found in {path.name}")


def load_all_lorebooks(lorebooks_dir: str | Path) -> dict[str, Lorebook]:
    """Load all .json and .png lorebooks in a directory."""
    lorebooks_dir = Path(lorebooks_dir)
    result: dict[str, Lorebook] = {}
    if not lorebooks_dir.exists():
        return result

    for path in sorted(lorebooks_dir.glob("*.json")):
        try:
            book = load_lorebook_from_file(path)
            result[book.name] = book
        except Exception as e:
            print(f"[warn] Skipping lorebook {path.name}: {e}")

    for path in sorted(lorebooks_dir.glob("*.png")):
        try:
            book = load_lorebook_from_png(path)
            result[book.name] = book
        except Exception as e:
            print(f"[warn] Skipping PNG lorebook {path.name}: {e}")

    return result
