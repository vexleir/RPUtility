"""
Core data models for the RP Utility engine.
All persistent structures are defined here using Pydantic v2.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────

class MemoryType(str, Enum):
    EVENT = "event"
    WORLD_FACT = "world_fact"
    CHARACTER_DETAIL = "character_detail"
    RELATIONSHIP_CHANGE = "relationship_change"
    RUMOR = "rumor"
    # Phase 2 additions
    WORLD_STATE = "world_state"       # durable faction/political/environmental facts
    SUSPICION = "suspicion"           # player or character suspicion not yet confirmed
    CONSOLIDATION = "consolidation"   # merged summary of multiple older memories


class CertaintyLevel(str, Enum):
    """How certain is this memory? Replaces boolean rumor flag with a spectrum."""
    CONFIRMED = "confirmed"     # treated as fact
    RUMOR = "rumor"             # uncertain, heard second-hand
    SUSPICION = "suspicion"     # gut feeling, not verified
    LIE = "lie"                 # known to be false (still worth tracking)
    MYTH = "myth"               # legendary/ancient, may be distorted


class ImportanceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─────────────────────────────────────────────
# Memory
# ─────────────────────────────────────────────

class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: MemoryType
    title: str
    content: str
    entities: list[str] = Field(default_factory=list)   # character names, place names
    location: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    importance: ImportanceLevel = ImportanceLevel.MEDIUM
    last_referenced_at: Optional[datetime] = None
    source_turn_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0   # 0.0–1.0; lower for rumors
    # Phase 2 additions — backward compatible (all Optional with safe defaults)
    certainty: CertaintyLevel = CertaintyLevel.CONFIRMED
    consolidated_from: list[str] = Field(default_factory=list)  # source memory IDs
    contradiction_of: Optional[str] = None   # ID of memory this contradicts
    archived: bool = False   # soft-deleted by consolidation; kept for debug


class WorldStateEntry(BaseModel):
    """Durable world-state facts derived from memory — separate from lorebooks."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: str       # e.g. "faction", "political", "environment", "secret"
    title: str
    content: str
    entities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    importance: ImportanceLevel = ImportanceLevel.HIGH
    source_memory_ids: list[str] = Field(default_factory=list)


