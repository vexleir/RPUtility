"""
Campaign system API routes.
Registered as a sub-router in server.py.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, UTC
from typing import Optional

def _new_id() -> str:
    return str(_uuid.uuid4())

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import config
from app.core.database import ensure_db
from app.core.models import (
    StyleGuide, PlayerCharacter, PcDevEntry,
    CampaignPlace, NpcCard, NpcStatus, NpcDevEntry,
    NpcRelationship,
    NarrativeThread, ThreadStatus,
    CampaignScene, CampaignFaction, SceneTurn, ChronicleEntry,
)
from app.campaigns.store import (
    CampaignStore,
    PlayerCharacterStore,
    WorldFactStore,
    CampaignPlaceStore,
    NpcCardStore,
    NarrativeThreadStore,
    SceneStore,
    ChronicleStore,
    CampaignFactionStore,
    NpcRelationshipStore,
)
from app.campaigns.world_builder import WorldBuilder, _dict_to_world_build_result
from app.campaigns.scene_prompter import build_scene_messages

log = logging.getLogger("rp_utility")

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

# ── Store accessors ────────────────────────────────────────────────────────────

def _db() -> str:
    ensure_db(config.db_path)
    return config.db_path

def _campaigns():           return CampaignStore(_db())
def _pcs():                 return PlayerCharacterStore(_db())
def _facts():               return WorldFactStore(_db())
def _places():              return CampaignPlaceStore(_db())
def _npcs():                return NpcCardStore(_db())
def _threads():             return NarrativeThreadStore(_db())
def _scenes():              return SceneStore(_db())
def _chronicle():           return ChronicleStore(_db())
def _factions():            return CampaignFactionStore(_db())
def _npc_relationships():   return NpcRelationshipStore(_db())

def _world_builder() -> WorldBuilder:
    return WorldBuilder(
        base_url=config.ollama_base_url,
        model=config.ollama_model,
    )

# ── Request models ─────────────────────────────────────────────────────────────

class CreateCampaignRequest(BaseModel):
    name: str
    model_name: Optional[str] = None
    prose_style: str = ""
    tone: str = ""
    themes: list[str] = []

class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    summary_model_name: Optional[str] = None
    prose_style: Optional[str] = None
    tone: Optional[str] = None
    themes: Optional[list[str]] = None
    magic_system: Optional[str] = None
    notes: Optional[str] = None
    # Gen settings
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None
    context_window: Optional[int] = None

class SavePlayerCharacterRequest(BaseModel):
    name: str = "The Protagonist"
    appearance: str = ""
    personality: str = ""
    background: str = ""
    wants: str = ""
    fears: str = ""
    how_seen: str = ""
    # dev_log is managed via POST /player-character/dev-log; not accepted on PUT


class AppendDevLogRequest(BaseModel):
    note: str
    scene_number: int = 0

class ReplaceWorldFactsRequest(BaseModel):
    facts: list[str]

class SavePlaceRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    current_state: str = ""

class SaveNpcRequest(BaseModel):
    id: Optional[str] = None
    name: str
    appearance: str = ""
    personality: str = ""
    role: str = ""
    gender: str = ""
    age: str = ""
    relationship_to_player: str = ""
    current_location: str = ""
    current_state: str = ""
    is_alive: bool = True          # legacy compat — ignored if status is set
    status: str = "active"
    status_reason: str = ""
    secrets: str = ""
    short_term_goal: str = ""
    long_term_goal: str = ""
    history_with_player: str = ""
    forms: list[dict] = []         # list of NpcForm dicts
    active_form: Optional[str] = None


class AppendNpcDevLogRequest(BaseModel):
    note: str
    scene_number: int = 0


class SaveNpcRelationshipRequest(BaseModel):
    id: Optional[str] = None
    npc_id_a: str
    npc_id_b: str
    dynamic: str = ""
    trust: str = ""
    hostility: str = ""
    history: str = ""

class SaveThreadRequest(BaseModel):
    id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"
    resolution: str = ""

class SaveFactionRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    goals: str = ""
    methods: str = ""
    standing_with_player: str = ""
    relationship_notes: str = ""

class CreateSceneRequest(BaseModel):
    title: str = ""
    location: str = ""
    npc_ids: list[str] = []
    intent: str = ""
    tone: str = ""
    allow_unselected_npcs: bool = False

class PatchSceneRequest(BaseModel):
    npc_ids: Optional[list[str]] = None
    title: Optional[str] = None
    location: Optional[str] = None
    tone: Optional[str] = None

class AddSceneTurnRequest(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ConfirmSceneRequest(BaseModel):
    proposed_summary: str = ""

class GenerateWorldRequest(BaseModel):
    description: str
    model_name: Optional[str] = None  # override model for this generation

class RefineWorldRequest(BaseModel):
    current: dict  # WorldBuildResult as dict
    section: str
    instructions: str
    model_name: Optional[str] = None

class ConfirmWorldRequest(BaseModel):
    world: dict  # WorldBuildResult as dict
    campaign_name: str
    model_name: Optional[str] = None
    prose_style: str = ""
    tone: str = ""


# ── Campaign CRUD ──────────────────────────────────────────────────────────────

@router.get("")
def list_campaigns():
    campaigns = _campaigns().list_all()
    return [_campaign_dict(c) for c in campaigns]


@router.post("", status_code=201)
def create_campaign(req: CreateCampaignRequest):
    sg = StyleGuide(
        prose_style=req.prose_style,
        tone=req.tone,
        themes=req.themes,
    )
    c = _campaigns().create(name=req.name, model_name=req.model_name, style_guide=sg)
    return _campaign_dict(c)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str):
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return _campaign_dict(c)


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: str, req: UpdateCampaignRequest):
    store = _campaigns()
    c = store.get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    updates: dict = {}
    if req.name is not None:                 updates["name"] = req.name
    if req.model_name is not None:           updates["model_name"] = req.model_name
    if req.summary_model_name is not None:   updates["summary_model_name"] = req.summary_model_name
    if any(f is not None for f in [req.prose_style, req.tone, req.themes, req.magic_system]):
        sg = c.style_guide
        if req.prose_style is not None:   sg = sg.model_copy(update={"prose_style": req.prose_style})
        if req.tone is not None:          sg = sg.model_copy(update={"tone": req.tone})
        if req.themes is not None:        sg = sg.model_copy(update={"themes": req.themes})
        if req.magic_system is not None:  sg = sg.model_copy(update={"magic_system": req.magic_system})
        updates["style_guide"] = sg
    if req.notes is not None:
        updates["notes"] = req.notes
    _GS_FIELDS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "max_tokens", "seed", "context_window")
    if any(getattr(req, f) is not None for f in _GS_FIELDS):
        gs = c.gen_settings
        patch = {f: getattr(req, f) for f in _GS_FIELDS if getattr(req, f) is not None}
        gs = gs.model_copy(update=patch)
        updates["gen_settings"] = gs
    updated = store.update(campaign_id, **updates)
    if not updated:
        raise HTTPException(404, "Campaign not found")
    return _campaign_dict(updated)


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str):
    deleted = _campaigns().delete(campaign_id)
    if not deleted:
        raise HTTPException(404, "Campaign not found")


# ── Player Character ───────────────────────────────────────────────────────────

@router.get("/{campaign_id}/player-character")
def get_player_character(campaign_id: str):
    pc = _pcs().get(campaign_id)
    if not pc:
        return {}
    return _pc_dict(pc)


@router.put("/{campaign_id}/player-character")
def save_player_character(campaign_id: str, req: SavePlayerCharacterRequest):
    _require_campaign(campaign_id)
    existing = _pcs().get(campaign_id)
    pc = PlayerCharacter(
        id=existing.id if existing else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        appearance=req.appearance,
        personality=req.personality,
        background=req.background,
        wants=req.wants,
        fears=req.fears,
        how_seen=req.how_seen,
        dev_log=existing.dev_log if existing else [],   # preserve existing log
    )
    _pcs().save(pc)
    return _pc_dict(pc)


@router.post("/{campaign_id}/player-character/dev-log", status_code=201)
def append_pc_dev_log(campaign_id: str, req: AppendDevLogRequest):
    """Append a development log entry to the player character."""
    store = _pcs()
    pc = store.get(campaign_id)
    if not pc:
        raise HTTPException(404, "Player character not found")
    pc.dev_log.append(PcDevEntry(scene_number=req.scene_number, note=req.note))
    store.save(pc)
    return _pc_dict(pc)


# ── World Facts ────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/world-facts")
def get_world_facts(campaign_id: str):
    facts = _facts().get_all(campaign_id)
    return [_fact_dict(f) for f in facts]


@router.put("/{campaign_id}/world-facts")
def replace_world_facts(campaign_id: str, req: ReplaceWorldFactsRequest):
    _require_campaign(campaign_id)
    saved = _facts().replace_all(campaign_id, req.facts)
    return [_fact_dict(f) for f in saved]


@router.delete("/{campaign_id}/world-facts/{fact_id}", status_code=204)
def delete_world_fact(campaign_id: str, fact_id: str):
    _facts().delete(fact_id)


class PatchWorldFactRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None          # "critical" | "normal" | "background"
    trigger_keywords: Optional[list[str]] = None


@router.patch("/{campaign_id}/world-facts/{fact_id}")
def patch_world_fact(campaign_id: str, fact_id: str, req: PatchWorldFactRequest):
    """Update content, category, priority, and/or trigger keywords of a single world fact."""
    updated = _facts().update(
        fact_id,
        content=req.content,
        category=req.category,
        priority=req.priority,
        trigger_keywords=req.trigger_keywords,
    )
    if not updated:
        raise HTTPException(404, "Fact not found")
    return _fact_dict(updated)


# ── Campaign notes (player scratchpad) ────────────────────────────────────────

class PatchNotesRequest(BaseModel):
    notes: str


@router.patch("/{campaign_id}/notes")
def patch_campaign_notes(campaign_id: str, req: PatchNotesRequest):
    """Save the player scratchpad notes for a campaign."""
    updated = _campaigns().update(campaign_id, notes=req.notes)
    return {"notes": updated.notes}


# ── Places ─────────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/places")
def get_places(campaign_id: str):
    return [_place_dict(p) for p in _places().get_all(campaign_id)]


@router.put("/{campaign_id}/places")
def save_place(campaign_id: str, req: SavePlaceRequest):
    _require_campaign(campaign_id)
    existing = _places().get(req.id) if req.id else None
    p = CampaignPlace(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        description=req.description,
        current_state=req.current_state,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _places().save(p)
    return _place_dict(p)


@router.delete("/{campaign_id}/places/{place_id}", status_code=204)
def delete_place(campaign_id: str, place_id: str):
    _places().delete(place_id)


# ── NPC Cards ──────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/npcs")
def get_npcs(campaign_id: str):
    return [_npc_dict(n) for n in _npcs().get_all(campaign_id)]


@router.put("/{campaign_id}/npcs")
def save_npc(campaign_id: str, req: SaveNpcRequest):
    _require_campaign(campaign_id)
    existing = _npcs().get(req.id) if req.id else None
    # Resolve status: prefer explicit status field; fall back to legacy is_alive
    try:
        status = NpcStatus(req.status)
    except ValueError:
        status = NpcStatus.ACTIVE
    if not req.is_alive and status == NpcStatus.ACTIVE:
        status = NpcStatus.DEAD
    # Parse forms list from request dicts
    from app.core.models import NpcForm as _NpcForm
    forms = [_NpcForm(**f) if isinstance(f, dict) else f for f in (req.forms or [])]

    n = NpcCard(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        appearance=req.appearance,
        personality=req.personality,
        role=req.role,
        gender=req.gender,
        age=req.age,
        relationship_to_player=req.relationship_to_player,
        current_location=req.current_location,
        current_state=req.current_state,
        status=status,
        status_reason=req.status_reason,
        secrets=req.secrets,
        short_term_goal=req.short_term_goal,
        long_term_goal=req.long_term_goal,
        history_with_player=req.history_with_player,
        forms=forms,
        active_form=req.active_form,
        portrait_image=existing.portrait_image if existing else None,
        dev_log=existing.dev_log if existing else [],
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _npcs().save(n)
    return _npc_dict(n)


@router.post("/{campaign_id}/npcs/{npc_id}/dev-log", status_code=201)
def append_npc_dev_log(campaign_id: str, npc_id: str, req: AppendNpcDevLogRequest):
    """Append a development log entry to an NPC card."""
    store = _npcs()
    n = store.get(npc_id)
    if not n or n.campaign_id != campaign_id:
        raise HTTPException(404, "NPC not found")
    n.dev_log.append(NpcDevEntry(scene_number=req.scene_number, note=req.note))
    store.save(n)
    return _npc_dict(n)


@router.delete("/{campaign_id}/npcs/{npc_id}", status_code=204)
def delete_npc(campaign_id: str, npc_id: str):
    _npcs().delete(npc_id)
    # Orphaned relationships (pointing to the deleted NPC) are benign;
    # they will not appear in scene prompts and can be removed manually.


# ── NPC Relationships ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/npc-relationships")
def get_npc_relationships(campaign_id: str):
    return [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)]


@router.put("/{campaign_id}/npc-relationships")
def save_npc_relationship(campaign_id: str, req: SaveNpcRelationshipRequest):
    _require_campaign(campaign_id)
    existing = _npc_relationships().get(req.id) if req.id else None
    r = NpcRelationship(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        npc_id_a=req.npc_id_a,
        npc_id_b=req.npc_id_b,
        dynamic=req.dynamic,
        trust=req.trust,
        hostility=req.hostility,
        history=req.history,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _npc_relationships().save(r)
    return _rel_dict(r)


@router.delete("/{campaign_id}/npc-relationships/{rel_id}", status_code=204)
def delete_npc_relationship(campaign_id: str, rel_id: str):
    store = _npc_relationships()
    r = store.get(rel_id)
    if not r or r.campaign_id != campaign_id:
        raise HTTPException(404, "Relationship not found")
    store.delete(rel_id)


# ── Narrative Threads ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/threads")
def get_threads(campaign_id: str):
    return [_thread_dict(t) for t in _threads().get_all(campaign_id)]


@router.put("/{campaign_id}/threads")
def save_thread(campaign_id: str, req: SaveThreadRequest):
    _require_campaign(campaign_id)
    existing = _threads().get(req.id) if req.id else None
    t = NarrativeThread(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        title=req.title,
        description=req.description,
        status=ThreadStatus(req.status),
        resolution=req.resolution,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _threads().save(t)
    return _thread_dict(t)


@router.delete("/{campaign_id}/threads/{thread_id}", status_code=204)
def delete_thread(campaign_id: str, thread_id: str):
    _threads().delete(thread_id)


# ── Factions ───────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/factions")
def get_factions(campaign_id: str):
    return [_faction_dict(f) for f in _factions().get_all(campaign_id)]


@router.put("/{campaign_id}/factions")
def save_faction(campaign_id: str, req: SaveFactionRequest):
    _require_campaign(campaign_id)
    existing = _factions().get(req.id) if req.id else None
    f = CampaignFaction(
        id=req.id if req.id else _new_id(),
        campaign_id=campaign_id,
        name=req.name,
        description=req.description,
        goals=req.goals,
        methods=req.methods,
        standing_with_player=req.standing_with_player,
        relationship_notes=req.relationship_notes,
        created_at=existing.created_at if existing else datetime.now(UTC).replace(tzinfo=None),
    )
    _factions().save(f)
    return _faction_dict(f)


@router.delete("/{campaign_id}/factions/{faction_id}", status_code=204)
def delete_faction(campaign_id: str, faction_id: str):
    _factions().delete(faction_id)


# ── Scenes ─────────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/scenes")
def get_scenes(campaign_id: str):
    return [_scene_dict(s) for s in _scenes().get_all(campaign_id)]


@router.get("/{campaign_id}/scenes/active")
def get_active_scene(campaign_id: str):
    scene = _scenes().get_active(campaign_id)
    if not scene:
        return None
    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes", status_code=201)
def create_scene(campaign_id: str, req: CreateSceneRequest):
    _require_campaign(campaign_id)
    scene_num = _scenes().next_scene_number(campaign_id)
    s = CampaignScene(
        campaign_id=campaign_id,
        scene_number=scene_num,
        title=req.title,
        location=req.location,
        npc_ids=req.npc_ids,
        intent=req.intent,
        tone=req.tone,
        allow_unselected_npcs=req.allow_unselected_npcs,
    )
    _scenes().save(s)
    return _scene_dict(s)


@router.patch("/{campaign_id}/scenes/{scene_id}")
def patch_scene(campaign_id: str, scene_id: str, req: PatchSceneRequest):
    """Update mutable scene fields (npc_ids, title, location, tone) mid-scene."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if req.npc_ids is not None:  scene.npc_ids = req.npc_ids
    if req.title is not None:    scene.title = req.title
    if req.location is not None: scene.location = req.location
    if req.tone is not None:     scene.tone = req.tone
    store.save(scene)
    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes/{scene_id}/turns", status_code=201)
