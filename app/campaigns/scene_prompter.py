"""
Builds the message list for campaign scene play.

Unlike the session engine, campaigns use a player-authoritative world model:
the world document (facts, NPCs, places, threads, factions) is the source of truth.
No extraction happens — the player confirms what is canon.
"""

from __future__ import annotations

import re as _re
from collections import defaultdict

# Maximum chronicle entries sent to AI. When the total exceeds this, we keep
# the first CHRON_ANCHOR entries (world-setting context) and the last
# CHRON_TAIL entries (recent events). Everything in between is omitted to
# avoid flooding the context window.
_CHRON_ANCHOR = 2
_CHRON_TAIL = 6
_CHRON_THRESHOLD = _CHRON_ANCHOR + _CHRON_TAIL   # below this → send all

# Rolling scene summary: if a scene has more than this many turns, keep only
# the most recent _SCENE_TURNS_KEEP turns verbatim and add a header noting
# how many earlier exchanges occurred.
_SCENE_TURNS_THRESHOLD = 40
_SCENE_TURNS_KEEP = 30

# How many recent turns to scan for keyword-triggered world facts.
_KEYWORD_SCAN_TURNS = 8

# Strip [Turn N] / [Turn N-M] labels the summary AI adds for human review.
# They are useful during editing but waste tokens in the AI context.
_TURN_LABEL_RE = _re.compile(r"^\s*-?\s*\[Turn\s+\d+(?:[–\-]\d+)?\]\s*", _re.IGNORECASE | _re.MULTILINE)


def _compress_chronicle(text: str) -> str:
    """Remove [Turn N] prefixes from a confirmed chronicle entry before injecting into context."""
    return _TURN_LABEL_RE.sub("- ", text).strip()


def _fact_is_active(fact, recent_text: str) -> bool:
    """
    Return True if this fact should be included in the current system prompt.
    - Critical facts: always included.
    - Facts with no trigger keywords: always included (unless background priority).
    - Background facts with no triggers: excluded (only appear when triggered).
    - Facts with trigger keywords: included only if any keyword appears in recent_text.
    """
    if fact.priority == "critical":
        return True
    if not fact.trigger_keywords:
        # Background facts without triggers are too general — skip them unless
        # nothing else fires. For now: normal = always, background = skip unless triggered.
        return fact.priority != "background"
    return any(kw.lower() in recent_text for kw in fact.trigger_keywords)


def build_scene_messages(
    *,
    campaign,
    player_character,
    world_facts: list,
    npcs_in_scene: list,
    active_threads: list,
    chronicle: list = [],
    places: list = [],
    factions: list = [],
    npc_relationships: list = [],
    all_world_npcs: list = [],
    allow_unselected_npcs: bool = False,
    scene,
    user_message: str,
    user_name: str = "Player",
) -> list[dict]:
    """
    Return an Ollama-compatible messages list for one turn of scene play.

    Structure:
      [system]  — world document + chronicle + scene context
      [user/assistant alternating history from scene.turns, possibly truncated]
      [user]    — current player input
    """
    # Build recent-text for keyword matching (last N turns + current message)
    recent_turns = scene.turns[-_KEYWORD_SCAN_TURNS:] if scene else []
    recent_text = " ".join(t.content.lower() for t in recent_turns) + " " + user_message.lower()

    system = _build_system(campaign, player_character, world_facts,
                           npcs_in_scene, active_threads, chronicle,
                           places, factions, npc_relationships, scene,
                           all_world_npcs=all_world_npcs,
                           allow_unselected_npcs=allow_unselected_npcs,
                           recent_text=recent_text)

    messages: list[dict] = [{"role": "system", "content": system}]

    # ── Rolling scene summary ────────────────────────────────────────────────
    # If the scene has accumulated many turns, keep only the most recent
    # _SCENE_TURNS_KEEP verbatim and add a brief header for the rest.
    turns = scene.turns if scene else []
    if len(turns) > _SCENE_TURNS_THRESHOLD:
        omitted = len(turns) - _SCENE_TURNS_KEEP
        recent = turns[-_SCENE_TURNS_KEEP:]
        messages.append({
            "role": "system",
            "content": (
                f"[Earlier in this scene — {omitted} exchanges preceded the visible history below. "
                "Continue naturally from where the conversation picks up.]"
            ),
        })
        for turn in recent:
            messages.append({"role": turn.role, "content": turn.content})
    else:
        for turn in turns:
            messages.append({"role": turn.role, "content": turn.content})

    # Current player input
    if user_name and user_name.lower() not in ("player", "user", ""):
        messages.append({"role": "user", "content": f"[{user_name}]: {user_message}"})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