class ContradictonFlag(BaseModel):
    """Record of a detected contradiction between new and existing memory."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    new_memory_id: str
    existing_memory_id: str
    description: str
    resolution: str = "mark_uncertain"   # what action was taken


# ─────────────────────────────────────────────
# Scene
# ─────────────────────────────────────────────

class SceneState(BaseModel):
    session_id: str
    location: str = "Unknown"
    active_characters: list[str] = Field(default_factory=list)
    summary: str = ""
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Relationships
# ─────────────────────────────────────────────

class RelationshipState(BaseModel):
    session_id: str
    source_entity: str   # who holds this feeling
    target_entity: str   # who is it directed at
    trust: float = 0.0       # -1.0 to 1.0
    fear: float = 0.0        # 0.0 to 1.0
    respect: float = 0.0     # -1.0 to 1.0
    affection: float = 0.0   # -1.0 to 1.0
    hostility: float = 0.0   # 0.0 to 1.0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Character Card
# ─────────────────────────────────────────────

class CharacterCard(BaseModel):
    """Parsed SillyTavern-compatible character card."""
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_message: str = ""
    example_dialogue: str = ""
    # Optional fields sometimes present in ST cards
    creator_notes: str = ""
    system_prompt: str = ""
    tags: list[str] = Field(default_factory=list)
    # Phase 3 — Voice Guide fields (optional; enriches character portrayal)
    voice_tone: str = ""              # "gravelly", "melodic", "clipped", "soft"
    speech_patterns: str = ""        # "uses archaic thee/thy", "short declarative sentences"
    verbal_tics: str = ""            # "ends with 'aye?'", "trails off when nervous"
    vocabulary_level: str = ""       # "sophisticated", "simple", "street slang", "archaic"
    accent_notes: str = ""           # "faint northern brogue", "clipped aristocratic"


# ─────────────────────────────────────────────
# Lorebook
# ─────────────────────────────────────────────

class LorebookEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    keys: list[str]        # keywords/phrases that trigger this entry
    content: str           # the lore text to inject
    enabled: bool = True
    priority: int = 0      # higher = injected first when multiple match
    comment: str = ""      # human-readable note


class Lorebook(BaseModel):
    name: str
    description: str = ""
    entries: list[LorebookEntry] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Conversation
# ─────────────────────────────────────────────

class ConversationTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    turn_number: int
    role: str            # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────

class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    character_name: str
    lorebook_name: Optional[str] = None
    model_name: Optional[str] = None   # overrides config model when set
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_active: datetime = Field(default_factory=lambda: datetime.now(UTC))
    turn_count: int = 0
    scenario_text: Optional[str] = None  # set when session created via Scenario Mode


# ─────────────────────────────────────────────
# Player Objectives  (Phase 3 — 1.2)
# ─────────────────────────────────────────────

class ObjectiveStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class PlayerObjective(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    description: str = ""
    status: ObjectiveStatus = ObjectiveStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Bookmarks  (Phase 1 — 1.5)
# ─────────────────────────────────────────────

class Bookmark(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    turn_id: str
    turn_number: int
    role: str
    content_preview: str = ""   # first 200 chars of turn content
    note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# NPC Roster  (Phase 2)
# ─────────────────────────────────────────────

class NpcEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    role: str = ""                    # e.g. "blacksmith", "guard captain"
    description: str = ""
    personality_notes: str = ""
    last_known_location: str = ""
    is_alive: bool = True
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Location Registry  (Phase 2)
# ─────────────────────────────────────────────

class LocationEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    description: str = ""
    atmosphere: str = ""              # "dark and gloomy", "bustling marketplace"
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    visit_count: int = 0
    first_visited: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_visited: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# In-World Clock  (Phase 2)
# ─────────────────────────────────────────────

class WorldClock(BaseModel):
    session_id: str                   # primary key — one clock per session
    year: int = 1
    month: int = 1
    day: int = 1
    hour: int = 12                    # 0–23
    era_label: str = ""               # "Third Age", "Year of the Dragon", etc.
    notes: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def time_of_day(self) -> str:
        if self.hour < 5:
            return "night"
        elif self.hour < 8:
            return "dawn"
        elif self.hour < 12:
            return "morning"
        elif self.hour < 14:
            return "midday"
        elif self.hour < 17:
            return "afternoon"
        elif self.hour < 20:
            return "evening"
        else:
            return "night"

    def display(self) -> str:
        era = f" ({self.era_label})" if self.era_label else ""
        return f"Day {self.day}, Month {self.month}, Year {self.year}{era} — {self.time_of_day}"


# ─────────────────────────────────────────────
# Story Beats  (Phase 2)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Emotional State  (Phase 3)
# ─────────────────────────────────────────────

class EmotionalState(BaseModel):
    session_id: str                   # primary key — one state per session
    mood: str = "neutral"             # free-text: "anxious", "hopeful", "grieving"
    stress: float = 0.0               # 0.0 (calm) → 1.0 (breaking point)
    motivation: str = ""              # what's driving the character right now
    notes: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def stress_label(self) -> str:
        if self.stress < 0.2:
            return "calm"
        elif self.stress < 0.4:
            return "uneasy"
        elif self.stress < 0.6:
            return "stressed"
        elif self.stress < 0.8:
            return "overwhelmed"
        else:
            return "breaking point"


# ─────────────────────────────────────────────
# Inventory  (Phase 3)
# ─────────────────────────────────────────────

class InventoryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    description: str = ""
    condition: str = "good"           # pristine / good / worn / damaged / broken
    quantity: int = 1
    tags: list[str] = Field(default_factory=list)
    is_equipped: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Status Effects  (Phase 3)
# ─────────────────────────────────────────────

class EffectType(str, Enum):
    BUFF = "buff"
    DEBUFF = "debuff"
    NEUTRAL = "neutral"


class StatusEffect(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    description: str = ""
    effect_type: EffectType = EffectType.NEUTRAL
    severity: str = "mild"            # mild / moderate / severe
    duration_turns: int = 0           # 0 = permanent until manually removed
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Character Stats & Skill Checks  (Phase 4)
# ─────────────────────────────────────────────

class CheckOutcome(str, Enum):
    CRITICAL_SUCCESS = "critical_success"
    SUCCESS = "success"
    FAILURE = "failure"
    CRITICAL_FAILURE = "critical_failure"


class CharacterStat(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str                       # "Strength", "Persuasion", "Stealth"
    value: int = 10                 # raw stat value
    modifier: int = 0               # manual override; 0 = use derived
    category: str = "attribute"     # "attribute", "skill", "saving_throw", "custom"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def effective_modifier(self) -> int:
        """If modifier is 0, derive D&D-style: (value-10)//2. Otherwise use stored value."""
        return self.modifier if self.modifier != 0 else (self.value - 10) // 2


class SkillCheckResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    stat_name: str                  # which stat was checked
    roll: int                       # raw dice result
    modifier: int                   # modifier applied
    total: int                      # roll + modifier
    difficulty: int                 # target number (DC)
    outcome: CheckOutcome
    narrative_context: str = ""     # what the check was for
    turn_number: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Narrative Arc  (Phase 4)
# ─────────────────────────────────────────────

class NarrativeArc(BaseModel):
    session_id: str                 # primary key — one arc per session
    current_act: int = 1            # 1–5
    act_label: str = "Opening"      # "Opening", "Rising Action", "Climax", etc.
    tension: float = 0.0            # 0.0 (peaceful) → 1.0 (crisis)
    pacing: str = "building"        # "slow", "building", "intense", "climactic", "falling"
    themes: list[str] = Field(default_factory=list)
    arc_notes: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def tension_label(self) -> str:
        if self.tension < 0.2:
            return "peaceful"
        elif self.tension < 0.4:
            return "tense"
        elif self.tension < 0.6:
            return "dramatic"
        elif self.tension < 0.8:
            return "intense"
        else:
            return "crisis"


# ─────────────────────────────────────────────
# Factions  (Phase 4)
# ─────────────────────────────────────────────

class Faction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    name: str
    description: str = ""
    alignment: str = ""             # free-text: "lawful good", "chaotic neutral", etc.
    standing: float = 0.0           # -1.0 (enemy) → 1.0 (allied); player's standing
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def standing_label(self) -> str:
        if self.standing >= 0.7:
            return "allied"
        elif self.standing >= 0.3:
            return "friendly"
        elif self.standing >= -0.2:
            return "neutral"
        elif self.standing >= -0.5:
            return "unfriendly"
        else:
            return "hostile"


class BeatType(str, Enum):
    INTRODUCTION = "introduction"
    REVELATION = "revelation"
    CLIMAX = "climax"
    RESOLUTION = "resolution"
    TWIST = "twist"
    ENCOUNTER = "encounter"
    MILESTONE = "milestone"
    TRAGEDY = "tragedy"