def add_scene_turn(campaign_id: str, scene_id: str, req: AddSceneTurnRequest):
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")

    scene.turns.append(SceneTurn(role=req.role, content=req.content))
    store.save(scene)
    return _scene_dict(scene)


@router.delete("/{campaign_id}/scenes/{scene_id}/turns/last")
def undo_last_turns(campaign_id: str, scene_id: str):
    """Remove the last AI response and its preceding user turn (undo one exchange)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot undo turns in a confirmed scene")
    if not scene.turns:
        raise HTTPException(400, "No turns to undo")
    # Pop trailing assistant turn, then any preceding user turn
    if scene.turns and scene.turns[-1].role == "assistant":
        scene.turns.pop()
    if scene.turns and scene.turns[-1].role == "user":
        scene.turns.pop()
    store.save(scene)
    return _scene_dict(scene)


@router.delete("/{campaign_id}/scenes/{scene_id}", status_code=204)
def delete_scene(campaign_id: str, scene_id: str):
    """Delete an unconfirmed scene and all its turns."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot delete a confirmed scene")
    store.delete(scene_id)


@router.put("/{campaign_id}/scenes/{scene_id}/turns/last-assistant")
def replace_last_assistant_turn(campaign_id: str, scene_id: str, req: ReplaceLastAssistantRequest):
    """Replace the content of the last assistant turn (used by the regenerate alternative selector)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Cannot modify a confirmed scene")
    for i in range(len(scene.turns) - 1, -1, -1):
        if scene.turns[i].role == "assistant":
            scene.turns[i] = SceneTurn(role="assistant", content=req.content)
            store.save(scene)
            return {"ok": True}
    raise HTTPException(400, "No assistant turn found")


@router.post("/{campaign_id}/scenes/{scene_id}/regenerate")
def scene_regenerate_stream(campaign_id: str, scene_id: str, req: SceneRegenerateRequest):
    """
    Stream a new AI response for the same user message as the last exchange.
    The previous assistant turn is replaced; the user turn is preserved.
    """
    import json as _json
    import httpx

    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")
    if not scene.turns or scene.turns[-1].role != "assistant":
        raise HTTPException(400, "Last turn is not an assistant turn")

    # Strip the last assistant turn; extract the preceding user message
    scene.turns.pop()
    if not scene.turns or scene.turns[-1].role != "user":
        raise HTTPException(400, "No preceding user turn found")
    last_user_content = scene.turns.pop().content

    # Load context
    pc = _pcs().get(campaign_id)
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = []
    npc_rels_list = []
    if scene.npc_ids:
        npc_list = _npcs().get_many(scene.npc_ids)
        npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []

    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=last_user_content,
        user_name="Player",
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    # Re-store the user turn before streaming begins
    scene.turns.append(SceneTurn(role="user", content=last_user_content))

    def _stream():
        full_response: list[str] = []
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        scene.turns.append(SceneTurn(role="assistant", content="".join(full_response)))
        scene_store.save(scene)

    return StreamingResponse(_stream(), media_type="text/plain")


@router.get("/{campaign_id}/scenes/{scene_id}/prompt-preview")
def get_prompt_preview(campaign_id: str, scene_id: str):
    """Return the rendered system prompt for the current scene state (debug tool)."""
    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    pc = _pcs().get(campaign_id)
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids) if scene.npc_ids else []
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []

    messages = build_scene_messages(
        campaign=campaign, player_character=pc, world_facts=world_facts_list,
        npcs_in_scene=npc_list, active_threads=threads_list, chronicle=chronicle_list,
        places=places_list, factions=factions_list, npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list, allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene, user_message="[preview only]", user_name="",
    )
    system_prompt = messages[0]["content"] if messages else ""
    return {"system_prompt": system_prompt, "total_messages": len(messages)}


@router.post("/{campaign_id}/scenes/{scene_id}/confirm")
def confirm_scene(campaign_id: str, scene_id: str, req: ConfirmSceneRequest):
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    summary = req.proposed_summary or scene.proposed_summary
    scene.proposed_summary = summary
    scene.confirmed_summary = summary
    scene.confirmed = True
    store.save(scene)

    # Upsert chronicle entry — update existing if one exists for this scene number
    if summary:
        _upsert_chronicle(campaign_id, scene.scene_number, summary)

    return _scene_dict(scene)


@router.post("/{campaign_id}/scenes/{scene_id}/reopen")
def reopen_scene(campaign_id: str, scene_id: str):
    """Reopen a confirmed scene so turns can be added or edited."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if not scene.confirmed:
        raise HTTPException(400, "Scene is not confirmed")
    scene.confirmed = False
    store.save(scene)
    return _scene_dict(scene)


class UpdateSummaryRequest(BaseModel):
    summary: str


