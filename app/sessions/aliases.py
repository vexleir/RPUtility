"""
Character alias store.
Maps alternate names/titles to a canonical character name within a session.
e.g. "Belinda Sossaman" and "The High Priestess" → canonical "Belinda"

The normalization is applied:
  - When displaying relationships and memories (read path)
  - When storing new relationship deltas (write path, in engine)
"""

from __future__ import annotations

import uuid
from typing import Optional

from app.core.database import get_connection


class CharacterAliasStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Read ───────────────────────────────────────────────────────────────

    def get_all(self, session_id: str) -> list[dict]:
        """Return all aliases for a session as list of {canonical, alias}."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT id, canonical_name, alias FROM character_aliases WHERE session_id=? ORDER BY canonical_name, alias",
                (session_id,),
            ).fetchall()
        return [{"id": r["id"], "canonical": r["canonical_name"], "alias": r["alias"]} for r in rows]

    def build_map(self, session_id: str) -> dict[str, str]:
        """
        Return a dict mapping every known alias (lower-cased) → canonical name.
        The canonical name itself is also included as a key mapping to itself.
        """
        rows = self.get_all(session_id)
        result: dict[str, str] = {}
        for r in rows:
            result[r["alias"].lower()] = r["canonical"]
            result[r["canonical"].lower()] = r["canonical"]
        return result

    def resolve(self, session_id: str, name: str) -> str:
        """Resolve a name to its canonical form. Returns name unchanged if no alias found."""
        alias_map = self.build_map(session_id)
        return alias_map.get(name.lower(), name)

    def resolve_list(self, session_id: str, names: list[str]) -> list[str]:
        """Resolve a list of names, deduplicating after normalization."""
        alias_map = self.build_map(session_id)
        seen: set[str] = set()
        result: list[str] = []
        for n in names:
            canonical = alias_map.get(n.lower(), n)
            if canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        return result

    # ── Write ──────────────────────────────────────────────────────────────

    def add_alias(self, session_id: str, canonical_name: str, alias: str) -> dict:
        """Add a single alias. Upserts if alias already exists."""
        entry_id = str(uuid.uuid4())
        with get_connection(self._db) as conn:
            conn.execute(
                """INSERT INTO character_aliases (id, session_id, canonical_name, alias)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id, alias) DO UPDATE SET
                       canonical_name = excluded.canonical_name""",
                (entry_id, session_id, canonical_name.strip(), alias.strip()),
            )
        return {"id": entry_id, "canonical": canonical_name.strip(), "alias": alias.strip()}

    def delete_alias(self, alias_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM character_aliases WHERE id=?", (alias_id,))

    def merge_entities(self, session_id: str, canonical_name: str, aliases: list[str]) -> None:
        """
        Add multiple aliases at once and rewrite existing relationship rows and
        memory entity lists that use any of the aliases to the canonical name.
        """
        for alias in aliases:
            if alias.strip() and alias.strip().lower() != canonical_name.strip().lower():
                self.add_alias(session_id, canonical_name.strip(), alias.strip())

        # Rewrite relationship rows — delete alias rows where canonical pair already
        # exists (to avoid UNIQUE constraint violations), then rename the rest.
        with get_connection(self._db) as conn:
            for alias in aliases:
                a = alias.strip()
                if not a:
                    continue
                # source_entity: drop alias rows whose target already has a canonical row
                conn.execute(
                    """DELETE FROM relationships
                       WHERE session_id=? AND lower(source_entity)=lower(?)
                         AND target_entity IN (
                           SELECT target_entity FROM relationships
                           WHERE session_id=? AND source_entity=?
                         )""",
                    (session_id, a, session_id, canonical_name),
                )
                conn.execute(
                    """UPDATE relationships SET source_entity=?
                       WHERE session_id=? AND lower(source_entity)=lower(?)""",
                    (canonical_name, session_id, a),
                )
                # target_entity: drop alias rows whose source already has a canonical row
                conn.execute(
                    """DELETE FROM relationships
                       WHERE session_id=? AND lower(target_entity)=lower(?)
                         AND source_entity IN (
                           SELECT source_entity FROM relationships
                           WHERE session_id=? AND target_entity=?
                         )""",
                    (session_id, a, session_id, canonical_name),
                )
                conn.execute(
                    """UPDATE relationships SET target_entity=?
                       WHERE session_id=? AND lower(target_entity)=lower(?)""",
                    (canonical_name, session_id, a),
                )

        # Rewrite memory entity JSON arrays
        import json
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT id, entities FROM memories WHERE session_id=?",
                (session_id,),
            ).fetchall()
            alias_lower = {a.strip().lower() for a in aliases}
            for row in rows:
                try:
                    ents = json.loads(row["entities"] or "[]")
                except Exception:
                    continue
                new_ents_set: list[str] = []
                seen: set[str] = set()
                changed = False
                for e in ents:
                    replacement = canonical_name if e.lower() in alias_lower else e
                    if replacement != e:
                        changed = True
                    if replacement not in seen:
                        seen.add(replacement)
                        new_ents_set.append(replacement)
                if changed:
                    conn.execute(
                        "UPDATE memories SET entities=? WHERE id=?",
                        (json.dumps(new_ents_set), row["id"]),
                    )