class StoryBeat(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    description: str = ""
    beat_type: BeatType = BeatType.MILESTONE
    turn_number: int = 0
    importance: ImportanceLevel = ImportanceLevel.MEDIUM
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Phase 5 — Quest Log, Journal, Lore Notes
# ─────────────────────────────────────────────

class QuestStatus(str, Enum):
    HIDDEN = "hidden"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class QuestStage(BaseModel):
    """Embedded sub-task within a quest (stored as JSON in the DB)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    completed: bool = False
    order: int = 0


class Quest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    description: str = ""
    status: QuestStatus = QuestStatus.ACTIVE
    giver_npc_name: str = ""
    location_name: str = ""
    reward_notes: str = ""
    importance: ImportanceLevel = ImportanceLevel.MEDIUM
    stages: list[QuestStage] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def stages_done(self) -> int:
        return sum(1 for s in self.stages if s.completed)

    @property
    def progress_label(self) -> str:
        if not self.stages:
            return ""
        return f"{self.stages_done}/{len(self.stages)} stages"


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    content: str
    turn_number: int = 0
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LoreNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    title: str
    content: str
    category: str = "general"   # history, magic, faction, character, location, etc.
    source: str = ""             # who told the player / where it was discovered
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────
# Campaign System (new architecture)
# ─────────────────────────────────────────────

class StyleGuide(BaseModel):
    """AI narration style preferences for a campaign."""
    prose_style: str = "atmospheric"   # terse / atmospheric / literary / pulpy
    perspective: str = "third_past"    # third_past / second_present
    tone: str = "dark"                 # dark / grounded / mythic / hopeful / gritty
    avoids: str = ""                   # free text: what the AI should NOT do
    magic_system: str = ""             # world magic / technology rules fed to AI


class GenSettings(BaseModel):
    """Per-campaign AI generation parameters."""
    temperature: float = 0.80
    top_p: float = 0.95
    top_k: int = 0
    min_p: float = 0.05
    repeat_penalty: float = 1.10
    max_tokens: int = 1024
    seed: int = -1
    context_window: int = 32768


class Campaign(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    model_name: Optional[str] = None
    summary_model_name: Optional[str] = None  # separate model for scene summary extraction
    style_guide: StyleGuide = Field(default_factory=StyleGuide)
    gen_settings: GenSettings = Field(default_factory=GenSettings)
    notes: str = ""                    # player scratchpad — never sent to AI
    cover_image: Optional[str] = None  # base64 data URL set via image generation
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PcDevEntry(BaseModel):
    """A timestamped note in the player character's development log."""
    scene_number: int = 0
    note: str


class PlayerCharacter(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    name: str = "The Player"
    appearance: str = ""
    personality: str = ""
    background: str = ""
    wants: str = ""
    fears: str = ""
    how_seen: str = ""
    dev_log: list[PcDevEntry] = Field(default_factory=list)  # Phase 4
    portrait_image: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CampaignWorldFact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    content: str
    category: str = ""                 # e.g. "history", "geography", "politics", "magic"
    priority: str = "normal"           # "critical" | "normal" | "background"
    trigger_keywords: list[str] = Field(default_factory=list)  # inject only when these words appear in recent turns
    fact_order: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CampaignPlace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    name: str
    description: str = ""
    current_state: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NpcStatus(str, Enum):
    ACTIVE      = "active"
    FLED        = "fled"
    IMPRISONED  = "imprisoned"
    TRANSFORMED = "transformed"
    DEAD        = "dead"


class NpcDevEntry(BaseModel):
    """A timestamped note in an NPC's development log."""
    scene_number: int = 0
    note: str


class NpcForm(BaseModel):
    """A distinct form or state an NPC can take (e.g. wolf form, corrupted version, disguise)."""
    label: str                           # "Wolf Form", "Corrupted", "Disguise as Merchant"
    appearance: str = ""
    personality: str = ""
    current_state: str = ""
    scene_introduced: Optional[int] = None  # scene number when this form first appeared


class NpcCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    name: str
    appearance: str = ""
    personality: str = ""
    role: str = ""
    gender: str = ""
    age: str = ""
    relationship_to_player: str = ""
    current_location: str = ""
    current_state: str = ""
    # Phase 4 additions
    status: NpcStatus = NpcStatus.ACTIVE
    status_reason: str = ""          # why they fled/died/etc.
    secrets: str = ""                # hidden knowledge — sent to AI, not shown in UI
    short_term_goal: str = ""        # immediate motivation
    long_term_goal: str = ""         # deeper ambition
    history_with_player: str = ""    # accumulated relationship history across scenes
    forms: list[NpcForm] = Field(default_factory=list)   # alternate forms/transformations
    active_form: Optional[str] = None   # label of currently active form; None = base form
    dev_log: list[NpcDevEntry] = Field(default_factory=list)
    portrait_image: Optional[str] = None   # base64 data URL set via image generation
    # Legacy compat — computed from status
    @property
    def is_alive(self) -> bool:
        return self.status != NpcStatus.DEAD
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NpcRelationship(BaseModel):
    """Relationship between two NPCs in a campaign."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    npc_id_a: str
    npc_id_b: str
    dynamic: str = ""        # e.g. "allies", "rivals", "old friends", "master/servant"
    trust: str = ""          # free-text descriptor: "high", "none", "broken"
    hostility: str = ""      # free-text: "none", "simmering", "open hatred"
    history: str = ""        # brief backstory of their relationship
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ThreadStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    RESOLVED = "resolved"


class NarrativeThread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    title: str
    description: str = ""
    status: ThreadStatus = ThreadStatus.ACTIVE
    resolution: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SceneTurn(BaseModel):
    role: str          # "player" or "narrator"
    content: str


class CampaignScene(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    scene_number: int
    title: str = ""
    location: str = ""
    npc_ids: list[str] = Field(default_factory=list)
    intent: str = ""
    tone: str = ""
    turns: list[SceneTurn] = Field(default_factory=list)
    proposed_summary: str = ""
    confirmed_summary: str = ""
    confirmed: bool = False
    allow_unselected_npcs: bool = False   # AI may incorporate world NPCs not added to scene
    scene_image: Optional[str] = None     # base64 data URL set via image generation
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChronicleEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    scene_range_start: int = 0
    scene_range_end: int = 0
    content: str = ""
    confirmed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CampaignFaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    name: str
    description: str = ""
    goals: str = ""
    methods: str = ""
    standing_with_player: str = ""   # Phase 4: e.g. "hostile", "neutral", "allied"
    relationship_notes: str = ""     # Phase 4: free-text history with the player
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorldBuildResult(BaseModel):
    """Structured output from the AI world builder."""
    premise: str = ""
    world_facts: list[str] = Field(default_factory=list)
    magic_system: str = ""
    factions: list[dict] = Field(default_factory=list)
    player_character: dict = Field(default_factory=dict)
    places: list[dict] = Field(default_factory=list)
    npcs: list[dict] = Field(default_factory=list)
    narrative_threads: list[dict] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
