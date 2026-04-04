"""
Configuration for the RP Utility engine.
Uses pydantic-settings so values can be overridden via environment variables
or a .env file without code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root is two levels up from this file (app/core/config.py → project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "rp_utility.db"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RP_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Provider settings ──────────────────────────────────────────────────
    provider: Literal["ollama", "lmstudio"] = "ollama"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # LM Studio
    lmstudio_base_url: str = "http://localhost:1234"
    lmstudio_model: str = "local-model"   # usually auto-detected by LM Studio

    # ── Generation parameters ──────────────────────────────────────────────
    temperature: float = 0.8
    max_tokens: int = 1024
    context_window: int = 8192

    # ── Memory settings ────────────────────────────────────────────────────
    max_retrieved_memories: int = 15
    memory_extraction_enabled: bool = True
    # Model used for memory extraction (can be a smaller/faster model)
    extraction_model: str = ""   # empty = use same as main model

    # ── Conversation history window ────────────────────────────────────────
    # How many recent turns to keep in the prompt. Increase for longer sessions.
    history_turns: int = 30

    # ── Memory retrieval scoring weights ───────────────────────────────────
    retrieval_weight_importance: float = 1.0
    retrieval_weight_entity: float = 2.0
    retrieval_weight_keyword: float = 0.5
    retrieval_weight_recency: float = 0.5   # reduced: recency is a bonus, not a gate
    retrieval_weight_reference: float = 0.5
    retrieval_recency_half_life_days: float = 60.0  # longer half-life: old facts still matter
    retrieval_reference_half_life_days: float = 14.0

    # Per-type memory caps (0 = no cap)
    max_memories_event: int = 6
    max_memories_world_fact: int = 5
    max_memories_character_detail: int = 5
    max_memories_relationship_change: int = 4
    max_memories_world_state: int = 4
    max_memories_rumor: int = 2
    max_memories_suspicion: int = 2

    # ── Memory consolidation ───────────────────────────────────────────────
    consolidation_enabled: bool = True
    # Trigger when this many memories of same type exist (0 = disabled)
    consolidation_threshold: int = 15
    consolidation_min_age_days: float = 7.0   # don't consolidate developing story arcs

    # ── Contradiction detection ────────────────────────────────────────────
    contradiction_detection_enabled: bool = True
    # "mark_uncertain" | "reject" | "downgrade" | "warn"
    contradiction_mode: str = "mark_uncertain"
    contradiction_similarity_threshold: float = 0.65

    # ── World-state ────────────────────────────────────────────────────────
    world_state_enabled: bool = True
    max_world_state_entries: int = 5

    # ── Lorebook settings ──────────────────────────────────────────────────
    max_lorebook_entries: int = 5

    # ── Prompt assembly ────────────────────────────────────────────────────
    # "soft" = memories injected as natural narrative prose
    # "raw"  = memories injected as a structured list (useful for debugging)
    memory_injection_mode: Literal["soft", "raw"] = "soft"

    # ── Developer / debug ──────────────────────────────────────────────────
    debug: bool = False
    show_prompt: bool = False        # print full prompt before each generation
    show_memory_extraction: bool = False
    debug_memory_scoring: bool = False   # log per-memory score breakdown

    # ── Paths ──────────────────────────────────────────────────────────────
    db_path: str = str(DB_PATH)
    cards_dir: str = str(DATA_DIR / "cards")
    lorebooks_dir: str = str(DATA_DIR / "lorebooks")

    def active_model(self) -> str:
        """Return the model name for the active provider."""
        if self.provider == "ollama":
            return self.ollama_model
        return self.lmstudio_model

    def extraction_model_name(self) -> str:
        """Return the model to use for memory extraction."""
        return self.extraction_model or self.active_model()


# Singleton config instance (loaded once at import time)
config = Config()
