"""
Core roleplay engine.
Coordinates all subsystems: providers, cards, lorebooks, memory, scene,
relationships, sessions, prompting, world-state, consolidation, contradiction.

Phase 2 additions:
  - WorldStateStore wired in
  - Contradiction detection in memory extraction pipeline
  - Memory consolidation triggered after extraction when threshold reached
  - Retriever uses config-driven scoring weights and per-type caps
  - Recently-used memory IDs passed to retriever to reduce repetition
  - build_messages receives world_state entries
  - Debug score breakdown via config.debug_memory_scoring
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, UTC
from typing import Optional, Generator

from app.core.config import Config
from app.core.database import ensure_db
from app.core.models import (
    CharacterCard,
    Lorebook,
    ConversationTurn,
    Session,
    SceneState,
)

from app.providers.factory import build_provider, build_extraction_provider
from app.cards.loader import load_card_from_file, load_all_cards
from app.lorebooks.loader import load_lorebook_from_file, load_all_lorebooks
from app.lorebooks.retriever import retrieve_entries
from app.memory.store import MemoryStore
from app.memory.world_state import WorldStateStore
from app.memory.extractor import extract_memories
from app.memory.retriever import retrieve as retrieve_memories
from app.memory.contradiction import check_contradictions
from app.memory.consolidator import consolidate_memories
from app.scene.state import SceneManager
from app.relationships.tracker import RelationshipTracker
from app.relationships.extractor import extract_relationship_deltas
from app.scene.extractor import extract_scene_update
from app.sessions.manager import SessionManager
from app.sessions.objectives import ObjectivesStore
from app.sessions.aliases import CharacterAliasStore
from app.sessions.bookmarks import BookmarkStore
from app.sessions.npc_roster import NpcRosterStore
from app.sessions.location_registry import LocationRegistryStore
from app.sessions.world_clock import WorldClockStore
from app.sessions.story_beats import StoryBeatStore
from app.sessions.emotional_state import EmotionalStateStore
from app.sessions.inventory import InventoryStore
from app.sessions.status_effects import StatusEffectStore
from app.sessions.npc_extractor import extract_npcs
from app.sessions.recap import generate_recap
from app.sessions.stats import CharacterStatStore
from app.sessions.skill_checks import SkillCheckStore, perform_check
from app.sessions.narrative_arc import NarrativeArcStore
from app.sessions.factions import FactionStore
from app.sessions.quests import QuestStore
from app.sessions.journal import JournalStore
from app.sessions.lore_notes import LoreNoteStore
from app.prompting.builder import build_messages, format_prompt_debug

log = logging.getLogger("rp_utility")


def _is_duplicate_title(title: str, existing_titles: set[str]) -> bool:
    """Return True if title shares ≥80% of its words with any existing title."""
    words = set(title.lower().split())
    if not words:
        return False
    for existing in existing_titles:
        existing_words = set(existing.split())
        if not existing_words:
            continue
        overlap = len(words & existing_words) / max(len(words), len(existing_words))
        if overlap >= 0.8:
            return True
    return False


class RoleplayEngine:
    """
    The main engine. Instantiate once and reuse across turns.
    All state is persisted to SQLite; the engine itself is stateless.
    """

    def __init__(self, config: Config):
        self.config = config

        ensure_db(config.db_path)

        self.provider = build_provider(config)
        self.extraction_provider = build_extraction_provider(config)

        self.sessions = SessionManager(config.db_path)
        self.memory_store = MemoryStore(config.db_path)
        self.world_state_store = WorldStateStore(config.db_path)
        self.scene_mgr = SceneManager(config.db_path)
        self.rel_tracker = RelationshipTracker(config.db_path)

        self.alias_store = CharacterAliasStore(config.db_path)
        self.objectives_store = ObjectivesStore(config.db_path)
        self.bookmark_store = BookmarkStore(config.db_path)
        self.npc_store = NpcRosterStore(config.db_path)
        self.location_store = LocationRegistryStore(config.db_path)
        self.clock_store = WorldClockStore(config.db_path)
        self.beat_store = StoryBeatStore(config.db_path)
        self.emotional_state_store = EmotionalStateStore(config.db_path)
        self.inventory_store = InventoryStore(config.db_path)
        self.status_effect_store = StatusEffectStore(config.db_path)
        self.stat_store = CharacterStatStore(config.db_path)
        self.skill_check_store = SkillCheckStore(config.db_path)
        self.narrative_arc_store = NarrativeArcStore(config.db_path)
        self.faction_store = FactionStore(config.db_path)
        self.quest_store = QuestStore(config.db_path)
        self.journal_store = JournalStore(config.db_path)
        self.lore_note_store = LoreNoteStore(config.db_path)

        self._cards: dict[str, CharacterCard] = {}
        self._lorebooks: dict[str, Lorebook] = {}

        # Per-session extraction locks — prevent concurrent background threads
        # from the same session racing to write memories/relationships/scene state.
        self._extraction_locks: dict[str, threading.Lock] = {}

        self._reload_assets()

    def _reload_assets(self) -> None:
        self._card_images: dict = {}
        try:
            self._cards = load_all_cards(self.config.cards_dir, image_map=self._card_images)
        except Exception:
            self._cards = {}
        try:
            self._lorebooks = load_all_lorebooks(self.config.lorebooks_dir)
        except Exception:
            self._lorebooks = {}

    def reload_assets(self) -> dict:
        """Reload all cards and lorebooks from disk. Returns counts."""
        self._reload_assets()
        return {"cards": len(self._cards), "lorebooks": len(self._lorebooks)}

    # ── Session management ────────────────────────────────────────────────

    def list_available_models(self) -> list[dict]:
        return self.provider.list_models()

    def new_session(
        self,
        name: str,
        character_name: str,
        lorebook_name: Optional[str] = None,
        initial_location: str = "Unknown",
        initial_characters: Optional[list[str]] = None,
        model_name: Optional[str] = None,
        scenario_text: Optional[str] = None,
    ) -> Session:
        session = self.sessions.create(name, character_name, lorebook_name, model_name,
                                       scenario_text=scenario_text)
        chars = initial_characters or [character_name]
        self.scene_mgr.update(
            session.id,
            location=initial_location,
            active_characters=chars,
        )
        # Register the starting location immediately
        if initial_location and initial_location.strip() and initial_location.lower() != "unknown":
            self.location_store.record_visit(session.id, initial_location.strip())
        if self.config.debug:
            log.debug("Created session %s '%s'", session.id[:8], name)
        return session

    def load_session(self, session_id: str) -> Optional[Session]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return self.sessions.list_all()

    def delete_session(self, session_id: str) -> None:
        self.sessions.delete(session_id)
        self.world_state_store.delete_session(session_id)
        self.objectives_store.delete_session(session_id)
        self.bookmark_store.delete_session(session_id)
        self.npc_store.delete_session(session_id)
        self.location_store.delete_session(session_id)
        self.clock_store.delete_session(session_id)
        self.beat_store.delete_session(session_id)
        self.emotional_state_store.delete_session(session_id)
        self.inventory_store.delete_session(session_id)
        self.status_effect_store.delete_session(session_id)
        self.stat_store.delete_session(session_id)
        self.skill_check_store.delete_session(session_id)
        self.narrative_arc_store.delete_session(session_id)
        self.faction_store.delete_session(session_id)
        self.quest_store.delete_session(session_id)
        self.journal_store.delete_session(session_id)
        self.lore_note_store.delete_session(session_id)

    # ── Asset loading ─────────────────────────────────────────────────────

    def load_card(self, path: str) -> CharacterCard:
        card = load_card_from_file(path)
        self._cards[card.name] = card
        return card

    def load_lorebook(self, path: str) -> Lorebook:
        book = load_lorebook_from_file(path)
        self._lorebooks[book.name] = book
        return book

    def get_card(self, name: str) -> Optional[CharacterCard]:
        return self._cards.get(name)

    def get_lorebook(self, name: str) -> Optional[Lorebook]:
        return self._lorebooks.get(name)

    def list_cards(self) -> list[str]:
        return list(self._cards.keys())

    def list_lorebooks(self) -> list[str]:
        return list(self._lorebooks.keys())

    # ── Context gathering (shared by chat / chat_stream) ──────────────────

    def _gather_context(self, session: Session, user_message: str):
        """Gather all context needed to build the prompt. Returns a dict."""
        session_id = session.id
        lorebook_entries = self._get_lorebook_entries(session, user_message)
        scene = self.scene_mgr.get(session_id)
        recent_text = self._recent_text(session_id, n=6)

        # Active memories (excludes archived)
        all_memories = self.memory_store.get_active(session_id)

        # Recently-used IDs for repetition reduction
        recently_used = {
            m.id for m in all_memories if m.last_referenced_at is not None
        }

        relevant_memories = retrieve_memories(
            all_memories,
            scene,
            recent_text=recent_text + " " + user_message,
            max_results=self.config.max_retrieved_memories,
            weight_importance=self.config.retrieval_weight_importance,
            weight_entity=self.config.retrieval_weight_entity,
            weight_keyword=self.config.retrieval_weight_keyword,
            weight_recency=self.config.retrieval_weight_recency,
            weight_reference=self.config.retrieval_weight_reference,
            recency_half_life=self.config.retrieval_recency_half_life_days,
            reference_half_life=self.config.retrieval_reference_half_life_days,
            type_caps={
                "event": self.config.max_memories_event,
                "world_fact": self.config.max_memories_world_fact,
                "character_detail": self.config.max_memories_character_detail,
                "relationship_change": self.config.max_memories_relationship_change,
                "world_state": self.config.max_memories_world_state,
                "rumor": self.config.max_memories_rumor,
                "suspicion": self.config.max_memories_suspicion,
            },
            recently_used_ids=recently_used,
            debug=self.config.debug_memory_scoring,
        )

        relationships = self.rel_tracker.get_all(session_id)
        history = self.sessions.get_last_n_turns(session_id, n=self.config.history_turns)
        world_state = (
            self.world_state_store.get_all(session_id)
            if self.config.world_state_enabled else []
        )

        objectives = self.objectives_store.get_active(session_id)
        npcs = self.npc_store.get_alive(session_id)
        clock = self.clock_store.get(session_id)
        story_beats = self.beat_store.get_recent(session_id, n=5)
        emotional_state = self.emotional_state_store.get(session_id)
        inventory = self.inventory_store.get_all(session_id)
        status_effects = self.status_effect_store.get_all(session_id)
        stats = self.stat_store.get_all(session_id)
        narrative_arc = self.narrative_arc_store.get(session_id)
        factions = self.faction_store.get_all(session_id)
        quests = self.quest_store.get_active(session_id)

        # Look up rich location data for current scene location
        location_entry = None
        if scene and scene.location and scene.location.lower() != "unknown":
            location_entry = self.location_store.get_by_name(session_id, scene.location)

        return dict(
            lorebook_entries=lorebook_entries,
            scene=scene,
            relevant_memories=relevant_memories,
            relationships=relationships,
            history=history,
            world_state=world_state,
            objectives=objectives,
            npcs=npcs,
            clock=clock,
            story_beats=story_beats,
            emotional_state=emotional_state,
            inventory=inventory,
            status_effects=status_effects,
            stats=stats,
            narrative_arc=narrative_arc,
            factions=factions,
            quests=quests,
            location_entry=location_entry,
        )

    # ── Main chat interface ───────────────────────────────────────────────

    def chat(
        self,
        session_id: str,
        user_message: str,
        *,
        stream: bool = False,
        user_name: str = "Player",
    ) -> str:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        card = self._cards.get(session.character_name)
        if not card:
            if session.scenario_text:
                card = CharacterCard(
                    name=session.character_name,
                    description=session.scenario_text,
                )
            else:
                raise ValueError(
                    f"Character card '{session.character_name}' not loaded. "
                    f"Available: {list(self._cards.keys())}"
                )

        ctx = self._gather_context(session, user_message)

        messages = build_messages(
            card=card,
            lorebook_entries=ctx["lorebook_entries"],
            memories=ctx["relevant_memories"],
            scene=ctx["scene"],
            relationships=ctx["relationships"],
            history=ctx["history"],
            user_message=user_message,
            config=self.config,
            user_name=user_name,
            world_state=ctx["world_state"],
            objectives=ctx["objectives"],
            npcs=ctx["npcs"],
            clock=ctx["clock"],
            story_beats=ctx["story_beats"],
            emotional_state=ctx["emotional_state"],
            inventory=ctx["inventory"],
            status_effects=ctx["status_effects"],
            stats=ctx["stats"],
            narrative_arc=ctx["narrative_arc"],
            factions=ctx["factions"],
            quests=ctx["quests"],
            location_entry=ctx["location_entry"],
        )

        if self.config.show_prompt or self.config.debug:
            print(format_prompt_debug(messages))

        turn_count = self.sessions.get_turn_count(session_id)
        user_turn = ConversationTurn(
            session_id=session_id,
            turn_number=turn_count * 2,
            role="user",
            content=user_message,
        )

        provider = self._provider_for_session(session)

        if stream:
            response_text = self._stream_response(messages, provider)
        else:
            response_text = provider.chat(
                messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

        assistant_turn = ConversationTurn(
            session_id=session_id,
            turn_number=turn_count * 2 + 1,
            role="assistant",
            content=response_text,
        )

        self.sessions.add_turn(user_turn)
        self.sessions.add_turn(assistant_turn)
        self.sessions.increment_turn(session_id)
        self.sessions.touch(session_id)
        self.status_effect_store.tick(session_id)

        for mem in ctx["relevant_memories"]:
            self.memory_store.mark_referenced(mem.id)

        if self.config.memory_extraction_enabled:
            self._run_background_extraction(
                session_id=session_id,
                user_message=user_message,
                assistant_message=response_text,
                scene=ctx["scene"],
                source_turn_ids=[user_turn.id, assistant_turn.id],
                provider=provider,
            )

        return response_text

    def chat_stream(
        self,
        session_id: str,
        user_message: str,
        gen_params: dict | None = None,
        user_name: str = "Player",
    ) -> Generator:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        card = self._cards.get(session.character_name)
        if not card:
            if session.scenario_text:
                card = CharacterCard(
                    name=session.character_name,
                    description=session.scenario_text,
                )
            else:
                raise ValueError(
                    f"Character card '{session.character_name}' not loaded. "
                    f"Available: {list(self._cards.keys())}"
                )

        ctx = self._gather_context(session, user_message)

        messages = build_messages(
            card=card,
            lorebook_entries=ctx["lorebook_entries"],
            memories=ctx["relevant_memories"],
            scene=ctx["scene"],
            relationships=ctx["relationships"],
            history=ctx["history"],
            user_message=user_message,
            config=self.config,
            user_name=user_name,
            world_state=ctx["world_state"],
            objectives=ctx["objectives"],
            npcs=ctx["npcs"],
            clock=ctx["clock"],
            story_beats=ctx["story_beats"],
            emotional_state=ctx["emotional_state"],
            inventory=ctx["inventory"],
            status_effects=ctx["status_effects"],
            stats=ctx["stats"],
            narrative_arc=ctx["narrative_arc"],
            factions=ctx["factions"],
            quests=ctx["quests"],
            location_entry=ctx["location_entry"],
        )

        if self.config.show_prompt or self.config.debug:
            print(format_prompt_debug(messages))

        turn_count = self.sessions.get_turn_count(session_id)
        user_turn = ConversationTurn(
            session_id=session_id,
            turn_number=turn_count * 2,
            role="user",
            content=user_message,
        )

        provider = self._provider_for_session(session)

        gp = gen_params or {}
        chunks: list[str] = []
        for token in provider.chat_stream(
            messages,
            temperature=gp.get("temperature", self.config.temperature),
            max_tokens=gp.get("max_tokens", self.config.max_tokens),
            top_k=gp.get("top_k"),
            top_p=gp.get("top_p"),
            min_p=gp.get("min_p"),
            repeat_penalty=gp.get("repeat_penalty"),
            seed=gp.get("seed"),
        ):
            chunks.append(token)
            yield token

        response_text = "".join(chunks)

        assistant_turn = ConversationTurn(
            session_id=session_id,
            turn_number=turn_count * 2 + 1,
            role="assistant",
            content=response_text,
        )

        self.sessions.add_turn(user_turn)
        self.sessions.add_turn(assistant_turn)
        self.sessions.increment_turn(session_id)
        self.sessions.touch(session_id)
        self.status_effect_store.tick(session_id)

        for mem in ctx["relevant_memories"]:
            self.memory_store.mark_referenced(mem.id)

        if self.config.memory_extraction_enabled:
            self._run_background_extraction(
                session_id=session_id,
                user_message=user_message,
                assistant_message=response_text,
                scene=ctx["scene"],
                source_turn_ids=[user_turn.id, assistant_turn.id],
                provider=provider,
            )

        yield {
            "scene": self.scene_mgr.get(session_id),
            "memory_count": self.memory_store.count(session_id),
            "relationships": self.rel_tracker.get_all(session_id),
        }

    def _provider_for_session(self, session: Session):
        if not session.model_name:
            return self.provider
        from app.providers.ollama import OllamaProvider
        from app.providers.lmstudio import LMStudioProvider
        if self.config.provider == "ollama":
            return OllamaProvider(self.config.ollama_base_url, session.model_name,
                                  num_ctx=self.config.context_window)
        return LMStudioProvider(self.config.lmstudio_base_url, session.model_name)

    def _stream_response(self, messages: list[dict], provider) -> str:
        chunks = []
        for chunk in provider.generate_stream(
            messages[-1]["content"],
            system=next((m["content"] for m in messages if m["role"] == "system"), ""),
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        ):
            print(chunk, end="", flush=True)
            chunks.append(chunk)
        print()
        return "".join(chunks)

    # ── Scene / relationship public helpers ───────────────────────────────

    def update_scene(
        self,
        session_id: str,
        *,
        location: Optional[str] = None,
        active_characters: Optional[list[str]] = None,
        summary: Optional[str] = None,
    ) -> SceneState:
        scene = self.scene_mgr.update(
            session_id,
            location=location,
            active_characters=active_characters,
            summary=summary,
        )
        # Auto-register the location in the registry whenever it changes
        if location and location.strip() and location.lower() != "unknown":
            self.location_store.record_visit(session_id, location.strip())
        return scene

    def adjust_relationship(self, session_id: str, source: str, target: str, **kwargs):
        return self.rel_tracker.adjust(session_id, source, target, **kwargs)

    def get_scene(self, session_id: str) -> SceneState:
        return self.scene_mgr.get(session_id)

    def get_memories(self, session_id: str) -> list:
        return self.memory_store.get_active(session_id)

    def get_relationships(self, session_id: str) -> list:
        return self.rel_tracker.get_all(session_id)

    def get_world_state(self, session_id: str) -> list:
        return self.world_state_store.get_all(session_id)

    def get_contradiction_flags(self, session_id: str) -> list:
        return self.memory_store.get_contradiction_flags(session_id)

    # ── Regenerate ────────────────────────────────────────────────────────

    def delete_last_exchange(self, session_id: str) -> dict:
        """
        Remove the most recent assistant turn and the user turn before it.
        Returns the user message text so it can be re-submitted.
        Decrements turn_count by 1 (one exchange = one turn_count unit).
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        # Find last assistant turn
        assistant_turns = self.sessions.get_last_turns_by_role(session_id, "assistant", n=1)
        if not assistant_turns:
            raise ValueError("No assistant turn to remove.")
        last_asst = assistant_turns[0]

        # Find last user turn (turn_number immediately before assistant)
        user_turns = self.sessions.get_last_turns_by_role(session_id, "user", n=1)
        last_user = user_turns[0] if user_turns else None

        # Delete both turns
        self.sessions.delete_turns_from(session_id, last_asst.turn_number)
        if last_user and last_user.turn_number < last_asst.turn_number:
            self.sessions.delete_turns_from(session_id, last_user.turn_number)

        self.sessions.decrement_turn_count(session_id, by=1)

        return {"original_message": last_user.content if last_user else ""}

    # ── Objectives ────────────────────────────────────────────────────────

    def get_objectives(self, session_id: str) -> list:
        return self.objectives_store.get_all(session_id)

    def add_objective(self, session_id: str, title: str, description: str = "") -> "PlayerObjective":
        from app.core.models import PlayerObjective
        obj = PlayerObjective(session_id=session_id, title=title, description=description)
        self.objectives_store.save(obj)
        return obj

    def update_objective(
        self,
        objective_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> "PlayerObjective":
        from app.core.models import ObjectiveStatus

        obj = self.objectives_store.get(objective_id)
        if not obj:
            raise ValueError(f"Objective not found: {objective_id}")
        if title is not None:
            obj.title = title
        if description is not None:
            obj.description = description
        if status is not None:
            obj.status = ObjectiveStatus(status)
        obj.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.objectives_store.save(obj)
        return obj

    def delete_objective(self, objective_id: str) -> None:
        self.objectives_store.delete(objective_id)

    # ── Bookmarks ─────────────────────────────────────────────────────────

    def get_bookmarks(self, session_id: str) -> list:
        return self.bookmark_store.get_all(session_id)

    def add_bookmark(self, session_id: str, turn_id: str, note: str = "") -> "Bookmark":
        from app.core.models import Bookmark
        # Fetch the turn to get number, role, and content preview
        turns = self.sessions.get_turns(session_id, limit=500)
        turn = next((t for t in turns if t.id == turn_id), None)
        if not turn:
            raise ValueError(f"Turn not found: {turn_id}")
        bm = Bookmark(
            session_id=session_id,
            turn_id=turn_id,
            turn_number=turn.turn_number,
            role=turn.role,
            content_preview=turn.content[:200],
            note=note,
        )
        self.bookmark_store.save(bm)
        return bm

    def delete_bookmark(self, bookmark_id: str) -> None:
        self.bookmark_store.delete(bookmark_id)

    def get_bookmark_for_turn(self, session_id: str, turn_id: str):
        return self.bookmark_store.get_by_turn(session_id, turn_id)

    # ── Search ────────────────────────────────────────────────────────────

    def search_turns(self, session_id: str, query: str) -> list:
        return self.sessions.search_turns(session_id, query)

    # ── Recap ─────────────────────────────────────────────────────────────

    def generate_recap(self, session_id: str, max_sentences: int = 5) -> str:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        provider = self._provider_for_session(session)
        memories = self.memory_store.get_active(session_id)
        scene = self.scene_mgr.get(session_id)
        relationships = self.rel_tracker.get_all(session_id)
        return generate_recap(
            provider=provider,
            memories=memories,
            scene=scene,
            relationships=relationships,
            max_sentences=max_sentences,
        )

    # ── NPC Roster ────────────────────────────────────────────────────────

    def get_npcs(self, session_id: str) -> list:
        return self.npc_store.get_all(session_id)

    def add_npc(self, session_id: str, name: str, **kwargs) -> "NpcEntry":
        from app.core.models import NpcEntry
        npc = NpcEntry(session_id=session_id, name=name, **kwargs)
        self.npc_store.save(npc)
        return npc

    def update_npc(self, npc_id: str, **kwargs) -> "NpcEntry":

        npc = self.npc_store.get(npc_id)
        if not npc:
            raise ValueError(f"NPC not found: {npc_id}")
        for k, v in kwargs.items():
            if hasattr(npc, k) and v is not None:
                setattr(npc, k, v)
        npc.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.npc_store.save(npc)
        return npc

    def delete_npc(self, npc_id: str) -> None:
        self.npc_store.delete(npc_id)

    # ── Location Registry ─────────────────────────────────────────────────

    def get_locations(self, session_id: str) -> list:
        return self.location_store.get_all(session_id)

    def add_location(self, session_id: str, name: str, **kwargs) -> "LocationEntry":
        from app.core.models import LocationEntry
        existing = self.location_store.get_by_name(session_id, name)
        if existing:
            for k, v in kwargs.items():
                if hasattr(existing, k) and v is not None:
                    setattr(existing, k, v)
            self.location_store.save(existing)
            return existing
        loc = LocationEntry(session_id=session_id, name=name, **kwargs)
        self.location_store.save(loc)
        return loc

    def update_location(self, location_id: str, **kwargs) -> "LocationEntry":
        loc = self.location_store.get(location_id)
        if not loc:
            raise ValueError(f"Location not found: {location_id}")
        for k, v in kwargs.items():
            if hasattr(loc, k) and v is not None:
                setattr(loc, k, v)
        self.location_store.save(loc)
        return loc

    def delete_location(self, location_id: str) -> None:
        self.location_store.delete(location_id)

    # ── World Clock ───────────────────────────────────────────────────────

    def get_clock(self, session_id: str) -> "WorldClock":
        return self.clock_store.get_or_default(session_id)

    def set_clock(self, session_id: str, **kwargs) -> "WorldClock":

        clock = self.clock_store.get_or_default(session_id)
        for k, v in kwargs.items():
            if hasattr(clock, k) and v is not None:
                setattr(clock, k, v)
        clock.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.clock_store.save(clock)
        return clock

    # ── Story Beats ───────────────────────────────────────────────────────

    def get_story_beats(self, session_id: str) -> list:
        return self.beat_store.get_all(session_id)

    def add_story_beat(
        self,
        session_id: str,
        title: str,
        description: str = "",
        beat_type: str = "milestone",
        turn_number: int = 0,
        importance: str = "medium",
    ) -> "StoryBeat":
        from app.core.models import StoryBeat, BeatType, ImportanceLevel
        beat = StoryBeat(
            session_id=session_id,
            title=title,
            description=description,
            beat_type=BeatType(beat_type),
            turn_number=turn_number,
            importance=ImportanceLevel(importance),
        )
        self.beat_store.save(beat)
        return beat

    def delete_story_beat(self, beat_id: str) -> None:
        self.beat_store.delete(beat_id)

    # ── Emotional State ───────────────────────────────────────────────────

    def get_emotional_state(self, session_id: str) -> "EmotionalState":
        return self.emotional_state_store.get_or_default(session_id)

    def set_emotional_state(self, session_id: str, **kwargs) -> "EmotionalState":

        state = self.emotional_state_store.get_or_default(session_id)
        for k, v in kwargs.items():
            if hasattr(state, k) and v is not None:
                setattr(state, k, v)
        state.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.emotional_state_store.save(state)
        return state

    # ── Inventory ─────────────────────────────────────────────────────────

    def get_inventory(self, session_id: str) -> list:
        return self.inventory_store.get_all(session_id)

    def add_item(
        self,
        session_id: str,
        name: str,
        description: str = "",
        condition: str = "good",
        quantity: int = 1,
        is_equipped: bool = False,
    ) -> "InventoryItem":
        from app.core.models import InventoryItem
        item = InventoryItem(
            session_id=session_id,
            name=name,
            description=description,
            condition=condition,
            quantity=quantity,
            is_equipped=is_equipped,
        )
        self.inventory_store.save(item)
        return item

    def update_item(self, item_id: str, **kwargs) -> "InventoryItem":

        item = self.inventory_store.get(item_id)
        if not item:
            raise ValueError(f"Inventory item not found: {item_id}")
        for k, v in kwargs.items():
            if hasattr(item, k) and v is not None:
                setattr(item, k, v)
        item.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.inventory_store.save(item)
        return item

    def delete_item(self, item_id: str) -> None:
        self.inventory_store.delete(item_id)

    # ── Status Effects ────────────────────────────────────────────────────

    def get_status_effects(self, session_id: str) -> list:
        return self.status_effect_store.get_all(session_id)

    def add_status_effect(
        self,
        session_id: str,
        name: str,
        description: str = "",
        effect_type: str = "neutral",
        severity: str = "mild",
        duration_turns: int = 0,
    ) -> "StatusEffect":
        from app.core.models import StatusEffect, EffectType
        effect = StatusEffect(
            session_id=session_id,
            name=name,
            description=description,
            effect_type=EffectType(effect_type),
            severity=severity,
            duration_turns=duration_turns,
        )
        self.status_effect_store.save(effect)
        return effect

    def delete_status_effect(self, effect_id: str) -> None:
        self.status_effect_store.delete(effect_id)

    # ── Character Stats ───────────────────────────────────────────────────

    def get_stats(self, session_id: str) -> list:
        return self.stat_store.get_all(session_id)

    def add_stat(
        self,
        session_id: str,
        name: str,
        value: int = 10,
        modifier: int = 0,
        category: str = "attribute",
    ) -> "CharacterStat":
        from app.core.models import CharacterStat
        stat = CharacterStat(
            session_id=session_id,
            name=name,
            value=value,
            modifier=modifier,
            category=category,
        )
        self.stat_store.save(stat)
        return stat

    def update_stat(self, stat_id: str, **kwargs) -> "CharacterStat":

        stat = self.stat_store.get(stat_id)
        if not stat:
            raise ValueError(f"Stat not found: {stat_id}")
        for k, v in kwargs.items():
            if hasattr(stat, k) and v is not None:
                setattr(stat, k, v)
        stat.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.stat_store.save(stat)
        return stat

    def delete_stat(self, stat_id: str) -> None:
        self.stat_store.delete(stat_id)

    # ── Skill Checks ──────────────────────────────────────────────────────

    def roll_check(
        self,
        session_id: str,
        stat_name: str,
        difficulty: int,
        dice: str = "d20",
        narrative_context: str = "",
    ) -> "SkillCheckResult":
        """Roll a skill check, persist the result, and return it."""
        turn_count = self.sessions.get_turn_count(session_id)
        stat = self.stat_store.get_by_name(session_id, stat_name)
        result = perform_check(
            session_id=session_id,
            stat=stat,
            stat_name=stat_name,
            difficulty=difficulty,
            dice=dice,
            narrative_context=narrative_context,
            turn_number=turn_count,
        )
        self.skill_check_store.save(result)
        return result

    def get_skill_checks(self, session_id: str, n: int = 20) -> list:
        return self.skill_check_store.get_recent(session_id, n=n)

    # ── Narrative Arc ─────────────────────────────────────────────────────

    def get_narrative_arc(self, session_id: str) -> "NarrativeArc":
        return self.narrative_arc_store.get_or_default(session_id)

    def set_narrative_arc(self, session_id: str, **kwargs) -> "NarrativeArc":

        arc = self.narrative_arc_store.get_or_default(session_id)
        for k, v in kwargs.items():
            if hasattr(arc, k) and v is not None:
                setattr(arc, k, v)
        arc.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.narrative_arc_store.save(arc)
        return arc

    # ── Factions ──────────────────────────────────────────────────────────

    def get_factions(self, session_id: str) -> list:
        return self.faction_store.get_all(session_id)

    def add_faction(self, session_id: str, name: str, **kwargs) -> "Faction":
        from app.core.models import Faction
        faction = Faction(session_id=session_id, name=name, **kwargs)
        self.faction_store.save(faction)
        return faction

    def update_faction(self, faction_id: str, **kwargs) -> "Faction":

        faction = self.faction_store.get(faction_id)
        if not faction:
            raise ValueError(f"Faction not found: {faction_id}")
        for k, v in kwargs.items():
            if hasattr(faction, k) and v is not None:
                setattr(faction, k, v)
        faction.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.faction_store.save(faction)
        return faction

    def adjust_faction_standing(self, faction_id: str, delta: float) -> "Faction":
        faction = self.faction_store.adjust_standing(faction_id, delta)
        if not faction:
            raise ValueError(f"Faction not found: {faction_id}")
        return faction

    def delete_faction(self, faction_id: str) -> None:
        self.faction_store.delete(faction_id)

    # ── Quest Log ─────────────────────────────────────────────────────────

    def get_quests(self, session_id: str) -> list:
        return self.quest_store.get_all(session_id)

    def add_quest(
        self,
        session_id: str,
        title: str,
        description: str = "",
        giver_npc_name: str = "",
        location_name: str = "",
        reward_notes: str = "",
        importance: str = "medium",
        stages: list[dict] | None = None,
    ) -> "Quest":
        from app.core.models import Quest, QuestStage, ImportanceLevel
        stage_objs = [
            QuestStage(description=s["description"], order=i)
            for i, s in enumerate(stages or [])
        ]
        quest = Quest(
            session_id=session_id,
            title=title,
            description=description,
            giver_npc_name=giver_npc_name,
            location_name=location_name,
            reward_notes=reward_notes,
            importance=ImportanceLevel(importance),
            stages=stage_objs,
        )
        self.quest_store.save(quest)
        return quest

    def update_quest(self, quest_id: str, **kwargs) -> "Quest":

        from app.core.models import QuestStatus, ImportanceLevel
        quest = self.quest_store.get(quest_id)
        if not quest:
            raise ValueError(f"Quest not found: {quest_id}")
        for k, v in kwargs.items():
            if v is None:
                continue
            if k == "status":
                quest.status = QuestStatus(v)
            elif k == "importance":
                quest.importance = ImportanceLevel(v)
            elif hasattr(quest, k):
                setattr(quest, k, v)
        quest.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.quest_store.save(quest)
        return quest

    def complete_quest_stage(self, quest_id: str, stage_id: str) -> "Quest":

        quest = self.quest_store.get(quest_id)
        if not quest:
            raise ValueError(f"Quest not found: {quest_id}")
        for stage in quest.stages:
            if stage.id == stage_id:
                stage.completed = True
                break
        quest.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.quest_store.save(quest)
        return quest

    def delete_quest(self, quest_id: str) -> None:
        self.quest_store.delete(quest_id)

    # ── Session Journal ───────────────────────────────────────────────────

    def get_journal(self, session_id: str) -> list:
        return self.journal_store.get_all(session_id)

    def add_journal_entry(
        self,
        session_id: str,
        title: str,
        content: str,
        turn_number: int = 0,
        tags: list[str] | None = None,
    ) -> "JournalEntry":
        from app.core.models import JournalEntry
        entry = JournalEntry(
            session_id=session_id,
            title=title,
            content=content,
            turn_number=turn_number,
            tags=tags or [],
        )
        self.journal_store.save(entry)
        return entry

    def delete_journal_entry(self, entry_id: str) -> None:
        self.journal_store.delete(entry_id)

    # ── Lore Notes ────────────────────────────────────────────────────────

    def get_lore_notes(self, session_id: str) -> list:
        return self.lore_note_store.get_all(session_id)

    def add_lore_note(
        self,
        session_id: str,
        title: str,
        content: str,
        category: str = "general",
        source: str = "",
        tags: list[str] | None = None,
    ) -> "LoreNote":
        from app.core.models import LoreNote
        note = LoreNote(
            session_id=session_id,
            title=title,
            content=content,
            category=category,
            source=source,
            tags=tags or [],
        )
        self.lore_note_store.save(note)
        return note

    def update_lore_note(self, note_id: str, **kwargs) -> "LoreNote":

        note = self.lore_note_store.get(note_id)
        if not note:
            raise ValueError(f"Lore note not found: {note_id}")
        for k, v in kwargs.items():
            if hasattr(note, k) and v is not None:
                setattr(note, k, v)
        note.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.lore_note_store.save(note)
        return note

    def delete_lore_note(self, note_id: str) -> None:
        self.lore_note_store.delete(note_id)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_lorebook_entries(self, session: Session, user_message: str) -> list:
        if not session.lorebook_name:
            return []
        lorebook = self._lorebooks.get(session.lorebook_name)
        if not lorebook:
            return []
        recent = self._recent_text(session.id, n=4)
        return retrieve_entries(
            lorebook,
            recent + " " + user_message,
            max_entries=self.config.max_lorebook_entries,
        )

    def _recent_text(self, session_id: str, n: int = 6) -> str:
        turns = self.sessions.get_last_n_turns(session_id, n=n)
        return " ".join(t.content for t in turns)

    def _run_background_extraction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        scene,
        source_turn_ids: list[str],
        provider,
    ) -> None:
        # One lock per session — extraction jobs for the same session run
        # sequentially so they never race on memory/relationship writes.
        if session_id not in self._extraction_locks:
            self._extraction_locks[session_id] = threading.Lock()
        lock = self._extraction_locks[session_id]

        jobs = [
            (self._do_memory_extraction,
             (session_id, user_message, assistant_message, scene, source_turn_ids, provider)),
            (self._do_relationship_extraction,
             (session_id, user_message, assistant_message, scene, provider)),
            (self._do_scene_extraction,
             (session_id, user_message, assistant_message, scene, provider)),
            (self._do_npc_extraction,
             (session_id, user_message, assistant_message, scene, provider)),
        ]

        def _run_serialized():
            with lock:
                for fn, args in jobs:
                    fn(*args)

        threading.Thread(target=_run_serialized, daemon=True).start()

    def _do_memory_extraction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        scene,
        source_turn_ids: list[str],
        provider,
    ) -> None:
        try:
            new_memories = extract_memories(
                provider=provider,
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
                scene=scene,
                source_turn_ids=source_turn_ids,
                debug=self.config.show_memory_extraction or self.config.debug,
            )
            if not new_memories:
                log.info("Memory extraction: no new memories for this turn.")
                return

            # Duplicate title suppression
            existing = self.memory_store.get_active(session_id)
            existing_titles = {m.title.lower() for m in existing}
            new_memories = [
                m for m in new_memories
                if not _is_duplicate_title(m.title, existing_titles)
            ]
            if not new_memories:
                log.info("Memory extraction: all entries were near-duplicates, skipped.")
                return

            # Contradiction detection
            if self.config.contradiction_detection_enabled:
                new_memories, flags = check_contradictions(
                    new_memories=new_memories,
                    existing_memories=existing,
                    session_id=session_id,
                    mode=self.config.contradiction_mode,
                    similarity_threshold=self.config.contradiction_similarity_threshold,
                    debug=self.config.debug,
                )
                for flag in flags:
                    self.memory_store.save_contradiction_flag(flag)

            if new_memories:
                self.memory_store.save_many(new_memories)
                log.info("Stored %d new memory entries.", len(new_memories))

            # Consolidation check
            if self.config.consolidation_enabled and self.config.consolidation_threshold > 0:
                self._maybe_consolidate(session_id, provider, scene)

        except Exception as e:
            log.warning("Memory extraction failed (non-fatal): %s", e)

    def _maybe_consolidate(self, session_id: str, provider, scene) -> None:
        """Trigger consolidation if any type exceeds the threshold."""
        try:
            active = self.memory_store.get_active(session_id)
            location = scene.location if scene else "Unknown"
            summaries, to_archive = consolidate_memories(
                provider=provider,
                memories=active,
                session_id=session_id,
                threshold=self.config.consolidation_threshold,
                min_age_days=self.config.consolidation_min_age_days,
                location=location,
                debug=self.config.debug,
            )
            if summaries:
                self.memory_store.save_many(summaries)
                self.memory_store.archive_many([m.id for m in to_archive])
                log.info(
                    "Consolidation: created %d summaries, archived %d memories.",
                    len(summaries), len(to_archive),
                )
        except Exception as e:
            log.warning("Consolidation failed (non-fatal): %s", e)

    def _do_relationship_extraction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        scene,
        provider,
    ) -> None:
        try:
            deltas = extract_relationship_deltas(
                provider=provider,
                user_message=user_message,
                assistant_message=assistant_message,
                scene=scene,
                debug=self.config.debug,
            )
            # Resolve aliases → canonical names before storing.
            alias_map = self.alias_store.build_map(session_id)
            # Build a case-insensitive allowlist from active characters.
            # Relationships between characters not in the scene are discarded.
            allowed = {c.lower() for c in (scene.active_characters if scene else [])}
            for d in deltas:
                source = alias_map.get(str(d.get("source", "")).strip().lower(),
                                       str(d.get("source", "")).strip())
                target = alias_map.get(str(d.get("target", "")).strip().lower(),
                                       str(d.get("target", "")).strip())
                if not source or not target:
                    continue
                if allowed and (source.lower() not in allowed or target.lower() not in allowed):
                    log.debug("Discarding relationship delta %s→%s: not in active scene.", source, target)
                    continue
                self.rel_tracker.adjust(
                    session_id, source, target,
                    trust=float(d.get("trust", 0.0)),
                    fear=float(d.get("fear", 0.0)),
                    respect=float(d.get("respect", 0.0)),
                    affection=float(d.get("affection", 0.0)),
                    hostility=float(d.get("hostility", 0.0)),
                )
            if deltas:
                log.info("Applied %d relationship delta(s) from turn.", len(deltas))
        except Exception as e:
            log.warning("Relationship extraction failed (non-fatal): %s", e)

    def _do_npc_extraction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        scene,
        provider,
    ) -> None:
        """4th extraction thread: identify NPCs from the turn and add to roster."""
        try:
            from app.sessions.manager import SessionManager
            session = self.sessions.get(session_id)
            if not session:
                return
            char_name = session.character_name

            candidates = extract_npcs(
                provider=provider,
                session_id=session_id,
                character_name=char_name,
                user_message=user_message,
                assistant_message=assistant_message,
                scene=scene,
                debug=self.config.debug,
            )
            if not candidates:
                return

            added = 0
            for npc in candidates:
                existing = self.npc_store.get_by_name(session_id, npc.name)
                if existing:
                    # Update last known location if the new one is more specific
                    if npc.last_known_location and not existing.last_known_location:
                        existing.last_known_location = npc.last_known_location
                
                        existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
                        self.npc_store.save(existing)
                else:
                    self.npc_store.save(npc)
                    added += 1

            if added:
                log.info("NPC extraction: added %d new NPC(s) to roster.", added)
        except Exception as e:
            log.warning("NPC extraction failed (non-fatal): %s", e)

    def _do_scene_extraction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        scene,
        provider,
    ) -> None:
        try:
            clock = self.clock_store.get_or_default(session_id)
            update = extract_scene_update(
                provider=provider,
                user_message=user_message,
                assistant_message=assistant_message,
                scene=scene,
                clock=clock,
                debug=self.config.debug,
            )
            summary = update.get("summary") or None
            if not summary:
                return
            new_location = update.get("location") or None
            new_chars = update.get("active_characters") or None
            self.scene_mgr.update(
                session_id,
                summary=summary,
                location=new_location,
                active_characters=new_chars,
            )
            # Register the effective location (new or current) so the registry
            # fills up even when the player stays in the same place.
            effective_location = new_location or (scene.location if scene else None)
            if effective_location and effective_location.strip() and effective_location.lower() != "unknown":
                self.location_store.record_visit(session_id, effective_location.strip())

            # Advance the in-world clock by however many hours the LLM estimated.
            hours = update.get("hours_passed")
            if isinstance(hours, (int, float)) and hours > 0:
                hours = int(hours)
                total_hours = clock.hour + hours
                extra_days = total_hours // 24
                clock.hour = total_hours % 24
                clock.day += extra_days
                clock.updated_at = datetime.now(UTC).replace(tzinfo=None)
                self.clock_store.save(clock)
                log.info("Clock advanced %dh → Day %d Month %d Year %d %s",
                         hours, clock.day, clock.month, clock.year, clock.time_of_day)

            log.info("Scene summary updated.")
        except Exception as e:
            log.warning("Scene extraction failed (non-fatal): %s", e)
