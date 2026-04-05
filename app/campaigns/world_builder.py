"""
AI-assisted world builder for the campaign system.

Takes a player's free-text world description (any level of detail) and uses
an LLM to generate a complete WorldBuildResult. Player input is sacred —
the AI fills gaps but never contradicts what the player described.

Supports iterative refinement: call refine_section() to regenerate a
specific section with additional guidance.
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any

import httpx

from app.core.models import WorldBuildResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Robustly pull the first JSON object out of an LLM response.
    The model often wraps JSON in markdown code fences or thinking blocks.
    """
    # Strip <think>...</think> blocks (Qwen3, DeepSeek-R1, etc.)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"```", "", cleaned)

    # Try to find a JSON object
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Last resort: try the whole cleaned string
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {}


def _ollama_generate(
    base_url: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.8,
) -> str:
    """Simple blocking call to Ollama /api/chat."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 8192,
        },
    }
    r = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=180.0)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


# ── System prompt ─────────────────────────────────────────────────────────────

_WORLD_BUILD_SYSTEM = textwrap.dedent("""
    You are a world-building assistant for collaborative roleplay.

    Your job is to take the player's description of their world and expand it
    into a complete, richly detailed world document. The player's words are
    SACRED — you must honour every detail they gave you exactly. Your role is
    only to fill in the parts they left blank.

    Output ONLY valid JSON with exactly this structure (no extra keys, no
    markdown fences, no commentary outside the JSON):

    {
      "premise": "1–3 paragraph narrative overview of the world and its current state",
      "world_facts": [
        "Short declarative fact about the world",
        ...
      ],
      "magic_system": "Description of magic / technology / special powers (or empty string if none)",
      "factions": [
        {
          "name": "Faction name",
          "description": "What this faction is",
          "goals": "What they want",
          "methods": "How they pursue it"
        }
      ],
      "player_character": {
        "name": "Character name (default 'The Protagonist' if not specified)",
        "appearance": "Physical description",
        "personality": "Core personality traits",
        "background": "History and backstory",
        "wants": "What the character deeply desires",
        "fears": "What the character fears"
      },
      "places": [
        {
          "name": "Location name",
          "description": "What it is and looks like",
          "current_state": "Current political/social/physical state"
        }
      ],
      "npcs": [
        {
          "name": "NPC name",
          "appearance": "Physical description",
          "personality": "Personality and manner",
          "role": "Their role in the world",
          "relationship_to_player": "How they relate to the player character",
          "current_location": "Where they currently are",
          "current_state": "Current situation or mood"
        }
      ],
      "narrative_threads": [
        {
          "title": "Short thread title",
          "description": "The dramatic tension or mystery driving this thread"
        }
      ]
    }

    Guidelines:
    - premise: 2–3 sentences maximum
    - world_facts: 5–8 facts, each one sentence
    - magic_system: 2–3 sentences, or empty string if none
    - factions: 2–3 factions; each field 1–2 sentences
    - player_character: each field 1–2 sentences
    - places: 3–5 locations; each field 1–2 sentences
    - npcs: 3–5 characters; each field 1–2 sentences
    - narrative_threads: 2–3 threads; description 1–2 sentences
    - Keep every text field SHORT — the player will expand them during review
    - If the player didn't specify a character name, use "The Protagonist"
    - Make everything coherent and internally consistent
    - Lean into genre and tone cues from the player's description
    - NEVER contradict the player's input — only expand it
    - Output ONLY the JSON object — no text before or after, no markdown fences
""").strip()


_REFINE_SYSTEM = textwrap.dedent("""
    You are a world-building assistant for collaborative roleplay.

    The player has an existing world document and wants to refine a specific
    section. You will receive the current world document (as JSON) and
    instructions for what to change.

    Output ONLY valid JSON of the ENTIRE world document with the same structure
    as the input, but with the requested changes applied. Do not add markdown
    fences or commentary outside the JSON.
