# RP Utility — Comprehensive Rebuild Plan

> Generated: 2026-04-09  
> Basis: Professional QA & Developer Evaluation across 5 domains  
> Spirit: Local-first, campaign-primary AI roleplay system. No external dependencies beyond a running LLM provider.  
> Freedom: Not bound by current implementation details — better approaches should replace worse ones.

---

## Design Principles for the Rebuild

1. **Campaign-first, always.** The campaign system is the product. The legacy session system is convenience-only ("Quick Play"). One unified codebase serves both.
2. **The player owns canon.** The AI generates freely; the player decides what sticks. No automatic, silent world mutation.
3. **Context is sacred.** Every token in the prompt must earn its place. Irrelevant context is noise that degrades output quality.
4. **Fail visibly.** Every error surfaces to the user. Silent swallowing of failures ends.
5. **Local-first, privacy-first.** No cloud calls, no telemetry, no accounts. The LLM runs on the user's machine.

---

## What We Keep

- SQLite as the database (excellent choice for local-first single-user)
- FastAPI + Pydantic (solid, well-tested)
- The campaign data model: NPC cards, world facts, chronicle, places, factions, narrative threads, player character
- The memory scoring algorithm (importance, entity, keyword, recency, certainty — genuinely good)
- The extraction prompt and pipeline (sound architecture, needs tuning not replacement)
- The multi-provider abstraction (Ollama / LM Studio / KoboldCPP)
- The streaming response UI
- The CSS variable theme system
- The provider settings persistence mechanism

## What We Replace or Rearchitect

- The dual legacy/campaign system split → unified engine
- The 22 separate store objects with individual connections → shared DataStore
- The 1,500-char extraction truncation → 4,000-char with full text fallback
- Pure lexical memory retrieval → hybrid lexical + semantic (embeddings)
- Wall-clock recency decay → turn-count-based recency decay
- No context budget management → token budget trimmer before every model call
- Global-scope vanilla JS → ES modules with named exports
- Silent fetch failures → centralized error-surfacing fetchJSON wrapper
- SillyTavern card file imports (legacy) → in-app character creation for Quick Play
- No extraction backpressure → single-depth async extraction queue

---

## Phase Structure

| Phase | Name | Focus | Priority |
|---|---|---|---|
| R1 | Architecture Unification | Merge systems, fix critical extraction bugs | Critical |
| R2 | Memory Intelligence | Embeddings, turn-based recency, prompt reordering | High |
| R3 | Backend Hardening | DataStore, context budget, extraction queue, thread safety | High |
| R4 | Frontend Refactor | ES modules, error handling, parallel loads | Medium |
| R5 | UI/UX Enhancements | NPC graph, slash commands, global search, scene suggestions | Medium |
| R6 | New Features | Auto-chronicle, conflict detection, campaign export, multi-model routing | Enhancement |

---

## Phase R1 — Architecture Unification *(Critical)*

### Goal
Remove the dual-system split. Fix the extraction truncation bug. Make Quick Play a lightweight campaign. All downstream phases build on this foundation.

### R1.1 — Unified Campaign-First Engine

**Current state:** Two completely separate data paths:
- Legacy: `RoleplayEngine` + `SessionManager` + `prompting/builder.py` + 22 stores
- Campaign: `CampaignStore` + `scene_prompter.py` (bypasses engine entirely)

**Target state:** One `CampaignEngine` that handles both. Quick Play is a campaign with:
- Auto-generated world doc (blank/minimal)
- One NPC card (the "character")
- No chronicle required
- No world-builder step

**Implementation:**

1. **New `app/core/campaign_engine.py`** — replaces `engine.py` as the single entry point  
   - `CampaignEngine(config)` — initializes unified stores only  
   - `chat(campaign_id, scene_id, user_message, **gen_overrides) -> str` — streaming  
   - `extract_after_turn(campaign_id, scene_id, turn_data)` — post-turn extraction (async)  
   - All legacy engine methods (`new_session`, `get_history`, etc.) re-exposed as thin wrappers that operate on a Quick Play campaign

2. **Quick Play campaigns** — created automatically when the user clicks "Quick Play":  
   - `Campaign(name="Quick Play — {char_name}", quick_play=True)` — add `quick_play: bool = False` to `Campaign` model  
   - One NPC created from user-supplied name + description (the "character card" concept, without the file)  
   - Scene created automatically on first turn  
   - No chronicle, no world-builder, no NPC relationships required