@router.patch("/{campaign_id}/scenes/{scene_id}/summary")
def update_scene_summary(campaign_id: str, scene_id: str, req: UpdateSummaryRequest):
    """Update the confirmed summary text of a scene (confirmed or not)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    scene.confirmed_summary = req.summary
    scene.proposed_summary = req.summary
    store.save(scene)
    # Keep chronicle in sync
    if req.summary:
        _upsert_chronicle(campaign_id, scene.scene_number, req.summary)
    return _scene_dict(scene)


class EditTurnRequest(BaseModel):
    content: str


@router.patch("/{campaign_id}/scenes/{scene_id}/turns/{turn_index}")
def edit_scene_turn(campaign_id: str, scene_id: str, turn_index: int, req: EditTurnRequest):
    """Edit the content of any turn by index (0-based)."""
    store = _scenes()
    scene = store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if turn_index < 0 or turn_index >= len(scene.turns):
        raise HTTPException(400, f"Turn index {turn_index} out of range (scene has {len(scene.turns)} turns)")
    if not req.content.strip():
        raise HTTPException(400, "Content cannot be empty")
    scene.turns[turn_index] = SceneTurn(role=scene.turns[turn_index].role, content=req.content.strip())
    store.save(scene)
    return _scene_dict(scene)


# ── Chronicle ──────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/chronicle")
def get_chronicle(campaign_id: str):
    return [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)]


class UpdateChronicleRequest(BaseModel):
    content: str


@router.patch("/{campaign_id}/chronicle/{entry_id}")
def update_chronicle_entry(campaign_id: str, entry_id: str, req: UpdateChronicleRequest):
    """Edit the text of a chronicle entry."""
    store = _chronicle()
    entry = store.get(entry_id)
    if not entry or entry.campaign_id != campaign_id:
        raise HTTPException(404, "Chronicle entry not found")
    updated = store.update_content(entry_id, req.content)
    return _chronicle_dict(updated)


@router.delete("/{campaign_id}/chronicle/{entry_id}", status_code=204)
def delete_chronicle_entry(campaign_id: str, entry_id: str):
    """Delete a chronicle entry."""
    store = _chronicle()
    entry = store.get(entry_id)
    if not entry or entry.campaign_id != campaign_id:
        raise HTTPException(404, "Chronicle entry not found")
    store.delete(entry_id)


_COMPRESS_SYSTEM = """You are a narrative historian. You will receive several chronicle entries from a roleplay campaign.
Merge them into a single, coherent summary that preserves all essential plot points, character developments, and consequences.
Write in past tense. Be concise but complete. Return only the merged summary text — no preamble, no labels."""


@router.post("/{campaign_id}/chronicle/compress")
def compress_chronicle(campaign_id: str, req: UpdateChronicleRequest):
    """
    AI-assisted chronicle compression.
    The client sends the IDs of entries to merge as a newline-separated list in req.content.
    Returns { "summary": "..." } for the client to confirm before replacing.
    """
    import json as _json
    import httpx

    entry_ids: list[str] = [line.strip() for line in req.content.splitlines() if line.strip()]
    if len(entry_ids) < 2:
        raise HTTPException(400, "Need at least 2 entry IDs to compress")

    store = _chronicle()
    entries = [store.get(eid) for eid in entry_ids]
    entries = [e for e in entries if e and e.campaign_id == campaign_id]
    if len(entries) < 2:
        raise HTTPException(400, "Could not find at least 2 valid entries for this campaign")

    entries_sorted = sorted(entries, key=lambda e: e.scene_range_start)
    combined = "\n\n".join(
        f"[Scene {e.scene_range_start}] {e.content}" for e in entries_sorted
    )

    campaign = _campaigns().get(campaign_id)
    model = (campaign.model_name if campaign else None) or config.ollama_model

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {"role": "user", "content": combined},
            ],
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 512, "num_ctx": 4096},
        }
        resp = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=180.0,
        )
        resp.raise_for_status()
        summary = resp.json()["message"]["content"].strip()
    except Exception as e:
        raise HTTPException(503, f"AI compression failed: {e}")

    # Apply: replace all selected entries with one merged entry
    start = entries_sorted[0].scene_range_start
    end = entries_sorted[-1].scene_range_end
    for e in entries_sorted:
        store.delete(e.id)
    merged = ChronicleEntry(
        campaign_id=campaign_id,
        scene_range_start=start,
        scene_range_end=end,
        content=summary,
        confirmed=True,
    )
    store.save(merged)
    return _chronicle_dict(merged)


# ── Export & Backup ──────────────────────────────────────────────────────────

@router.get("/{campaign_id}/export/markdown")
def export_campaign_markdown(campaign_id: str):
    """Export the full campaign as a formatted Markdown document (download)."""
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    pc     = _pcs().get(campaign_id)
    facts  = _facts().get_all(campaign_id)
    places = _places().get_all(campaign_id)
    npcs   = _npcs().get_all(campaign_id)
    threads = _threads().get_all(campaign_id)
    factions = _factions().get_all(campaign_id)
    scenes = _scenes().get_all(campaign_id)
    chronicle = _chronicle().get_all(campaign_id)
    sg = c.style_guide

    lines: list[str] = []
    lines.append(f"# {c.name}")
    lines.append(f"*Exported {datetime.now(UTC).strftime('%Y-%m-%d')}*\n")

    if sg.prose_style or sg.tone:
        lines.append("## Style")
        if sg.prose_style: lines.append(f"- **Style:** {sg.prose_style}")
        if sg.tone:        lines.append(f"- **Tone:** {sg.tone}")
        lines.append("")

    if facts:
        lines.append("## World Facts")
        for f in facts:
            prefix = f"**[{f.category.upper()}]** " if f.category else ""
            lines.append(f"- {prefix}{f.content}")
        lines.append("")

    if sg.magic_system:
        lines.append("## Magic / Technology")
        lines.append(sg.magic_system)
        lines.append("")

    if pc and pc.name:
        lines.append(f"## Player Character: {pc.name}")
        for label, val in [("Appearance", pc.appearance), ("Personality", pc.personality),
                            ("Background", pc.background), ("Wants", pc.wants), ("Fears", pc.fears)]:
            if val: lines.append(f"**{label}:** {val}")
        if pc.dev_log:
            lines.append("\n### Development Log")
            for e in pc.dev_log:
                prefix = f"Scene {e.scene_number}: " if e.scene_number else ""
                lines.append(f"- {prefix}{e.note}")
        lines.append("")

    if npcs:
        lines.append("## NPCs")
        for n in npcs:
            status = f" [{n.status.upper()}]" if n.status and n.status != "active" else ""
            lines.append(f"### {n.name}{status}")
            for label, val in [("Role", n.role), ("Personality", n.personality),
                                ("Relationship to player", n.relationship_to_player),
                                ("Current state", n.current_state)]:
                if val: lines.append(f"**{label}:** {val}")
        lines.append("")

    if places:
        lines.append("## Places")
        for p in places:
            lines.append(f"### {p.name}")
            if p.description:   lines.append(p.description)
            if p.current_state: lines.append(f"*Currently: {p.current_state}*")
        lines.append("")

    if factions:
        lines.append("## Factions")
        for f in factions:
            lines.append(f"### {f.name}")
            if f.description:          lines.append(f.description)
            if f.goals:                lines.append(f"**Goals:** {f.goals}")
            if f.standing_with_player: lines.append(f"**Standing:** {f.standing_with_player}")
        lines.append("")

    if threads:
        lines.append("## Narrative Threads")
        for t in threads:
            status_str = f" [{t.status.value.upper()}]" if hasattr(t.status, "value") else ""
            lines.append(f"### {t.title}{status_str}")
            if t.description: lines.append(t.description)
            if t.resolution:  lines.append(f"*Resolution: {t.resolution}*")
        lines.append("")

    if chronicle:
        lines.append("## Chronicle")
        for e in sorted(chronicle, key=lambda x: x.scene_range_start):
            label = (f"Scene {e.scene_range_start}" if e.scene_range_start == e.scene_range_end
                     else f"Scenes {e.scene_range_start}–{e.scene_range_end}")
            lines.append(f"**[{label}]** {e.content}")
        lines.append("")

    if scenes:
        lines.append("## Scenes")
        for s in sorted(scenes, key=lambda x: x.scene_number):
            conf = " ✓" if s.confirmed else " (in progress)"
            lines.append(f"### Scene {s.scene_number}{conf}" + (f": {s.title}" if s.title else ""))
            if s.location:           lines.append(f"*Location: {s.location}*")
            if s.confirmed_summary:  lines.append(f"\n**Summary:** {s.confirmed_summary}")
            if s.turns:
                lines.append("")
                for t in s.turns:
                    speaker = "**Player**" if t.role == "user" else "**Narrator**"
                    lines.append(f"{speaker}: {t.content}\n")
        lines.append("")

    if c.notes:
        lines.append("## Player Notes")
        lines.append(c.notes)

    md = "\n".join(lines)
    filename = f"{c.name.replace(' ', '_')}_export.md"
    return _Response(content=md.encode("utf-8"), media_type="text/markdown",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{campaign_id}/export/json")
def export_campaign_json(campaign_id: str):
    """Export the full campaign as a JSON backup (download)."""
    import json as _json
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    data = {
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "campaign": _campaign_dict(c),
        "player_character": _pc_dict(_pcs().get(campaign_id)),
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
        "scenes": [_scene_dict(s) for s in _scenes().get_all(campaign_id)],
        "chronicle": [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)],
    }
    payload = _json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"{c.name.replace(' ', '_')}_backup.json"
    return _Response(content=payload.encode("utf-8"), media_type="application/json",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class ImportCampaignRequest(BaseModel):
    data: dict              # full JSON backup as parsed object
    campaign_name: Optional[str] = None   # override the auto-generated name


@router.get("/{campaign_id}/export/template")
def export_campaign_template(campaign_id: str):
    """Export world document only (no scenes/chronicle) as a shareable template file."""
    import json as _json
    from fastapi.responses import Response as _Response
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    data = {
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "campaign": {k: v for k, v in _campaign_dict(c).items() if k != "notes"},
        "player_character": _pc_dict(_pcs().get(campaign_id)),
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
    }
    payload = _json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"{c.name.replace(' ', '_')}_template.json"
    return _Response(content=payload.encode("utf-8"), media_type="application/json",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/import", status_code=201)
def import_campaign(req: ImportCampaignRequest):
    """Restore a campaign from a JSON backup. Creates a new campaign with a new ID."""
    import json as _json
    d = req.data
    if d.get("version") != 1:
        raise HTTPException(400, "Unsupported backup version")

    orig = d.get("campaign", {})
    sg_dict = orig.get("style_guide", {})
    sg = StyleGuide(
        prose_style=sg_dict.get("prose_style", ""),
        tone=sg_dict.get("tone", ""),
        themes=sg_dict.get("themes", []),
        magic_system=sg_dict.get("magic_system", ""),
        avoids=sg_dict.get("avoids", ""),
    )
    if req.campaign_name:
        new_name = req.campaign_name
    else:
        new_name = orig.get("name", "Imported Campaign") + " (restored)"
    c = _campaigns().create(name=new_name, model_name=orig.get("model_name"), style_guide=sg)
    if orig.get("notes"):
        _campaigns().update(c.id, notes=orig["notes"])
    cid = c.id
    now = datetime.now(UTC).replace(tzinfo=None)

    # ID remapping so cross-references stay consistent
    npc_id_map: dict[str, str] = {}

    pc_data = d.get("player_character") or {}
    if pc_data.get("name"):
        _pcs().save(PlayerCharacter(
            campaign_id=cid, name=pc_data["name"],
            appearance=pc_data.get("appearance", ""), personality=pc_data.get("personality", ""),
            background=pc_data.get("background", ""), wants=pc_data.get("wants", ""),
            fears=pc_data.get("fears", ""), how_seen=pc_data.get("how_seen", ""),
        ))

    for f in d.get("world_facts", []):
        if f.get("content"):
            from app.core.models import CampaignWorldFact
            _facts().save(CampaignWorldFact(
                campaign_id=cid, content=f["content"],
                category=f.get("category", ""), fact_order=f.get("fact_order", 0),
            ))

    for p in d.get("places", []):
        if p.get("name"):
            _places().save(CampaignPlace(campaign_id=cid, name=p["name"],
                description=p.get("description", ""), current_state=p.get("current_state", ""),
                created_at=now))

    for n in d.get("npcs", []):
        if n.get("name"):
            new_npc = NpcCard(campaign_id=cid, name=n["name"],
                appearance=n.get("appearance", ""), personality=n.get("personality", ""),
                role=n.get("role", ""), relationship_to_player=n.get("relationship_to_player", ""),
                current_location=n.get("current_location", ""),
                current_state=n.get("current_state", ""),
                status=NpcStatus(n["status"]) if n.get("status") else NpcStatus.ACTIVE,
                status_reason=n.get("status_reason", ""), secrets=n.get("secrets", ""),
                short_term_goal=n.get("short_term_goal", ""),
                long_term_goal=n.get("long_term_goal", ""), created_at=now)
            _npcs().save(new_npc)
            npc_id_map[n["id"]] = new_npc.id

    for r in d.get("npc_relationships", []):
        a = npc_id_map.get(r.get("npc_id_a", ""))
        b = npc_id_map.get(r.get("npc_id_b", ""))
        if a and b:
            _npc_relationships().save(NpcRelationship(
                campaign_id=cid, npc_id_a=a, npc_id_b=b,
                dynamic=r.get("dynamic", ""), trust=r.get("trust", ""),
                hostility=r.get("hostility", ""), history=r.get("history", ""),
                created_at=now))

    for t in d.get("threads", []):
        if t.get("title"):
            _threads().save(NarrativeThread(campaign_id=cid, title=t["title"],
                description=t.get("description", ""),
                status=ThreadStatus(t["status"]) if t.get("status") else ThreadStatus.ACTIVE,
                resolution=t.get("resolution", ""), created_at=now))

    for f in d.get("factions", []):
        if f.get("name"):
            _factions().save(CampaignFaction(campaign_id=cid, name=f["name"],
                description=f.get("description", ""), goals=f.get("goals", ""),
                methods=f.get("methods", ""),
                standing_with_player=f.get("standing_with_player", ""),
                relationship_notes=f.get("relationship_notes", ""), created_at=now))

    for s in d.get("scenes", []):
        npc_ids = [npc_id_map.get(nid, nid) for nid in s.get("npc_ids", [])]
        turns = [SceneTurn(role=t["role"], content=t["content"]) for t in s.get("turns", [])]
        scene = CampaignScene(campaign_id=cid, scene_number=s.get("scene_number", 1),
            title=s.get("title", ""), location=s.get("location", ""),
            npc_ids=npc_ids, intent=s.get("intent", ""), tone=s.get("tone", ""),
            turns=turns, proposed_summary=s.get("proposed_summary", ""),
            confirmed_summary=s.get("confirmed_summary", ""),
            confirmed=s.get("confirmed", False),
            allow_unselected_npcs=s.get("allow_unselected_npcs", False))
        _scenes().save(scene)

    for e in d.get("chronicle", []):
        if e.get("content"):
            _chronicle().save(ChronicleEntry(campaign_id=cid,
                scene_range_start=e.get("scene_range_start", 0),
                scene_range_end=e.get("scene_range_end", 0),
                content=e["content"], confirmed=e.get("confirmed", True)))

    return {"campaign_id": cid, "name": new_name}


# ── Campaign Statistics ────────────────────────────────────────────────────────

@router.get("/{campaign_id}/stats")
def get_campaign_stats(campaign_id: str):
    """Return aggregate statistics for a campaign."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    scenes_all  = _scenes().get_all(campaign_id)
    npcs_all    = _npcs().get_all(campaign_id)
    threads_all = _threads().get_all(campaign_id)
    facts_all   = _facts().get_all(campaign_id)
    chronicle   = _chronicle().get_all(campaign_id)

    confirmed_scenes = [s for s in scenes_all if s.confirmed]
    active_scenes    = [s for s in scenes_all if not s.confirmed]

    # Word counts
    total_words = sum(
        len(t.content.split())
        for s in scenes_all for t in s.turns
    )
    player_words = sum(
        len(t.content.split())
        for s in scenes_all for t in s.turns if t.role == "user"
    )
    narrator_words = total_words - player_words

    # NPC usage — count scenes each NPC appears in
    npc_counts: dict[str, int] = {}
    for s in scenes_all:
        for nid in s.npc_ids:
            npc_counts[nid] = npc_counts.get(nid, 0) + 1
    npc_name_map = {n.id: n.name for n in npcs_all}
    top_npcs = sorted(
        [{"name": npc_name_map.get(k, k), "scene_count": v} for k, v in npc_counts.items()],
        key=lambda x: -x["scene_count"]
    )[:5]

    # Thread stats
    resolved = sum(1 for t in threads_all if hasattr(t.status, "value") and t.status.value == "resolved")
    active_t = sum(1 for t in threads_all if hasattr(t.status, "value") and t.status.value == "active")
    resolution_rate = round(resolved / len(threads_all) * 100) if threads_all else 0

    return {
        "scenes_total": len(scenes_all),
        "scenes_confirmed": len(confirmed_scenes),
        "scenes_active": len(active_scenes),
        "total_turns": sum(len(s.turns) for s in scenes_all),
        "total_words": total_words,
        "player_words": player_words,
        "narrator_words": narrator_words,
        "npc_count": len(npcs_all),
        "top_npcs": top_npcs,
        "thread_count": len(threads_all),
        "threads_resolved": resolved,
        "threads_active": active_t,
        "thread_resolution_rate": resolution_rate,
        "world_fact_count": len(facts_all),
        "chronicle_entries": len(chronicle),
    }