""").strip()


# ── Public API ────────────────────────────────────────────────────────────────

class WorldBuilder:
    """
    Generates and refines campaign world documents using a local LLM.

    Usage:
        wb = WorldBuilder(base_url="http://localhost:11434", model="llama3.2")
        result = wb.generate("I want to play a wizard in a dark fantasy world")
        result = wb.refine(result, "npcs", "Add a corrupt city guard captain")
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    # ── Core generation ───────────────────────────────────────────────────

    def generate(self, player_description: str) -> WorldBuildResult:
        """
        Generate a complete WorldBuildResult from the player's description.
        Raises RuntimeError if Ollama is unreachable or returns unparseable output.
        """
        prompt = (
            f"Here is the player's world description:\n\n"
            f"{player_description.strip()}\n\n"
            f"Generate the complete world document JSON now."
        )

        raw = _ollama_generate(
            self.base_url, self.model,
            system=_WORLD_BUILD_SYSTEM,
            prompt=prompt,
            max_tokens=4096,
            temperature=0.85,
        )

        data = _extract_json(raw)
        if not data:
            raise RuntimeError(
                "The model did not return valid JSON. "
                "Try a different model or a more detailed description."
            )

        return _dict_to_world_build_result(data)

    # ── Iterative refinement ──────────────────────────────────────────────

    def refine(
        self,
        current: WorldBuildResult,
        section: str,
        instructions: str,
    ) -> WorldBuildResult:
        """
        Regenerate a specific section of an existing WorldBuildResult.

        section: one of premise / world_facts / magic_system / factions /
                 player_character / places / npcs / narrative_threads
        instructions: free-text guidance for what to change
        """
        current_json = json.dumps(current.model_dump(), indent=2, ensure_ascii=False)

        prompt = (
            f"Here is the current world document:\n\n"
            f"```json\n{current_json}\n```\n\n"
            f"The player wants to refine the '{section}' section:\n\n"
            f"{instructions.strip()}\n\n"
            f"Return the complete updated world document JSON."
        )

        raw = _ollama_generate(
            self.base_url, self.model,
            system=_REFINE_SYSTEM,
            prompt=prompt,
            max_tokens=4096,
            temperature=0.75,
        )

        data = _extract_json(raw)
        if not data:
            # Fall back to returning the unchanged result
            return current

        return _dict_to_world_build_result(data)

    # ── Streaming generation (for UI progress feedback) ───────────────────

    def generate_stream(self, player_description: str):
        """
        Stream the raw LLM output token-by-token.
        The caller is responsible for calling _extract_json on the full text.
        Yields str chunks.
        """
        prompt = (
            f"Here is the player's world description:\n\n"
            f"{player_description.strip()}\n\n"
            f"Generate the complete world document JSON now."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _WORLD_BUILD_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "think": False,          # suppress chain-of-thought for thinking models
            "options": {
                "temperature": 0.85,
                "num_predict": 8192,
                "num_ctx": 16384,
            },
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from e

    def parse_streamed(self, full_text: str) -> WorldBuildResult:
        """Parse the accumulated streaming output into a WorldBuildResult."""
        data = _extract_json(full_text)
        if not data:
            raise RuntimeError("Model output could not be parsed as JSON.")
        return _dict_to_world_build_result(data)

    # ── Cards + lorebook synthesis ────────────────────────────────────────

    def generate_from_cards_stream(
        self,
        cards: list[dict],
        lorebook_entries: list[dict],
        additional_details: str = "",
    ):
        """
        Stream a WorldBuildResult synthesised from SillyTavern-style character
        cards and lorebook entries. Yields str chunks; caller accumulates and
        calls parse_streamed().
        """
        # Build a structured prompt from the source material
        card_block = ""
        for i, c in enumerate(cards, 1):
            name = c.get("name") or c.get("char_name") or f"Character {i}"
            parts = [f"CHARACTER {i}: {name}"]
            for field in ("description", "personality", "scenario", "creator_notes"):
                v = (c.get(field) or "").strip()
                if v:
                    parts.append(f"  {field.upper()}: {v[:500]}")
            card_block += "\n".join(parts) + "\n\n"

        lore_block = ""
        for entry in lorebook_entries:
            keys = ", ".join(entry.get("keys") or entry.get("key") or [])
            content = (entry.get("content") or "").strip()
            if content:
                lore_block += f"LORE [{keys}]: {content[:400]}\n\n"

        prompt_parts = ["Synthesise a complete world document from the following source material."]
        if card_block:
            prompt_parts.append(f"CHARACTER CARDS:\n{card_block.strip()}")
        if lore_block:
            prompt_parts.append(f"LOREBOOK ENTRIES:\n{lore_block.strip()}")
        if additional_details.strip():
            prompt_parts.append(f"ADDITIONAL PLAYER NOTES:\n{additional_details.strip()}")
        prompt_parts.append(
            "Rules:\n"
            "- Preserve every character card EXACTLY as the primary NPC list — do not alter names, personalities, or relationships\n"
            "- Distribute lorebook content across world_facts, magic_system, and premise as appropriate\n"
            "- If contradictions exist between cards or lorebook entries, choose the most internally consistent interpretation\n"
            "- Fill in gaps for places, factions, and narrative_threads based on the overall tone\n"
            "- Output ONLY the JSON world document"
        )
        prompt = "\n\n".join(prompt_parts)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _WORLD_BUILD_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "think": False,          # suppress chain-of-thought for thinking models
            "options": {
                "temperature": 0.80,
                "num_predict": 8192,
                "num_ctx": 16384,
            },
        }
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=240.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.RequestError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from e


