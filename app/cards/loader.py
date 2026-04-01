"""
Character card loader.
Supports SillyTavern V1/V2 JSON format, simplified flat JSON, and PNG cards
(SillyTavern-style: JSON embedded in the 'chara' tEXt/iTXt PNG chunk).
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path
from app.core.models import CharacterCard


# ─── PNG chunk parser ──────────────────────────────────────────────────────────

_PNG_SIG = b'\x89PNG\r\n\x1a\n'


def _iter_png_chunks(data: bytes):
    """Yield (chunk_type, chunk_data) for every chunk in a PNG bytestring."""
    if data[:8] != _PNG_SIG:
        raise ValueError("Not a valid PNG file")
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8].decode('ascii', errors='replace')
        chunk_data = data[offset + 8:offset + 8 + length]
        yield chunk_type, chunk_data
        offset += 12 + length


def extract_png_chara(data: bytes) -> dict:
    """
    Extract and decode the SillyTavern 'chara' payload from PNG bytes.
    Checks tEXt chunks first (most common), then iTXt (compressed variant).
    Returns the parsed JSON dict.
    """
    for chunk_type, chunk_data in _iter_png_chunks(data):
        if chunk_type == 'tEXt':
            sep = chunk_data.find(b'\x00')
            if sep != -1 and chunk_data[:sep] == b'chara':
                b64_text = chunk_data[sep + 1:]
                return json.loads(base64.b64decode(b64_text).decode('utf-8'))

        elif chunk_type == 'iTXt':
            sep = chunk_data.find(b'\x00')
            if sep != -1 and chunk_data[:sep] == b'chara':
                rest = chunk_data[sep + 1:]
                comp_flag = rest[0] if rest else 0
                rest = rest[2:]                           # skip comp_flag + comp_method
                rest = rest[rest.find(b'\x00') + 1:]     # skip language tag
                rest = rest[rest.find(b'\x00') + 1:]     # skip translated keyword
                if comp_flag:
                    rest = zlib.decompress(rest)
                return json.loads(base64.b64decode(rest).decode('utf-8'))

    raise ValueError("No 'chara' chunk found in PNG")


# ─── Field name aliases ────────────────────────────────────────────────────────
# Maps SillyTavern field names → our model field names where they differ.
_ST_FIELD_MAP = {
    "first_mes": "first_message",
    "mes_example": "example_dialogue",
    "creator_notes": "creator_notes",
    "system_prompt": "system_prompt",
}


def load_card_from_file(path: str | Path) -> CharacterCard:
    """Load and parse a character card from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Character card not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return parse_card(raw)


def load_card_from_png(path: str | Path) -> CharacterCard:
    """Load and parse a SillyTavern-style PNG character card."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PNG card not found: {path}")
    raw = extract_png_chara(path.read_bytes())
    return parse_card(raw)


def parse_card(raw: dict) -> CharacterCard:
    """
    Parse a raw dict into a CharacterCard.

    Handles:
      - SillyTavern V2: {"spec": "chara_card_v2", "data": {...}}
      - SillyTavern V1: flat dict with "name", "description", etc.
      - Our simplified format: same as V1 but with "first_message" already normalised
    """
    # Unwrap SillyTavern V2/V3 wrapper (spec: "chara_card_v2", "chara_card_v3", etc.)
    if "spec" in raw and str(raw.get("spec", "")).startswith("chara_card_v"):
        raw = raw.get("data", raw)

    # Normalise field names
    normalised: dict = {}
    for src_key, value in raw.items():
        dst_key = _ST_FIELD_MAP.get(src_key, src_key)
        normalised[dst_key] = value

    # Required field
    if "name" not in normalised:
        raise ValueError("Character card must have a 'name' field.")

    # Extract only the fields our model knows about
    known_fields = CharacterCard.model_fields.keys()
    filtered = {k: v for k, v in normalised.items() if k in known_fields}

    return CharacterCard(**filtered)


def load_all_cards(
    cards_dir: str | Path,
    image_map: dict[str, Path] | None = None,
) -> dict[str, CharacterCard]:
    """
    Load every .json and .png file in cards_dir as a character card.
    Returns a dict mapping card name → CharacterCard.
    If image_map is provided, it is populated with {card_name: png_path}
    for every successfully loaded PNG card.
    """
    cards_dir = Path(cards_dir)
    result: dict[str, CharacterCard] = {}
    if not cards_dir.exists():
        return result

    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = load_card_from_file(path)
            result[card.name] = card
        except Exception as e:
            print(f"[warn] Skipping card {path.name}: {e}")

    for path in sorted(cards_dir.glob("*.png")):
        try:
            card = load_card_from_png(path)
            result[card.name] = card
            if image_map is not None:
                image_map[card.name] = path
        except Exception as e:
            print(f"[warn] Skipping PNG card {path.name}: {e}")

    return result
