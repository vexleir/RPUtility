# RP Utility — Implementation Roadmap

> Spirit: A comprehensive local-first roleplay system for long-form custom RP sessions.
> Character cards are characters brought **into** the world — not the world instructions themselves.
> The campaign system is the primary architecture. The legacy session system is quick-play.

---

## ✅ Phase 1 — Campaign Foundation *(complete)*
- Campaign creation wizard with AI world-builder
- World facts, places, NPCs (as characters brought into the world), factions, narrative threads
- Player character card
- AI-assisted generation from a free-text premise

## ✅ Phase 2 — Scene Play *(complete)*
- Streaming AI scene chat with full world context in system prompt
- Opening narration (AI sets the scene on creation)
- Chronicle: confirmed scene summaries fed back into AI context
- Post-scene world update suggestions (NPC changes, new facts, thread resolutions)
- Dead NPC conflict detection before scene creation
- `?new=1` URL param to force new scene setup vs. resume

## ✅ QA Remediation *(complete)*
- `datetime.utcnow()` → `datetime.now(UTC)` across all models (54 occurrences)
- FK `ON DELETE CASCADE` added to all 17 migration-added tables in database.py
- Test fixtures updated to seed parent session rows
- Path traversal audit (no changes needed)
- **Result: 374 passed, 0 warnings**

---

## 🔧 Pre-Phase 3 Bug Fixes *(included in Phase 3 delivery)*
- **[BUG]** Factions and Places never sent to AI during scene play — `scene_prompter.py` omits them
- **[BUG]** `StyleGuide` has no `mechanics_notes` field — Magic/Technology display always shows "(none)" and saving does nothing

---

## Phase 3 — Narrative Intelligence & Context Management

### Goals
Keep the AI performing well and the player oriented as campaigns scale past 10–15 scenes.
Fix data model bugs. Add tools for reviewing and editing narrative history.

### Features
- **[BUG FIX]** Factions and Places added to scene system prompt
- **[BUG FIX]** `magic_system` field added to `StyleGuide`; Magic/Technology section wired up
- **World fact categories** — `category` field on facts; facts grouped by category in world doc and in scene prompt
- **Campaign notes/scratchpad** — per-campaign private text field stored in DB; shown in scene play sidebar; never sent to AI
- **Scene transcript viewer** — "View" button on each scene card opens a modal with full turn-by-turn dialogue
- **Chronicle manual editing** — edit and delete chronicle entries from the Chronicle tab
- **Chronicle compression** — AI endpoint to merge multiple chronicle entries into one; accessible from Chronicle tab
- **Smart "Previously on..." recap** — scene prompter sends only the last 6 + first 2 chronicle entries (if > 10 total) instead of the full dump
- **Thread staleness indicator** — threads show how many scenes have passed since they were last mentioned
- **`prompt()` → modals** — "Add World Fact" and "Edit Fact" use proper modals instead of native browser dialogs

### Implementation Files
- `app/core/models.py` — `StyleGuide.magic_system`, `Campaign.notes`, `CampaignWorldFact.category`
- `app/core/database.py` — migrations: `campaigns.notes`, `campaign_world_facts.category`
- `app/campaigns/store.py` — CampaignStore (notes), WorldFactStore (category), ChronicleStore (update/delete)
- `app/campaigns/scene_prompter.py` — places, factions, magic_system, smart recap, grouped facts
- `app/web/campaign_routes.py` — UpdateCampaignRequest (magic_system), notes endpoint, chronicle CRUD, fact PATCH, scene endpoints pass places/factions
- `app/web/templates/campaign_overview.html` — transcript modal, chronicle edit controls, fact category, compress button, fact edit modal
- `app/web/static/campaign_overview.js` — all new feature logic + bug fixes
- `app/web/templates/campaign_play.html` — scratchpad in sidebar
- `app/web/static/campaign_play.js` — scratchpad load/save
- `app/web/static/style.css` — new component styles

---

## Phase 4 — Living Characters

### Goals
NPCs feel like real people with hidden depths, goals, and evolving relationships — not static props.

### Features
- **NPC secrets/hidden knowledge** — AI-visible field not shown in the campaign overview UI
- **NPC goals** (short-term + long-term) — fed into scene context so AI plays NPCs with authentic drive
- **NPC development log** — per-NPC milestone notes keyed to scene number (AI or player-written)
- **NPC-to-NPC relationship matrix** — trust/hostility/history between any two NPCs; used when multiple NPCs share a scene
- **Expanded NPC status** — `active`, `fled`, `imprisoned`, `transformed`, `dead` + reason field (replacing binary `is_alive`)
- **Player character development log** — PC card is currently static; add per-scene growth notes
- **Faction standing with player** — factions have no relationship-to-player field; add it and include in scene context
- **Character card file import as NPC** — use existing `app/cards/loader.py` to import `.json`/`.png` cards as NPC entries

---

## Phase 5 — UI/UX Optimization & Polish

### Goals
The system should feel as enjoyable to use as the stories it generates.

### Scene Play View
- NPC quick-reference side panel (collapsible; shows NPC cards for everyone in the current scene)
- Tone/mood indicator in scene header (displays scene tone as a visual accent)
- Keyboard shortcuts: `Ctrl+Enter` to send, `Esc` to close modals, `/` to focus input
- **Undo last turn** — remove last user+assistant turn pair from scene
- **In-scene dice roll** — `/roll 2d6` command or roll button; result fed into narrative

### Campaign Overview
- Collapsible sections with remembered state
- Inline editing for world facts and NPC fields (click-to-edit)
- Visual NPC status badges (color-coded by status: active/fled/imprisoned/dead)

### Global
- Toast notifications replacing `alert()` dialogs
- Consistent loading spinners and skeleton states
- Typography pass: narrative text uses a readable serif font
- **"What the AI sees" system prompt viewer** — debug panel showing generated system prompt
- `prompt()` dialogs fully eliminated (started in Phase 3)

---

## Phase 6 — Export, Search & Campaign Management

### Goals
Long-term playability, archival, and the ability to search and share campaigns.

### Features
- **Full campaign export** — one-click export to formatted markdown
- **Scene/turn search** — text search across all turns
- **Campaign statistics** — scenes played, most-used NPCs, thread resolution rate, word count
- **Campaign backup/restore** — export campaign as JSON; import to restore or share
- **Campaign template library** — save a world (without scenes/chronicle) as a reusable template
- **Per-campaign model verified** — ensure `campaign.model_name` is used in scene streaming (already wired; verify end-to-end)

---

## Test Baseline
| Phase completed | Tests passing |
|---|---|
| Phase 1 | 106 |
| Phase 2 | ~200 |
| QA Remediation | 374 |
| Phase 3 | TBD |