# ── Internal helpers ──────────────────────────────────────────────────────────

def _dict_to_world_build_result(data: dict) -> WorldBuildResult:
    """Convert a raw parsed dict into a validated WorldBuildResult."""

    def _str(d: dict, key: str, default: str = "") -> str:
        v = d.get(key, default)
        return str(v) if v is not None else default

    def _list(d: dict, key: str) -> list:
        v = d.get(key, [])
        return v if isinstance(v, list) else []

    def _npc(raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {}
        return {
            "name": _str(raw, "name"),
            "appearance": _str(raw, "appearance"),
            "personality": _str(raw, "personality"),
            "role": _str(raw, "role"),
            "relationship_to_player": _str(raw, "relationship_to_player"),
            "current_location": _str(raw, "current_location"),
            "current_state": _str(raw, "current_state"),
        }

    def _place(raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {}
        return {
            "name": _str(raw, "name"),
            "description": _str(raw, "description"),
            "current_state": _str(raw, "current_state"),
        }

    def _faction(raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {}
        return {
            "name": _str(raw, "name"),
            "description": _str(raw, "description"),
            "goals": _str(raw, "goals"),
            "methods": _str(raw, "methods"),
        }

    def _thread(raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {}
        return {
            "title": _str(raw, "title"),
            "description": _str(raw, "description"),
        }

    pc_raw = data.get("player_character", {})
    if not isinstance(pc_raw, dict):
        pc_raw = {}

    player_character = {
        "name": _str(pc_raw, "name", "The Protagonist"),
        "appearance": _str(pc_raw, "appearance"),
        "personality": _str(pc_raw, "personality"),
        "background": _str(pc_raw, "background"),
        "wants": _str(pc_raw, "wants"),
        "fears": _str(pc_raw, "fears"),
    }

    # world_facts may be a list of strings or a list of dicts
    raw_facts = _list(data, "world_facts")
    world_facts: list[str] = []
    for f in raw_facts:
        if isinstance(f, str):
            world_facts.append(f)
        elif isinstance(f, dict):
            world_facts.append(f.get("content") or f.get("fact") or str(f))

    return WorldBuildResult(
        premise=_str(data, "premise"),
        world_facts=world_facts,
        magic_system=_str(data, "magic_system"),
        factions=[_faction(f) for f in _list(data, "factions") if f],
        player_character=player_character,
        places=[_place(p) for p in _list(data, "places") if p],
        npcs=[_npc(n) for n in _list(data, "npcs") if n],
        narrative_threads=[_thread(t) for t in _list(data, "narrative_threads") if t],
    )