def _build_system(
    campaign,
    player_character,
    world_facts: list,
    npcs_in_scene: list,
    active_threads: list,
    chronicle: list,
    places: list,
    factions: list,
    npc_relationships: list,
    scene,
    *,
    all_world_npcs: list = [],
    allow_unselected_npcs: bool = False,
    recent_text: str = "",
) -> str:
    parts: list[str] = []

    # ── Role instruction ──────────────────────────────────────────────────────
    sg = campaign.style_guide if campaign else None
    tone = sg.tone if sg else ""
    style = sg.prose_style if sg else ""
    avoids = sg.avoids if sg else ""
    magic = sg.magic_system if sg else ""

    role_lines = [
        "You are a collaborative storytelling AI running a roleplay campaign.",
        "Your role is to play the world — narrate events, voice NPCs, describe consequences.",
        "You do NOT play the player character. Respond to what the player does.",
        "Keep responses immersive, vivid, and grounded in the world document below.",
    ]
    if style:
        role_lines.append(f"Narration style: {style}")
    if tone:
        role_lines.append(f"Tone: {tone}")
    if avoids:
        role_lines.append(f"Avoid: {avoids}")
    if not allow_unselected_npcs:
        role_lines.append(
            "Do not introduce named NPCs from the world document who are not listed in "
            "[NPCs IN THIS SCENE]. You may freely create entirely new named characters "
            "who do not exist in the world document."
        )

    parts.append("\n".join(role_lines))

    # ── World facts (priority-sorted, keyword-filtered) ───────────────────────
    fact_texts = [f for f in world_facts if f.content and _fact_is_active(f, recent_text)]
    if fact_texts:
        # Critical facts first, then normal, then background (in case any background
        # facts passed the keyword trigger check)
        priority_order = {"critical": 0, "normal": 1, "background": 2}
        fact_texts.sort(key=lambda f: priority_order.get(f.priority, 1))

        # Group by category
        grouped: dict[str, list] = defaultdict(list)
        for f in fact_texts:
            cat = (f.category or "").strip()
            grouped[cat].append(f)

        fact_block_lines = ["[WORLD FACTS]"]
        # Critical facts always at top under a CRITICAL marker
        critical = [f for f in fact_texts if f.priority == "critical"]
        if critical:
            fact_block_lines.append("  [CRITICAL — always true]")
            for f in critical:
                fact_block_lines.append(f"• {f.content}")

        # Remaining facts grouped by category
        for cat in sorted(grouped.keys(), key=lambda c: ("" if not c else c.lower())):
            cat_facts = [f for f in grouped[cat] if f.priority != "critical"]
            if not cat_facts:
                continue
            if cat:
                fact_block_lines.append(f"  [{cat.upper()}]")
            for f in cat_facts:
                fact_block_lines.append(f"• {f.content}")

        parts.append("\n".join(fact_block_lines))

    # ── Magic / technology rules ───────────────────────────────────────────────
    if magic:
        parts.append(f"[MAGIC / TECHNOLOGY]\n{magic}")

    # ── Chronicle (smart recap — anchor + recent tail, turn labels stripped) ──
    confirmed = [e for e in chronicle if e.content]
    if confirmed:
        confirmed_sorted = sorted(confirmed, key=lambda x: x.scene_range_start)
        if len(confirmed_sorted) <= _CHRON_THRESHOLD:
            recap = confirmed_sorted
        else:
            anchor = confirmed_sorted[:_CHRON_ANCHOR]
            tail = confirmed_sorted[-_CHRON_TAIL:]
            anchor_ids = {e.id for e in anchor}
            tail = [e for e in tail if e.id not in anchor_ids]
            recap = anchor + tail

        chron_lines = ["[STORY SO FAR]"]
        if len(confirmed_sorted) > _CHRON_THRESHOLD:
            skipped = len(confirmed_sorted) - len(recap)
            if skipped > 0:
                chron_lines.append(f"(earlier events summarised — {skipped} entries omitted for brevity)")
        for e in recap:
            if e.scene_range_start == e.scene_range_end:
                label = f"Scene {e.scene_range_start}"
            else:
                label = f"Scenes {e.scene_range_start}–{e.scene_range_end}"
            chron_lines.append(f"[{label}]\n{_compress_chronicle(e.content)}")
        parts.append("\n".join(chron_lines))

    # ── Player character ──────────────────────────────────────────────────────
    if player_character and player_character.name:
        pc = player_character
        pc_lines = [f"[PLAYER CHARACTER: {pc.name}]"]
        if pc.appearance:    pc_lines.append(f"Appearance: {pc.appearance}")
        if pc.personality:   pc_lines.append(f"Personality: {pc.personality}")
        if pc.background:    pc_lines.append(f"Background: {pc.background}")
        if pc.wants:         pc_lines.append(f"Wants: {pc.wants}")
        if pc.fears:         pc_lines.append(f"Fears: {pc.fears}")
        if pc.dev_log:
            recent = pc.dev_log[-3:]
            pc_lines.append("Recent development:")
            for entry in recent:
                label = f"Scene {entry.scene_number}: " if entry.scene_number else ""
                pc_lines.append(f"  • {label}{entry.note}")
        parts.append("\n".join(pc_lines))

    # ── NPCs in this scene ────────────────────────────────────────────────────
    if npcs_in_scene:
        npc_block = ["[NPCs IN THIS SCENE]"]
        pc_name = player_character.name if player_character else "player"
        for n in npcs_in_scene:
            # Resolve active form vs base form
            active_form = _get_active_form(n)

            status_str = ""
            if hasattr(n, "status") and n.status and n.status != "active":
                status_str = f" [{n.status.upper()}]"
                if hasattr(n, "status_reason") and n.status_reason:
                    status_str += f" ({n.status_reason})"

            form_label = f" [{active_form.label}]" if active_form else ""
            line = f"• {n.name}{status_str}{form_label}"
            if n.role:          line += f" ({n.role})"

            # Use active form's appearance/personality if set, else base
            appearance  = active_form.appearance  if active_form and active_form.appearance  else n.appearance
            personality = active_form.personality if active_form and active_form.personality else n.personality
            curr_state  = active_form.current_state if active_form and active_form.current_state else n.current_state

            if personality:   line += f" — {personality}"
            if curr_state:    line += f" | Currently: {curr_state}"
            npc_block.append(line)

            # If in a different form, note original identity
            if active_form:
                orig_parts = []
                if n.appearance:  orig_parts.append(f"appearance: {n.appearance}")
                if n.personality: orig_parts.append(f"personality: {n.personality}")
                if orig_parts:
                    npc_block.append(f"  Original form: {'; '.join(orig_parts)}")

            if appearance and appearance != (active_form.appearance if active_form else ""):
                pass  # already shown via personality line above

            if n.relationship_to_player:
                npc_block.append(f"  Relationship to {pc_name}: {n.relationship_to_player}")
            if hasattr(n, "history_with_player") and n.history_with_player:
                npc_block.append(f"  History: {n.history_with_player}")
            if hasattr(n, "short_term_goal") and n.short_term_goal:
                npc_block.append(f"  Immediate goal: {n.short_term_goal}")
            if hasattr(n, "long_term_goal") and n.long_term_goal:
                npc_block.append(f"  Long-term goal: {n.long_term_goal}")
            if hasattr(n, "secrets") and n.secrets:
                npc_block.append(f"  [Hidden: {n.secrets}]")
        parts.append("\n".join(npc_block))

    # ── Other world NPCs available (when flag is set) ────────────────────────
    if allow_unselected_npcs and all_world_npcs:
        scene_npc_ids = {n.id for n in npcs_in_scene}
        available = [n for n in all_world_npcs if n.id not in scene_npc_ids]
        if available:
            avail_block = [
                "[OTHER AVAILABLE NPCs]",
                "These characters exist in the world and may appear if narratively fitting:",
            ]
            for n in available:
                status_str = ""
                if hasattr(n, "status") and n.status and n.status != "active":
                    status_str = f" [{n.status.upper()}]"
                active_form = _get_active_form(n)
                form_label = f" [{active_form.label}]" if active_form else ""
                line = f"• {n.name}{status_str}{form_label}"
                if n.role:        line += f" ({n.role})"
                personality = active_form.personality if active_form and active_form.personality else n.personality
                if personality: line += f" — {personality}"
                avail_block.append(line)
            parts.append("\n".join(avail_block))

    # ── NPC-to-NPC relationships ──────────────────────────────────────────────
    if npc_relationships:
        npc_map = {n.id: n.name for n in npcs_in_scene}
        rel_lines = ["[NPC DYNAMICS]"]
        for r in npc_relationships:
            a = npc_map.get(r.npc_id_a, r.npc_id_a)
            b = npc_map.get(r.npc_id_b, r.npc_id_b)
            line = f"• {a} ↔ {b}"
            if r.dynamic:   line += f": {r.dynamic}"
            if r.trust:     line += f" | Trust: {r.trust}"
            if r.hostility: line += f" | Hostility: {r.hostility}"
            rel_lines.append(line)
            if r.history:
                rel_lines.append(f"  History: {r.history}")
        if len(rel_lines) > 1:
            parts.append("\n".join(rel_lines))

    # ── Places ────────────────────────────────────────────────────────────────
    if places:
        place_block = ["[KNOWN LOCATIONS]"]
        for p in places:
            line = f"• {p.name}"
            if p.description:   line += f" — {p.description}"
            if p.current_state: line += f" (currently: {p.current_state})"
            place_block.append(line)
        parts.append("\n".join(place_block))

    # ── Factions ──────────────────────────────────────────────────────────────
    if factions:
        faction_block = ["[FACTIONS]"]
        for f in factions:
            line = f"• {f.name}"
            if f.description: line += f" — {f.description}"
            if hasattr(f, "standing_with_player") and f.standing_with_player:
                line += f" | Standing with player: {f.standing_with_player}"
            faction_block.append(line)
            if f.goals:   faction_block.append(f"  Goals: {f.goals}")
            if f.methods: faction_block.append(f"  Methods: {f.methods}")
            if hasattr(f, "relationship_notes") and f.relationship_notes:
                faction_block.append(f"  History with player: {f.relationship_notes}")
        parts.append("\n".join(faction_block))

    # ── Active narrative threads ──────────────────────────────────────────────
    if active_threads:
        thread_block = ["[ACTIVE NARRATIVE THREADS]"]
        for t in active_threads:
            line = f"• {t.title}"
            if t.description: line += f": {t.description}"
            thread_block.append(line)
        parts.append("\n".join(thread_block))

    # ── Scene context ─────────────────────────────────────────────────────────
    if scene:
        scene_lines = ["[CURRENT SCENE]"]
        if scene.title:    scene_lines.append(f"Title: {scene.title}")
        if scene.location: scene_lines.append(f"Location: {scene.location}")
        if scene.intent:   scene_lines.append(f"Intent: {scene.intent}")
        if scene.tone:     scene_lines.append(f"Scene tone: {scene.tone}")
        scene_lines.append(f"Scene #{scene.scene_number}")
        parts.append("\n".join(scene_lines))

    return "\n\n".join(parts)


def _get_active_form(npc):
    """Return the NpcForm object for the NPC's active_form, or None if on base form."""
    if not hasattr(npc, "active_form") or not npc.active_form:
        return None
    if not hasattr(npc, "forms") or not npc.forms:
        return None
    for form in npc.forms:
        if form.label == npc.active_form:
            return form
    return None