3. **Deprecation path:**  
   - Keep `server.py` legacy endpoints functional for the transition (they proxy to the new engine)  
   - After R1 is stable, mark legacy endpoints as deprecated in comments  
   - Remove entirely in R3

**Files to create/modify:**
- `app/core/campaign_engine.py` — NEW
- `app/core/models.py` — add `quick_play: bool = False` to `Campaign`
- `app/core/database.py` — migration: `campaigns.quick_play INTEGER DEFAULT 0`
- `app/web/server.py` — legacy endpoints proxy to `CampaignEngine`
- `app/web/campaign_routes.py` — wire `CampaignEngine` (replacing direct store access)
- `app/web/templates/index.html` — replace "New Session" legacy form with "Quick Play" button
- `app/web/static/index.js` — Quick Play modal (name + character description, no file required)

---

### R1.2 — Fix Extraction Truncation

**Current bug:** `extractor.py:28` truncates both user and assistant messages to 1,500 chars. Long AI responses (often 800–1,200 words) have their second half — where scene outcomes and consequences land — silently discarded.

**Fix:**
```python
# app/memory/extractor.py
_MAX_INPUT_CHARS = 4000   # was 1500
```

Additionally, when the combined text exceeds 4,000 chars, prioritize the assistant message (AI response contains the story outcomes; user message is usually much shorter):
```python
user_budget = min(len(user_message), 1200)
asst_budget = _MAX_INPUT_CHARS - user_budget
prompt = EXTRACTION_USER_TEMPLATE.format(
    user_message=user_message[:user_budget],
    assistant_message=assistant_message[:asst_budget],
    ...
)
```

**Files:** `app/memory/extractor.py`

---

### R1.3 — In-App Character Creation (Replaces Card Import for Quick Play)

**Current:** Quick Play requires importing a SillyTavern `.json` or `.png` card file.  
**Target:** A simple modal with:
- Character Name
- Description (who they are, their personality)
- Voice / speaking style (optional)
- Opening line (optional — what they say first)

These fields map directly to `NpcCard` fields already in the campaign system. No new model needed.

**Files:**
- `app/web/templates/index.html` — replace card file input with form fields in Quick Play modal
- `app/web/static/index.js` — POST to new `/api/quick-play/create` endpoint
- `app/web/server.py` — `POST /api/quick-play/create` creates campaign + NPC + first scene

---

## Phase R2 — Memory Intelligence *(High Priority)*

### Goal
Make the memory system actually remember what matters. Three targeted improvements: semantic retrieval, story-time recency, and correct prompt positioning of critical facts.

### R2.1 — Semantic Memory Search (Embeddings)

**Problem:** Memory retrieval is purely lexical. "The tavern fire" is not found when the player says "the inn burning last year."

**Solution:** Add embedding-based semantic similarity as an additional scoring component. Use Ollama's `nomic-embed-text` (or any embedding model the user has pulled) for fully local operation.

**Data model change:**
```sql
-- migration in database.py
ALTER TABLE memories ADD COLUMN embedding BLOB;  -- stores float32 array as bytes
```

**New module: `app/memory/embedder.py`**
```python
class EmbeddingStore:
    """
    Generates and stores embeddings for memory entries.
    Uses Ollama /api/embeddings endpoint (or provider equivalent).
    Gracefully degrades if no embedding model is configured.
    """
    def embed(self, text: str) -> list[float] | None: ...
    def cosine_similarity(self, a: list[float], b: list[float]) -> float: ...
```

**Config additions (`app/core/config.py`):**
```python
embedding_model: str = ""          # e.g. "nomic-embed-text" — empty = disabled
embedding_weight: float = 1.5      # weight of semantic score in retrieval
```

**Retrieval integration (`app/memory/retriever.py`):**
- Add `query_embedding: list[float] | None = None` parameter to `retrieve()`
- If provided and memory has an embedding, compute cosine similarity and add `embedding_weight * similarity` to the score
- Embeddings are computed lazily: at extraction time if embedding model is configured
- If a memory has no embedding (created before this feature), it still works — just misses the semantic bonus

**Extraction integration (`app/memory/extractor.py`):**
- After building `MemoryEntry` objects, if `config.embedding_model` is set, call `EmbeddingStore.embed(entry.content)` and store in `entry.embedding`
- Fire this synchronously in the extraction thread (same background thread, sequential)

