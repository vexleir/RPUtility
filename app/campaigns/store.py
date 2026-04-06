"""
Campaign system stores.
All persistent state for the new campaign architecture.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC

from app.core.database import get_connection, json_encode, json_decode
from app.core.models import (
    Campaign, StyleGuide, GenSettings,
    PlayerCharacter, PcDevEntry,
    CampaignWorldFact,
    CampaignPlace,
    NpcCard, NpcStatus, NpcDevEntry, NpcForm,
    NpcRelationship,
    NarrativeThread, ThreadStatus,
    CampaignScene, SceneTurn,
    ChronicleEntry,
    CampaignFaction,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── Campaign ──────────────────────────────────────────────────────────────────

class CampaignStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def create(self, name: str, model_name: str | None = None,
               style_guide: StyleGuide | None = None) -> Campaign:
        now = _now()
        sg = style_guide or StyleGuide()
        c = Campaign(name=name, model_name=model_name, style_guide=sg,
                     created_at=now, updated_at=now)
        with get_connection(self._db) as conn:
            conn.execute(
                "INSERT INTO campaigns (id,name,model_name,style_guide,gen_settings,notes,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (c.id, c.name, c.model_name,
                 json_encode(sg.model_dump()),
                 json_encode(c.gen_settings.model_dump()),
                 c.notes,
                 c.created_at.isoformat(), c.updated_at.isoformat()),
            )
        return c

    def get(self, campaign_id: str) -> Campaign | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
        return _row_to_campaign(row) if row else None

    def list_all(self) -> list[Campaign]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaigns ORDER BY updated_at DESC"
            ).fetchall()
        return [_row_to_campaign(r) for r in rows]

    def update(self, campaign_id: str, **kwargs) -> Campaign:
        c = self.get(campaign_id)
        if not c:
            raise ValueError(f"Campaign not found: {campaign_id}")
        for k, v in kwargs.items():
            if hasattr(c, k) and v is not None:
                setattr(c, k, v)
        c.updated_at = _now()
        with get_connection(self._db) as conn:
            conn.execute(
                "UPDATE campaigns SET name=?,model_name=?,summary_model_name=?,style_guide=?,gen_settings=?,notes=?,cover_image=?,updated_at=? WHERE id=?",
                (c.name, c.model_name, c.summary_model_name,
                 json_encode(c.style_guide.model_dump()),
                 json_encode(c.gen_settings.model_dump()),
                 c.notes, c.cover_image,
                 c.updated_at.isoformat(), c.id),
            )
        return c

    def delete(self, campaign_id: str) -> bool:
        with get_connection(self._db) as conn:
            cur = conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            return cur.rowcount > 0


def _row_to_campaign(row) -> Campaign:
    sg_raw = json_decode(row["style_guide"]) if row["style_guide"] else {}
    keys = row.keys() if hasattr(row, "keys") else []
    gs_raw = json_decode(row["gen_settings"]) if "gen_settings" in keys and row["gen_settings"] else {}
    return Campaign(
        id=row["id"],
        name=row["name"],
        model_name=row["model_name"],
        summary_model_name=row["summary_model_name"] if "summary_model_name" in keys else None,
        style_guide=StyleGuide(**sg_raw) if sg_raw else StyleGuide(),
        gen_settings=GenSettings(**{k: v for k, v in gs_raw.items() if k in GenSettings.model_fields}) if gs_raw else GenSettings(),
        notes=row["notes"] if "notes" in keys else "",
        cover_image=row["cover_image"] if "cover_image" in keys else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Player Character ──────────────────────────────────────────────────────────

class PlayerCharacterStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, pc: PlayerCharacter) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO player_characters
                    (id,campaign_id,name,appearance,personality,background,
                     wants,fears,how_seen,dev_log,portrait_image,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, appearance=excluded.appearance,
                    personality=excluded.personality, background=excluded.background,
                    wants=excluded.wants, fears=excluded.fears,
                    how_seen=excluded.how_seen, dev_log=excluded.dev_log,
                    portrait_image=excluded.portrait_image,
                    updated_at=excluded.updated_at
            """, (pc.id, pc.campaign_id, pc.name, pc.appearance, pc.personality,
                  pc.background, pc.wants, pc.fears, pc.how_seen,
                  json_encode([e.model_dump() for e in pc.dev_log]),
                  pc.portrait_image,
                  pc.created_at.isoformat(), pc.updated_at.isoformat()))

    def get(self, campaign_id: str) -> PlayerCharacter | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM player_characters WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        return _row_to_pc(row) if row else None

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM player_characters WHERE campaign_id=?", (campaign_id,))


