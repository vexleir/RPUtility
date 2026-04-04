"""
Prompt builder.
Assembles the final message list sent to the model on each turn.

Phase 2 prompt section order:
  [SYSTEM]
    1. Core roleplay instructions
    2. Character card
    3. Lorebook entries (if any matched)
    4. World-state summary (durable world facts, Phase 2)
    5. Critical facts (guaranteed placement)
    6. Episodic memories (relevant events, character details, etc.)
    7. Relationship summaries
    8. Current scene state
  [CONVERSATION HISTORY]
    9. Recent turns
  [CURRENT USER TURN]
    10. The user's latest message
"""

from __future__ import annotations

from app.core.models import (
    CharacterCard,
    LorebookEntry,
    MemoryEntry,
    ImportanceLevel,
    CertaintyLevel,
    RelationshipState,
    SceneState,
    ConversationTurn,
    WorldStateEntry,
    PlayerObjective,
    ObjectiveStatus,
    NpcEntry,
    WorldClock,
    StoryBeat,
    EmotionalState,
    InventoryItem,
    StatusEffect,
    EffectType,
    CharacterStat,
    NarrativeArc,
    Faction,
    Quest,
    QuestStatus,
    LocationEntry,
)
from app.core.config import Config


# ── Core system instructions ──────────────────────────────────────────────────

_CORE_INSTRUCTIONS = """You are an AI participating in a collaborative roleplay story.
You are playing the role described below. Follow these rules:

NARRATIVE RULES:
- Stay fully in character at all times unless asked a direct out-of-character question.
- Write in third-person past tense unless the character card specifies otherwise.
- Keep responses focused and appropriately detailed (2-4 paragraphs is typical).
- Never repeat what the user just said; advance the story forward.

MEMORY RULES:
- Treat all [MEMORY] entries as established facts about this world and story.
- Do not contradict or ignore remembered facts.
- [CRITICAL] facts must never be ignored or contradicted under any circumstances.
- Memories marked [RUMOR] or [SUSPICION] are uncertain — treat with skepticism.
- [LIE] entries are known falsehoods — a character may believe them or not.
- Weave memory naturally into the narrative; never dump lists of facts.

WORLD-STATE RULES:
- [WORLD STATE] entries describe the current condition of the world — honor them.
- If a location is described as destroyed, it remains destroyed.
- If a faction controls territory, respect that unless the story has changed it.

SCENE RULES:
- Respect the current location and active characters in [SCENE].
- If a character is not in the active character list, they are not physically present.

RELATIONSHIP RULES:
- Honor the relationship dynamics shown in [RELATIONSHIPS].
- Allow relationships to evolve naturally through the story.

CHARACTER RULES:
- Preserve the character's established personality and voice.
- Let the character have opinions, quirks, and consistent reactions.
- If a Voice Guide is provided, apply it consistently in every response.
- If a Player Character State is provided, let it colour the narrative and reactions.
- If Status Effects are active, weave their consequences naturally into the story.
- If Inventory items are listed, treat them as the character's actual possessions.
- If Character Stats are provided, reference them when describing physical or mental actions.
- If a Narrative Arc is present, let act, tension, and pacing shape the tone of the scene.
- If Faction Standings are listed, reflect those relationships in NPC attitudes and world reactions.
- If Active Quests are listed, keep them in mind and allow the story to progress them naturally."""


def _resolve_vars(text: str, char_name: str, user_name: str) -> str:
    """Replace SillyTavern-style {{char}} and {{user}} template variables."""
    import re
    text = re.sub(r"\{\{char\}\}", char_name, text, flags=re.IGNORECASE)
    text = re.sub(r"\{\{user\}\}", user_name, text, flags=re.IGNORECASE)
    return text