**Engine integration (`app/core/campaign_engine.py`):**
- Before calling `retrieve()`, compute an embedding of the current user message + last AI response (the "query embedding")
- Pass it to `retrieve()` as `query_embedding`

**Files to create/modify:**
- `app/memory/embedder.py` — NEW
- `app/memory/extractor.py` — embed at extraction time
- `app/memory/retriever.py` — accept and apply query embedding
- `app/memory/store.py` — persist embedding BLOB column
- `app/core/database.py` — migration
- `app/core/config.py` — `embedding_model`, `embedding_weight`
- `app/web/templates/index.html` (provider modal) — add embedding model field

---

### R2.2 — Turn-Based Recency Decay

**Problem:** Recency decay uses wall-clock time (`datetime.now(UTC) - memory.created_at`). A player who runs five scenes in one afternoon gets identical recency scores for scene 1 and scene 5. Story time doesn't match calendar time.

**Solution:** Store `source_turn_number` on each memory. Decay by turn distance from the current turn rather than by days elapsed.

**Data model change:**
```python
# app/core/models.py — MemoryEntry
source_turn_number: int = 0    # turn number when this memory was extracted
```

```sql
-- migration
ALTER TABLE memories ADD COLUMN source_turn_number INTEGER DEFAULT 0;
```

**Retriever change:**
```python
# retrieve() signature — add:
current_turn_number: int = 0
turn_half_life: float = 40.0   # turns; default configurable

# In _score():
# Replace or supplement recency_decay calculation:
turn_gap = max(0, current_turn_number - memory.source_turn_number)
recency = math.exp(-turn_gap / max(turn_half_life, 1.0))
```

**Keep wall-clock decay** as a secondary signal (some stories span real days). Blend: `0.6 * turn_decay + 0.4 * time_decay`.

**Config:**
```python
memory_turn_half_life: float = 40.0   # turns before a memory's recency score halves
```

**Files:** `app/core/models.py`, `app/core/database.py`, `app/memory/retriever.py`, `app/core/config.py`

---

### R2.3 — Raise Memory Retrieval Caps

**Current:** `max_retrieved_memories = 10` default. Far too low for complex campaigns.

**New defaults:**
```python
# app/core/config.py
max_retrieved_memories: int = 20   # was 10
```

```python
# app/memory/retriever.py — _DEFAULT_TYPE_CAPS
_DEFAULT_TYPE_CAPS = {
    "event": 8,            # was 6
    "world_fact": 6,       # was 5
    "character_detail": 6, # was 5
    "relationship_change": 5, # was 4
    "world_state": 5,      # was 4
    "rumor": 3,            # was 2
    "suspicion": 3,        # was 2
    "consolidation": 5,    # was 4
}
```

---

### R2.4 — Reposition Critical Facts in Prompt

**Problem:** `[CRITICAL FACTS]` section appears in the middle of a 2,000-token system prompt. Models attend more to the start and end of context.

**Fix in `app/prompting/builder.py`:**
```python
# New section order:
system_parts = [
    _CORE_INSTRUCTIONS,           # 1. Role instructions
    _format_critical_facts(...),  # 2. Critical facts IMMEDIATELY after instructions  ← MOVED
    _format_character_card(...),  # 3. Character card
    _format_lorebook(...),        # 4. Lorebook
    _format_world_state(...),     # 5. World state
    _format_memories_soft(...),   # 6. Episodic memories (non-critical only)
    _format_relationships(...),   # 7. Relationships
    _format_scene(...),           # 8. Scene (last system section — most immediate)
    # ... optional sections ...
]
```

Also place the `[CRITICAL FACTS]` block again as the **final** system section (just before conversation history) for the end-of-context attention boost. A short deduplicated version:
```python
if critical:
    system_parts.insert(1, _format_critical_facts(critical))   # near top
    system_parts.append(_format_critical_facts_brief(critical)) # near bottom
```

**Files:** `app/prompting/builder.py`

---

### R2.5 — Scene Working Memory (Campaigns)

**Problem:** Campaign system has no within-scene memory. If a key event happens at turn 5 and the scene reaches turn 50, that event is outside the context window and invisible to the model.

**Solution:** A lightweight "scene event log" — a rolling list of bullet-point events extracted by the summary model after every N turns within a scene. Stored on the scene object. Injected at the top of the scene context (after the system prompt, before conversation history).