def _row_to_pc(row) -> PlayerCharacter:
    keys = row.keys() if hasattr(row, "keys") else []
    raw_dev = json_decode(row["dev_log"]) if "dev_log" in keys and row["dev_log"] else []
    dev_log = [PcDevEntry(**e) if isinstance(e, dict) else e for e in raw_dev]
    return PlayerCharacter(
        id=row["id"], campaign_id=row["campaign_id"],
        name=row["name"], appearance=row["appearance"],
        personality=row["personality"], background=row["background"],
        wants=row["wants"], fears=row["fears"], how_seen=row["how_seen"],
        dev_log=dev_log,
        portrait_image=row["portrait_image"] if "portrait_image" in keys else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── World Facts ───────────────────────────────────────────────────────────────

class WorldFactStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, fact: CampaignWorldFact) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO campaign_world_facts "
                "(id,campaign_id,content,category,priority,trigger_keywords,fact_order,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (fact.id, fact.campaign_id, fact.content, fact.category,
                 fact.priority, json_encode(fact.trigger_keywords),
                 fact.fact_order, fact.created_at.isoformat()),
            )

    def save_many(self, facts: list[CampaignWorldFact]) -> None:
        for f in facts:
            self.save(f)

    def update(self, fact_id: str, content: str | None = None, category: str | None = None,
               priority: str | None = None, trigger_keywords: list | None = None) -> CampaignWorldFact | None:
        """Update fields of an individual fact."""
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_world_facts WHERE id=?", (fact_id,)
            ).fetchone()
            if not row:
                return None
            fact = _row_to_fact(row)
            if content is not None:
                fact.content = content
            if category is not None:
                fact.category = category
            if priority is not None:
                fact.priority = priority
            if trigger_keywords is not None:
                fact.trigger_keywords = trigger_keywords
            conn.execute(
                "UPDATE campaign_world_facts SET content=?,category=?,priority=?,trigger_keywords=? WHERE id=?",
                (fact.content, fact.category, fact.priority,
                 json_encode(fact.trigger_keywords), fact_id),
            )
        return fact

    def get_all(self, campaign_id: str) -> list[CampaignWorldFact]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_world_facts WHERE campaign_id=? ORDER BY fact_order, created_at",
                (campaign_id,),
            ).fetchall()
        return [_row_to_fact(r) for r in rows]

    def delete(self, fact_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_world_facts WHERE id=?", (fact_id,))

    def replace_all(self, campaign_id: str, contents: list[str]) -> list[CampaignWorldFact]:
        """Bulk-replace all facts from a list of plain strings (categories reset to empty)."""
        now = _now()
        facts = [
            CampaignWorldFact(campaign_id=campaign_id, content=c, fact_order=i, created_at=now)
            for i, c in enumerate(contents)
        ]
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_world_facts WHERE campaign_id=?", (campaign_id,))
            for f in facts:
                conn.execute(
                    "INSERT INTO campaign_world_facts (id,campaign_id,content,category,fact_order,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (f.id, f.campaign_id, f.content, f.category, f.fact_order, f.created_at.isoformat()),
                )
        return facts

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_world_facts WHERE campaign_id=?", (campaign_id,))


def _row_to_fact(row) -> CampaignWorldFact:
    keys = row.keys() if hasattr(row, "keys") else []
    raw_kw = json_decode(row["trigger_keywords"]) if "trigger_keywords" in keys and row["trigger_keywords"] else []
    return CampaignWorldFact(
        id=row["id"], campaign_id=row["campaign_id"],
        content=row["content"],
        category=row["category"] if "category" in keys else "",
        priority=row["priority"] if "priority" in keys else "normal",
        trigger_keywords=raw_kw if isinstance(raw_kw, list) else [],
        fact_order=row["fact_order"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ── Places ────────────────────────────────────────────────────────────────────

class CampaignPlaceStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, place: CampaignPlace) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO campaign_places
                    (id,campaign_id,name,description,current_state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    current_state=excluded.current_state, updated_at=excluded.updated_at
            """, (place.id, place.campaign_id, place.name, place.description,
                  place.current_state, place.created_at.isoformat(), place.updated_at.isoformat()))

    def get_all(self, campaign_id: str) -> list[CampaignPlace]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_places WHERE campaign_id=? ORDER BY name",
                (campaign_id,),
            ).fetchall()
        return [_row_to_place(r) for r in rows]

    def get(self, place_id: str) -> CampaignPlace | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_places WHERE id=?", (place_id,)
            ).fetchone()
        return _row_to_place(row) if row else None

    def delete(self, place_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_places WHERE id=?", (place_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_places WHERE campaign_id=?", (campaign_id,))


def _row_to_place(row) -> CampaignPlace:
    return CampaignPlace(
        id=row["id"], campaign_id=row["campaign_id"], name=row["name"],
        description=row["description"], current_state=row["current_state"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── NPC Cards ─────────────────────────────────────────────────────────────────

class NpcCardStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, npc: NpcCard) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO npc_cards
                    (id,campaign_id,name,appearance,personality,role,
                     gender,age,
                     relationship_to_player,current_location,current_state,
                     is_alive,status,status_reason,secrets,
                     short_term_goal,long_term_goal,
                     history_with_player,forms,active_form,
                     dev_log,portrait_image,
                     created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, appearance=excluded.appearance,
                    personality=excluded.personality, role=excluded.role,
                    gender=excluded.gender, age=excluded.age,
                    relationship_to_player=excluded.relationship_to_player,
                    current_location=excluded.current_location,
                    current_state=excluded.current_state,
                    is_alive=excluded.is_alive,
                    status=excluded.status, status_reason=excluded.status_reason,
                    secrets=excluded.secrets,
                    short_term_goal=excluded.short_term_goal,
                    long_term_goal=excluded.long_term_goal,
                    history_with_player=excluded.history_with_player,
                    forms=excluded.forms,
                    active_form=excluded.active_form,
                    dev_log=excluded.dev_log,
                    portrait_image=excluded.portrait_image,
                    updated_at=excluded.updated_at
            """, (npc.id, npc.campaign_id, npc.name, npc.appearance, npc.personality,
                  npc.role, npc.gender, npc.age,
                  npc.relationship_to_player, npc.current_location,
                  npc.current_state, int(npc.status != NpcStatus.DEAD),
                  npc.status.value, npc.status_reason, npc.secrets,
                  npc.short_term_goal, npc.long_term_goal,
                  npc.history_with_player,
                  json_encode([f.model_dump() for f in npc.forms]),
                  npc.active_form,
                  json_encode([e.model_dump() for e in npc.dev_log]),
                  npc.portrait_image,
                  npc.created_at.isoformat(), npc.updated_at.isoformat()))

    def get(self, npc_id: str) -> NpcCard | None:
        with get_connection(self._db) as conn:
            row = conn.execute("SELECT * FROM npc_cards WHERE id=?", (npc_id,)).fetchone()
        return _row_to_npc(row) if row else None

    def get_all(self, campaign_id: str) -> list[NpcCard]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM npc_cards WHERE campaign_id=? ORDER BY name",
                (campaign_id,),
            ).fetchall()
        return [_row_to_npc(r) for r in rows]

    def get_many(self, npc_ids: list[str]) -> list[NpcCard]:
        if not npc_ids:
            return []
        placeholders = ",".join("?" * len(npc_ids))
        with get_connection(self._db) as conn:
            rows = conn.execute(
                f"SELECT * FROM npc_cards WHERE id IN ({placeholders})", npc_ids
            ).fetchall()
        return [_row_to_npc(r) for r in rows]

    def delete(self, npc_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_cards WHERE id=?", (npc_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_cards WHERE campaign_id=?", (campaign_id,))


def _row_to_npc(row) -> NpcCard:
    keys = row.keys() if hasattr(row, "keys") else []
    raw_dev = json_decode(row["dev_log"]) if "dev_log" in keys and row["dev_log"] else []
    dev_log = [NpcDevEntry(**e) if isinstance(e, dict) else e for e in raw_dev]
    raw_forms = json_decode(row["forms"]) if "forms" in keys and row["forms"] else []
    forms = [NpcForm(**f) if isinstance(f, dict) else f for f in raw_forms]
    # Determine status: prefer new status column, fall back to is_alive for old rows
    if "status" in keys and row["status"]:
        status = NpcStatus(row["status"])
    else:
        status = NpcStatus.ACTIVE if bool(row["is_alive"]) else NpcStatus.DEAD
    return NpcCard(
        id=row["id"], campaign_id=row["campaign_id"], name=row["name"],
        appearance=row["appearance"], personality=row["personality"],
        role=row["role"], relationship_to_player=row["relationship_to_player"],
        current_location=row["current_location"], current_state=row["current_state"],
        status=status,
        gender=row["gender"] if "gender" in keys else "",
        age=row["age"] if "age" in keys else "",
        status_reason=row["status_reason"] if "status_reason" in keys else "",
        secrets=row["secrets"] if "secrets" in keys else "",
        short_term_goal=row["short_term_goal"] if "short_term_goal" in keys else "",
        long_term_goal=row["long_term_goal"] if "long_term_goal" in keys else "",
        history_with_player=row["history_with_player"] if "history_with_player" in keys else "",
        forms=forms,
        active_form=row["active_form"] if "active_form" in keys else None,
        dev_log=dev_log,
        portrait_image=row["portrait_image"] if "portrait_image" in keys else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Narrative Threads ─────────────────────────────────────────────────────────

class NarrativeThreadStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, thread: NarrativeThread) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO narrative_threads
                    (id,campaign_id,title,description,status,resolution,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, description=excluded.description,
                    status=excluded.status, resolution=excluded.resolution,
                    updated_at=excluded.updated_at
            """, (thread.id, thread.campaign_id, thread.title, thread.description,
                  thread.status.value, thread.resolution,
                  thread.created_at.isoformat(), thread.updated_at.isoformat()))

    def get_all(self, campaign_id: str) -> list[NarrativeThread]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM narrative_threads WHERE campaign_id=? ORDER BY created_at",
                (campaign_id,),
            ).fetchall()
        return [_row_to_thread(r) for r in rows]

    def get_active(self, campaign_id: str) -> list[NarrativeThread]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM narrative_threads WHERE campaign_id=? AND status='active' ORDER BY created_at",
                (campaign_id,),
            ).fetchall()
        return [_row_to_thread(r) for r in rows]

    def get(self, thread_id: str) -> NarrativeThread | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM narrative_threads WHERE id=?", (thread_id,)
            ).fetchone()
        return _row_to_thread(row) if row else None

    def delete(self, thread_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM narrative_threads WHERE id=?", (thread_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM narrative_threads WHERE campaign_id=?", (campaign_id,))


def _row_to_thread(row) -> NarrativeThread:
    return NarrativeThread(
        id=row["id"], campaign_id=row["campaign_id"],
        title=row["title"], description=row["description"],
        status=ThreadStatus(row["status"]), resolution=row["resolution"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Scenes ────────────────────────────────────────────────────────────────────

class SceneStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, scene: CampaignScene) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO campaign_scenes
                    (id,campaign_id,scene_number,title,location,npc_ids,intent,tone,
                     turns,proposed_summary,confirmed_summary,confirmed,
                     allow_unselected_npcs,scene_image,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, location=excluded.location,
                    npc_ids=excluded.npc_ids, intent=excluded.intent, tone=excluded.tone,
                    turns=excluded.turns, proposed_summary=excluded.proposed_summary,
                    confirmed_summary=excluded.confirmed_summary,
                    confirmed=excluded.confirmed,
                    allow_unselected_npcs=excluded.allow_unselected_npcs,
                    scene_image=excluded.scene_image,
                    updated_at=excluded.updated_at
            """, (
                scene.id, scene.campaign_id, scene.scene_number, scene.title,
                scene.location, json_encode([n for n in scene.npc_ids]),
                scene.intent, scene.tone,
                json_encode([t.model_dump() for t in scene.turns]),
                scene.proposed_summary, scene.confirmed_summary,
                int(scene.confirmed),
                int(scene.allow_unselected_npcs),
                scene.scene_image,
                scene.created_at.isoformat(), scene.updated_at.isoformat(),
            ))

    def get(self, scene_id: str) -> CampaignScene | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_scenes WHERE id=?", (scene_id,)
            ).fetchone()
        return _row_to_scene(row) if row else None

    def get_all(self, campaign_id: str) -> list[CampaignScene]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_scenes WHERE campaign_id=? ORDER BY scene_number",
                (campaign_id,),
            ).fetchall()
        return [_row_to_scene(r) for r in rows]

    def get_confirmed(self, campaign_id: str) -> list[CampaignScene]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_scenes WHERE campaign_id=? AND confirmed=1 ORDER BY scene_number",
                (campaign_id,),
            ).fetchall()
        return [_row_to_scene(r) for r in rows]

    def get_active(self, campaign_id: str) -> CampaignScene | None:
        """Return the most recent unconfirmed scene, or None."""
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_scenes WHERE campaign_id=? AND confirmed=0 "
                "ORDER BY scene_number DESC LIMIT 1",
                (campaign_id,),
            ).fetchone()
        return _row_to_scene(row) if row else None

    def next_scene_number(self, campaign_id: str) -> int:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT MAX(scene_number) as mx FROM campaign_scenes WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        return (row["mx"] or 0) + 1

    def delete(self, scene_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_scenes WHERE id=?", (scene_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_scenes WHERE campaign_id=?", (campaign_id,))