# ── Scene / turn search ────────────────────────────────────────────────────────

@router.get("/{campaign_id}/search")
def search_turns(campaign_id: str, q: str = "", limit: int = 30):
    """Full-text search across all scene turns. Returns matching excerpts."""
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    scenes = _scenes().get_all(campaign_id)
    results: list[dict] = []
    for s in scenes:
        for i, t in enumerate(s.turns):
            if q_lower in t.content.lower():
                # Find position for excerpt
                pos = t.content.lower().find(q_lower)
                start = max(0, pos - 60)
                end = min(len(t.content), pos + len(q) + 60)
                excerpt = ("…" if start > 0 else "") + t.content[start:end] + ("…" if end < len(t.content) else "")
                results.append({
                    "scene_id": s.id,
                    "scene_number": s.scene_number,
                    "scene_title": s.title,
                    "turn_index": i,
                    "role": t.role,
                    "excerpt": excerpt,
                    "match_pos": pos - start,
                    "match_len": len(q),
                })
                if len(results) >= limit:
                    return results
    return results


# ── Campaign Templates ─────────────────────────────────────────────────────────

class SaveTemplateRequest(BaseModel):
    name: str


@router.post("/{campaign_id}/save-as-template", status_code=201)
def save_as_template(campaign_id: str, req: SaveTemplateRequest):
    """
    Clone the world document of this campaign as a new campaign (template).
    Scenes, chronicle, and player notes are NOT copied — only world facts,
    NPCs, places, threads, factions, and style guide.
    """
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    template = _campaigns().create(
        name=req.name,
        model_name=c.model_name,
        style_guide=c.style_guide,
    )
    tid = template.id
    now = datetime.now(UTC).replace(tzinfo=None)

    pc = _pcs().get(campaign_id)
    if pc and pc.name:
        _pcs().save(PlayerCharacter(campaign_id=tid, name=pc.name,
            appearance=pc.appearance, personality=pc.personality,
            background=pc.background, wants=pc.wants, fears=pc.fears,
            how_seen=pc.how_seen))

    npc_id_map: dict[str, str] = {}
    for n in _npcs().get_all(campaign_id):
        new_n = NpcCard(campaign_id=tid, name=n.name, appearance=n.appearance,
            personality=n.personality, role=n.role,
            relationship_to_player=n.relationship_to_player,
            current_location=n.current_location, current_state=n.current_state,
            status=n.status, secrets=n.secrets,
            short_term_goal=n.short_term_goal, long_term_goal=n.long_term_goal,
            created_at=now)
        _npcs().save(new_n)
        npc_id_map[n.id] = new_n.id

    for r in _npc_relationships().get_all(campaign_id):
        a = npc_id_map.get(r.npc_id_a)
        b = npc_id_map.get(r.npc_id_b)
        if a and b:
            _npc_relationships().save(NpcRelationship(
                campaign_id=tid, npc_id_a=a, npc_id_b=b,
                dynamic=r.dynamic, trust=r.trust, hostility=r.hostility,
                history=r.history, created_at=now))

    for p in _places().get_all(campaign_id):
        _places().save(CampaignPlace(campaign_id=tid, name=p.name,
            description=p.description, current_state=p.current_state, created_at=now))

    for t in _threads().get_all(campaign_id):
        _threads().save(NarrativeThread(campaign_id=tid, title=t.title,
            description=t.description, status=t.status,
            resolution=t.resolution, created_at=now))

    for f in _factions().get_all(campaign_id):
        _factions().save(CampaignFaction(campaign_id=tid, name=f.name,
            description=f.description, goals=f.goals, methods=f.methods,
            standing_with_player=f.standing_with_player,
            relationship_notes=f.relationship_notes, created_at=now))

    from app.core.models import CampaignWorldFact
    for f in _facts().get_all(campaign_id):
        _facts().save(CampaignWorldFact(campaign_id=tid, content=f.content,
            category=f.category, fact_order=f.fact_order))

    return {"campaign_id": tid, "name": req.name}


# ── Image storage ─────────────────────────────────────────────────────────────

class SaveImageRequest(BaseModel):
    data_url: str


@router.patch("/{campaign_id}/cover-image", status_code=204)
def save_campaign_cover_image(campaign_id: str, req: SaveImageRequest):
    """Save a generated image as the campaign cover."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    _campaigns().update(campaign_id, cover_image=req.data_url)


@router.patch("/{campaign_id}/player-character/portrait", status_code=204)
def save_pc_portrait(campaign_id: str, req: SaveImageRequest):
    """Save a generated or uploaded image as the player character portrait."""
    pc = _pcs().get(campaign_id)
    if not pc:
        raise HTTPException(404, "Player character not found")
    pc.portrait_image = req.data_url
    _pcs().save(pc)


@router.patch("/{campaign_id}/npcs/{npc_id}/portrait", status_code=204)
def save_npc_portrait(campaign_id: str, npc_id: str, req: SaveImageRequest):
    """Save a generated image as an NPC portrait."""
    npc = _npcs().get(npc_id)
    if not npc or npc.campaign_id != campaign_id:
        raise HTTPException(404, "NPC not found")
    from app.core.models import NpcDevEntry as _NDE  # noqa: avoid circular at module level
    npc.portrait_image = req.data_url
    _npcs().save(npc)


_CARD_IMPORT_SYSTEM = """You are a campaign integration assistant for collaborative roleplay.