**Data model:**
```python
# app/core/models.py — CampaignScene
scene_event_log: list[str] = Field(default_factory=list)  # bullet points; auto-updated
event_log_through_turn: int = 0  # how many turns the log covers
```

**Extraction trigger:** Every 10 turns, fire a background extraction call:
```
"Summarize the key events of turns {N} through {M} of this scene in 3-5 bullet points.
Focus only on facts with lasting consequence: injuries, decisions, revelations, relationship changes."
```

**Injection in `scene_prompter.py`:**
```python
if scene.scene_event_log:
    messages.append({
        "role": "system",
        "content": f"[EARLIER IN THIS SCENE — key events]\n" + "\n".join(f"• {e}" for e in scene.scene_event_log)
    })
```

Inject this immediately after the main system message, before conversation history.

**Files:** `app/core/models.py`, `app/core/database.py`, `app/campaigns/scene_prompter.py`, `app/web/campaign_routes.py`

---

## Phase R3 — Backend Hardening *(High Priority)*

### R3.1 — Unified DataStore (Shared Connection)

**Problem:** 22 store objects each manage their own connection lifecycle. On every API request involving extraction, 5+ stores open and close connections in rapid succession.

**Solution:** A `DataStore` class that holds a single thread-local connection and exposes all table operations as methods. Stores become thin namespaced facades over `DataStore`.

**New `app/core/data_store.py`:**
```python
class DataStore:
    """
    Single access point for all DB operations.
    Uses a thread-local connection pool (one connection per thread).
    Stores are inner classes / factory methods on this object.
    """
    def __init__(self, db_path: str): ...
    
    # Thread-local connection
    def _conn(self) -> sqlite3.Connection: ...
    
    # Namespaced operations — replaces individual store files
    @property
    def memories(self) -> MemoryOps: ...
    @property
    def scenes(self) -> SceneOps: ...
    @property
    def npcs(self) -> NpcOps: ...
    # ... etc
```

**Migration path:**
- Create `DataStore` with all operations
- Old store files (`memory/store.py`, `sessions/manager.py`, etc.) become thin wrappers that delegate to `DataStore`
- Engine uses `DataStore` directly on new code paths
- Remove old stores in R3 cleanup once engine is fully migrated

**Files:**
- `app/core/data_store.py` — NEW
- `app/core/campaign_engine.py` — use `DataStore`
- Existing store files — delegate to `DataStore` (backward compat shim)

---

### R3.2 — Context Budget Manager

**Problem:** `build_messages()` / `build_scene_messages()` assemble prompts with no awareness of the model's context window. Sections are included based on "is data available" not "do we have token budget".

**New `app/prompting/budget.py`:**
```python
# Rough token estimator (chars / 4 — conservative for mixed prose/code)
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

class ContextBudget:
    """
    Tracks token usage during prompt assembly.
    Allows callers to check remaining budget before appending a section.
    """
    def __init__(self, total: int, conversation_reserve: int = 4000):
        # Reserve tokens for conversation history + current turn + response
        self.available = total - conversation_reserve
        self.used = 0
    
    def fits(self, text: str) -> bool:
        return self.used + estimate_tokens(text) <= self.available
    
    def consume(self, text: str) -> None:
        self.used += estimate_tokens(text)
    
    def fits_and_consume(self, text: str) -> bool:
        if self.fits(text):
            self.consume(text)
            return True
        return False
```

**Integration in `build_scene_messages()` and `build_messages()`:**

Sections are appended in priority order. Each section is only added if budget allows:

```
Priority (highest to lowest):
  1. Core instructions              [always included — truncate if necessary]
  2. Critical facts                 [always included]
  3. Character card / NPC context   [always included]
  4. Chronicle (first 2 + last 6)   [always included]
  5. World facts (critical)         [always included]
  6. Active NPCs in scene           [budget check]
  7. Active threads                 [budget check]
  8. Episodic memories (scored)     [budget check — add until budget exhausted]
  9. Relationships                  [budget check]
  10. World facts (normal)          [budget check — lowest priority]
  11. Factions / places             [budget check — background]
```

When the budget is exhausted, log a warning with which sections were dropped.

**Files:**
- `app/prompting/budget.py` — NEW
- `app/prompting/builder.py` — integrate budget checks
- `app/campaigns/scene_prompter.py` — integrate budget checks
- `app/core/config.py` — `context_window` already in `GenSettings`; expose at config level too

---

### R3.3 — Async Extraction Queue

