"""
Scene extraction pipeline.
After each turn, asks the LLM to update the rolling scene summary and
detect any location or character changes implied by the exchange.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.core.models import SceneState
from app.providers.base import BaseProvider

log = logging.getLogger("rp_utility")

# ── Prompts ────────────────────────────────────────────────────────────────────

SCENE_SYSTEM_PROMPT = """You are a scene tracker for a roleplay system.
Read the current scene state and the latest exchange, then output an updated scene description.

Output ONLY a JSON object with these fields:
{
  "summary": "1-3 sentence present-tense description of what is happening right now",
  "location": "current location name where the scene takes place",
  "active_characters": ["name1", "name2"] or null if unchanged,
  "hours_passed": <integer 0-48>
}

Rules:
- summary: always provide an updated one; keep it concise and present-tense
- location: ALWAYS output the current location name. If no location is explicitly stated, infer it from context (e.g. a tavern, a forest, a castle). If truly unknown, output "Unknown". Update if the characters moved somewhere new.
- active_characters: only set if characters entered or left the scene
- hours_passed: how many in-world hours elapsed during this exchange. Use 0 for a brief moment of dialogue, 1 for a short scene, 2-4 for a significant encounter or travel, 8 for a full journey or rest, 24+ only if the story explicitly skips days. Default to 1 if unclear.
- Output ONLY the JSON object, no other text"""

SCENE_USER_TEMPLATE = """Current scene:
- Location: {location}
- Present: {characters}
- Previous summary: {summary}
- Current in-world time: {time_of_day}

Latest exchange:
USER: {user_message}

A: {assistant_message}

Output the updated scene JSON."""


# ── Public API ────────────────────────────────────────────────────────────────

def extract_scene_update(
    provider: BaseProvider,
    user_message: str,
    assistant_message: str,
    scene: Optional[SceneState],
    clock=None,
    debug: bool = False,
) -> dict:
    """
    Ask the LLM to update the scene state based on this exchange.
    Returns a dict with keys: summary, location (may be None), active_characters (may be None),
    hours_passed (int, 0 if absent).
    Never raises — on failure returns an empty dict.
    """
    location = scene.location if scene else "Unknown"
    characters = ", ".join(scene.active_characters) if scene and scene.active_characters else "Unknown"
    summary = scene.summary if scene and scene.summary else "(none yet)"
    time_of_day = clock.time_of_day if clock else "midday"

    prompt = SCENE_USER_TEMPLATE.format(
        location=location,
        characters=characters,
        summary=summary,
        time_of_day=time_of_day,
        user_message=user_message,
        assistant_message=assistant_message,
    )

    try:
        raw = provider.generate(
            prompt,
            system=SCENE_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=256,
        )
        if debug:
            log.debug("Scene extraction response: %s", raw)
        return _parse(raw)
    except Exception as e:
        log.warning("Scene extraction failed (non-fatal): %s", e)
        return {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse(raw: str) -> dict:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return {}