You are given an existing campaign's world document and a SillyTavern-format character card.
Your job is to:
1. Convert the character card into an NPC that fits this campaign's world
2. Identify contradictions between the card and the world (e.g. references to modern technology in a fantasy world, place names that don't exist, anachronistic elements)
3. Suggest world-appropriate alternatives for each contradiction

Output ONLY valid JSON with exactly this structure (no markdown fences, no extra text):
{
  "proposed_npc": {
    "name": "Character name from card",
    "gender": "inferred gender",
    "age": "inferred age or age range",
    "appearance": "physical description adapted to the world",
    "personality": "personality from card",
    "role": "their role in this world",
    "relationship_to_player": "how they might relate to the player character",
    "current_location": "a world-appropriate location",
    "current_state": "their current situation",
    "short_term_goal": "what they want right now",
    "long_term_goal": "their deeper ambition"
  },
  "contradictions": [
    {
      "field": "which NPC field is affected (e.g. 'current_location', 'appearance', 'role')",
      "issue": "description of the contradiction",
      "original": "the original value from the card",
      "suggested": "the world-appropriate alternative"
    }
  ]
}

If there are no contradictions, return an empty array for contradictions.
Keep all text fields concise (1-2 sentences each).
Output ONLY the JSON — no commentary before or after."""


class ImportCardRequest(BaseModel):
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    creator_notes: str = ""
    additional_context: str = ""
    model_name: Optional[str] = None


class GenerateNpcRequest(BaseModel):
    description: str        # free-text intent from the player
    model_name: Optional[str] = None


@router.post("/{campaign_id}/npcs/import-card")
def import_npc_from_card(campaign_id: str, req: ImportCardRequest):
    """Analyse a character card against the campaign world and return a proposed NPC + contradictions."""
    import json as _json
    _require_campaign(campaign_id)
    from app.campaigns.world_builder import _ollama_generate, _extract_json

    # Build world context from DB
    facts = _facts().get_all(campaign_id)
    world_parts: list[str] = []
    if facts:
        world_parts.append("WORLD FACTS:\n" + "\n".join(f"- {f.content}" for f in facts[:15]))
    existing_npcs = _npcs().get_all(campaign_id)
    if existing_npcs:
        world_parts.append("EXISTING NPCS: " + ", ".join(n.name for n in existing_npcs[:20]))
    factions = _factions().get_all(campaign_id)
    if factions:
        world_parts.append("FACTIONS:\n" + "\n".join(f"- {f.name}: {f.description}" for f in factions))
    world_context = "\n\n".join(world_parts) or "No world document established yet."

    # Build card text
    card_parts = [f"NAME: {req.name}"]
    if req.description:
        card_parts.append(f"DESCRIPTION:\n{req.description[:800]}")
    if req.personality:
        card_parts.append(f"PERSONALITY:\n{req.personality[:400]}")
    if req.scenario:
        card_parts.append(f"SCENARIO:\n{req.scenario[:400]}")
    if req.creator_notes:
        card_parts.append(f"CREATOR NOTES:\n{req.creator_notes[:300]}")
    if req.additional_context:
        card_parts.append(f"ADDITIONAL CONTEXT:\n{req.additional_context}")
    card_text = "\n\n".join(card_parts)

    prompt = (
        f"CAMPAIGN WORLD DOCUMENT:\n{world_context}\n\n"
        f"CHARACTER CARD TO IMPORT:\n{card_text}\n\n"
        f"Analyse this card for contradictions with the campaign world and return the integration JSON."
    )

    model = req.model_name or config.ollama_model
    try:
        raw = _ollama_generate(
            config.ollama_base_url, model,
            system=_CARD_IMPORT_SYSTEM,
            prompt=prompt,
            max_tokens=2048,
            temperature=0.3,
        )
    except Exception as e:
        raise HTTPException(503, f"AI unavailable: {e}")

    data = _extract_json(raw)
    if not data or "proposed_npc" not in data:
        raise HTTPException(500, "AI did not return valid analysis. Try a different model or try again.")

    return {
        "proposed_npc": data.get("proposed_npc", {}),
        "contradictions": data.get("contradictions", []),
    }


_GENERATE_NPC_SYSTEM = """You are a character creation assistant for collaborative roleplay.

You are given a campaign world document and a player's description of an NPC they want to create.
Your job is to flesh out all fields for this NPC, staying true to the player's intent and consistent with the world.

Output ONLY valid JSON with exactly this structure (no markdown fences, no extra text):
{
  "name": "Character name",
  "gender": "gender",
  "age": "age or age range (e.g. 'mid-30s', '60s', 'young adult')",
  "appearance": "physical description in 1-2 sentences",
  "personality": "core personality traits in 1-2 sentences",
  "role": "their role or occupation in the world",
  "relationship_to_player": "how they might relate to the player character",
  "current_location": "where they currently are",
  "current_state": "their current situation or mood",
  "short_term_goal": "what they want right now",
  "long_term_goal": "their deeper ambition or life goal",
  "secrets": "something they are hiding (optional, can be empty string)"
}

Rules:
- Honour EVERY detail the player specified — do not contradict their description
- Fill in only what the player left unspecified
- Keep all fields concise (1-2 sentences)
- Make the character internally consistent and fitting for the world
- Output ONLY the JSON object — no commentary before or after"""


@router.post("/{campaign_id}/npcs/generate")
def generate_npc(campaign_id: str, req: GenerateNpcRequest):
    """Generate a fully-populated NPC from a player's free-text description."""
    _require_campaign(campaign_id)
    from app.campaigns.world_builder import _ollama_generate, _extract_json

    # Build world context
    facts = _facts().get_all(campaign_id)
    world_parts: list[str] = []
    if facts:
        world_parts.append("WORLD FACTS:\n" + "\n".join(f"- {f.content}" for f in facts[:15]))
    existing_npcs = _npcs().get_all(campaign_id)
    if existing_npcs:
        world_parts.append("EXISTING NPCS: " + ", ".join(n.name for n in existing_npcs[:20]))
    factions = _factions().get_all(campaign_id)
    if factions:
        world_parts.append("FACTIONS:\n" + "\n".join(f"- {f.name}: {f.description}" for f in factions))
    world_context = "\n\n".join(world_parts) or "No world document established yet."

    prompt = (
        f"CAMPAIGN WORLD:\n{world_context}\n\n"
        f"PLAYER'S NPC DESCRIPTION:\n{req.description.strip()}\n\n"
        f"Generate the complete NPC JSON now."
    )

    model = req.model_name or config.ollama_model
    try:
        raw = _ollama_generate(
            config.ollama_base_url, model,
            system=_GENERATE_NPC_SYSTEM,
            prompt=prompt,
            max_tokens=1024,
            temperature=0.7,
        )
    except Exception as e:
        raise HTTPException(503, f"AI unavailable: {e}")

    data = _extract_json(raw)
    if not data or "name" not in data:
        raise HTTPException(500, "AI did not return a valid NPC. Try again or use a different model.")

    return data


@router.patch("/{campaign_id}/scenes/{scene_id}/scene-image", status_code=204)
def save_scene_image(campaign_id: str, scene_id: str, req: SaveImageRequest):
    """Save a generated image as the scene illustration."""
    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    scene.scene_image = req.data_url
    _scenes().save(scene)


# ── Image Prompt Generation ────────────────────────────────────────────────────

_IMG_PROMPT_SYSTEM = (
    "You are an expert Stable Diffusion prompt engineer.\n\n"
    "Your task: write a vivid SD image generation prompt based on the provided context.\n\n"
    "CRITICAL: Do NOT show any thinking, reasoning steps, planning, or explanation. "
    "Output ONLY the final raw prompt text and nothing else.\n\n"
    "Rules:\n"
    "- Comma-separated descriptive tags and short phrases\n"
    "- Lead with subject/composition (e.g. 'lone mage on a clifftop, stormy sky')\n"
    "- Include physical descriptions of each character present: gender, apparent age, hair colour, clothing, expression, pose\n"
    "  If gender or age are not explicitly stated, make a reasonable visual guess based on context\n"
    "- ALWAYS specify the character's gender and apparent age (e.g. 'young woman', 'middle-aged man', 'elderly elf female')\n"
    "- Include environment, lighting, mood, atmosphere\n"
    "- Do NOT include style tags — the user will add those separately\n"
    "- Do NOT include negative prompt syntax\n"
    "- Under 160 words total\n"
    "- Output ONLY the raw prompt text — no labels, no preamble, no explanation, no markdown"
)


class ImagePromptRequest(BaseModel):
    source_type: str          # "campaign" | "scene" | "chat" | "npc"
    scene_id: Optional[str] = None
    npc_id: Optional[str] = None
    model_name: Optional[str] = None
    last_message: Optional[str] = None   # for "chat" type — the last AI response text


@router.post("/{campaign_id}/image-prompt")
def generate_image_prompt(campaign_id: str, req: ImagePromptRequest):
    """Ask the LLM to produce a Stable Diffusion optimised prompt from campaign context."""
    import json as _json
    import httpx

    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")

    parts: list[str] = []

    if req.source_type == "campaign":
        facts = _facts().get_all(campaign_id)
        world_text = "\n".join(f"- {f.content}" for f in facts[:10] if f.content)
        pc = _pcs().get(campaign_id)
        pc_text = (
            f"{pc.name}: {pc.appearance}".strip()
            if pc and pc.name and pc.appearance else
            (pc.name if pc and pc.name else "")
        )
        sg = c.style_guide
        parts = [
            f"TYPE: Campaign cover image",
            f"CAMPAIGN NAME: {c.name}",
            f"WORLD DOCUMENT:\n{world_text}" if world_text else "",
            f"PLAYER CHARACTER: {pc_text}" if pc_text else "",
            f"TONE / THEMES: {sg.tone}" if sg and sg.tone else "",
            "",
            "Create a cinematic cover image prompt that captures the world's essence and atmosphere.",
        ]

    elif req.source_type == "scene":
        if not req.scene_id:
            raise HTTPException(400, "scene_id required for scene image")
        scene = _scenes().get(req.scene_id)
        if not scene:
            raise HTTPException(404, "Scene not found")
        npc_lines = []
        for nid in (scene.npc_ids or []):
            npc = _npcs().get(nid)
            if npc:
                meta = ", ".join(p for p in [npc.gender, npc.age] if p)
                desc = f"{npc.name}"
                if meta:
                    desc += f" [{meta}]"
                if npc.role:
                    desc += f" ({npc.role})"
                if npc.appearance:
                    desc += f": {npc.appearance[:120]}"
                npc_lines.append(desc)
        pc = _pcs().get(campaign_id)
        pc_text = (
            f"{pc.name}: {pc.appearance[:120]}".strip()
            if pc and pc.name and pc.appearance else
            (pc.name if pc and pc.name else "")
        )
        summary = scene.confirmed_summary or scene.proposed_summary or ""
        parts = [
            "TYPE: Scene illustration",
            f"LOCATION: {scene.location or 'unknown'}",
            f"SCENE TITLE: {scene.title}" if scene.title else "",
            f"SCENE SUMMARY: {summary[:400]}" if summary else "",
            f"SCENE INTENT: {scene.intent[:200]}" if scene.intent else "",
            f"TONE: {scene.tone}" if scene.tone else "",
            "NPCs PRESENT:\n" + "\n".join(f"  - {n}" for n in npc_lines) if npc_lines else "",
            f"PLAYER CHARACTER: {pc_text}" if pc_text else "",
            "",
            "Create an evocative scene illustration prompt that captures this moment in the story.",
        ]

    elif req.source_type == "chat":
        if not req.last_message:
            raise HTTPException(400, "last_message required for chat image")
        scene = _scenes().get(req.scene_id) if req.scene_id else None
        location = (scene.location if scene else None) or "unknown"
        parts = [
            "TYPE: In-story illustration",
            f"LOCATION: {location}",
            "",
            "LAST NARRATIVE TEXT (verbatim):",
            req.last_message[:600],
            "",
            "Create an illustration prompt for exactly this story moment — the characters, action, and atmosphere described above.",
        ]

    elif req.source_type == "pc":
        pc = _pcs().get(campaign_id)
        if not pc:
            raise HTTPException(404, "Player character not found")
        parts = [
            "TYPE: Player character portrait",
            f"NAME: {pc.name}",
            f"APPEARANCE: {pc.appearance}" if pc.appearance else "",
            f"PERSONALITY (for expression clues): {pc.personality[:200]}" if pc.personality else "",
            f"BACKGROUND: {pc.background[:200]}" if pc.background else "",
            f"WANTS: {pc.wants}" if pc.wants else "",
            f"FEARS: {pc.fears}" if pc.fears else "",
            "",
            "Create a character portrait prompt for the player character. ALWAYS lead with gender and apparent age (infer from context if not stated). Emphasise face, expression, clothing, and distinctive visual traits.",
        ]

    elif req.source_type == "npc":
        if not req.npc_id:
            raise HTTPException(400, "npc_id required for character image")
        npc = _npcs().get(req.npc_id)
        if not npc:
            raise HTTPException(404, "NPC not found")
        parts = [
            "TYPE: Character portrait",
            f"NAME: {npc.name}",
            f"GENDER: {npc.gender}" if npc.gender else "GENDER: unspecified — infer from name/context",
            f"AGE: {npc.age}" if npc.age else "AGE: unspecified — make a reasonable visual guess",
            f"ROLE: {npc.role}" if npc.role else "",
            f"APPEARANCE: {npc.appearance}" if npc.appearance else "",
            f"PERSONALITY (for expression clues): {npc.personality[:200]}" if npc.personality else "",
            f"CURRENT STATE: {npc.current_state}" if npc.current_state else "",
            "",
            "Create a character portrait prompt. ALWAYS lead with the character's gender and apparent age. Emphasise face, expression, and distinctive visual traits.",
        ]

    else:
        raise HTTPException(400, f"Unknown source_type: {req.source_type!r}")

    context = "\n".join(p for p in parts if p)
    model = req.model_name or (c.model_name if c.model_name else config.ollama_model)

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _IMG_PROMPT_SYSTEM},
                {"role": "user", "content": context},
            ],
            "stream": False,
            "think": False,   # Qwen3 / QwQ: suppress chain-of-thought output
            "options": {"temperature": 0.75, "num_predict": 350},
        }
        resp = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            # Short connect timeout (localhost), generous read timeout for slow/cold models
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        resp.raise_for_status()
        import re as _re
        raw = resp.json()
        msg = raw.get("message", {})
        content = (msg.get("content") or "").strip()
        # Strip <think>…</think> blocks (DeepSeek-R1, Qwen3 with tags)
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
        # Strip plain-text thinking preambles: paragraphs that start with
        # "Thinking", numbered steps, or bullet reasoning before the actual prompt.
        # The real SD prompt is comma-separated tags without markdown list markers.
        # Strategy: take everything after the last blank line that follows a
        # "step" / heading pattern, or just grab the last non-empty paragraph.
        if _re.search(r"(?m)^(Thinking|#+\s|\d+\.\s+\*\*)", content):
            # Split on double newlines and take the last non-empty block
            blocks = [b.strip() for b in _re.split(r"\n{2,}", content) if b.strip()]
            # Prefer the last block that looks like comma-separated tags (no list markers)
            for block in reversed(blocks):
                if not _re.match(r"^(\d+\.|\*|-|#)", block):
                    content = block
                    break
        # Some thinking models leave content empty and put the answer in message.thinking
        prompt_text = content or (msg.get("thinking") or "").strip()
        if not prompt_text:
            raise HTTPException(500,
                "The model returned an empty response. "
                "Try selecting a different model or ensure the model is fully loaded in Ollama.")
        return {"prompt": prompt_text}
    except HTTPException:
        raise
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, (
            "Prompt generation timed out (model took >5 min). "
            "This usually means Ollama is loading a large model — wait a moment and try again, "
            "or select a smaller/faster model."
        ))
    except Exception as e:
        raise HTTPException(500, f"Prompt generation failed: {e}")


