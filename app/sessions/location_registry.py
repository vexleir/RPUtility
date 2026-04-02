"""
Location Registry store — persists visited/known locations for a session.
"""

from __future__ import annotations

from datetime import datetime, UTC

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import LocationEntry


class LocationRegistryStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    # ── Write ──────────────────────────────────────────────────────────────

    def save(self, loc: LocationEntry) -> None:
        """Insert or replace a location entry (upsert by id)."""
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO location_registry
                    (id, session_id, name, description, atmosphere, notes,
                     tags, visit_count, first_visited, last_visited)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    atmosphere=excluded.atmosphere,
                    notes=excluded.notes,
                    tags=excluded.tags,
                    visit_count=excluded.visit_count,
                    last_visited=excluded.last_visited
            """, (
                loc.id, loc.session_id, loc.name,
                loc.description, loc.atmosphere, loc.notes,
                json_encode(loc.tags), loc.visit_count,
                loc.first_visited.isoformat(), loc.last_visited.isoformat(),
            ))

    def record_visit(self, session_id: str, name: str) -> LocationEntry:
        """
        Increment visit_count and update last_visited for a named location.
        Creates a new entry if the location is not yet registered.
        """
        existing = self.get_by_name(session_id, name)
        now = datetime.now(UTC).replace(tzinfo=None)
        if existing:
            existing.visit_count += 1
            existing.last_visited = now
            self.save(existing)
            return existing
        entry = LocationEntry(
            session_id=session_id,
            name=name,
            visit_count=1,
            first_visited=now,
            last_visited=now,
        )
        self.save(entry)
        return entry

    def delete(self, location_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM location_registry WHERE id=?", (location_id,))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM location_registry WHERE session_id=?", (session_id,))

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, location_id: str) -> LocationEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM location_registry WHERE id=?", (location_id,)
            ).fetchone()
        return _row_to_loc(row) if row else None

    def get_by_name(self, session_id: str, name: str) -> LocationEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM location_registry WHERE session_id=? AND LOWER(name)=LOWER(?)",
                (session_id, name),
            ).fetchone()
        return _row_to_loc(row) if row else None

    def get_all(self, session_id: str) -> list[LocationEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM location_registry WHERE session_id=? ORDER BY last_visited DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_loc(r) for r in rows]


def _row_to_loc(row) -> LocationEntry:
    return LocationEntry(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        description=row["description"] or "",
        atmosphere=row["atmosphere"] or "",
        notes=row["notes"] or "",
        tags=json_decode(row["tags"]),
        visit_count=row["visit_count"],
        first_visited=datetime.fromisoformat(row["first_visited"]),
        last_visited=datetime.fromisoformat(row["last_visited"]),
    )