def build_messages(
    *,
    card: CharacterCard,
    lorebook_entries: list[LorebookEntry],
    memories: list[MemoryEntry],
    scene: SceneState | None,
    relationships: list[RelationshipState],
    history: list[ConversationTurn],
    user_message: str,
    config: Config,
    user_name: str = "Player",
    world_state: list[WorldStateEntry] | None = None,
    objectives: list[PlayerObjective] | None = None,
    npcs: list[NpcEntry] | None = None,
    clock: WorldClock | None = None,
    story_beats: list[StoryBeat] | None = None,
    emotional_state: EmotionalState | None = None,
    inventory: list[InventoryItem] | None = None,
    status_effects: list[StatusEffect] | None = None,
    stats: list[CharacterStat] | None = None,
    narrative_arc: NarrativeArc | None = None,
    factions: list[Faction] | None = None,
    quests: list[Quest] | None = None,
    location_entry: LocationEntry | None = None,
) -> list[dict]:
    """
    Build the full message list for the model.
    Returns a list of {"role": ..., "content": ...} dicts.
    """
    system_parts: list[str] = [_CORE_INSTRUCTIONS]

    # 1. Character card
    system_parts.append(_format_character_card(card, user_name=user_name))

    # 2. Lorebook entries
    if lorebook_entries:
        system_parts.append(_format_lorebook(lorebook_entries))

    # 3. World-state (Phase 2 — placed before episodic memories)
    if world_state:
        system_parts.append(_format_world_state(world_state, config))

    # 4 & 5. Memories — split critical (guaranteed) from episodic
    if memories:
        critical = [m for m in memories if m.importance == ImportanceLevel.CRITICAL]
        episodic = [m for m in memories if m.importance != ImportanceLevel.CRITICAL]

        if critical:
            system_parts.append(_format_critical_facts(critical))

        if episodic:
            if config.memory_injection_mode == "soft":
                system_parts.append(_format_memories_soft(episodic))
            else:
                system_parts.append(_format_memories_raw(episodic))

    # 6. Relationships
    if relationships:
        system_parts.append(_format_relationships(relationships))

    # 7. Scene state (placed last in system — most immediately relevant)
    if scene:
        system_parts.append(_format_scene(scene, clock, location_entry))

    # 8. Player objectives (active goals only)
    if objectives:
        active = [o for o in objectives if o.status == ObjectiveStatus.ACTIVE]
        if active:
            system_parts.append(_format_objectives(active))

    # 9. Known NPCs (alive only — suppressed if empty)
    if npcs:
        system_parts.append(_format_npcs(npcs))

    # 10. Recent story beats (key narrative moments)
    if story_beats:
        system_parts.append(_format_story_beats(story_beats))

    # 11. Inventory (what the player character is carrying)
    if inventory:
        system_parts.append(_format_inventory(inventory))

    # 12. Status effects (active conditions on the player character)
    if status_effects:
        system_parts.append(_format_status_effects(status_effects))

    # 13. Emotional state (player character's current inner condition)
    if emotional_state and (emotional_state.mood != "neutral" or emotional_state.motivation):
        system_parts.append(_format_emotional_state(emotional_state))

    # 14. Character stats (attributes/skills used for skill checks)
    if stats:
        system_parts.append(_format_stats(stats))

    # 15. Narrative arc (current act, tension, pacing)
    if narrative_arc:
        system_parts.append(_format_narrative_arc(narrative_arc))

    # 16. Faction standings
    if factions:
        system_parts.append(_format_faction_standings(factions))

    # 17. Active quests
    if quests:
        active = [q for q in quests if q.status == QuestStatus.ACTIVE]
        if active:
            system_parts.append(_format_quests(active))

    system_content = "\n\n".join(system_parts)
    messages: list[dict] = [{"role": "system", "content": system_content}]

    # 8. Conversation history (resolve any template vars left in stored turns)
    for turn in history:
        messages.append({"role": turn.role, "content": _resolve_vars(turn.content, card.name, user_name)})

    # 9. Current user message
    messages.append({"role": "user", "content": user_message})

    return messages


# ── Section formatters ────────────────────────────────────────────────────────

def _format_character_card(card: CharacterCard, user_name: str = "Player") -> str:
    rv = lambda t: _resolve_vars(t, card.name, user_name)
    parts = [f"[CHARACTER: {card.name.upper()}]"]
    if card.description:
        parts.append(f"Description: {rv(card.description)}")
    if card.personality:
        parts.append(f"Personality: {rv(card.personality)}")
    if card.scenario:
        parts.append(f"Scenario: {rv(card.scenario)}")
    if card.system_prompt:
        parts.append(f"Additional instructions: {rv(card.system_prompt)}")
    if card.example_dialogue:
        parts.append(f"Example dialogue:\n{rv(card.example_dialogue)}")
    # Phase 3 — Voice Guide (injected only when fields are present on the card)
    voice_parts: list[str] = []
    if card.voice_tone:
        voice_parts.append(f"tone: {card.voice_tone}")
    if card.speech_patterns:
        voice_parts.append(f"patterns: {card.speech_patterns}")
    if card.verbal_tics:
        voice_parts.append(f"tics: {card.verbal_tics}")
    if card.vocabulary_level:
        voice_parts.append(f"vocabulary: {card.vocabulary_level}")
    if card.accent_notes:
        voice_parts.append(f"accent: {card.accent_notes}")
    if voice_parts:
        parts.append("Voice guide — " + "; ".join(voice_parts))
    return "\n".join(parts)