# ── World Builder ──────────────────────────────────────────────────────────────

@router.post("/world-builder/generate/stream")
def generate_world_stream(req: GenerateWorldRequest):
    """Stream world generation tokens. Client accumulates, then POSTs to /parse."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)

    def _stream():
        try:
            for chunk in wb.generate_stream(req.description):
                yield chunk
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/world-builder/generate")
def generate_world(req: GenerateWorldRequest):
    """Blocking world generation. Returns a WorldBuildResult JSON."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)
    try:
        result = wb.generate(req.description)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return result.model_dump()


@router.post("/world-builder/refine")
def refine_world(req: RefineWorldRequest):
    """Refine a specific section of a WorldBuildResult."""
    wb = _world_builder()
    if req.model_name:
        from app.campaigns.world_builder import WorldBuilder
        wb = WorldBuilder(base_url=config.ollama_base_url, model=req.model_name)
    current = _dict_to_world_build_result(req.current)
    try:
        result = wb.refine(current, req.section, req.instructions)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return result.model_dump()


@router.post("/world-builder/refine/stream")
def refine_world_stream(req: RefineWorldRequest):
    """Stream a section refinement. Client accumulates and parses JSON."""
    import json as _json
    import httpx
    from app.campaigns.world_builder import _REFINE_SYSTEM

    model = req.model_name or config.ollama_model
    current = _dict_to_world_build_result(req.current)
    current_json = _json.dumps(current.model_dump(mode="json"), indent=2, ensure_ascii=False)

    prompt = (
        f"Here is the current world document:\n\n"
        f"```json\n{current_json}\n```\n\n"
        f"The player wants to refine the '{req.section}' section:\n\n"
        f"{req.instructions.strip()}\n\n"
        f"Return the complete updated world document JSON."
    )

    def _stream():
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _REFINE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "think": False,
                "options": {"temperature": 0.75, "num_predict": 4096, "num_ctx": 8192},
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


class GenerateFromCardsRequest(BaseModel):
    cards: list[dict] = []
    lorebook_entries: list[dict] = []
    additional_details: str = ""
    model_name: Optional[str] = None


@router.post("/world-builder/from-cards/stream")
def generate_from_cards_stream(req: GenerateFromCardsRequest):
    """Stream world synthesis from character cards and lorebook entries."""
    from app.campaigns.world_builder import WorldBuilder
    model = req.model_name or config.ollama_model
    wb = WorldBuilder(base_url=config.ollama_base_url, model=model)

    def _stream():
        try:
            for chunk in wb.generate_from_cards_stream(
                req.cards, req.lorebook_entries, req.additional_details
            ):
                yield chunk
        except Exception as e:
            yield f"\n\n[ERROR: {e}]"

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/world-builder/confirm", status_code=201)
def confirm_world(req: ConfirmWorldRequest):
    """
    Persist a confirmed WorldBuildResult as a new Campaign with all sub-entities.
    Returns the created campaign id and summary counts.
    """
    world = _dict_to_world_build_result(req.world)
    sg = StyleGuide(
        prose_style=req.prose_style,
        tone=req.tone,
    )
    store = _campaigns()
    campaign = store.create(
        name=req.campaign_name,
        model_name=req.model_name,
        style_guide=sg,
    )
    cid = campaign.id

    now = datetime.now(UTC).replace(tzinfo=None)

    # Player character
    pc_data = world.player_character
    if pc_data and pc_data.get("name"):
        _pcs().save(PlayerCharacter(
            campaign_id=cid,
            name=pc_data.get("name", "The Protagonist"),
            appearance=pc_data.get("appearance", ""),
            personality=pc_data.get("personality", ""),
            background=pc_data.get("background", ""),
            wants=pc_data.get("wants", ""),
            fears=pc_data.get("fears", ""),
        ))

    # World facts — premise goes first, then bullet facts
    all_fact_texts: list[str] = []
    if world.premise:
        all_fact_texts.append(world.premise)
    all_fact_texts.extend(world.world_facts)
    if all_fact_texts:
        _facts().replace_all(cid, all_fact_texts)

    # Places
    for place in world.places:
        if place.get("name"):
            _places().save(CampaignPlace(
                campaign_id=cid,
                name=place.get("name", ""),
                description=place.get("description", ""),
                current_state=place.get("current_state", ""),
                created_at=now,
            ))

    # NPCs
    for npc in world.npcs:
        if npc.get("name"):
            _npcs().save(NpcCard(
                campaign_id=cid,
                name=npc.get("name", ""),
                appearance=npc.get("appearance", ""),
                personality=npc.get("personality", ""),
                role=npc.get("role", ""),
                relationship_to_player=npc.get("relationship_to_player", ""),
                current_location=npc.get("current_location", ""),
                current_state=npc.get("current_state", ""),
                created_at=now,
            ))

    # Narrative threads
    for thread in world.narrative_threads:
        if thread.get("title"):
            _threads().save(NarrativeThread(
                campaign_id=cid,
                title=thread.get("title", ""),
                description=thread.get("description", ""),
                created_at=now,
            ))

    # Factions
    for faction in world.factions:
        if faction.get("name"):
            _factions().save(CampaignFaction(
                campaign_id=cid,
                name=faction.get("name", ""),
                description=faction.get("description", ""),
                goals=faction.get("goals", ""),
                methods=faction.get("methods", ""),
                created_at=now,
            ))

    return {
        "campaign_id": cid,
        "name": campaign.name,
        "counts": {
            "world_facts": len(world.world_facts) + (1 if world.premise else 0),
            "places": len(world.places),
            "npcs": len(world.npcs),
            "threads": len(world.narrative_threads),
            "factions": len(world.factions),
        },
    }


# ── Full world state (for overview / scene context) ───────────────────────────

@router.get("/{campaign_id}/world")
def get_full_world(campaign_id: str):
    """Return everything needed for the campaign overview in one call."""
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return {
        "campaign": _campaign_dict(c),
        "player_character": _pc_dict(_pcs().get(campaign_id)) if _pcs().get(campaign_id) else None,
        "world_facts": [_fact_dict(f) for f in _facts().get_all(campaign_id)],
        "places": [_place_dict(p) for p in _places().get_all(campaign_id)],
        "npcs": [_npc_dict(n) for n in _npcs().get_all(campaign_id)],
        "npc_relationships": [_rel_dict(r) for r in _npc_relationships().get_all(campaign_id)],
        "threads": [_thread_dict(t) for t in _threads().get_all(campaign_id)],
        "factions": [_faction_dict(f) for f in _factions().get_all(campaign_id)],
        "scenes": [_scene_dict(s) for s in _scenes().get_all(campaign_id)],
        "chronicle": [_chronicle_dict(e) for e in _chronicle().get_all(campaign_id)],
    }


