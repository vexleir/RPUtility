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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS world_state (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL,
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
            session_id          TEXT NOT NULL,
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
            session_id  TEXT NOT NULL,
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
            session_id      TEXT NOT NULL,
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
            session_id           TEXT NOT NULL,
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
            session_id      TEXT NOT NULL,
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
            session_id  TEXT PRIMARY KEY,
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
            session_id  TEXT NOT NULL,
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
            session_id  TEXT PRIMARY KEY,
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
            session_id  TEXT NOT NULL,
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
            session_id      TEXT NOT NULL,
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
            session_id  TEXT NOT NULL,
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
            session_id          TEXT NOT NULL,
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
            session_id   TEXT PRIMARY KEY,
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
            session_id  TEXT NOT NULL,
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
            session_id      TEXT NOT NULL,
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
            session_id  TEXT NOT NULL,
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
            session_id  TEXT NOT NULL,
            title       TEXT NOT NULL,
            content     TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'general',
            source      TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)

    # Character aliases: maps alternate names/titles to a canonical name
    conn.execute("""
        CREATE TABLE IF NOT EXISTS character_aliases (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL,
            canonical_name  TEXT NOT NULL,
            alias           TEXT NOT NULL,
            UNIQUE(session_id, alias)
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