def _row_to_scene(row) -> CampaignScene:
    raw_turns = json_decode(row["turns"])
    turns = [SceneTurn(**t) for t in raw_turns] if raw_turns else []
    return CampaignScene(
        id=row["id"], campaign_id=row["campaign_id"],
        scene_number=row["scene_number"], title=row["title"],
        location=row["location"],
        npc_ids=json_decode(row["npc_ids"]),
        intent=row["intent"], tone=row["tone"], turns=turns,
        proposed_summary=row["proposed_summary"],
        confirmed_summary=row["confirmed_summary"],
        confirmed=bool(row["confirmed"]),
        allow_unselected_npcs=bool(row["allow_unselected_npcs"]) if "allow_unselected_npcs" in row.keys() else False,
        scene_image=row["scene_image"] if "scene_image" in row.keys() else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Chronicle ─────────────────────────────────────────────────────────────────

class ChronicleStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, entry: ChronicleEntry) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO chronicle_entries
                    (id,campaign_id,scene_range_start,scene_range_end,content,confirmed,created_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    content=excluded.content, confirmed=excluded.confirmed
            """, (entry.id, entry.campaign_id, entry.scene_range_start,
                  entry.scene_range_end, entry.content, int(entry.confirmed),
                  entry.created_at.isoformat()))

    def get_all(self, campaign_id: str) -> list[ChronicleEntry]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM chronicle_entries WHERE campaign_id=? ORDER BY scene_range_start",
                (campaign_id,),
            ).fetchall()
        return [_row_to_chronicle(r) for r in rows]

    def get(self, entry_id: str) -> ChronicleEntry | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM chronicle_entries WHERE id=?", (entry_id,)
            ).fetchone()
        return _row_to_chronicle(row) if row else None

    def update_content(self, entry_id: str, content: str) -> ChronicleEntry | None:
        """Update the text content of an existing chronicle entry."""
        with get_connection(self._db) as conn:
            conn.execute(
                "UPDATE chronicle_entries SET content=? WHERE id=?", (content, entry_id)
            )
        return self.get(entry_id)

    def delete(self, entry_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM chronicle_entries WHERE id=?", (entry_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM chronicle_entries WHERE campaign_id=?", (campaign_id,))


def _row_to_chronicle(row) -> ChronicleEntry:
    return ChronicleEntry(
        id=row["id"], campaign_id=row["campaign_id"],
        scene_range_start=row["scene_range_start"],
        scene_range_end=row["scene_range_end"],
        content=row["content"], confirmed=bool(row["confirmed"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ── Factions ──────────────────────────────────────────────────────────────────

class CampaignFactionStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, faction: CampaignFaction) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO campaign_factions
                    (id,campaign_id,name,description,goals,methods,
                     standing_with_player,relationship_notes,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    goals=excluded.goals, methods=excluded.methods,
                    standing_with_player=excluded.standing_with_player,
                    relationship_notes=excluded.relationship_notes,
                    updated_at=excluded.updated_at
            """, (faction.id, faction.campaign_id, faction.name, faction.description,
                  faction.goals, faction.methods,
                  faction.standing_with_player, faction.relationship_notes,
                  faction.created_at.isoformat(), faction.updated_at.isoformat()))

    def get_all(self, campaign_id: str) -> list[CampaignFaction]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_factions WHERE campaign_id=? ORDER BY name",
                (campaign_id,),
            ).fetchall()
        return [_row_to_faction(r) for r in rows]

    def get(self, faction_id: str) -> CampaignFaction | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM campaign_factions WHERE id=?", (faction_id,)
            ).fetchone()
        return _row_to_faction(row) if row else None

    def delete(self, faction_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_factions WHERE id=?", (faction_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM campaign_factions WHERE campaign_id=?", (campaign_id,))


