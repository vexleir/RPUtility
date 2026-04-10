"""
Character Memory Profile updater.

After each scene is confirmed, this module asks the LLM to update the
CharacterProfile for every character who appeared in that scene.

The update is additive — it merges new observations into the existing
profile rather than rewriting from scratch, so details from earlier scenes
are never silently discarded.

Design rules:
- Only call once per scene-per-character (idempotent given same scene number)
- Non-fatal: any failure leaves the existing profile unchanged
- Runs in a background thread (same pattern as scene event log updates)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.memory.profile_store import CharacterProfile, CharacterProfileStore, make_profile

log = logging.getLogger("rp_utility")

# ── Prompts ────────────────────────────────────────────────────────────────────

_UPDATE_SYSTEM = """You are a character memory archivist for a roleplay campaign.
You will receive an existing character profile and a scene transcript excerpt.
Your job is to UPDATE the profile with anything new learned in this scene.

Rules:
- ADD new confirmed traits; do NOT remove existing ones unless they were wrong
- ADD newly revealed secrets (only what the player character now knows)
- UPDATE last_known_state to reflect where the character is and their condition after this scene
- Write a 2-3 sentence profile_summary combining old and new information
- Keep confirmed_traits as SHORT PHRASES (max 8 words each)
- Keep known_secrets as SHORT PHRASES (max 15 words each)
- If nothing new was learned about this character, return the existing values unchanged
- MUST PRESERVE full names; do not shorten or paraphrase proper nouns

Output ONLY a JSON object:
{
  "confirmed_traits": ["trait1", "trait2", ...],
  "known_secrets": ["secret1", ...],
  "last_known_state": "one sentence: location and current condition",
  "profile_summary": "2-3 sentence narrative summary of who this character is"
}
No other text."""

_UPDATE_USER = """Character name: {name}

Existing profile:
- Traits: {traits}
- Known secrets: {secrets}
- Last known state: {state}
- Summary: {summary}

Scene #{scene_number} excerpt (relevant passages only):
{excerpt}

Update the profile JSON for {name}."""


def update_profiles_for_scene(
    provider,
    campaign_id: str,
    scene_number: int,
    scene_transcript: str,
    character_names: list[str],
    db_path: str,
    max_excerpt_chars: int = 3000,
) -> None:
    """
    Update CharacterProfiles for all named characters in a scene.

    Args:
        provider:          Any object with a .generate(prompt, *, system, temperature, max_tokens) method.
        campaign_id:       The campaign these characters belong to.
        scene_number:      Used to avoid duplicate updates on re-confirm.
        scene_transcript:  Full scene text (user + AI turns interleaved).
        character_names:   List of character names to update.
        db_path:           Path to the SQLite database.
        max_excerpt_chars: Max chars of transcript passed to the LLM.
    """
    store = CharacterProfileStore(db_path)
    excerpt = scene_transcript[:max_excerpt_chars]

    for name in character_names:
        try:
            _update_one_profile(
                provider=provider,
                store=store,
                campaign_id=campaign_id,
                character_name=name,
                scene_number=scene_number,
                excerpt=excerpt,
            )
        except Exception:
            log.exception(
                "Profile update failed for '%s' in scene %d (non-fatal)", name, scene_number
            )


def _update_one_profile(
    provider,
    store: CharacterProfileStore,
    campaign_id: str,
    character_name: str,
    scene_number: int,
    excerpt: str,
) -> None:
    """Update the profile for a single character. Non-fatal."""
    existing = store.get(campaign_id, character_name) or make_profile(campaign_id, character_name)

    # Skip if this scene was already processed for this character
    if scene_number in existing.source_scene_numbers:
        log.debug("Profile for '%s' already updated through scene %d — skipping", character_name, scene_number)
        return

    prompt = _UPDATE_USER.format(
        name=character_name,
        traits=", ".join(existing.confirmed_traits) if existing.confirmed_traits else "none recorded",
        secrets=", ".join(existing.known_secrets) if existing.known_secrets else "none recorded",
        state=existing.last_known_state or "unknown",
        summary=existing.profile_summary or "no summary yet",
        scene_number=scene_number,
        excerpt=excerpt,
    )

    raw = provider.generate(
        prompt,
        system=_UPDATE_SYSTEM,
        temperature=0.2,
        max_tokens=512,
    )

    data = _parse(raw)
    if not data:
        log.debug("Profile update for '%s': LLM returned unparseable JSON — skipping", character_name)
        return

    # Merge: keep all existing traits, add new ones de-duplicated
    old_traits_lower = {t.lower() for t in existing.confirmed_traits}
    new_traits = existing.confirmed_traits[:]
    for t in data.get("confirmed_traits", []):
        if t and t.lower() not in old_traits_lower:
            new_traits.append(str(t)[:120])

    old_secrets_lower = {s.lower() for s in existing.known_secrets}
    new_secrets = existing.known_secrets[:]
    for s in data.get("known_secrets", []):
        if s and s.lower() not in old_secrets_lower:
            new_secrets.append(str(s)[:200])

    existing.confirmed_traits = new_traits
    existing.known_secrets = new_secrets
    existing.last_known_state = str(data.get("last_known_state", existing.last_known_state))[:500]
    existing.profile_summary = str(data.get("profile_summary", existing.profile_summary))[:1000]
    existing.source_scene_numbers = sorted(set(existing.source_scene_numbers + [scene_number]))

    store.save(existing)
    log.debug(
        "Profile updated for '%s' through scene %d (%d traits, %d secrets)",
        character_name, scene_number, len(new_traits), len(new_secrets),
    )


def _parse(raw: str) -> Optional[dict]:
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
    return None