# ── Scene chat (streaming) ────────────────────────────────────────────────────

class SceneChatRequest(BaseModel):
    message: str
    user_name: str = "Player"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class SceneOpenRequest(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class SceneRegenerateRequest(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

class ReplaceLastAssistantRequest(BaseModel):
    content: str


@router.post("/{campaign_id}/scenes/{scene_id}/open")
def scene_open_stream(campaign_id: str, scene_id: str, req: SceneOpenRequest):
    """
    Stream the AI narrator's opening narration for a newly started scene.
    Uses a hidden system-level prompt — no user turn is stored.
    Only the assistant response is persisted to the scene.
    """
    import json as _json
    import httpx

    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    pc = _pcs().get(campaign_id)
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)
    npc_list = _npcs().get_many(scene.npc_ids) if scene.npc_ids else []
    npc_rels_list = (
        _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
        if scene.npc_ids else []
    )
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []

    # Build messages with a hidden opening prompt (not stored as a user turn)
    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=(
            "[Scene begins. Narrate the opening of this scene. Set the mood, "
            "describe the environment, and establish the situation. Do not wait "
            "for the player — begin the story now.]"
        ),
        user_name="",  # suppresses name prefix so it reads as a system cue
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    def _stream():
        full_response: list[str] = []
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        # Persist only the assistant turn
        scene.turns.append(SceneTurn(role="assistant", content="".join(full_response)))
        scene_store.save(scene)

    return StreamingResponse(_stream(), media_type="text/plain")


@router.post("/{campaign_id}/scenes/{scene_id}/chat")
def scene_chat_stream(campaign_id: str, scene_id: str, req: SceneChatRequest):
    """
    Stream the AI narrator response for one turn of scene play.
    Stores the user turn and AI response in the scene's turn list.
    """
    import json as _json
    import httpx

    # Load all context
    campaign = _campaigns().get(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    scene_store = _scenes()
    scene = scene_store.get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if scene.confirmed:
        raise HTTPException(400, "Scene is already confirmed")

    pc = _pcs().get(campaign_id)
    world_facts_list = _facts().get_all(campaign_id)
    threads_list = _threads().get_active(campaign_id)
    chronicle_list = _chronicle().get_all(campaign_id)
    places_list = _places().get_all(campaign_id)
    factions_list = _factions().get_all(campaign_id)

    # Resolve NPC cards present in this scene
    npc_list = []
    npc_rels_list = []
    if scene.npc_ids:
        npc_list = _npcs().get_many(scene.npc_ids)
        npc_rels_list = _npc_relationships().get_for_npcs(campaign_id, scene.npc_ids)
    all_npcs_list = _npcs().get_all(campaign_id) if scene.allow_unselected_npcs else []

    messages = build_scene_messages(
        campaign=campaign,
        player_character=pc,
        world_facts=world_facts_list,
        npcs_in_scene=npc_list,
        active_threads=threads_list,
        chronicle=chronicle_list,
        places=places_list,
        factions=factions_list,
        npc_relationships=npc_rels_list,
        all_world_npcs=all_npcs_list,
        allow_unselected_npcs=scene.allow_unselected_npcs,
        scene=scene,
        user_message=req.message,
        user_name=req.user_name,
    )

    model = campaign.model_name or config.ollama_model
    gs = campaign.gen_settings
    temperature    = req.temperature    if req.temperature    is not None else gs.temperature
    top_p          = req.top_p          if req.top_p          is not None else gs.top_p
    top_k          = req.top_k          if req.top_k          is not None else gs.top_k
    min_p          = req.min_p          if req.min_p          is not None else gs.min_p
    repeat_penalty = req.repeat_penalty if req.repeat_penalty is not None else gs.repeat_penalty
    max_tokens     = req.max_tokens     if req.max_tokens     is not None else gs.max_tokens
    seed           = req.seed           if req.seed           is not None else gs.seed

    # Store user turn first (before streaming)
    scene.turns.append(SceneTurn(role="user", content=req.message))

    def _stream():
        full_response: list[str] = []
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "min_p": min_p,
                    "repeat_penalty": repeat_penalty,
                    "num_predict": max_tokens,
                    "seed": seed,
                    "num_ctx": gs.context_window,
                },
            }
            with httpx.stream(
                "POST",
                f"{config.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=180.0,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = _json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        yield delta
                    if chunk.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Error: {e}]"
            return

        # Persist both turns to the scene
        scene.turns.append(SceneTurn(role="assistant", content="".join(full_response)))
        scene_store.save(scene)

    return StreamingResponse(_stream(), media_type="text/plain")


# ── Post-scene AI tools ───────────────────────────────────────────────────────

_SUGGEST_SUMMARY_SYSTEM = """You are a transcript indexer. Your only job is to extract events from a numbered roleplay transcript and list them, one per line, with the turn number they came from.

CRITICAL RULES:
- You are NOT a storyteller. Do NOT write fiction, narration, or creative prose.
- You are NOT a narrator or character. The scene is FINISHED — do not continue it.
- Every line you write MUST cite the exact turn number it came from using [Turn N].
- If you cannot point to a specific turn that supports a claim, you MUST NOT include it.
- Do NOT infer, speculate, or add ANY detail not explicitly present in the cited turn.
- Do NOT merge or paraphrase multiple turns into one statement — cite only one turn per line.
- Do NOT embellish, add atmosphere, or use creative language.

Output format — one line per event, strictly:
- [Turn N] Past-tense statement of exactly what happened in that turn.

Work chronologically from Turn 1 to the last turn. Include every significant action, statement, decision, and outcome. Omit only trivial filler with no story consequence.
Output ONLY the list — no title, no preamble, no closing sentence."""

_SUGGEST_UPDATES_SYSTEM = """Extract world-document entries from a completed roleplay scene.

TASK: Read the transcript and summary, then output a JSON object cataloguing every character, place, fact, transformation, and relationship development worth recording. The player reviews every entry and approves or rejects — err heavily toward including MORE, not less.

CRITICAL OUTPUT RULE: Your response must be ONLY the JSON object below. No thinking prose outside the JSON. No markdown. No explanation. Begin your response with { and end with }.

REQUIRED JSON FORMAT (all seven keys must be present, use [] if nothing qualifies):
{
  "new_npcs": [
    {"name":"...", "role":"...", "gender":"...", "age":"...", "appearance":"(hair colour, eye colour, build, clothing, distinguishing features)", "personality":"...", "relationship_to_player":"...", "current_location":"...", "current_state":"...", "short_term_goal":"...", "long_term_goal":"...", "secrets":"(hidden backstory, concealed motives, or unknown truths about them)", "significance":"..."}
  ],
  "new_locations": [
    {"name":"...", "description":"...", "current_state":"...", "significance":"..."}
  ],
  "new_facts": [
    {"content":"...", "reason":"..."}
  ],
  "npc_updates": [
    {"npc_id":"exact-uuid", "npc_name":"...", "field":"current_state", "current_value":"...", "suggested_value":"...", "reason":"..."}
  ],
  "thread_updates": [
    {"thread_id":"exact-uuid", "thread_title":"...", "new_status":"resolved", "reason":"..."}
  ],
  "history_updates": [
    {"npc_id":"exact-uuid", "npc_name":"...", "addition":"one-sentence summary of what happened between this NPC and the player in this scene", "reason":"..."}
  ],
  "form_transitions": [
    {"npc_id":"exact-uuid", "npc_name":"...", "new_form_label":"...", "new_appearance":"...", "new_personality":"...", "new_current_state":"...", "reason":"..."}
  ]
}

WHAT TO EXTRACT:

new_npcs: Every character who appears in the scene AND is not in the CURRENT NPCs list. Fill every field as completely as possible — infer appearance and personality from descriptions and dialogue; put concealed backstory in "secrets".

new_locations: Every named or described place visited or mentioned in the scene that is not in the CURRENT LOCATIONS list.

new_facts: Every revelation, secret, lore detail, rule of the world, plot twist, or piece of backstory established in this scene.

npc_updates: Changes to characters already in the CURRENT NPCs list. Valid fields: current_state, is_alive, current_location. Match by the exact uuid shown.

thread_updates: Narrative threads already in the list that were resolved or went dormant. Match by exact uuid.

history_updates: For any NPC in the CURRENT NPCs list who had a meaningful interaction with the player in this scene — add a brief note to their history. One entry per NPC, one sentence. Only include if something significant happened (trust gained/lost, secret shared, conflict, alliance, etc.).

form_transitions: If any NPC in the CURRENT NPCs list visibly changed their physical form, appearance, or fundamental personality during this scene (transformation, shapeshifting, corruption, revealed disguise, possession, etc.) — record the new form. Leave new_form_label short and descriptive (e.g. "Wolf Form", "Corrupted", "True Form").

EXAMPLE — given a scene where Oren (already in the NPC list) revealed a dragon collar secret to the player, then transformed into a wolf at scene's end, the correct output includes:
{"new_npcs":[],"new_locations":[],"new_facts":[{"content":"Dragons are controlled by magical collars; removing the collar frees them.","reason":"Oren revealed this to the player"}],"npc_updates":[],"thread_updates":[],"history_updates":[{"npc_id":"oren-uuid","npc_name":"Oren","addition":"Shared the secret of dragon collars with the player, revealing his true nature as a shapeshifter.","reason":"Major trust moment and revelation"}],"form_transitions":[{"npc_id":"oren-uuid","npc_name":"Oren","new_form_label":"Wolf Form","new_appearance":"massive grey wolf, amber eyes, a scar across the left flank","new_personality":"primal, protective, still recognises the player","new_current_state":"transformed, guarding the forge entrance","reason":"Transformed at scene end when threatened"}]}"""


class SuggestSummaryRequest(BaseModel):
    model_name: Optional[str] = None


_SUMMARY_CHUNK_SIZE = 12  # turns per extraction call


@router.post("/{campaign_id}/scenes/{scene_id}/suggest-summary")
def suggest_scene_summary(campaign_id: str, scene_id: str, req: SuggestSummaryRequest = None):
    """
    Generate a suggested summary by chunking the transcript into batches of
    _SUMMARY_CHUNK_SIZE turns and extracting events from each chunk separately.
    This prevents early turns being ignored due to attention degradation on long transcripts.
    """
    import httpx
    import re as _re

    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")
    if not scene.turns:
        return {"summary": ""}

    # Exclude silent continue nudges
    visible_turns = [t for t in scene.turns if t.content != "(Continue the story.)"]

    campaign = _campaigns().get(campaign_id)
    model = (req.model_name if req and req.model_name else None) \
            or (getattr(campaign, "summary_model_name", None) if campaign else None) \
            or (campaign.model_name if campaign else None) \
            or config.ollama_model

    def _call(prompt: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUGGEST_SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 1024,
                "num_ctx": config.context_window,
            },
        }
        r = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        r.raise_for_status()
        raw = r.json()["message"]["content"]
        return _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()

    # Split into chunks and extract events from each independently
    all_lines: list[str] = []
    total = len(visible_turns)
    try:
        for chunk_start in range(0, total, _SUMMARY_CHUNK_SIZE):
            chunk = visible_turns[chunk_start:chunk_start + _SUMMARY_CHUNK_SIZE]
            chunk_text = "\n\n".join(
                f"[Turn {chunk_start + i + 1} — {'Player' if t.role == 'user' else 'Narrator'}]: {t.content}"
                for i, t in enumerate(chunk)
            )
            first_turn = chunk_start + 1
            last_turn = chunk_start + len(chunk)
            prompt = (
                f"Scene title: {scene.title or 'Untitled'}\n"
                f"Location: {scene.location or 'Unknown'}\n"
                f"This is turns {first_turn}–{last_turn} of {total} total.\n\n"
                f"TRANSCRIPT EXCERPT:\n\n{chunk_text}\n\n"
                f"--- END OF EXCERPT ---\n\n"
                f"List every significant event from ONLY these turns, one per line with its turn number. "
                f"Only include what is explicitly stated above. Begin:"
            )
            chunk_result = _call(prompt)
            # Collect non-empty lines that look like bullet entries
            for line in chunk_result.splitlines():
                line = line.strip()
                if line and (line.startswith("-") or line.startswith("[")):
                    all_lines.append(line)
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "Summary generation timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"Summary generation failed: {e}")

    return {"summary": "\n".join(all_lines)}