def _format_lorebook(entries: list[LorebookEntry]) -> str:
    lines = ["[WORLD LORE]"]
    for entry in entries:
        lines.append(entry.content)
    return "\n\n".join(lines)


def _format_world_state(entries: list[WorldStateEntry], config: Config) -> str:
    cap = config.max_world_state_entries
    shown = entries[:cap] if cap else entries
    lines = ["[WORLD STATE — current conditions]"]
    for e in shown:
        imp = " [CRITICAL]" if e.importance == ImportanceLevel.CRITICAL else ""
        lines.append(f"  • {e.title}{imp}: {e.content}")
    return "\n".join(lines)


def _format_critical_facts(memories: list[MemoryEntry]) -> str:
    """Critical facts get their own section with explicit instruction."""
    lines = ["[CRITICAL FACTS — must never be contradicted or ignored]"]
    for m in memories:
        certainty_tag = _certainty_tag(m)
        lines.append(f"  !! {m.title}{certainty_tag}: {m.content}")
    return "\n".join(lines)


def _format_memories_raw(memories: list[MemoryEntry]) -> str:
    """Debug mode: structured list of memories."""
    lines = ["[MEMORY — established facts about this story]"]
    for m in memories:
        cert = _certainty_tag(m)
        imp = f"({m.importance.value})"
        lines.append(f"• {m.title} {imp}{cert}: {m.content}")
    return "\n".join(lines)


def _format_memories_soft(memories: list[MemoryEntry]) -> str:
    """Soft injection: grouped narrative prose."""
    groups: dict[str, list[MemoryEntry]] = {
        "event": [],
        "world_fact": [],
        "character_detail": [],
        "relationship_change": [],
        "world_state": [],
        "consolidation": [],
        "rumor": [],
        "suspicion": [],
    }
    for m in memories:
        key = m.type.value
        if key in groups:
            groups[key].append(m)
        else:
            groups.setdefault(key, []).append(m)

    sections: list[str] = ["[STORY SO FAR — what has been established]"]

    _add_group(sections, groups["event"], "Events that have occurred")
    _add_group(sections, groups["world_fact"], "Known facts about this world")
    _add_group(sections, groups["world_state"], "World conditions established")
    _add_group(sections, groups["character_detail"], "Character details established")
    _add_group(sections, groups["relationship_change"], "Relationship developments")
    _add_group(sections, groups["consolidation"], "Summary of past events")

    # Uncertain entries with explicit labels
    if groups["rumor"]:
        sections.append("Unverified rumors (treat with skepticism):")
        for m in groups["rumor"]:
            sections.append(f"  — {m.content} [confidence: {m.confidence:.0%}]")

    if groups["suspicion"]:
        sections.append("Suspicions (not confirmed):")
        for m in groups["suspicion"]:
            sections.append(f"  — {m.content} [unverified]")

    return "\n".join(sections)


def _add_group(sections: list[str], mems: list[MemoryEntry], header: str) -> None:
    if not mems:
        return
    sections.append(f"{header}:")
    for m in mems:
        tag = " [CRITICAL]" if m.importance == ImportanceLevel.CRITICAL else ""
        entities_tag = f" ({', '.join(m.entities)})" if m.entities else ""
        sections.append(f"  — {m.content}{entities_tag}{tag}")


def _certainty_tag(m: MemoryEntry) -> str:
    if m.certainty == CertaintyLevel.RUMOR:
        return " [RUMOR]"
    if m.certainty == CertaintyLevel.SUSPICION:
        return " [SUSPICION]"
    if m.certainty == CertaintyLevel.LIE:
        return " [LIE — known false]"
    if m.certainty == CertaintyLevel.MYTH:
        return " [MYTH]"
    return ""