**Problem:** Memory extraction fires as a background thread immediately after every chat turn, potentially queuing parallel inference requests on a single-model endpoint.

**Solution:** Per-session extraction queue — a `asyncio.Queue(maxsize=1)` (drop-if-full) that ensures at most one extraction call is in-flight per session at a time.

```python
# app/core/campaign_engine.py
class CampaignEngine:
    def __init__(self, config):
        ...
        self._extraction_queues: dict[str, asyncio.Queue] = {}
        # A background task per session that drains the queue
    
    async def _extraction_worker(self, session_id: str):
        q = self._extraction_queues[session_id]
        while True:
            turn_data = await q.get()
            if turn_data is None:  # sentinel — stop worker
                break
            try:
                await self._run_extraction(turn_data)
            except Exception:
                pass  # extraction is always non-fatal
            finally:
                q.task_done()
    
    def enqueue_extraction(self, session_id: str, turn_data: dict):
        q = self._extraction_queues.setdefault(session_id, asyncio.Queue(maxsize=1))
        try:
            q.put_nowait(turn_data)  # drop if full — previous extraction still running
        except asyncio.QueueFull:
            pass  # acceptable — extraction is best-effort
```

**Files:** `app/core/campaign_engine.py`

---

### R3.4 — Config Thread Safety

**Problem:** `saveProviderSettings()` mutates the config singleton with `setattr()` and rebuilds `_engine`. Not thread-safe under concurrent requests.

**Solution:** Use a threading lock around the mutation + rebuild:

```python
# app/web/server.py
import threading
_config_lock = threading.Lock()

@app.post("/api/settings/provider")
def api_save_provider_settings(req: ProviderSettingsRequest):
    global _engine
    with _config_lock:
        config.provider = req.provider
        # ... other fields ...
        _engine = CampaignEngine(config)
    return {"ok": True, ...}
```

**Files:** `app/web/server.py`

---

## Phase R4 — Frontend Refactor *(Medium Priority)*

### R4.1 — ES Modules

**Problem:** All JS is global-scope. As files grow (800+ lines), naming collisions and implicit dependencies are a growing risk.

**Solution:** Convert all JS files to ES modules. No bundler required — modern browsers (and Chromium-based desktop apps) support native ES modules.

```html
<!-- index.html -->
<script type="module" src="/static/index.js?v={{CACHE_VER}}"></script>
```

**Each file:**
- Uses `import { func } from './other.js'` for cross-file dependencies
- Exports only the functions meant to be called from HTML (`onclick`, etc.) via a module-level assignment to `window.funcName`
- Internal helpers are module-private

**Migration order:** theme.js → status.js → index.js → chat.js → campaign_*.js

**Files:** All `app/web/static/*.js`

---

### R4.2 — Centralized Error-Surfacing `fetchJSON` Wrapper

**Problem:** Fetch calls have inconsistent error handling. Many `catch` blocks are empty or silent.

**New global utility in `app/web/static/utils.js`:**
```javascript
export async function fetchJSON(url, opts = {}) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (networkErr) {
    showBanner(`Network error: ${networkErr.message}`, "error");
    throw networkErr;
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.error || detail;
    } catch {}
    showBanner(`Request failed: ${detail}`, "error");
    throw new Error(detail);
  }
  return res.json();
}
```

All existing fetch calls are replaced with `fetchJSON()`. The `showBanner()` function is shared from `utils.js`.

**Files:**
- `app/web/static/utils.js` — NEW
- `app/web/static/chat.js` — replace fetch calls
- `app/web/static/index.js` — replace fetch calls
- `app/web/static/campaign_play.js` — replace fetch calls
- `app/web/static/campaign_overview.js` — replace fetch calls

---

### R4.3 — Parallel Page-Load Fetches

**Problem:** `chat.js` DOMContentLoaded awaits five sequential fetches before the page is usable.

**Fix:**
```javascript
// chat.js — DOMContentLoaded
document.addEventListener("DOMContentLoaded", async () => {
  // Group independent loads
  const [sessionData, bookmarkIds] = await Promise.all([
    fetchJSON(`/api/session/${SESSION_ID}`),
    fetchJSON(`/api/session/${SESSION_ID}/bookmarks/ids`),
  ]);
  applySession(sessionData);
  applyBookmarkIds(bookmarkIds);

  // History and sidebar can load in parallel after session is known
  await Promise.all([
    loadHistory(),
    refreshSidebar(),
  ]);

  // Non-blocking
  loadRecap();
  applyStoredBackground();
  loadGenSettings();
  loadPersona();
  scrollToBottom();
  setupInput();
  setupSearch();
  setupSidebarCollapse();
});
```

