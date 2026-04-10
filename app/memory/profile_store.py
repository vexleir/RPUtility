"""
Character Memory Profile store.

One profile row per character per campaign.  Each profile is a living
summary of what has been established about that character across all
confirmed scenes — traits, secrets revealed to the player, and current state.

Profiles are injected into the scene prompt whenever the character is
present, ensuring character continuity without relying on scored retrieval.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, UTC
from typing import Optional

from app.core.database import get_connection, json_encode, json_decode


class CharacterProfile:
    """In-memory representation of a character's accumulated profile."""

    def __init__(
        self,
        id: str,
        campaign_id: str,
        character_name: str,
        confirmed_traits: list[str],
        known_secrets: list[str],
        last_known_state: str,
        profile_summary: str,
        source_scene_numbers: list[int],
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.campaign_id = campaign_id
        self.character_name = character_name
        self.confirmed_traits = confirmed_traits
        self.known_secrets = known_secrets
        self.last_known_state = last_known_state
        self.profile_summary = profile_summary
        self.source_scene_numbers = source_scene_numbers
        self.updated_at = updated_at


class CharacterProfileStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def get(self, campaign_id: str, character_name: str) -> Optional[CharacterProfile]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM character_profiles "
                "WHERE campaign_id = ? AND character_name = ?",
                (campaign_id, character_name),
            ).fetchone()
        return _row_to_profile(row) if row else None

    def get_all(self, campaign_id: str) -> list[CharacterProfile]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM character_profiles WHERE campaign_id = ? "
                "ORDER BY character_name",
                (campaign_id,),
            ).fetchall()
        return [_row_to_profile(r) for r in rows]

    def get_many(self, campaign_id: str, names: list[str]) -> list[CharacterProfile]:
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM character_profiles "
                f"WHERE campaign_id = ? AND character_name IN ({placeholders})",
                (campaign_id, *names),
            ).fetchall()
        return [_row_to_profile(r) for r in rows]

    def save(self, profile: CharacterProfile) -> None:
        profile.updated_at = datetime.now(UTC).replace(tzinfo=None)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO character_profiles
                    (id, campaign_id, character_name, confirmed_traits, known_secrets,
                     last_known_state, profile_summary, source_scene_numbers, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, character_name) DO UPDATE SET
                    confirmed_traits     = excluded.confirmed_traits,
                    known_secrets        = excluded.known_secrets,
                    last_known_state     = excluded.last_known_state,
                    profile_summary      = excluded.profile_summary,
                    source_scene_numbers = excluded.source_scene_numbers,
                    updated_at           = excluded.updated_at
                """,
                (
                    profile.id,
                    profile.campaign_id,
                    profile.character_name,
                    json_encode(profile.confirmed_traits),
                    json_encode(profile.known_secrets),
                    profile.last_known_state,
                    profile.profile_summary,
                    json_encode(profile.source_scene_numbers),
                    profile.updated_at.isoformat(),
                ),
            )

    def delete_campaign(self, campaign_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM character_profiles WHERE campaign_id = ?", (campaign_id,)
            )


def _row_to_profile(row: sqlite3.Row) -> CharacterProfile:
    return CharacterProfile(
        id=row["id"],
        campaign_id=row["campaign_id"],
        character_name=row["character_name"],
        confirmed_traits=json_decode(row["confirmed_traits"]),
        known_secrets=json_decode(row["known_secrets"]),
        last_known_state=row["last_known_state"] or "",
        profile_summary=row["profile_summary"] or "",
        source_scene_numbers=json_decode(row["source_scene_numbers"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def make_profile(campaign_id: str, character_name: str) -> CharacterProfile:
    """Create a blank profile for a new character."""
    return CharacterProfile(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        character_name=character_name,
        confirmed_traits=[],
        known_secrets=[],
        last_known_state="",
        profile_summary="",
        source_scene_numbers=[],
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