def _format_scene(scene: SceneState, clock: WorldClock | None = None, location_entry: LocationEntry | None = None) -> str:
    chars = ", ".join(scene.active_characters) if scene.active_characters else "None specified"
    lines = [
        "[SCENE]",
        f"Location: {scene.location}",
    ]
    if location_entry:
        if location_entry.description:
            lines.append(f"Location description: {location_entry.description}")
        if location_entry.atmosphere:
            lines.append(f"Atmosphere: {location_entry.atmosphere}")
    if clock:
        lines.append(f"Time: {clock.display()}")
    lines.append(f"Present characters: {chars}")
    if scene.summary:
        lines.append(f"Scene summary: {scene.summary}")
    return "\n".join(lines)


def _format_npcs(npcs: list[NpcEntry]) -> str:
    lines = ["[KNOWN NPCs — characters the player character has encountered]"]
    for npc in npcs[:15]:  # cap at 15 to avoid token bloat
        role_part = f" ({npc.role})" if npc.role else ""
        loc_part = f" — last seen: {npc.last_known_location}" if npc.last_known_location else ""
        desc_part = f": {npc.description}" if npc.description else ""
        personality_part = f" [{npc.personality_notes}]" if npc.personality_notes else ""
        lines.append(f"  • {npc.name}{role_part}{desc_part}{personality_part}{loc_part}")
    return "\n".join(lines)


def _format_story_beats(beats: list[StoryBeat]) -> str:
    lines = ["[KEY STORY MOMENTS — significant events that have shaped the narrative]"]
    for beat in beats:
        imp = " [CRITICAL]" if beat.importance.value == "critical" else ""
        desc_part = f" — {beat.description}" if beat.description else ""
        lines.append(f"  • [{beat.beat_type.value.upper()}]{imp} {beat.title}{desc_part}")
    return "\n".join(lines)


def _format_relationships(rels: list[RelationshipState]) -> str:
    lines = ["[RELATIONSHIPS]"]
    for r in rels:
        summary = derive_relationship_summary(r)
        axes = _describe_axes(r)
        if axes:
            lines.append(f"  {r.source_entity} → {r.target_entity}: {summary} ({axes})")
        elif summary != "neutral":
            lines.append(f"  {r.source_entity} → {r.target_entity}: {summary}")
    return "\n".join(lines) if len(lines) > 1 else ""


def derive_relationship_summary(r: RelationshipState) -> str:
    """
    Derive a named relationship state from numeric axes.
    Phase 2: richer vocabulary beyond simple axis descriptions.
    """
    # Dominant-signal classification
    if r.hostility > 0.6 and r.trust < -0.3:
        return "enemy"
    if r.hostility > 0.4 and r.affection < 0:
        return "hostile"
    if r.trust > 0.6 and r.affection > 0.4:
        return "close ally"
    if r.trust > 0.5 and r.respect > 0.4:
        return "loyal"
    if r.trust > 0.3 and r.affection > 0.3:
        return "ally"
    if r.affection > 0.5:
        return "affectionate"
    if r.fear > 0.5 and r.trust < 0:
        return "fearful"
    if r.fear > 0.3:
        return "wary"
    if r.trust < -0.4:
        return "suspicious"
    if r.trust < -0.6:
        return "deeply distrustful"
    if r.respect > 0.4 and abs(r.affection) < 0.2:
        return "respectful rival" if r.hostility > 0.2 else "respectful"
    if r.hostility > 0.2:
        return "unfriendly"
    return "neutral"


def _describe_axes(r: RelationshipState) -> str:
    """Concise axis description for supplementary detail."""
    parts = []
    if r.trust > 0.2:
        parts.append(f"trust {r.trust:+.2f}")
    elif r.trust < -0.2:
        parts.append(f"trust {r.trust:+.2f}")
    if r.affection > 0.2 or r.affection < -0.2:
        parts.append(f"affection {r.affection:+.2f}")
    if r.fear > 0.2:
        parts.append(f"fear {r.fear:.2f}")
    if r.hostility > 0.2:
        parts.append(f"hostility {r.hostility:.2f}")
    if r.respect > 0.2 or r.respect < -0.2:
        parts.append(f"respect {r.respect:+.2f}")
    return ", ".join(parts)


def _format_objectives(objectives: list[PlayerObjective]) -> str:
    lines = ["[PLAYER GOALS — the player character is pursuing these objectives]"]
    for o in objectives:
        desc = f" — {o.description}" if o.description else ""
        lines.append(f"  • {o.title}{desc}")
    return "\n".join(lines)