**Files:** `app/web/static/chat.js`

---

### R4.4 — Stream Abort on Navigation

**Problem:** If the user navigates away mid-stream, the fetch continues in the background, writing orphaned turns to the DB.

**Fix:** Wire `beforeunload` and `visibilitychange` to abort:
```javascript
// campaign_play.js and chat.js
window.addEventListener("beforeunload", () => _streamAbort?.abort());
document.addEventListener("visibilitychange", () => {
  if (document.hidden) _streamAbort?.abort();
});
```

**Files:** `app/web/static/chat.js`, `app/web/static/campaign_play.js`

---

## Phase R5 — UI/UX Enhancements *(Medium Priority)*

### R5.1 — NPC Relationship Graph

**Tool:** [vis.js Network](https://visjs.github.io/vis-network/docs/network/) — single JS dependency, ~400KB, no build step.

**Where:** A new "Relations" tab on the campaign overview between "NPCs" and "Factions."

**What it shows:**
- Each NPC as a node (colored by status: active=green, fled=yellow, dead=gray, imprisoned=orange)
- Each `NpcRelationship` as an edge with a label showing the `dynamic` field
- Click a node → opens the NPC editor panel
- Hover an edge → tooltip shows trust/hostility/history

**Data source:** existing `NpcRelationship` model — no new API needed, just a new endpoint:
```
GET /api/campaigns/{id}/npc-graph
→ { nodes: [{id, label, color, status}], edges: [{from, to, label, title}] }
```

**Files:**
- `app/web/templates/campaign_overview.html` — add "Relations" tab + graph container div
- `app/web/static/campaign_overview.js` — graph initialization and click handlers
- `app/web/campaign_routes.py` — `GET /api/campaigns/{id}/npc-graph`

---

### R5.2 — Slash Command System in Chat Input

**What it solves:** Sidebar management (adding inventory items, marking objectives done, adding journal notes) requires the user to switch panes. Slash commands let them do it from the chat input.

**Commands:**
```
/roll [NdN+mod]         — rolls dice, shows result inline (no AI call)
/note [text]            — adds a journal entry
/done [objective text]  — marks matching active objective as completed
/add [item name]        — adds item to inventory
/remove [item name]     — removes item from inventory
/memory [text]          — manually adds a memory entry (high importance)
/location [name]        — updates the current scene location
```

**Implementation:**
```javascript
// chat.js — in handleSend()
function parseSlashCommand(text) {
  if (!text.startsWith("/")) return null;
  const [cmd, ...args] = text.slice(1).split(" ");
  return { cmd: cmd.toLowerCase(), args: args.join(" ") };
}
```

Commands are intercepted before sending to the API. Roll commands resolve locally. Others POST to existing API endpoints (`/api/session/{id}/objectives`, etc.).

**Visual feedback:** Commands produce a system-message bubble (different style from player/AI messages) confirming the action.

**Files:**
- `app/web/static/chat.js` — command parser and handlers
- `app/web/static/campaign_play.js` — same
- `app/web/static/style.css` — `.system-bubble` style

---

### R5.3 — Global Campaign Search

**Where:** A search icon/button in the campaign overview header.

**What it searches:** NPC names/descriptions, world facts, chronicle entries, scene titles, place names, faction names.

**API endpoint:**
```
GET /api/campaigns/{id}/search?q={query}
→ {
    npcs: [{id, name, snippet}],
    world_facts: [{id, category, snippet}],
    chronicle: [{id, scene_range, snippet}],
    scenes: [{id, scene_number, title, snippet}],
    places: [{id, name, snippet}],
    factions: [{id, name, snippet}]
  }
```

SQLite's `LIKE '%query%'` is sufficient for local data sizes. No full-text search engine needed.

**UI:** A modal overlay with grouped results. Clicking a result navigates to the relevant tab and highlights the item.

**Files:**
- `app/web/campaign_routes.py` — search endpoint
- `app/web/templates/campaign_overview.html` — search button + results modal
- `app/web/static/campaign_overview.js` — search logic + navigation

---

### R5.4 — Scene NPC Suggestions

**When:** User clicks "New Scene" on the campaign play page.

**What it does:** Pre-select NPCs based on who appeared in the most recent confirmed scene at the same location (or the most recent scene if location is different).

**Logic:**
```python
# app/web/campaign_routes.py — GET /api/campaigns/{id}/scene-suggestions
def get_scene_suggestions(campaign_id: str, location: str = ""):
    last_scene = store.get_last_confirmed_scene(campaign_id)
    if not last_scene:
        return {"suggested_npc_ids": []}
    if location and last_scene.location.lower() == location.lower():
        return {"suggested_npc_ids": last_scene.npc_ids}
    return {"suggested_npc_ids": []}
```

**UI:** When the location field is filled in scene setup, fire a fetch to this endpoint and pre-check matching NPCs in the selection list. User can override.

**Files:**
- `app/web/campaign_routes.py` — suggestions endpoint
- `app/web/static/campaign_play.js` — pre-select NPCs on location fill

---

### R5.5 — World Fact Undo (Last Edit)

**Problem:** Editing a world fact overwrites it with no recovery.

**Solution:** Store the previous value in the database before overwriting:
```sql
-- migration
ALTER TABLE campaign_world_facts ADD COLUMN previous_content TEXT;
ALTER TABLE campaign_world_facts ADD COLUMN edited_at TEXT;
```

The world fact editor shows an "Undo last edit" link if `previous_content` is non-null. Clicking it restores the value.

**Files:**
- `app/core/models.py` — `previous_content: Optional[str]`, `edited_at: Optional[datetime]`
- `app/core/database.py` — migration
- `app/campaigns/store.py` — save previous before update
- `app/web/campaign_routes.py` — `POST /api/campaigns/{id}/facts/{fid}/undo`
- `app/web/static/campaign_overview.js` — undo link in fact editor

---

## Phase R6 — New Features *(Enhancement)*

### R6.1 — Auto-Chronicle Drafting

**Problem:** After a scene, the player must write the chronicle summary from scratch. The blank page is friction.

**Solution:** After every 10 turns within a scene, silently generate a draft chronicle candidate using the summary model. Store it on the scene as `proposed_draft`. When the player clicks "End Scene," pre-populate the chronicle edit field with this draft.

```python
# app/web/campaign_routes.py — triggered in POST /api/campaigns/{id}/scenes/{sid}/turn
async def maybe_draft_chronicle(campaign_id, scene_id, turn_number, summary_model):
    if turn_number % 10 != 0:
        return
    # Fire draft generation in background
    ...
```

**New API:**
```
GET /api/campaigns/{id}/scenes/{sid}/chronicle-draft
→ { draft: "..." }   # may be empty if not yet generated
```

**Files:**
- `app/web/campaign_routes.py` — trigger + endpoint
- `app/core/models.py` — `CampaignScene.proposed_draft: str = ""`
- `app/core/database.py` — migration
- `app/web/static/campaign_play.js` — fetch draft when "End Scene" is clicked

---

### R6.2 — World Fact Conflict Detection

**When:** User saves a new world fact or edits an existing one.

**What it does:** Sends the new fact text + all existing facts to the summary model with a short prompt:
```
"Does this new fact: '{new_fact}' contradict any of the existing facts listed below?
Answer with JSON: { "conflict": true/false, "conflicting_fact": "...", "reason": "..." }
Existing facts: ..."
```

**UI:** If `conflict: true`, show a non-blocking warning banner on the world doc editor:
```
⚠ Possible conflict detected: This may contradict "{conflicting_fact}" — {reason}. Save anyway?
```

This is advisory only — the user can override and save anyway.

**Files:**
- `app/web/campaign_routes.py` — `POST /api/campaigns/{id}/facts/check-conflict`
- `app/web/static/campaign_overview.js` — call check after save, show warning

---

### R6.3 — Campaign Export (Markdown + ZIP)

**Endpoints:**
```
GET /api/campaigns/{id}/export/markdown   → text/markdown download
GET /api/campaigns/{id}/export/zip        → application/zip download (markdown + images)
```

**Markdown export structure:**
```markdown
# Campaign: {name}

## Player Character
{pc fields}

## World Facts
### History
- fact 1
- fact 2

### Magic System
...

## NPCs
### {npc name}
**Role:** ...  **Status:** ...
{description, personality, relationship to player, goals, secrets}

## Chronicle
### Scenes 1–3
{chronicle content}

## Scene History
### Scene 1 — {title} ({location})
{confirmed summary}
```

**ZIP export** = the above markdown + any portrait/scene images stored as base64 URLs (decoded to PNG files).

**Files:**
- `app/web/campaign_routes.py` — export endpoints
- `app/web/templates/campaign_overview.html` — export buttons
- `app/web/static/campaign_overview.js` — trigger download

---

### R6.4 — Multi-Model Operation Routing

**Current:** `extraction_provider` is a separate provider. Extended to cover all operations.

**Target:** Per-operation model configuration:
```python
# app/core/config.py (additions)
chat_model: str = ""           # main creative model (defaults to ollama_model)
extraction_model: str = ""     # memory extraction (already exists)
summary_model: str = ""        # chronicle drafting, scene compression
embedding_model: str = ""      # semantic memory embeddings
```

**UI:** Provider settings modal gets a second section: "Model Routing" with fields for each operation. Grayed out if the selected provider doesn't support model selection.

**Files:**
- `app/core/config.py` — add `summary_model`
- `app/providers/factory.py` — `build_summary_provider(config)` alongside existing `build_extraction_provider`
- `app/web/templates/index.html` — model routing fields in provider modal
- `app/web/static/index.js` — show/hide routing fields

---

## Implementation Order (Recommended)

```
R1.2 (Fix extraction truncation)           — 1 line change, immediate quality improvement
R2.3 (Raise memory caps)                   — config change, immediate improvement
R2.4 (Reposition critical facts in prompt) — low effort, meaningful improvement
R3.4 (Config thread safety)                — small, correctness fix
R1.3 (In-app character creation)           — removes onboarding barrier
R1.1 (Unified engine)                      — large, foundational
R2.1 (Semantic embeddings)                 — high complexity, highest impact
R2.2 (Turn-based recency)                  — medium complexity, good impact
R2.5 (Scene working memory)                — medium complexity, good impact
R3.2 (Context budget manager)              — medium complexity, prevents context overflow
R3.1 (DataStore unification)               — large refactor, sets up clean architecture
R3.3 (Extraction queue)                    — medium, prevents contention
R4.1–R4.4 (Frontend refactor)              — incremental, no behavior change
R5.1 (NPC relationship graph)              — high UX impact
R5.2 (Slash commands)                      — high UX impact
R5.3 (Global search)                       — medium UX impact
R5.4 (Scene NPC suggestions)               — low effort, nice UX
R5.5 (World fact undo)                     — low effort, prevents data loss
R6.1 (Auto-chronicle drafting)             — medium, removes friction
R6.2 (Conflict detection)                  — medium, quality improvement
R6.3 (Campaign export)                     — low-medium, high user value
R6.4 (Multi-model routing)                 — extends existing pattern
```

---

## Testing Strategy

Each phase must pass the full test suite before the next begins. Key additions:

- **R1:** Tests for Quick Play campaign creation end-to-end; legacy endpoint backward compatibility
- **R2.1:** Embedding storage and retrieval; graceful degradation when no embedding model configured
- **R2.2:** Turn-based decay scoring with known inputs
- **R3.2:** Budget manager correctly drops low-priority sections; never drops critical facts
- **R3.3:** Extraction queue drops correctly under concurrent pressure
- **R4:** All JS changes are behavior-equivalent (no new API calls, same API surface)
- **R5.1:** NPC graph endpoint returns correct nodes/edges for a known campaign fixture
- **R6.3:** Export markdown contains all expected sections; ZIP contains correct file count

Maintain the existing test count (374+) and expand by approximately 50 tests across R1–R3.

---

## Migration Notes

- All schema migrations are additive (ALTER TABLE ADD COLUMN) and idempotent
- No existing data is destroyed at any phase
- Rollback: if a phase introduces a regression, the DB is backward-compatible with the previous code
- The legacy session system remains functional through R1; deprecated in R3; removed in R6 cleanup pass
- `provider_settings.json` persists across the rebuild — no user reconfiguration needed

---

## Open Questions (Resolve Before Starting Each Phase)

1. **R2.1:** Which embedding model does the user have pulled in Ollama? (`nomic-embed-text` is recommended but not universal)
2. **R1.1:** What should happen to existing legacy sessions on migration? Recommend: auto-convert to Quick Play campaigns on first access (same data, different wrapper)
3. **R5.1:** vis.js as a CDN link or bundled? Recommend: single `vendor/vis-network.min.js` served from `/static` to preserve local-first principle
4. **R6.3:** Should the ZIP export include the SQLite DB itself as a backup option? Simple to add, high value.