@router.post("/{campaign_id}/scenes/{scene_id}/suggest-updates")
def suggest_world_updates(campaign_id: str, scene_id: str):
    """
    After a scene is confirmed, suggest world document updates based on what happened.
    Returns structured suggestions the player can approve/reject.
    """
    import json as _json
    import httpx
    from app.campaigns.world_builder import _extract_json

    scene = _scenes().get(scene_id)
    if not scene or scene.campaign_id != campaign_id:
        raise HTTPException(404, "Scene not found")

    npcs = _npcs().get_all(campaign_id)
    threads = _threads().get_all(campaign_id)
    places = _places().get_all(campaign_id)

    # Build world state snapshot for context
    npc_lines = [
        f"• {n.name} (id={n.id}) — role: {n.role or 'unknown'}, "
        f"current_state: \"{n.current_state}\", is_alive: {n.is_alive}, "
        f"location: \"{n.current_location}\""
        for n in npcs
    ]
    thread_lines = [
        f"• {t.title} (id={t.id}) [{t.status.value}]: {t.description}"
        for t in threads
    ]
    place_lines = [
        f"• {p.name}: {p.description}"
        for p in places
    ]
    # Exclude silent continue nudges from transcript
    visible_turns = [t for t in scene.turns if t.content != "(Continue the story.)"]
    transcript_lines = [
        f"[{'Player' if t.role == 'user' else 'Narrator'}]: {t.content}"
        for t in visible_turns
    ]

    # Build prompt — put the content FIRST so the model reads scene before exclusion lists
    parts = []
    if scene.confirmed_summary:
        parts.append(f"[CONFIRMED SCENE SUMMARY]\n{scene.confirmed_summary}")
    if transcript_lines:
        parts.append("[SCENE TRANSCRIPT]\n" + "\n\n".join(transcript_lines))
    if thread_lines:
        parts.append("[ACTIVE NARRATIVE THREADS — update status if resolved/dormant]\n" + "\n".join(thread_lines))
    if npc_lines:
        parts.append("[ALREADY RECORDED NPCs — do NOT add these again]\n" + "\n".join(npc_lines))
    if place_lines:
        parts.append("[ALREADY RECORDED LOCATIONS — do NOT add these again]\n" + "\n".join(place_lines))

    prompt = "\n\n".join(parts) + (
        "\n\nFirst, mentally list every character name (or title/role if unnamed) that appears anywhere in the transcript above. "
        "Then, for each one NOT in the ALREADY RECORDED NPCs list, add a new_npc entry. "
        "Also extract every new location and every plot fact or revelation. "
        "Output ONLY the JSON object starting with {."
    )

    campaign = _campaigns().get(campaign_id)
    model = (getattr(campaign, "summary_model_name", None) if campaign else None) \
            or (campaign.model_name if campaign else None) \
            or config.ollama_model

    log.info("suggest_world_updates: using model=%s for scene=%s", model, scene_id)

    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SUGGEST_UPDATES_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.5, "num_predict": 8192, "num_ctx": config.context_window},
        }
        r = httpx.post(
            f"{config.ollama_base_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=httpx.Timeout(10.0, read=300.0),
        )
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
    except httpx.ConnectError:
        raise HTTPException(503, "Cannot reach Ollama. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "World updates generation timed out. Try a faster model.")
    except Exception as e:
        raise HTTPException(503, f"World updates generation failed: {e}")

    # Strip <think> blocks before parsing (Qwen3, DeepSeek-R1, etc.)
    import re as _re
    raw = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()

    data = _extract_json(raw)
    has_any = any([data.get("npc_updates"), data.get("new_facts"), data.get("thread_updates"),
                   data.get("new_npcs"), data.get("new_locations"),
                   data.get("history_updates"), data.get("form_transitions")])
    parse_ok = bool(data)

    log.info(
        "suggest_world_updates: model=%s raw_len=%d parse_ok=%s has_any=%s "
        "new_npcs=%d new_locations=%d new_facts=%d npc_updates=%d thread_updates=%d "
        "history_updates=%d form_transitions=%d",
        model, len(raw), parse_ok, has_any,
        len(data.get("new_npcs", [])), len(data.get("new_locations", [])),
        len(data.get("new_facts", [])), len(data.get("npc_updates", [])),
        len(data.get("thread_updates", [])),
        len(data.get("history_updates", [])), len(data.get("form_transitions", [])),
    )
    if not parse_ok:
        log.warning("suggest_world_updates: JSON parse FAILED. Raw (first 3000 chars):\n%s", raw[:3000])
    elif not has_any:
        log.warning("suggest_world_updates: model returned all-empty arrays. Raw (first 3000 chars):\n%s", raw[:3000])

    return {
        "npc_updates": data.get("npc_updates", []),
        "new_facts": data.get("new_facts", []),
        "thread_updates": data.get("thread_updates", []),
        "new_npcs": data.get("new_npcs", []),
        "new_locations": data.get("new_locations", []),
        "history_updates": data.get("history_updates", []),
        "form_transitions": data.get("form_transitions", []),
        "_model": model,
        "_parse_ok": parse_ok,
        "_raw": raw[:2000],   # first 2000 chars for client-side debug panel
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _upsert_chronicle(campaign_id: str, scene_number: int, content: str) -> None:
    """Create or update the chronicle entry for a specific scene number."""
    store = _chronicle()
    existing = next(
        (e for e in store.get_all(campaign_id)
         if e.scene_range_start == scene_number and e.scene_range_end == scene_number),
        None,
    )
    if existing:
        store.update_content(existing.id, content)
    else:
        store.save(ChronicleEntry(
            campaign_id=campaign_id,
            scene_range_start=scene_number,
            scene_range_end=scene_number,
            content=content,
            confirmed=True,
        ))


def _require_campaign(campaign_id: str):
    c = _campaigns().get(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


def _campaign_dict(c) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "model_name": c.model_name,
        "summary_model_name": c.summary_model_name if hasattr(c, "summary_model_name") else None,
        "style_guide": c.style_guide.model_dump(),
        "gen_settings": c.gen_settings.model_dump(),
        "notes": c.notes,
        "cover_image": c.cover_image,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _pc_dict(pc) -> dict:
    if pc is None:
        return {}
    return {
        "id": pc.id,
        "campaign_id": pc.campaign_id,
        "name": pc.name,
        "appearance": pc.appearance,
        "personality": pc.personality,
        "background": pc.background,
        "wants": pc.wants,
        "fears": pc.fears,
        "how_seen": pc.how_seen,
        "dev_log": [{"scene_number": e.scene_number, "note": e.note} for e in (pc.dev_log or [])],
        "portrait_image": pc.portrait_image,
        "created_at": pc.created_at.isoformat(),
        "updated_at": pc.updated_at.isoformat(),
    }


def _fact_dict(f) -> dict:
    return {
        "id": f.id,
        "campaign_id": f.campaign_id,
        "content": f.content,
        "category": f.category,
        "priority": f.priority if hasattr(f, "priority") else "normal",
        "trigger_keywords": f.trigger_keywords if hasattr(f, "trigger_keywords") else [],
        "fact_order": f.fact_order,
        "created_at": f.created_at.isoformat(),
    }


def _place_dict(p) -> dict:
    return {
        "id": p.id,
        "campaign_id": p.campaign_id,
        "name": p.name,
        "description": p.description,
        "current_state": p.current_state,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _npc_dict(n) -> dict:
    return {
        "id": n.id,
        "campaign_id": n.campaign_id,
        "name": n.name,
        "appearance": n.appearance,
        "personality": n.personality,
        "role": n.role,
        "gender": n.gender,
        "age": n.age,
        "relationship_to_player": n.relationship_to_player,
        "current_location": n.current_location,
        "current_state": n.current_state,
        "is_alive": n.is_alive,
        "status": n.status.value if hasattr(n.status, "value") else n.status,
        "status_reason": n.status_reason,
        "secrets": n.secrets,
        "short_term_goal": n.short_term_goal,
        "long_term_goal": n.long_term_goal,
        "history_with_player": n.history_with_player if hasattr(n, "history_with_player") else "",
        "forms": [f.model_dump() for f in n.forms] if hasattr(n, "forms") else [],
        "active_form": n.active_form if hasattr(n, "active_form") else None,
        "dev_log": [{"scene_number": e.scene_number, "note": e.note} for e in (n.dev_log or [])],
        "portrait_image": n.portrait_image,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _thread_dict(t) -> dict:
    return {
        "id": t.id,
        "campaign_id": t.campaign_id,
        "title": t.title,
        "description": t.description,
        "status": t.status.value if hasattr(t.status, "value") else t.status,
        "resolution": t.resolution,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _faction_dict(f) -> dict:
    return {
        "id": f.id,
        "campaign_id": f.campaign_id,
        "name": f.name,
        "description": f.description,
        "goals": f.goals,
        "methods": f.methods,
        "standing_with_player": f.standing_with_player,
        "relationship_notes": f.relationship_notes,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }


def _rel_dict(r) -> dict:
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "npc_id_a": r.npc_id_a,
        "npc_id_b": r.npc_id_b,
        "dynamic": r.dynamic,
        "trust": r.trust,
        "hostility": r.hostility,
        "history": r.history,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _scene_dict(s) -> dict:
    return {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "scene_number": s.scene_number,
        "title": s.title,
        "location": s.location,
        "npc_ids": s.npc_ids,
        "intent": s.intent,
        "tone": s.tone,
        "turns": [
            {"role": t.role, "content": t.content}
            for t in s.turns
        ],
        "proposed_summary": s.proposed_summary,
        "confirmed_summary": s.confirmed_summary,
        "confirmed": s.confirmed,
        "allow_unselected_npcs": s.allow_unselected_npcs,
        "scene_image": s.scene_image,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _chronicle_dict(e) -> dict:
    return {
        "id": e.id,
        "campaign_id": e.campaign_id,
        "scene_range_start": e.scene_range_start,
        "scene_range_end": e.scene_range_end,
        "content": e.content,
        "confirmed": e.confirmed,
        "created_at": e.created_at.isoformat(),
    }