def _format_inventory(items: list[InventoryItem]) -> str:
    lines = ["[INVENTORY — items the player character is carrying]"]
    for item in items:
        equipped = " (equipped)" if item.is_equipped else ""
        qty = f" ×{item.quantity}" if item.quantity > 1 else ""
        cond = f" [{item.condition}]" if item.condition and item.condition != "good" else ""
        desc = f" — {item.description}" if item.description else ""
        lines.append(f"  • {item.name}{equipped}{qty}{cond}{desc}")
    return "\n".join(lines)


def _format_status_effects(effects: list[StatusEffect]) -> str:
    _icon = {
        EffectType.BUFF: "✦",
        EffectType.DEBUFF: "✖",
        EffectType.NEUTRAL: "◆",
    }
    lines = ["[STATUS EFFECTS — active conditions on the player character]"]
    for e in effects:
        icon = _icon.get(e.effect_type, "◆")
        dur = f" ({e.duration_turns} turns remaining)" if e.duration_turns > 0 else ""
        desc = f" — {e.description}" if e.description else ""
        lines.append(f"  {icon} {e.name} ({e.effect_type.value}, {e.severity}){dur}{desc}")
    return "\n".join(lines)


def _format_emotional_state(state: EmotionalState) -> str:
    lines = [
        "[PLAYER CHARACTER STATE]",
        f"  Mood: {state.mood}",
        f"  Stress: {state.stress_label} ({state.stress:.0%})",
    ]
    if state.motivation:
        lines.append(f"  Motivation: {state.motivation}")
    if state.notes:
        lines.append(f"  Note: {state.notes}")
    return "\n".join(lines)


def _format_stats(stats: list[CharacterStat]) -> str:
    # Group by category
    groups: dict[str, list[CharacterStat]] = {}
    for s in stats:
        groups.setdefault(s.category, []).append(s)
    lines = ["[CHARACTER STATS]"]
    for category, group in sorted(groups.items()):
        cat_label = category.title()
        stat_parts = []
        for s in sorted(group, key=lambda x: x.name):
            mod = s.effective_modifier
            mod_str = f" ({mod:+d})" if mod != 0 else ""
            stat_parts.append(f"{s.name} {s.value}{mod_str}")
        lines.append(f"  {cat_label}: {', '.join(stat_parts)}")
    return "\n".join(lines)


def _format_narrative_arc(arc: NarrativeArc) -> str:
    lines = [
        "[NARRATIVE ARC]",
        f"  Act {arc.current_act}: {arc.act_label}",
        f"  Tension: {arc.tension_label} ({arc.tension:.0%})",
        f"  Pacing: {arc.pacing}",
    ]
    if arc.themes:
        lines.append(f"  Themes: {', '.join(arc.themes)}")
    if arc.arc_notes:
        lines.append(f"  Notes: {arc.arc_notes}")
    return "\n".join(lines)


def _format_quests(quests: list[Quest]) -> str:
    lines = ["[ACTIVE QUESTS — objectives the player character is currently pursuing]"]
    for q in quests:
        imp = " [CRITICAL]" if q.importance.value == "critical" else ""
        giver = f" (from: {q.giver_npc_name})" if q.giver_npc_name else ""
        progress = f" [{q.progress_label}]" if q.stages else ""
        desc = f" — {q.description}" if q.description else ""
        lines.append(f"  • {q.title}{imp}{giver}{progress}{desc}")
        for stage in sorted(q.stages, key=lambda s: s.order):
            check = "✓" if stage.completed else "○"
            lines.append(f"      {check} {stage.description}")
        if q.reward_notes:
            lines.append(f"      Reward: {q.reward_notes}")
    return "\n".join(lines)


def _format_faction_standings(factions: list[Faction]) -> str:
    lines = ["[FACTION STANDINGS — player character's relationship with major groups]"]
    for f in factions:
        align = f" ({f.alignment})" if f.alignment else ""
        lines.append(f"  • {f.name}{align}: {f.standing_label} ({f.standing:+.2f})")
    return "\n".join(lines)


def format_prompt_debug(messages: list[dict]) -> str:
    """Pretty-print the full message list for developer inspection."""
    lines = ["=" * 60, "FULL PROMPT (debug view)", "=" * 60]
    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        lines.append(f"\n[{role}]\n{content}")
    lines.append("=" * 60)
    return "\n".join(lines)
