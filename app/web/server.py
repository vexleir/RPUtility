"""
FastAPI web server for RP Utility.
Serves the session creation UI and chat interface.
Start with: python -m app.main serve
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import json

# Cache-buster: changes every server restart so browsers always fetch fresh JS/CSS.
_BOOT_TS = str(int(time.time()))

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Route-level logger — errors will appear in the uvicorn console
log = logging.getLogger("rp_utility")

from app.core.config import config
from app.core.engine import RoleplayEngine
from app.prompting.builder import derive_relationship_summary

# ── Paths ─────────────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="RP Utility", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Campaign system routes
from app.web.campaign_routes import router as campaign_router  # noqa: E402
app.include_router(campaign_router)

# Single engine instance shared across requests
_engine: Optional[RoleplayEngine] = None


def get_engine() -> RoleplayEngine:
    global _engine
    if _engine is None:
        _engine = RoleplayEngine(config)
    return _engine


def read_template(name: str, **substitutions: str) -> str:
    """Read an HTML template and apply simple {{KEY}} substitutions.
    CACHE_VER is automatically injected so ?v={{CACHE_VER}} on static URLs
    busts the browser cache on every server restart."""
    html = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    substitutions.setdefault("CACHE_VER", _BOOT_TS)
    for key, value in substitutions.items():
        html = html.replace(f"{{{{{key}}}}}", value)
    return html


# ── Request / response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: str
    character_name: str = "Character"    # default for Scenario Mode
    lorebook_name: Optional[str] = None
    model_name: Optional[str] = None
    location: str = "Unknown"
    scenario_text: Optional[str] = None  # Scenario Mode — replaces a card file


class ChatRequest(BaseModel):
    message: str
    user_name: str = "Player"
    # Optional per-request generation overrides (from the settings panel)
    temperature: Optional[float] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None

    def gen_params(self) -> dict:
        """Return only the overrides that were explicitly set."""
        return {k: v for k, v in {
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "min_p": self.min_p,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
        }.items() if v is not None}


class UpdateSceneRequest(BaseModel):
    location: Optional[str] = None
    summary: Optional[str] = None


class CreateObjectiveRequest(BaseModel):
    title: str
    description: str = ""


class UpdateObjectiveRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class BookmarkRequest(BaseModel):
    note: str = ""


class RegenerateRequest(ChatRequest):
    pass


class EditTurnRequest(BaseModel):
    content: str


class AddAliasRequest(BaseModel):
    canonical: str
    alias: str


class MergeCharactersRequest(BaseModel):
    canonical: str
    aliases: list[str]


class CreateNpcRequest(BaseModel):
    name: str
    role: str = ""
    description: str = ""
    personality_notes: str = ""
    last_known_location: str = ""
    is_alive: bool = True


class UpdateNpcRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    personality_notes: Optional[str] = None
    last_known_location: Optional[str] = None
    is_alive: Optional[bool] = None


class CreateLocationRequest(BaseModel):
    name: str
    description: str = ""
    atmosphere: str = ""
    notes: str = ""


class UpdateLocationRequest(BaseModel):
    description: Optional[str] = None
    atmosphere: Optional[str] = None
    notes: Optional[str] = None


class SetClockRequest(BaseModel):
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    hour: Optional[int] = None
    era_label: Optional[str] = None
    notes: Optional[str] = None


class CreateStoryBeatRequest(BaseModel):
    title: str
    description: str = ""
    beat_type: str = "milestone"
    turn_number: int = 0
    importance: str = "medium"


class SetEmotionalStateRequest(BaseModel):
    mood: Optional[str] = None
    stress: Optional[float] = None
    motivation: Optional[str] = None
    notes: Optional[str] = None


class CreateItemRequest(BaseModel):
    name: str
    description: str = ""
    condition: str = "good"
    quantity: int = 1
    is_equipped: bool = False


class UpdateItemRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[str] = None
    quantity: Optional[int] = None
    is_equipped: Optional[bool] = None


class CreateStatusEffectRequest(BaseModel):
    name: str
    description: str = ""
    effect_type: str = "neutral"
    severity: str = "mild"
    duration_turns: int = 0


class CreateStatRequest(BaseModel):
    name: str
    value: int = 10
    modifier: int = 0
    category: str = "attribute"


class UpdateStatRequest(BaseModel):
    name: str | None = None
    value: int | None = None
    modifier: int | None = None
    category: str | None = None


class RollCheckRequest(BaseModel):
    stat_name: str
    difficulty: int
    dice: str = "d20"
    narrative_context: str = ""


class SetNarrativeArcRequest(BaseModel):
    current_act: int | None = None
    act_label: str | None = None
    tension: float | None = None
    pacing: str | None = None
    themes: list[str] | None = None
    arc_notes: str | None = None


class CreateFactionRequest(BaseModel):
    name: str
    description: str = ""
    alignment: str = ""
    standing: float = 0.0
    notes: str = ""


class UpdateFactionRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    alignment: str | None = None
    standing: float | None = None
    notes: str | None = None


class AdjustStandingRequest(BaseModel):
    delta: float


class CreateQuestRequest(BaseModel):
    title: str
    description: str = ""
    giver_npc_name: str = ""
    location_name: str = ""
    reward_notes: str = ""
    importance: str = "medium"
    stages: list[dict] = []


class UpdateQuestRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    giver_npc_name: str | None = None
    location_name: str | None = None
    reward_notes: str | None = None
    importance: str | None = None


class CompleteStageRequest(BaseModel):
    stage_id: str


class CreateJournalEntryRequest(BaseModel):
    title: str
    content: str
    turn_number: int = 0
    tags: list[str] = []


class CreateLoreNoteRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    source: str = ""
    tags: list[str] = []


class UpdateLoreNoteRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    source: str | None = None


# ── HTML pages ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    """Session list and new-session creation form."""
    return HTMLResponse(read_template("index.html"))


@app.get("/chat/{session_id}", response_class=HTMLResponse)
def chat_page(session_id: str):
    """Chat interface for a session."""
    engine = get_engine()
    session = engine.load_session(session_id)
    if not session:
        # Try prefix match
        sessions = engine.list_sessions()
        session = next((s for s in sessions if s.id.startswith(session_id)), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return HTMLResponse(read_template("chat.html", SESSION_ID=session.id))


@app.get("/chat/{session_id}/status", response_class=HTMLResponse)
def status_page(session_id: str):
    """Session status and inspection page."""
    engine = get_engine()
    session = engine.load_session(session_id)
    if not session:
        sessions = engine.list_sessions()
        session = next((s for s in sessions if s.id.startswith(session_id)), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return HTMLResponse(read_template("status.html", SESSION_ID=session.id))


@app.get("/chat/{session_id}/recap", response_class=HTMLResponse)
def recap_page(session_id: str):
    """Dedicated story recap page for returning players."""
    engine = get_engine()
    session = engine.load_session(session_id)
    if not session:
        sessions = engine.list_sessions()
        session = next((s for s in sessions if s.id.startswith(session_id)), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return HTMLResponse(read_template("recap.html", SESSION_ID=session.id))


# ── Campaign HTML pages ───────────────────────────────────────────────────────

@app.get("/campaigns/new", response_class=HTMLResponse)
def campaign_new_page():
    """World builder / new campaign creation page."""
    return HTMLResponse(read_template("campaign_new.html"))


@app.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_overview_page(campaign_id: str):
    """Campaign overview: world document, NPCs, threads, scene history."""
    return HTMLResponse(read_template("campaign_overview.html", CAMPAIGN_ID=campaign_id))


@app.get("/campaigns/{campaign_id}/play", response_class=HTMLResponse)
def campaign_play_page(campaign_id: str):
    """Scene play interface for a campaign."""
    return HTMLResponse(read_template("campaign_play.html", CAMPAIGN_ID=campaign_id))


@app.get("/api/session/{session_id}/recap/full")
def api_get_full_recap(session_id: str):
    """Generate and return the full narrative recap for the recap page."""
    from app.sessions.recap import generate_full_recap
    engine = get_engine()
    session = _resolve(engine, session_id)
    if session.turn_count == 0:
        return {"recap": "", "scene": None, "relationships": [], "npcs": [], "objectives": []}

    provider = engine._provider_for_session(session)
    memories = engine.memory_store.get_active(session_id)
    scene = engine.scene_mgr.get(session_id)
    relationships = engine.rel_tracker.get_all(session_id)
    clock = engine.clock_store.get_or_default(session_id)
    npcs = engine.get_npcs(session_id)
    objectives = engine.get_objectives(session_id)

    recap_text = generate_full_recap(
        provider=provider,
        memories=memories,
        scene=scene,
        relationships=relationships,
        clock=clock,
        session_name=session.name,
        character_name=session.character_name,
        turn_count=session.turn_count,
    )

    return {
        "recap": recap_text,
        "scene": _scene_dict(scene) if scene else None,
        "clock": _clock_dict(clock),
        "relationships": [_rel_dict(r) for r in relationships],
        "npcs": [
            {"name": n.name, "role": n.role, "description": n.description}
            for n in npcs
        ],
        "objectives": [
            {"title": o.title, "status": o.status.value, "description": o.description}
            for o in objectives
        ],
        "session": {
            "name": session.name,
            "character_name": session.character_name,
            "turn_count": session.turn_count,
        },
    }


# ── API: assets ───────────────────────────────────────────────────────────────

@app.get("/api/cards")
def api_list_cards():
    """List all available character cards with their key fields."""
    engine = get_engine()
    result = []
    for name, card in engine._cards.items():
        result.append({
            "name": card.name,
            "description": card.description,
            "personality": card.personality,
            "scenario": card.scenario,
            "first_message": card.first_message,
            "tags": card.tags,
            "has_image": name in engine._card_images,
        })
    return result


@app.get("/api/lorebooks")
def api_list_lorebooks():
    """List all available lorebooks."""
    engine = get_engine()
    return [
        {"name": book.name, "description": book.description, "entries": len(book.entries)}
        for book in engine._lorebooks.values()
    ]


@app.get("/api/cards/{card_name}/details")
def api_card_details(card_name: str):
    """Return all fields of a character card for in-browser viewing."""
    engine = get_engine()
    card = engine._cards.get(card_name)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card '{card_name}' not found")
    data = card.model_dump()
    data["has_image"] = card_name in engine._card_images
    return data


@app.get("/api/cards/{card_name}/image")
def api_card_image(card_name: str):
    """Serve the portrait PNG for a card (only available for PNG-sourced cards)."""
    engine = get_engine()
    img_path = engine._card_images.get(card_name)
    if not img_path or not img_path.exists():
        raise HTTPException(status_code=404, detail="No image for this card")
    return Response(content=img_path.read_bytes(), media_type="image/png")


@app.post("/api/cards/upload", status_code=201)
async def api_upload_card(file: UploadFile = File(...)):
    """Upload a .json or .png character card into the cards directory."""
    filename = Path(file.filename or "card").name
    if not filename.lower().endswith((".json", ".png")):
        raise HTTPException(status_code=400, detail="Only .json and .png files are accepted")

    dest = Path(config.cards_dir) / filename
    content = await file.read()
    dest.write_bytes(content)

    try:
        engine = get_engine()
        if filename.lower().endswith(".png"):
            from app.cards.loader import load_card_from_png
            card = load_card_from_png(dest)
            engine._card_images[card.name] = dest
        else:
            from app.cards.loader import load_card_from_file
            card = load_card_from_file(dest)
        engine._cards[card.name] = card
        return {"name": card.name, "description": card.description, "has_image": filename.lower().endswith(".png")}
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not parse card: {e}")


@app.get("/api/lorebooks/{lorebook_name}/details")
def api_lorebook_details(lorebook_name: str):
    """Return full lorebook contents including all entries."""
    engine = get_engine()
    book = engine._lorebooks.get(lorebook_name)
    if not book:
        raise HTTPException(status_code=404, detail=f"Lorebook '{lorebook_name}' not found")
    return {
        "name": book.name,
        "description": book.description,
        "entries": [
            {
                "keys": e.keys,
                "content": e.content,
                "enabled": e.enabled,
                "priority": e.priority,
                "comment": e.comment,
            }
            for e in book.entries
        ],
    }


@app.post("/api/lorebooks/upload", status_code=201)
async def api_upload_lorebook(file: UploadFile = File(...)):
    """Upload a .json or .png lorebook into the lorebooks directory."""
    filename = Path(file.filename or "lorebook").name
    if not filename.lower().endswith((".json", ".png")):
        raise HTTPException(status_code=400, detail="Only .json and .png files are accepted")

    dest = Path(config.lorebooks_dir) / filename
    content = await file.read()
    dest.write_bytes(content)

    try:
        engine = get_engine()
        if filename.lower().endswith(".png"):
            from app.lorebooks.loader import load_lorebook_from_png
            book = load_lorebook_from_png(dest)
        else:
            from app.lorebooks.loader import load_lorebook_from_file
            book = load_lorebook_from_file(dest)
        engine._lorebooks[book.name] = book
        return {"name": book.name, "description": book.description, "entries": len(book.entries)}
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not parse lorebook: {e}")


@app.post("/api/reload")
def api_reload_assets():
    """Reload all cards and lorebooks from disk without restarting."""
    engine = get_engine()
    counts = engine.reload_assets()
    return counts


@app.get("/api/models")
def api_list_models():
    """List models available on the configured provider."""
    engine = get_engine()
    raw = engine.list_available_models()
    result = []
    for m in raw:
        name = m.get("name") or m.get("id", "unknown")
        size_bytes = m.get("size", 0)
        result.append({
            "name": name,
            "size": size_bytes,
            "size_formatted": _fmt_size(size_bytes),
            "modified": (m.get("modified_at") or m.get("created", ""))[:10],
        })
    return result


@app.get("/api/provider")
def api_provider_status():
    """Check if the model provider is reachable."""
    engine = get_engine()
    return {
        "provider": config.provider,
        "available": engine.provider.is_available(),
        "default_model": config.active_model(),
    }


# ── API: sessions ─────────────────────────────────────────────────────────────

@app.get("/api/sessions")
def api_list_sessions():
    """List all sessions, most recent first."""
    engine = get_engine()
    sessions = engine.list_sessions()
    return [
        {
            "id": s.id,
            "name": s.name,
            "character_name": s.character_name,
            "lorebook_name": s.lorebook_name,
            "model_name": s.model_name,
            "turn_count": s.turn_count,
            "created_at": s.created_at.isoformat(),
            "last_active": s.last_active.isoformat(),
            "scenario_text": s.scenario_text,
        }
        for s in sessions
    ]


@app.post("/api/sessions", status_code=201)
def api_create_session(req: CreateSessionRequest):
    """Create a new roleplay session."""
    engine = get_engine()

    # Card validation only applies when not using Scenario Mode
    if not req.scenario_text:
        if req.character_name not in engine._cards:
            raise HTTPException(
                status_code=400,
                detail=f"Character card '{req.character_name}' not found. "
                       f"Available: {engine.list_cards()}",
            )

    char_name = req.character_name or "Character"
    session = engine.new_session(
        name=req.name,
        character_name=char_name,
        lorebook_name=req.lorebook_name or None,
        model_name=req.model_name or None,
        initial_location=req.location or "Unknown",
        initial_characters=[char_name],
        scenario_text=req.scenario_text or None,
    )
    return {
        "id": session.id,
        "name": session.name,
        "character_name": session.character_name,
        "model_name": session.model_name,
    }


# ── API: session state ────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}")
def api_get_session(session_id: str):
    """Get full session info including first_message from the character card."""
    engine = get_engine()
    session = _resolve(engine, session_id)
    card = engine.get_card(session.character_name)
    scene = engine.get_scene(session.id)

    return {
        "id": session.id,
        "name": session.name,
        "character_name": session.character_name,
        "lorebook_name": session.lorebook_name,
        "model_name": session.model_name or config.active_model(),
        "turn_count": session.turn_count,
        "first_message": card.first_message if card else "",
        "scene": _scene_dict(scene),
    }


@app.get("/api/session/{session_id}/turns")
def api_get_turns(session_id: str, limit: int = 60, offset: int = 0):
    """Get conversation turns for display in the chat UI."""
    engine = get_engine()
    _resolve(engine, session_id)  # validates existence
    turns = engine.sessions.get_turns(session_id, limit=limit, offset=offset)
    return [
        {
            "id": t.id,
            "role": t.role,
            "content": t.content,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in turns
    ]


@app.delete("/api/sessions/{session_id}", status_code=204)
def api_delete_session(session_id: str):
    """Delete a session and all its associated data."""
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_session(session_id)


@app.post("/api/session/{session_id}/chat")
def api_chat(session_id: str, req: ChatRequest):
    """Send a message and get the character's response."""
    engine = get_engine()
    _resolve(engine, session_id)

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        response = engine.chat(session_id, req.message, user_name=req.user_name)
    except RuntimeError as e:
        # Provider unreachable or returned an API error
        log.error("Provider error during chat: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        # Card not loaded, session not found, etc.
        log.error("Configuration error during chat: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Catch-all — log full traceback so it appears in the uvicorn console
        log.exception("Unexpected error during chat for session %s", session_id)
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {e}")

    scene = engine.get_scene(session_id)
    memories = engine.get_memories(session_id)
    rels = engine.get_relationships(session_id)

    return {
        "response": response,
        "scene": _scene_dict(scene),
        "memory_count": len(memories),
        "relationships": [_rel_dict(r) for r in rels],
    }


@app.post("/api/session/{session_id}/chat/stream")
def api_chat_stream(session_id: str, req: ChatRequest):
    """Send a message and stream the response as Server-Sent Events."""
    engine = get_engine()
    _resolve(engine, session_id)

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    def event_generator():
        try:
            for item in engine.chat_stream(session_id, req.message, gen_params=req.gen_params(), user_name=req.user_name):
                if isinstance(item, str):
                    # Text token — send as SSE data
                    yield f"data: {json.dumps({'token': item})}\n\n"
                else:
                    # Final metadata dict
                    payload = {
                        "done": True,
                        "scene": _scene_dict(item["scene"]),
                        "memory_count": item["memory_count"],
                        "relationships": [_rel_dict(r) for r in item["relationships"]],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except (RuntimeError, ValueError) as e:
            log.error("Stream error for session %s: %s", session_id, e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:
            log.exception("Unexpected stream error for session %s", session_id)
            yield f"data: {json.dumps({'error': f'Internal error: {type(e).__name__}: {e}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/session/{session_id}/scene")
def api_get_scene(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return _scene_dict(engine.get_scene(session_id))


@app.put("/api/session/{session_id}/scene")
def api_update_scene(session_id: str, req: UpdateSceneRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    scene = engine.update_scene(
        session_id,
        location=req.location,
        summary=req.summary,
    )
    return _scene_dict(scene)


@app.get("/api/session/{session_id}/memories")
def api_get_memories(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    memories = engine.get_memories(session_id)
    return [
        {
            "id": m.id,
            "type": m.type.value,
            "title": m.title,
            "content": m.content,
            "importance": m.importance.value,
            "certainty": m.certainty.value,
            "entities": m.entities,
            "tags": m.tags,
            "location": m.location,
            "confidence": m.confidence,
            "archived": m.archived,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories
    ]


class CreateMemoryRequest(BaseModel):
    title: str
    content: str
    type: str = "world_fact"
    importance: str = "critical"
    certainty: str = "confirmed"
    entities: list[str] = []


@app.post("/api/session/{session_id}/memories", status_code=201)
def api_create_memory(session_id: str, req: CreateMemoryRequest):
    """Manually create a memory entry (e.g. to correct a hallucination)."""
    from app.core.models import MemoryEntry, MemoryType, ImportanceLevel, CertaintyLevel
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        mem_type = MemoryType(req.type)
        importance = ImportanceLevel(req.importance)
        certainty = CertaintyLevel(req.certainty)
    except ValueError as e:
        raise HTTPException(400, str(e))
    entry = MemoryEntry(
        session_id=session_id,
        type=mem_type,
        title=req.title.strip(),
        content=req.content.strip(),
        importance=importance,
        certainty=certainty,
        entities=req.entities,
        confidence=1.0,
    )
    engine.memory_store.save(entry)
    return {"id": entry.id, "title": entry.title, "importance": entry.importance.value}


@app.delete("/api/session/{session_id}/memories/{memory_id}", status_code=204)
def api_delete_memory(session_id: str, memory_id: str):
    """Permanently delete a single memory entry."""
    engine = get_engine()
    _resolve(engine, session_id)
    mem = engine.memory_store.get(memory_id)
    if not mem or mem.session_id != session_id:
        raise HTTPException(404, "Memory not found.")
    engine.memory_store.delete(memory_id)


@app.get("/api/session/{session_id}/memories/archived")
def api_get_archived_memories(session_id: str):
    """Return consolidated-away (archived) memories for debug inspection."""
    engine = get_engine()
    _resolve(engine, session_id)
    memories = engine.memory_store.get_archived(session_id)
    return [
        {
            "id": m.id,
            "type": m.type.value,
            "title": m.title,
            "content": m.content,
            "importance": m.importance.value,
            "certainty": m.certainty.value,
            "confidence": m.confidence,
            "consolidated_from": m.consolidated_from,
            "created_at": m.created_at.isoformat(),
        }
        for m in memories
    ]


@app.get("/api/session/{session_id}/world-state")
def api_get_world_state(session_id: str):
    """Return world-state entries for the session."""
    engine = get_engine()
    _resolve(engine, session_id)
    entries = engine.get_world_state(session_id)
    return [
        {
            "id": e.id,
            "category": e.category,
            "title": e.title,
            "content": e.content,
            "importance": e.importance.value,
            "entities": e.entities,
            "tags": e.tags,
            "updated_at": e.updated_at.isoformat(),
        }
        for e in entries
    ]


@app.get("/api/session/{session_id}/contradictions")
def api_get_contradictions(session_id: str):
    """Return contradiction flags detected during extraction."""
    engine = get_engine()
    _resolve(engine, session_id)
    flags = engine.get_contradiction_flags(session_id)
    return [
        {
            "id": f.id,
            "detected_at": f.detected_at.isoformat(),
            "new_memory_id": f.new_memory_id,
            "existing_memory_id": f.existing_memory_id,
            "description": f.description,
            "resolution": f.resolution,
        }
        for f in flags
    ]


class ResolveContradictionRequest(BaseModel):
    action: str  # "keep_new" | "keep_old" | "dismiss"


@app.post("/api/session/{session_id}/contradictions/{flag_id}/resolve", status_code=200)
def api_resolve_contradiction(session_id: str, flag_id: str, req: ResolveContradictionRequest):
    """
    Resolve a contradiction flag.
    - keep_new: archive the existing (old) memory, delete the flag
    - keep_old: archive the new memory, delete the flag
    - dismiss: delete the flag without archiving either memory
    """
    engine = get_engine()
    _resolve(engine, session_id)

    flags = engine.get_contradiction_flags(session_id)
    flag = next((f for f in flags if f.id == flag_id), None)
    if not flag:
        raise HTTPException(404, "Contradiction flag not found.")

    action = req.action
    if action not in ("keep_new", "keep_old", "dismiss"):
        raise HTTPException(400, "action must be keep_new, keep_old, or dismiss")

    if action == "keep_new" and flag.existing_memory_id:
        engine.memory_store.archive(flag.existing_memory_id)
    elif action == "keep_old" and flag.new_memory_id:
        engine.memory_store.archive(flag.new_memory_id)

    engine.memory_store.delete_contradiction_flag(flag_id)
    return {"resolved": True, "action": action}


@app.get("/api/session/{session_id}/relationships")
def api_get_relationships(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    alias_map = engine.alias_store.build_map(session_id)
    rels = engine.get_relationships(session_id)
    # Normalise entity names through alias map before returning
    for r in rels:
        r.source_entity = alias_map.get(r.source_entity.lower(), r.source_entity)
        r.target_entity = alias_map.get(r.target_entity.lower(), r.target_entity)
    # Deduplicate: if two rows resolve to same source→target, keep highest trust
    seen: dict[tuple, object] = {}
    for r in rels:
        key = (r.source_entity, r.target_entity)
        if key not in seen or abs(r.trust) + abs(r.affection) > abs(seen[key].trust) + abs(seen[key].affection):
            seen[key] = r
    return [_rel_dict(r) for r in seen.values()]


# ── API: regenerate ───────────────────────────────────────────────────────────

@app.delete("/api/session/{session_id}/turns/last", status_code=200)
def api_delete_last_turn(session_id: str):
    """Remove the last assistant+user exchange. Returns the original user message."""
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        result = engine.delete_last_exchange(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/api/session/{session_id}/chat/regenerate")
def api_regenerate(session_id: str, req: RegenerateRequest):
    """Re-run the last user message and stream a fresh response."""
    engine = get_engine()
    _resolve(engine, session_id)

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    def event_generator():
        try:
            for item in engine.chat_stream(session_id, req.message, gen_params=req.gen_params(), user_name=req.user_name):
                if isinstance(item, str):
                    yield f"data: {json.dumps({'token': item})}\n\n"
                else:
                    payload = {
                        "done": True,
                        "scene": _scene_dict(item["scene"]),
                        "memory_count": item["memory_count"],
                        "relationships": [_rel_dict(r) for r in item["relationships"]],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            log.exception("Regenerate stream error for session %s", session_id)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── API: objectives ───────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/objectives")
def api_get_objectives(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_obj_dict(o) for o in engine.get_objectives(session_id)]


@app.post("/api/session/{session_id}/objectives", status_code=201)
def api_create_objective(session_id: str, req: CreateObjectiveRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    obj = engine.add_objective(session_id, req.title.strip(), req.description)
    return _obj_dict(obj)


@app.put("/api/session/{session_id}/objectives/{objective_id}")
def api_update_objective(session_id: str, objective_id: str, req: UpdateObjectiveRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        obj = engine.update_objective(
            objective_id,
            title=req.title,
            description=req.description,
            status=req.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _obj_dict(obj)


@app.delete("/api/session/{session_id}/objectives/{objective_id}", status_code=204)
def api_delete_objective(session_id: str, objective_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_objective(objective_id)


# ── API: turn editing ────────────────────────────────────────────────────────

@app.put("/api/session/{session_id}/turns/{turn_id}")
def api_edit_turn(session_id: str, turn_id: str, req: EditTurnRequest):
    """Update the content of a single conversation turn."""
    engine = get_engine()
    _resolve(engine, session_id)
    content = req.content.strip()
    if not content:
        raise HTTPException(400, "Content cannot be empty.")
    found = engine.sessions.update_turn_content(turn_id, content)
    if not found:
        raise HTTPException(404, f"Turn '{turn_id}' not found.")
    return {"id": turn_id, "content": content}


@app.delete("/api/session/{session_id}/turns/{turn_id}", status_code=204)
def api_delete_turn(session_id: str, turn_id: str):
    """Delete a single conversation turn by ID."""
    engine = get_engine()
    _resolve(engine, session_id)
    found = engine.sessions.delete_turn_by_id(turn_id)
    if not found:
        raise HTTPException(404, f"Turn '{turn_id}' not found.")


# ── API: character aliases ─────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/aliases")
def api_get_aliases(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return engine.alias_store.get_all(session_id)


@app.post("/api/session/{session_id}/aliases", status_code=201)
def api_add_alias(session_id: str, req: AddAliasRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.canonical.strip() or not req.alias.strip():
        raise HTTPException(400, "Both canonical and alias are required.")
    return engine.alias_store.add_alias(session_id, req.canonical.strip(), req.alias.strip())


@app.post("/api/session/{session_id}/aliases/merge")
def api_merge_characters(session_id: str, req: MergeCharactersRequest):
    """
    Merge one or more alias names into a canonical character name.
    Rewrites existing relationship rows and memory entity lists in the DB.
    """
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.canonical.strip():
        raise HTTPException(400, "canonical is required.")
    aliases = [a.strip() for a in req.aliases if a.strip()]
    if not aliases:
        raise HTTPException(400, "At least one alias is required.")
    engine.alias_store.merge_entities(session_id, req.canonical.strip(), aliases)
    return {"merged": aliases, "into": req.canonical.strip()}


@app.delete("/api/session/{session_id}/aliases/{alias_id}", status_code=204)
def api_delete_alias(session_id: str, alias_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.alias_store.delete_alias(alias_id)


# ── API: bookmarks ────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/bookmarks")
def api_get_bookmarks(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_bookmark_dict(b) for b in engine.get_bookmarks(session_id)]


@app.post("/api/session/{session_id}/turns/{turn_id}/bookmark", status_code=201)
def api_add_bookmark(session_id: str, turn_id: str, req: BookmarkRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    # Toggle: if already bookmarked, remove it
    existing = engine.get_bookmark_for_turn(session_id, turn_id)
    if existing:
        engine.delete_bookmark(existing.id)
        return {"removed": True, "id": existing.id}
    try:
        bm = engine.add_bookmark(session_id, turn_id, req.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _bookmark_dict(bm)


@app.delete("/api/session/{session_id}/bookmarks/{bookmark_id}", status_code=204)
def api_delete_bookmark(session_id: str, bookmark_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_bookmark(bookmark_id)


# ── API: search ───────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/turns/search")
def api_search_turns(session_id: str, q: str = Query(default="", min_length=1)):
    engine = get_engine()
    _resolve(engine, session_id)
    turns = engine.search_turns(session_id, q)
    return [
        {
            "id": t.id,
            "role": t.role,
            "content": t.content,
            "timestamp": t.timestamp.isoformat(),
            "turn_number": t.turn_number,
        }
        for t in turns
    ]


# ── API: recap ────────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/recap")
def api_get_recap(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    # Only generate a recap if the session has turns
    session = engine.load_session(session_id)
    if session.turn_count == 0:
        return {"recap": ""}
    recap = engine.generate_recap(session_id)
    return {"recap": recap}


# ── API: export ───────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/export")
def api_export_session(session_id: str):
    """Export full session as a markdown document download."""
    engine = get_engine()
    session = _resolve(engine, session_id)
    turns = engine.sessions.get_turns(session_id, limit=10000)
    bookmarks = engine.get_bookmarks(session_id)
    bookmarked_ids = {b.turn_id for b in bookmarks}

    scene = engine.scene_mgr.get(session_id)
    clock = engine.clock_store.get_or_default(session_id)
    clock_str = f"Day {clock.day}, Month {clock.month}, Year {clock.year} — {clock.time_of_day}"

    lines: list[str] = [
        f"# {session.name}",
        f"*Character: {session.character_name}*",
        f"*Location: {scene.location}*" if scene else "",
        f"*{clock_str}*",
        "",
    ]

    for turn in reversed(turns):
        star = " ⭐" if turn.id in bookmarked_ids else ""
        if turn.role == "user":
            lines.append(f"**You:** {turn.content}{star}\n")
        else:
            lines.append(f"*{session.character_name}:* {turn.content}{star}\n")

    content = "\n".join(lines)
    filename = session.name.replace(" ", "_") + ".md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── API: NPC roster ───────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/npcs")
def api_get_npcs(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_npc_dict(n) for n in engine.get_npcs(session_id)]


@app.post("/api/session/{session_id}/npcs", status_code=201)
def api_create_npc(session_id: str, req: CreateNpcRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    npc = engine.add_npc(
        session_id, req.name.strip(),
        role=req.role, description=req.description,
        personality_notes=req.personality_notes,
        last_known_location=req.last_known_location,
        is_alive=req.is_alive,
    )
    return _npc_dict(npc)


@app.put("/api/session/{session_id}/npcs/{npc_id}")
def api_update_npc(session_id: str, npc_id: str, req: UpdateNpcRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        npc = engine.update_npc(npc_id, **{k: v for k, v in req.model_dump().items() if v is not None})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _npc_dict(npc)


@app.delete("/api/session/{session_id}/npcs/{npc_id}", status_code=204)
def api_delete_npc(session_id: str, npc_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_npc(npc_id)


# ── API: location registry ────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/locations")
def api_get_locations(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_loc_dict(l) for l in engine.get_locations(session_id)]


@app.post("/api/session/{session_id}/locations", status_code=201)
def api_create_location(session_id: str, req: CreateLocationRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    loc = engine.add_location(
        session_id, req.name.strip(),
        description=req.description, atmosphere=req.atmosphere, notes=req.notes,
    )
    return _loc_dict(loc)


@app.put("/api/session/{session_id}/locations/{location_id}")
def api_update_location(session_id: str, location_id: str, req: UpdateLocationRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        loc = engine.update_location(
            location_id, **{k: v for k, v in req.model_dump().items() if v is not None}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _loc_dict(loc)


@app.delete("/api/session/{session_id}/locations/{location_id}", status_code=204)
def api_delete_location(session_id: str, location_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_location(location_id)


# ── API: world clock ──────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/clock")
def api_get_clock(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return _clock_dict(engine.get_clock(session_id))


@app.put("/api/session/{session_id}/clock")
def api_set_clock(session_id: str, req: SetClockRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    clock = engine.set_clock(
        session_id, **{k: v for k, v in req.model_dump().items() if v is not None}
    )
    return _clock_dict(clock)


# ── API: story beats ──────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/story-beats")
def api_get_story_beats(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_beat_dict(b) for b in engine.get_story_beats(session_id)]


@app.post("/api/session/{session_id}/story-beats", status_code=201)
def api_create_story_beat(session_id: str, req: CreateStoryBeatRequest):
    engine = get_engine()
    session = _resolve(engine, session_id)
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    beat = engine.add_story_beat(
        session_id,
        title=req.title.strip(),
        description=req.description,
        beat_type=req.beat_type,
        turn_number=req.turn_number or session.turn_count,
        importance=req.importance,
    )
    return _beat_dict(beat)


@app.delete("/api/session/{session_id}/story-beats/{beat_id}", status_code=204)
def api_delete_story_beat(session_id: str, beat_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_story_beat(beat_id)


# ── API: emotional state ──────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/emotional-state")
def api_get_emotional_state(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return _emotional_state_dict(engine.get_emotional_state(session_id))


@app.put("/api/session/{session_id}/emotional-state")
def api_set_emotional_state(session_id: str, req: SetEmotionalStateRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    state = engine.set_emotional_state(session_id, **kwargs)
    return _emotional_state_dict(state)


# ── API: inventory ────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/inventory")
def api_get_inventory(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_item_dict(i) for i in engine.get_inventory(session_id)]


@app.post("/api/session/{session_id}/inventory", status_code=201)
def api_add_item(session_id: str, req: CreateItemRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    item = engine.add_item(
        session_id,
        name=req.name.strip(),
        description=req.description,
        condition=req.condition,
        quantity=req.quantity,
        is_equipped=req.is_equipped,
    )
    return _item_dict(item)


@app.put("/api/session/{session_id}/inventory/{item_id}")
def api_update_item(session_id: str, item_id: str, req: UpdateItemRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    try:
        item = engine.update_item(
            item_id, **{k: v for k, v in req.model_dump().items() if v is not None}
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _item_dict(item)


@app.delete("/api/session/{session_id}/inventory/{item_id}", status_code=204)
def api_delete_item(session_id: str, item_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_item(item_id)


# ── API: status effects ───────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/status-effects")
def api_get_status_effects(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_effect_dict(e) for e in engine.get_status_effects(session_id)]


@app.post("/api/session/{session_id}/status-effects", status_code=201)
def api_add_status_effect(session_id: str, req: CreateStatusEffectRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    effect = engine.add_status_effect(
        session_id,
        name=req.name.strip(),
        description=req.description,
        effect_type=req.effect_type,
        severity=req.severity,
        duration_turns=req.duration_turns,
    )
    return _effect_dict(effect)


@app.delete("/api/session/{session_id}/status-effects/{effect_id}", status_code=204)
def api_delete_status_effect(session_id: str, effect_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_status_effect(effect_id)


# ── Character Stats ───────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/stats")
def api_get_stats(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    stats = engine.get_stats(session_id)
    return [_stat_dict(s) for s in stats]


@app.post("/api/session/{session_id}/stats", status_code=201)
def api_create_stat(session_id: str, req: CreateStatRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    stat = engine.add_stat(
        session_id,
        name=req.name,
        value=req.value,
        modifier=req.modifier,
        category=req.category,
    )
    return _stat_dict(stat)


@app.put("/api/session/{session_id}/stats/{stat_id}")
def api_update_stat(session_id: str, stat_id: str, req: UpdateStatRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    stat = engine.update_stat(stat_id, **req.model_dump(exclude_none=True))
    return _stat_dict(stat)


@app.delete("/api/session/{session_id}/stats/{stat_id}", status_code=204)
def api_delete_stat(session_id: str, stat_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_stat(stat_id)


# ── Skill Checks ──────────────────────────────────────────────────────────────

@app.post("/api/session/{session_id}/stats/roll", status_code=201)
def api_roll_check(session_id: str, req: RollCheckRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    result = engine.roll_check(
        session_id,
        stat_name=req.stat_name,
        difficulty=req.difficulty,
        dice=req.dice,
        narrative_context=req.narrative_context,
    )
    return _check_dict(result)


@app.get("/api/session/{session_id}/skill-checks")
def api_get_skill_checks(session_id: str, n: int = 20):
    engine = get_engine()
    _resolve(engine, session_id)
    checks = engine.get_skill_checks(session_id, n=n)
    return [_check_dict(c) for c in checks]


# ── Narrative Arc ─────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/narrative-arc")
def api_get_narrative_arc(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    arc = engine.get_narrative_arc(session_id)
    return _arc_dict(arc)


@app.put("/api/session/{session_id}/narrative-arc")
def api_set_narrative_arc(session_id: str, req: SetNarrativeArcRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    arc = engine.set_narrative_arc(session_id, **req.model_dump(exclude_none=True))
    return _arc_dict(arc)


# ── Factions ──────────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/factions")
def api_get_factions(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    factions = engine.get_factions(session_id)
    return [_faction_dict(f) for f in factions]


@app.post("/api/session/{session_id}/factions", status_code=201)
def api_create_faction(session_id: str, req: CreateFactionRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    faction = engine.add_faction(
        session_id,
        name=req.name,
        description=req.description,
        alignment=req.alignment,
        standing=req.standing,
        notes=req.notes,
    )
    return _faction_dict(faction)


@app.put("/api/session/{session_id}/factions/{faction_id}")
def api_update_faction(session_id: str, faction_id: str, req: UpdateFactionRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    faction = engine.update_faction(faction_id, **req.model_dump(exclude_none=True))
    return _faction_dict(faction)


@app.post("/api/session/{session_id}/factions/{faction_id}/standing")
def api_adjust_faction_standing(session_id: str, faction_id: str, req: AdjustStandingRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    faction = engine.adjust_faction_standing(faction_id, req.delta)
    return _faction_dict(faction)


@app.delete("/api/session/{session_id}/factions/{faction_id}", status_code=204)
def api_delete_faction(session_id: str, faction_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_faction(faction_id)


# ── Quest Log ─────────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/quests")
def api_get_quests(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_quest_dict(q) for q in engine.get_quests(session_id)]


@app.post("/api/session/{session_id}/quests", status_code=201)
def api_create_quest(session_id: str, req: CreateQuestRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    quest = engine.add_quest(
        session_id,
        title=req.title,
        description=req.description,
        giver_npc_name=req.giver_npc_name,
        location_name=req.location_name,
        reward_notes=req.reward_notes,
        importance=req.importance,
        stages=req.stages,
    )
    return _quest_dict(quest)


@app.put("/api/session/{session_id}/quests/{quest_id}")
def api_update_quest(session_id: str, quest_id: str, req: UpdateQuestRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    quest = engine.update_quest(quest_id, **req.model_dump(exclude_none=True))
    return _quest_dict(quest)


@app.post("/api/session/{session_id}/quests/{quest_id}/complete-stage")
def api_complete_stage(session_id: str, quest_id: str, req: CompleteStageRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    quest = engine.complete_quest_stage(quest_id, req.stage_id)
    return _quest_dict(quest)


@app.delete("/api/session/{session_id}/quests/{quest_id}", status_code=204)
def api_delete_quest(session_id: str, quest_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_quest(quest_id)


# ── Session Journal ───────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/journal")
def api_get_journal(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_journal_dict(e) for e in engine.get_journal(session_id)]


@app.post("/api/session/{session_id}/journal", status_code=201)
def api_create_journal_entry(session_id: str, req: CreateJournalEntryRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    entry = engine.add_journal_entry(
        session_id,
        title=req.title,
        content=req.content,
        turn_number=req.turn_number,
        tags=req.tags,
    )
    return _journal_dict(entry)


@app.delete("/api/session/{session_id}/journal/{entry_id}", status_code=204)
def api_delete_journal_entry(session_id: str, entry_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_journal_entry(entry_id)


# ── Lore Notes ────────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/lore-notes")
def api_get_lore_notes(session_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    return [_lore_dict(n) for n in engine.get_lore_notes(session_id)]


@app.post("/api/session/{session_id}/lore-notes", status_code=201)
def api_create_lore_note(session_id: str, req: CreateLoreNoteRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    note = engine.add_lore_note(
        session_id,
        title=req.title,
        content=req.content,
        category=req.category,
        source=req.source,
        tags=req.tags,
    )
    return _lore_dict(note)


@app.put("/api/session/{session_id}/lore-notes/{note_id}")
def api_update_lore_note(session_id: str, note_id: str, req: UpdateLoreNoteRequest):
    engine = get_engine()
    _resolve(engine, session_id)
    note = engine.update_lore_note(note_id, **req.model_dump(exclude_none=True))
    return _lore_dict(note)


@app.delete("/api/session/{session_id}/lore-notes/{note_id}", status_code=204)
def api_delete_lore_note(session_id: str, note_id: str):
    engine = get_engine()
    _resolve(engine, session_id)
    engine.delete_lore_note(note_id)


# ── ComfyUI image generation proxy ───────────────────────────────────────────

class ComfyUIGenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = "lowres, bad anatomy, blurry, watermark"
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg: float = 7.0
    checkpoint: str = ""          # empty = auto-detect first available
    comfyui_url: str = "http://localhost:8188"


@app.post("/api/comfyui/generate")
async def api_comfyui_generate(req: ComfyUIGenerateRequest):
    """Proxy image generation to a locally running ComfyUI instance."""
    import asyncio
    import base64
    import random

    base = req.comfyui_url.rstrip("/")

    async with __import__("httpx").AsyncClient(timeout=10.0) as client:
        # ── Resolve checkpoint ──────────────────────────────────────────
        checkpoint = req.checkpoint
        if not checkpoint:
            try:
                r = await client.get(f"{base}/object_info/CheckpointLoaderSimple")
                r.raise_for_status()
                info = r.json()
                ckpts = info.get("CheckpointLoaderSimple", {}).get(
                    "input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                checkpoint = ckpts[0] if ckpts else ""
            except Exception as e:
                raise HTTPException(502, f"Could not reach ComfyUI at {base}: {e}")
        if not checkpoint:
            raise HTTPException(400, "No checkpoint found in ComfyUI. Load a model first.")

        # ── Build workflow ──────────────────────────────────────────────
        seed = random.randint(0, 2**32 - 1)
        workflow = {
            "4": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": checkpoint}},
            "5": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": req.width, "height": req.height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": req.prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": req.negative_prompt, "clip": ["4", 1]}},
            "3": {"class_type": "KSampler",
                  "inputs": {"model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                             "latent_image": ["5", 0], "seed": seed, "steps": req.steps,
                             "cfg": req.cfg, "sampler_name": "euler",
                             "scheduler": "normal", "denoise": 1.0}},
            "8": {"class_type": "VAEDecode",
                  "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage",
                  "inputs": {"images": ["8", 0], "filename_prefix": "rpu"}},
        }

        # ── Queue prompt ────────────────────────────────────────────────
        try:
            r = await client.post(f"{base}/prompt", json={"prompt": workflow}, timeout=15.0)
            r.raise_for_status()
            prompt_id = r.json()["prompt_id"]
        except Exception as e:
            raise HTTPException(502, f"ComfyUI queue error: {e}")

        # ── Poll history ────────────────────────────────────────────────
        async with __import__("httpx").AsyncClient(timeout=300.0) as poll_client:
            for _ in range(180):     # up to ~3 min
                await asyncio.sleep(1)
                try:
                    hr = await poll_client.get(f"{base}/history/{prompt_id}")
                    history = hr.json()
                    if prompt_id in history:
                        outputs = history[prompt_id].get("outputs", {})
                        for node_id, node_out in outputs.items():
                            for img in node_out.get("images", []):
                                filename = img["filename"]
                                subfolder = img.get("subfolder", "")
                                img_type  = img.get("type", "output")
                                params = f"filename={filename}&type={img_type}"
                                if subfolder:
                                    params += f"&subfolder={subfolder}"
                                img_r = await poll_client.get(f"{base}/view?{params}")
                                img_r.raise_for_status()
                                b64 = base64.b64encode(img_r.content).decode()
                                ct = img_r.headers.get("content-type", "image/png")
                                return {"data_url": f"data:{ct};base64,{b64}",
                                        "filename": filename}
                except Exception:
                    pass

    raise HTTPException(504, "ComfyUI did not finish generating within the timeout.")


@app.get("/api/comfyui/checkpoints")
async def api_comfyui_checkpoints(comfyui_url: str = "http://localhost:8188"):
    """Return the list of available checkpoints from ComfyUI."""
    base = comfyui_url.rstrip("/")
    try:
        async with __import__("httpx").AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/object_info/CheckpointLoaderSimple")
            r.raise_for_status()
            info = r.json()
            ckpts = info.get("CheckpointLoaderSimple", {}).get(
                "input", {}).get("required", {}).get("ckpt_name", [[]])[0]
            return {"checkpoints": ckpts}
    except Exception as e:
        raise HTTPException(502, f"Could not reach ComfyUI: {e}")


@app.post("/api/session/{session_id}/image-prompt")
async def api_generate_image_prompt(session_id: str):
    """Ask the LLM to build a Stable Diffusion optimised prompt from the current scene context."""
    engine = get_engine()
    session = _resolve(engine, session_id)

    # ── Gather scene context ──────────────────────────────────────────────────
    scene = engine.scene_mgr.get(session_id)
    location = (scene.location if scene else None) or "Unknown"
    summary = (scene.summary if scene else None) or "(no summary yet)"
    active_chars = (scene.active_characters if scene else None) or []

    memories = engine.get_memories(session_id)
    mem_lines = [
        f"- [{m.type.value}] {m.title}: {m.content}"
        for m in memories[:30]
    ]

    rels = engine.get_relationships(session_id)
    rel_lines = [
        f"- {r.source_entity} → {r.target_entity}: trust={r.trust:+.1f} affection={r.affection:+.1f} hostility={r.hostility:.1f}"
        for r in rels[:10]
    ] if rels else []

    turns = engine.sessions.get_turns(session_id, limit=6)
    turns_chrono = list(reversed(turns))   # get_turns returns newest-first
    recent_lines = [
        f"{t.role.upper()}: {t.content[:400].replace(chr(10), ' ')}"
        for t in turns_chrono
    ]

    # ── Build LLM request ─────────────────────────────────────────────────────
    system = (
        "You are an expert Stable Diffusion prompt engineer for roleplay scenes.\n\n"
        "Your task: write a vivid SD image generation prompt that captures the current roleplay scene.\n\n"
        "SD prompt format rules:\n"
        "- Comma-separated descriptive tags and short phrases\n"
        "- Lead with subject/composition (e.g. 'two figures in a dimly lit tavern')\n"
        "- Include physical descriptions of each character present (hair color, eye color, clothing, expression, pose)\n"
        "  If physical details are not explicitly stated, make a reasonable visual guess based on context\n"
        "- Include environment, lighting, mood, atmosphere\n"
        "- Do NOT include style tags — the user will add those separately\n"
        "- Do NOT include negative prompt syntax\n"
        "- Under 160 words total\n"
        "- Output ONLY the raw prompt text — no labels, no preamble, no explanation"
    )

    parts = [
        f"CHARACTER NAME: {session.character_name}",
        f"LOCATION: {location}",
        f"SCENE SUMMARY: {summary}",
        f"PRESENT CHARACTERS: {', '.join(active_chars) if active_chars else 'unspecified'}",
        "",
        "MEMORY / CHARACTER DETAILS:",
        "\n".join(mem_lines) if mem_lines else "(none yet)",
        "",
        "RELATIONSHIPS:",
        "\n".join(rel_lines) if rel_lines else "(none yet)",
        "",
        "RECENT EXCHANGE:",
        "\n".join(recent_lines) if recent_lines else "(none)",
        "",
        "Write the SD image prompt now.",
    ]

    try:
        provider = engine._provider_for_session(session)
        raw = provider.generate(
            "\n".join(parts),
            system=system,
            temperature=0.75,
            max_tokens=350,
        )
        return {"prompt": raw.strip()}
    except Exception as e:
        raise HTTPException(500, f"Prompt generation failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(engine: RoleplayEngine, session_id: str):
    """Resolve a session by full or partial ID. Raises 404 if not found."""
    session = engine.load_session(session_id)
    if session:
        return session
    sessions = engine.list_sessions()
    session = next((s for s in sessions if s.id.startswith(session_id)), None)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


def _scene_dict(scene) -> dict:
    return {
        "location": scene.location,
        "active_characters": scene.active_characters,
        "summary": scene.summary,
        "last_updated": scene.last_updated.isoformat(),
    }


def _rel_dict(r) -> dict:
    return {
        "source": r.source_entity,
        "target": r.target_entity,
        "summary": derive_relationship_summary(r),
        "trust": round(r.trust, 2),
        "fear": round(r.fear, 2),
        "respect": round(r.respect, 2),
        "affection": round(r.affection, 2),
        "hostility": round(r.hostility, 2),
    }


def _stat_dict(s) -> dict:
    return {
        "id": s.id,
        "session_id": s.session_id,
        "name": s.name,
        "value": s.value,
        "modifier": s.modifier,
        "effective_modifier": s.effective_modifier,
        "category": s.category,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _check_dict(c) -> dict:
    return {
        "id": c.id,
        "session_id": c.session_id,
        "stat_name": c.stat_name,
        "roll": c.roll,
        "modifier": c.modifier,
        "total": c.total,
        "difficulty": c.difficulty,
        "outcome": c.outcome.value,
        "narrative_context": c.narrative_context,
        "turn_number": c.turn_number,
        "created_at": c.created_at.isoformat(),
    }


def _arc_dict(arc) -> dict:
    return {
        "session_id": arc.session_id,
        "current_act": arc.current_act,
        "act_label": arc.act_label,
        "tension": arc.tension,
        "tension_label": arc.tension_label,
        "pacing": arc.pacing,
        "themes": arc.themes,
        "arc_notes": arc.arc_notes,
        "updated_at": arc.updated_at.isoformat(),
    }


def _faction_dict(f) -> dict:
    return {
        "id": f.id,
        "session_id": f.session_id,
        "name": f.name,
        "description": f.description,
        "alignment": f.alignment,
        "standing": f.standing,
        "standing_label": f.standing_label,
        "tags": f.tags,
        "notes": f.notes,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }


def _quest_dict(q) -> dict:
    return {
        "id": q.id,
        "session_id": q.session_id,
        "title": q.title,
        "description": q.description,
        "status": q.status.value,
        "giver_npc_name": q.giver_npc_name,
        "location_name": q.location_name,
        "reward_notes": q.reward_notes,
        "importance": q.importance.value,
        "stages": [
            {"id": s.id, "description": s.description, "completed": s.completed, "order": s.order}
            for s in q.stages
        ],
        "stages_done": q.stages_done,
        "progress_label": q.progress_label,
        "tags": q.tags,
        "created_at": q.created_at.isoformat(),
        "updated_at": q.updated_at.isoformat(),
    }


def _journal_dict(e) -> dict:
    return {
        "id": e.id,
        "session_id": e.session_id,
        "title": e.title,
        "content": e.content,
        "turn_number": e.turn_number,
        "tags": e.tags,
        "created_at": e.created_at.isoformat(),
    }


def _lore_dict(n) -> dict:
    return {
        "id": n.id,
        "session_id": n.session_id,
        "title": n.title,
        "content": n.content,
        "category": n.category,
        "source": n.source,
        "tags": n.tags,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _fmt_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _obj_dict(o) -> dict:
    return {
        "id": o.id,
        "session_id": o.session_id,
        "title": o.title,
        "description": o.description,
        "status": o.status.value,
        "created_at": o.created_at.isoformat(),
        "updated_at": o.updated_at.isoformat(),
    }


def _bookmark_dict(b) -> dict:
    return {
        "id": b.id,
        "session_id": b.session_id,
        "turn_id": b.turn_id,
        "turn_number": b.turn_number,
        "role": b.role,
        "content_preview": b.content_preview,
        "note": b.note,
        "created_at": b.created_at.isoformat(),
    }


def _npc_dict(n) -> dict:
    return {
        "id": n.id,
        "session_id": n.session_id,
        "name": n.name,
        "role": n.role,
        "description": n.description,
        "personality_notes": n.personality_notes,
        "last_known_location": n.last_known_location,
        "is_alive": n.is_alive,
        "tags": n.tags,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
    }


def _loc_dict(l) -> dict:
    return {
        "id": l.id,
        "session_id": l.session_id,
        "name": l.name,
        "description": l.description,
        "atmosphere": l.atmosphere,
        "notes": l.notes,
        "tags": l.tags,
        "visit_count": l.visit_count,
        "first_visited": l.first_visited.isoformat(),
        "last_visited": l.last_visited.isoformat(),
    }


def _clock_dict(c) -> dict:
    return {
        "session_id": c.session_id,
        "year": c.year,
        "month": c.month,
        "day": c.day,
        "hour": c.hour,
        "time_of_day": c.time_of_day,
        "era_label": c.era_label,
        "notes": c.notes,
        "display": c.display(),
        "updated_at": c.updated_at.isoformat(),
    }


def _beat_dict(b) -> dict:
    return {
        "id": b.id,
        "session_id": b.session_id,
        "title": b.title,
        "description": b.description,
        "beat_type": b.beat_type.value,
        "turn_number": b.turn_number,
        "importance": b.importance.value,
        "tags": b.tags,
        "created_at": b.created_at.isoformat(),
    }


def _emotional_state_dict(s) -> dict:
    return {
        "session_id": s.session_id,
        "mood": s.mood,
        "stress": round(s.stress, 2),
        "stress_label": s.stress_label,
        "motivation": s.motivation,
        "notes": s.notes,
        "updated_at": s.updated_at.isoformat(),
    }


def _item_dict(i) -> dict:
    return {
        "id": i.id,
        "session_id": i.session_id,
        "name": i.name,
        "description": i.description,
        "condition": i.condition,
        "quantity": i.quantity,
        "tags": i.tags,
        "is_equipped": i.is_equipped,
        "created_at": i.created_at.isoformat(),
        "updated_at": i.updated_at.isoformat(),
    }


def _effect_dict(e) -> dict:
    return {
        "id": e.id,
        "session_id": e.session_id,
        "name": e.name,
        "description": e.description,
        "effect_type": e.effect_type.value,
        "severity": e.severity,
        "duration_turns": e.duration_turns,
        "created_at": e.created_at.isoformat(),
    }