def _row_to_faction(row) -> CampaignFaction:
    keys = row.keys() if hasattr(row, "keys") else []
    return CampaignFaction(
        id=row["id"], campaign_id=row["campaign_id"], name=row["name"],
        description=row["description"], goals=row["goals"], methods=row["methods"],
        standing_with_player=row["standing_with_player"] if "standing_with_player" in keys else "",
        relationship_notes=row["relationship_notes"] if "relationship_notes" in keys else "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── NPC Relationships ─────────────────────────────────────────────────────────

class NpcRelationshipStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, rel: NpcRelationship) -> None:
        now = _now()
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT INTO npc_relationships
                    (id,campaign_id,npc_id_a,npc_id_b,dynamic,trust,hostility,history,
                     created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(campaign_id,npc_id_a,npc_id_b) DO UPDATE SET
                    dynamic=excluded.dynamic, trust=excluded.trust,
                    hostility=excluded.hostility, history=excluded.history,
                    updated_at=excluded.updated_at
            """, (rel.id, rel.campaign_id, rel.npc_id_a, rel.npc_id_b,
                  rel.dynamic, rel.trust, rel.hostility, rel.history,
                  rel.created_at.isoformat(), now.isoformat()))

    def get_all(self, campaign_id: str) -> list[NpcRelationship]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM npc_relationships WHERE campaign_id=? ORDER BY npc_id_a, npc_id_b",
                (campaign_id,),
            ).fetchall()
        return [_row_to_rel(r) for r in rows]

    def get(self, rel_id: str) -> NpcRelationship | None:
        with get_connection(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM npc_relationships WHERE id=?", (rel_id,)
            ).fetchone()
        return _row_to_rel(row) if row else None

    def get_for_npcs(self, campaign_id: str, npc_ids: list[str]) -> list[NpcRelationship]:
        """Return all relationships where both NPCs are in npc_ids."""
        if not npc_ids:
            return []
        all_rels = self.get_all(campaign_id)
        id_set = set(npc_ids)
        return [r for r in all_rels if r.npc_id_a in id_set and r.npc_id_b in id_set]

    def delete(self, rel_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_relationships WHERE id=?", (rel_id,))

    def delete_campaign(self, campaign_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute("DELETE FROM npc_relationships WHERE campaign_id=?", (campaign_id,))


def _row_to_rel(row) -> NpcRelationship:
    return NpcRelationship(
        id=row["id"], campaign_id=row["campaign_id"],
        npc_id_a=row["npc_id_a"], npc_id_b=row["npc_id_b"],
        dynamic=row["dynamic"], trust=row["trust"],
        hostility=row["hostility"], history=row["history"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
