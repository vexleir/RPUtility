"""
Quest log store.
Quests have embedded QuestStage objects stored as a JSON blob.
Status: hidden | active | completed | failed
"""

from __future__ import annotations

import json
from datetime import datetime

from app.core.database import get_connection, json_decode, json_encode
from app.core.models import Quest, QuestStage, QuestStatus, ImportanceLevel


class QuestStore:
    def __init__(self, db_path: str):
        self._db = db_path

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self, quest: Quest) -> None:
        stages_json = json.dumps(
            [s.model_dump() for s in quest.stages], ensure_ascii=False
        )
        with get_connection(self._db) as conn:
            conn.execute(
                """
                INSERT INTO quests
                    (id, session_id, title, description, status, giver_npc_name,
                     location_name, reward_notes, importance, stages, tags,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title           = excluded.title,
                    description     = excluded.description,
                    status          = excluded.status,
                    giver_npc_name  = excluded.giver_npc_name,
                    location_name   = excluded.location_name,
                    reward_notes    = excluded.reward_notes,
                    importance      = excluded.importance,
                    stages          = excluded.stages,
                    tags            = excluded.tags,
                    updated_at      = excluded.updated_at
                """,
                (
                    quest.id,
                    quest.session_id,
                    quest.title,
                    quest.description,
                    quest.status.value,
                    quest.giver_npc_name,
                    quest.location_name,
                    quest.reward_notes,
                    quest.importance.value,
                    stages_json,
                    json_encode(quest.tags),
                    quest.created_at.isoformat(),
                    quest.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, quest_id: str) -> Quest | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM quests WHERE id = ?", (quest_id,)
            ).fetchone()
        return _row_to_quest(row) if row else None

    def get_all(self, session_id: str) -> list[Quest]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM quests WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_quest(r) for r in rows]

    def get_active(self, session_id: str) -> list[Quest]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM quests WHERE session_id = ? AND status = 'active' ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [_row_to_quest(r) for r in rows]

    def delete(self, quest_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM quests WHERE id = ?", (quest_id,))
            conn.commit()

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM quests WHERE session_id = ?", (session_id,))
            conn.commit()


# ── Row deserialization ────────────────────────────────────────────────────────

def _row_to_quest(row) -> Quest:
    stages_raw = json.loads(row["stages"] or "[]")
    stages = [
        QuestStage(
            id=s.get("id", ""),
            description=s.get("description", ""),
            completed=bool(s.get("completed", False)),
            order=int(s.get("order", 0)),
        )
        for s in stages_raw
    ]
    return Quest(
        id=row["id"],
        session_id=row["session_id"],
        title=row["title"],
        description=row["description"] or "",
        status=QuestStatus(row["status"]),
        giver_npc_name=row["giver_npc_name"] or "",
        location_name=row["location_name"] or "",
        reward_notes=row["reward_notes"] or "",
        importance=ImportanceLevel(row["importance"]),
        stages=stages,
        tags=json_decode(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
