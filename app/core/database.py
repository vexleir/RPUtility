"""
SQLite database setup and low-level helpers.
All tables are created here on first run (schema-as-code).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a SQLite connection with row_factory for dict-style access."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_db(db_path: str) -> None:
    """Create all tables if they do not already exist, and run any migrations."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        _create_tables(conn)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Apply additive schema migrations for existing databases.
    Each migration is idempotent — safe to run on a fresh DB too.
    """
    # v1 → v2: add model_name column to sessions
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN model_name TEXT")
    except Exception:
        pass   # column already exists

    # v2 → v3 (Phase 2): new columns on memories
    for col_def in [
        "certainty TEXT NOT NULL DEFAULT 'confirmed'",
        "consolidated_from TEXT NOT NULL DEFAULT '[]'",
        "contradiction_of TEXT",
        "archived INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {col_def}")
        except Exception:
            pass  # column already exists

    # v2 → v3 (Phase 2): world_state table
    # Note: SQLite does not support adding FK constraints via ALTER TABLE.
    # Tables created here for the first time include FKs; existing tables retain
    # their original schema. Application-layer cascade deletes compensate.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS world_state (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            category        TEXT NOT NULL DEFAULT 'general',
            title           TEXT NOT NULL,
            content         TEXT NOT NULL,
            entities        TEXT NOT NULL DEFAULT '[]',
            tags            TEXT NOT NULL DEFAULT '[]',
            importance      TEXT NOT NULL DEFAULT 'high',
            source_memory_ids TEXT NOT NULL DEFAULT '[]'
        )
    """)

    # v2 → v3 (Phase 2): contradiction_flags table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contradiction_flags (
            id                  TEXT PRIMARY KEY,
            session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            detected_at         TEXT NOT NULL,
            new_memory_id       TEXT NOT NULL,
            existing_memory_id  TEXT NOT NULL,
            description         TEXT NOT NULL,
            resolution          TEXT NOT NULL DEFAULT 'mark_uncertain'
        )
    """)

    # Phase 1 additions: player_objectives table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_objectives (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 1 additions: bookmarks table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            turn_id         TEXT NOT NULL,
            turn_number     INTEGER NOT NULL,
            role            TEXT NOT NULL DEFAULT 'assistant',
            content_preview TEXT NOT NULL DEFAULT '',
            note            TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)

    # Phase 2 additions: NPC roster
    conn.execute("""
        CREATE TABLE IF NOT EXISTS npc_roster (
            id                   TEXT PRIMARY KEY,
            session_id           TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name                 TEXT NOT NULL,
            role                 TEXT NOT NULL DEFAULT '',
            description          TEXT NOT NULL DEFAULT '',
            personality_notes    TEXT NOT NULL DEFAULT '',
            last_known_location  TEXT NOT NULL DEFAULT '',
            is_alive             INTEGER NOT NULL DEFAULT 1,
            tags                 TEXT NOT NULL DEFAULT '[]',
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
    """)

    # Phase 2 additions: location registry
    conn.execute("""
        CREATE TABLE IF NOT EXISTS location_registry (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            atmosphere      TEXT NOT NULL DEFAULT '',
            notes           TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '[]',
            visit_count     INTEGER NOT NULL DEFAULT 0,
            first_visited   TEXT NOT NULL,
            last_visited    TEXT NOT NULL
        )
    """)

    # Phase 2 additions: in-world clock (one row per session)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS world_clock (
            session_id  TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            year        INTEGER NOT NULL DEFAULT 1,
            month       INTEGER NOT NULL DEFAULT 1,
            day         INTEGER NOT NULL DEFAULT 1,
            hour        INTEGER NOT NULL DEFAULT 12,
            era_label   TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 2 additions: story beats
    conn.execute("""
        CREATE TABLE IF NOT EXISTS story_beats (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            beat_type   TEXT NOT NULL DEFAULT 'milestone',
            turn_number INTEGER NOT NULL DEFAULT 0,
            importance  TEXT NOT NULL DEFAULT 'medium',
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL
        )
    """)

    # Phase 3 additions: emotional state (one row per session)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emotional_state (
            session_id  TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            mood        TEXT NOT NULL DEFAULT 'neutral',
            stress      REAL NOT NULL DEFAULT 0.0,
            motivation  TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 3 additions: inventory
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            condition   TEXT NOT NULL DEFAULT 'good',
            quantity    INTEGER NOT NULL DEFAULT 1,
            tags        TEXT NOT NULL DEFAULT '[]',
            is_equipped INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 3 additions: status effects
    conn.execute("""
        CREATE TABLE IF NOT EXISTS status_effects (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            effect_type     TEXT NOT NULL DEFAULT 'neutral',
            severity        TEXT NOT NULL DEFAULT 'mild',
            duration_turns  INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL
        )
    """)

    # Phase 4 additions: character stats
    conn.execute("""
        CREATE TABLE IF NOT EXISTS character_stats (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            value       INTEGER NOT NULL DEFAULT 10,
            modifier    INTEGER NOT NULL DEFAULT 0,
            category    TEXT NOT NULL DEFAULT 'attribute',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 4 additions: skill check results log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_checks (
            id                  TEXT PRIMARY KEY,
            session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            stat_name           TEXT NOT NULL,
            roll                INTEGER NOT NULL,
            modifier            INTEGER NOT NULL DEFAULT 0,
            total               INTEGER NOT NULL,
            difficulty          INTEGER NOT NULL,
            outcome             TEXT NOT NULL,
            narrative_context   TEXT NOT NULL DEFAULT '',
            turn_number         INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL
        )
    """)

    # Phase 4 additions: narrative arc (one row per session)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS narrative_arc (
            session_id   TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            current_act  INTEGER NOT NULL DEFAULT 1,
            act_label    TEXT NOT NULL DEFAULT 'Opening',
            tension      REAL NOT NULL DEFAULT 0.0,
            pacing       TEXT NOT NULL DEFAULT 'building',
            themes       TEXT NOT NULL DEFAULT '[]',
            arc_notes    TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL
        )
    """)

    # Phase 4 additions: factions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factions (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            alignment   TEXT NOT NULL DEFAULT '',
            standing    REAL NOT NULL DEFAULT 0.0,
            tags        TEXT NOT NULL DEFAULT '[]',
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 5 additions: quest log (stages stored as JSON blob)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'active',
            giver_npc_name  TEXT NOT NULL DEFAULT '',
            location_name   TEXT NOT NULL DEFAULT '',
            reward_notes    TEXT NOT NULL DEFAULT '',
            importance      TEXT NOT NULL DEFAULT 'medium',
            stages          TEXT NOT NULL DEFAULT '[]',
            tags            TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    # Phase 5 additions: session journal
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            turn_number INTEGER NOT NULL DEFAULT 0,
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL
        )
    """)

    # Phase 5 additions: lore notes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lore_notes (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'general',
            source      TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Phase 4: NPC expanded fields
    for col_def in [
        "status TEXT NOT NULL DEFAULT 'active'",
        "status_reason TEXT NOT NULL DEFAULT ''",
        "secrets TEXT NOT NULL DEFAULT ''",
        "short_term_goal TEXT NOT NULL DEFAULT ''",
        "long_term_goal TEXT NOT NULL DEFAULT ''",
        "dev_log TEXT NOT NULL DEFAULT '[]'",
    ]:
        try:
            conn.execute(f"ALTER TABLE npc_cards ADD COLUMN {col_def}")
        except Exception:
            pass

    # Phase 4: player character development log
    try:
        conn.execute("ALTER TABLE player_characters ADD COLUMN dev_log TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass

    # Phase 4: faction standing with player
    for col_def in [
        "standing_with_player TEXT NOT NULL DEFAULT ''",
        "relationship_notes TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            conn.execute(f"ALTER TABLE campaign_factions ADD COLUMN {col_def}")
        except Exception:
            pass

    # Phase 4: NPC-to-NPC relationship matrix
    conn.execute("""
        CREATE TABLE IF NOT EXISTS npc_relationships (
            id          TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            npc_id_a    TEXT NOT NULL,
            npc_id_b    TEXT NOT NULL,
            dynamic     TEXT NOT NULL DEFAULT '',
            trust       TEXT NOT NULL DEFAULT '',
            hostility   TEXT NOT NULL DEFAULT '',
            history     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE(campaign_id, npc_id_a, npc_id_b)
        )
    """)

    # allow_unselected_npcs flag on scenes
    try:
        conn.execute("ALTER TABLE campaign_scenes ADD COLUMN allow_unselected_npcs INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # column already exists

    # Phase 3: campaign notes (player scratchpad) and world fact categories
    try:
        conn.execute("ALTER TABLE campaigns ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # column already exists

    try:
        conn.execute("ALTER TABLE campaign_world_facts ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # column already exists

    # Image generation: cover/portrait/scene images stored as base64 data URLs
    try:
        conn.execute("ALTER TABLE campaigns ADD COLUMN cover_image TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE npc_cards ADD COLUMN portrait_image TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE campaign_scenes ADD COLUMN scene_image TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE campaigns ADD COLUMN gen_settings TEXT NOT NULL DEFAULT '{}'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE player_characters ADD COLUMN portrait_image TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE npc_cards ADD COLUMN gender TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE npc_cards ADD COLUMN age TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    # Character aliases: maps alternate names/titles to a canonical name
    conn.execute("""
        CREATE TABLE IF NOT EXISTS character_aliases (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            canonical_name  TEXT NOT NULL,
            alias           TEXT NOT NULL,
            UNIQUE(session_id, alias)
        )
    """)

    # Scenario Mode: free-text scenario description stored on session row
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN scenario_text TEXT")
    except Exception:
        pass  # column already exists

    # Summary model: separate Ollama model for scene summary extraction
    try:
        conn.execute("ALTER TABLE campaigns ADD COLUMN summary_model_name TEXT")
    except Exception:
        pass  # column already exists

    # NPC forms, transformation history, and player relationship history
    for _col in [
        "history_with_player TEXT NOT NULL DEFAULT ''",
        "forms TEXT NOT NULL DEFAULT '[]'",
        "active_form TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE npc_cards ADD COLUMN {_col}")
        except Exception:
            pass  # column already exists

    # World fact priority tiers and keyword triggers
    for _col in [
        "priority TEXT NOT NULL DEFAULT 'normal'",
        "trigger_keywords TEXT NOT NULL DEFAULT '[]'",
    ]:
        try:
            conn.execute(f"ALTER TABLE campaign_world_facts ADD COLUMN {_col}")
        except Exception:
            pass  # column already exists

    # ── Campaign system (new architecture) ───────────────────────────────────

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            model_name      TEXT,
            style_guide     TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_characters (
            id              TEXT PRIMARY KEY,
            campaign_id     TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            name            TEXT NOT NULL DEFAULT 'The Player',
            appearance      TEXT NOT NULL DEFAULT '',
            personality     TEXT NOT NULL DEFAULT '',
            background      TEXT NOT NULL DEFAULT '',
            wants           TEXT NOT NULL DEFAULT '',
            fears           TEXT NOT NULL DEFAULT '',
            how_seen        TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_world_facts (
            id          TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            content     TEXT NOT NULL,
            fact_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_places (
            id              TEXT PRIMARY KEY,
            campaign_id     TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            current_state   TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS npc_cards (
            id                      TEXT PRIMARY KEY,
            campaign_id             TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            name                    TEXT NOT NULL,
            appearance              TEXT NOT NULL DEFAULT '',
            personality             TEXT NOT NULL DEFAULT '',
            role                    TEXT NOT NULL DEFAULT '',
            relationship_to_player  TEXT NOT NULL DEFAULT '',
            current_location        TEXT NOT NULL DEFAULT '',
            current_state           TEXT NOT NULL DEFAULT '',
            is_alive                INTEGER NOT NULL DEFAULT 1,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS narrative_threads (
            id          TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active',
            resolution  TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_scenes (
            id                  TEXT PRIMARY KEY,
            campaign_id         TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            scene_number        INTEGER NOT NULL,
            title               TEXT NOT NULL DEFAULT '',
            location            TEXT NOT NULL DEFAULT '',
            npc_ids             TEXT NOT NULL DEFAULT '[]',
            intent              TEXT NOT NULL DEFAULT '',
            tone                TEXT NOT NULL DEFAULT '',
            turns               TEXT NOT NULL DEFAULT '[]',
            proposed_summary    TEXT NOT NULL DEFAULT '',
            confirmed_summary   TEXT NOT NULL DEFAULT '',
            confirmed           INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chronicle_entries (
            id                  TEXT PRIMARY KEY,
            campaign_id         TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            scene_range_start   INTEGER NOT NULL DEFAULT 0,
            scene_range_end     INTEGER NOT NULL DEFAULT 0,
            content             TEXT NOT NULL DEFAULT '',
            confirmed           INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_factions (
            id          TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            goals       TEXT NOT NULL DEFAULT '',
            methods     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- Sessions
        CREATE TABLE IF NOT EXISTS sessions (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            character_name  TEXT NOT NULL,
            lorebook_name   TEXT,
            model_name      TEXT,
            created_at      TEXT NOT NULL,
            last_active     TEXT NOT NULL,
            turn_count      INTEGER DEFAULT 0
        );

        -- Conversation turns (kept for context window assembly)
        CREATE TABLE IF NOT EXISTS turns (
            id           TEXT PRIMARY KEY,
            session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            turn_number  INTEGER NOT NULL,
            role         TEXT NOT NULL,
            content      TEXT NOT NULL,
            timestamp    TEXT NOT NULL
        );

        -- Memory entries (the persistent world state)
        CREATE TABLE IF NOT EXISTS memories (
            id                  TEXT PRIMARY KEY,
            session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            type                TEXT NOT NULL,
            title               TEXT NOT NULL,
            content             TEXT NOT NULL,
            entities            TEXT NOT NULL DEFAULT '[]',
            location            TEXT,
            tags                TEXT NOT NULL DEFAULT '[]',
            importance          TEXT NOT NULL DEFAULT 'medium',
            last_referenced_at  TEXT,
            source_turn_ids     TEXT NOT NULL DEFAULT '[]',
            confidence          REAL NOT NULL DEFAULT 1.0
        );

        -- Scene state (one row per session, upserted on each update)
        CREATE TABLE IF NOT EXISTS scene_state (
            session_id          TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            location            TEXT NOT NULL DEFAULT 'Unknown',
            active_characters   TEXT NOT NULL DEFAULT '[]',
            summary             TEXT NOT NULL DEFAULT '',
            last_updated        TEXT NOT NULL
        );

        -- Relationship state (one row per source/target pair per session)
        CREATE TABLE IF NOT EXISTS relationships (
            session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            source_entity   TEXT NOT NULL,
            target_entity   TEXT NOT NULL,
            trust           REAL NOT NULL DEFAULT 0.0,
            fear            REAL NOT NULL DEFAULT 0.0,
            respect         REAL NOT NULL DEFAULT 0.0,
            affection       REAL NOT NULL DEFAULT 0.0,
            hostility       REAL NOT NULL DEFAULT 0.0,
            last_updated    TEXT NOT NULL,
            PRIMARY KEY (session_id, source_entity, target_entity)
        );
    """)


# ─────────────────────────────────────────────
# JSON helpers (SQLite stores lists as JSON text)
# ─────────────────────────────────────────────

def json_encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_decode(value: str | None) -> Any:
    if value is None:
        return []
    return json.loads(value)
