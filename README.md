# RP Utility

A local-first AI roleplay engine that runs entirely on your machine. It connects to a locally running language model (Ollama or LM Studio) and maintains a rich, persistent world behind every conversation — tracking memories, relationships, locations, quests, factions, and much more, automatically, as you play.

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Launching the App](#launching-the-app)
- [The Home Screen](#the-home-screen)
  - [Creating a Session](#creating-a-session)
  - [Resuming a Session](#resuming-a-session)
  - [The Library](#the-library)
- [Character Cards](#character-cards)
- [Lorebooks](#lorebooks)
- [The Chat Interface](#the-chat-interface)
- [The Status Page](#the-status-page)
  - [Summary Bar](#summary-bar)
  - [Current Scene](#current-scene)
  - [Memory System](#memory-system)
  - [Relationships](#relationships)
  - [World State](#world-state)
  - [Player Objectives](#player-objectives)
  - [Story Bookmarks](#story-bookmarks)
  - [Contradiction Flags](#contradiction-flags)
  - [Player Character State](#player-character-state)
  - [Inventory](#inventory)
  - [Status Effects](#status-effects)
  - [NPC Roster](#npc-roster)
  - [Location Registry](#location-registry)
  - [Story Beats](#story-beats)
  - [Quest Log](#quest-log)
  - [Session Journal](#session-journal)
  - [Lore Notes](#lore-notes)
  - [Character Stats](#character-stats)
  - [Skill Check Log](#skill-check-log)
  - [Narrative Arc](#narrative-arc)
  - [Factions](#factions)
  - [Archived Memories](#archived-memories)
- [Configuration](#configuration)
- [Data & Privacy](#data--privacy)
- [Directory Structure](#directory-structure)
- [Advanced: CLI Usage](#advanced-cli-usage)
- [Running Tests](#running-tests)

---

## Requirements

- **Python 3.10 or newer** — [python.org/downloads](https://www.python.org/downloads/)
- **A local LLM provider** — one of:
  - **[Ollama](https://ollama.com)** (recommended) — free, easy to install, runs in the background
  - **[LM Studio](https://lmstudio.ai)** — GUI-based local model runner

You do **not** need an internet connection, an API key, or a cloud account. Everything runs on your own hardware.

### Setting Up Ollama (recommended)

1. Download and install Ollama from [ollama.com](https://ollama.com)
2. Pull a model — a good starting point:
   ```
   ollama pull llama3.2
   ```
3. Ollama starts automatically in the background after installation. You can verify it is running by visiting `http://localhost:11434` in your browser.

For best roleplay quality, models with 7B+ parameters work well. Larger models (13B, 70B) produce richer, more coherent responses if your hardware supports them.

---

## Quick Start

1. Install Python and Ollama (see above).
2. Double-click **`Launch RP Utility.bat`** — this installs all Python dependencies automatically, then opens the web UI in your browser.
3. On the home screen, pick a character card, give your session a name, and click **Create Session →**.
4. Start writing. RP Utility handles everything else automatically.

---

## Launching the App

Double-click **`Launch RP Utility.bat`** from the project folder. It will:

1. Check and install any missing Python dependencies from `requirements.txt`.
2. Open `http://localhost:7860` in your default browser.
3. Start the web server. Keep the terminal window open while playing — closing it stops the server.

To stop the app, close the terminal window or press `Ctrl+C` inside it.

---

## The Home Screen

The home screen (`http://localhost:7860`) is divided into three areas:

- **Sessions** (left) — your existing sessions, sorted by most recently updated. Click any session to jump straight into that chat.
- **New Session** (right) — form to create a new session.
- **Library** (bottom) — manage your character cards and lorebooks.

### Creating a Session

Fill in the **New Session** form:

| Field | Required | Description |
|---|---|---|
| Session Name | Yes | A label for this playthrough (e.g. "The Crosshaven Affair") |
| Character Card | Yes | The AI character you'll be roleplaying with |
| Lorebook | No | A world-knowledge document to attach (see [Lorebooks](#lorebooks)) |
| Ollama Model | No | Override the default model for this session only |
| Starting Location | No | Where the story begins (e.g. "Tallow & Ink Tavern") |

Click **Create Session →** to begin. You'll be taken straight to the chat.

### Resuming a Session

Click any session card on the left side of the home screen. Sessions show the character name, turn count, and last active time.

### The Library

The Library section at the bottom of the home screen lets you manage your collection of cards and lorebooks.

**Importing files:**
- Click **⬆ Import Card** to pick a character card file from anywhere on your computer (`.json` or `.png`). It will be copied into the `data/cards/` folder automatically.
- Click **⬆ Import Lorebook** to do the same for lorebook files.
- Click **↺ Reload** if you manually added files to those folders and want the UI to pick them up.

**Viewing details:**
- Click the **detail button** (the eye icon or the card name) on any card or lorebook tile to open a full-detail viewer showing all fields, tags, and entries.

---

## Character Cards

A character card defines the AI character's personality, background, speech style, scenario, and opening message. RP Utility supports two formats:

### JSON Cards

Plain `.json` files in `data/cards/`. The minimum required field is `name`. Common fields:

```json
{
  "name": "Lyra Ashveil",
  "description": "A sharp-tongued rogue with a complicated past...",
  "personality": "Sarcastic, loyal to a fault, hides vulnerability behind wit.",
  "scenario": "You've just hired Lyra as a guide through the Ashfen marshes.",
  "first_message": "So you're the one who posted that job. You look soft. I've buried softer.",
  "mes_example": "<START>\nUser: Are you reliable?\nLyra: More reliable than your instincts, clearly."
}
```

### PNG Cards (SillyTavern format)

`.png` image files that have character data embedded invisibly inside them. RP Utility reads these automatically — just drop them in `data/cards/` or import them via the Library. Both V2 and V3 SillyTavern card specs are supported, including embedded lorebooks (V3).

A card thumbnail image will appear in the Library grid for PNG cards.

### Demo Card

A demo card (`lyra_ashveil.json`) is included in `data/cards/` to get you started immediately.

---

## Lorebooks

A lorebook is a collection of world-knowledge entries that get injected into the AI's context automatically when relevant keywords appear in the conversation. They're used to give the AI consistent knowledge of your world's lore, locations, factions, and history without cramming it all into the character card.

**How they work:** Each lorebook entry has a list of trigger keywords. When those words appear in recent conversation, that entry is included in the prompt for that turn. Entries that aren't triggered stay hidden, keeping the prompt lean.

**Format:** `.json` files in `data/lorebooks/`. SillyTavern-format PNG lorebooks are also supported.

A demo lorebook (`crosshaven_and_the_ashfen.json`) is included as an example.

---

## The Chat Interface

The chat page is where the roleplay happens. The layout has:

- **Left sidebar** — live-updating panel showing the current scene, active memories, world state, relationships, objectives, character state, and status effects.
- **Chat area** — the conversation history.
- **Input bar** — type your message and press Enter or click Send.

**Per-message actions** (hover over any message):

| Button | Action |
|---|---|
| 📋 Copy | Copy the message text to clipboard |
| ✏ Edit | Edit the message text in-place |
| 🗑 Delete | Remove the message from history |
| ⭐ Bookmark | Save this moment as a story bookmark |

**Header buttons:**

| Button | Action |
|---|---|
| 📊 Status | Open the full Status page for this session in a new tab |
| ↺ Refresh | Manually refresh the sidebar data |

**After each response**, RP Utility automatically runs background analysis on the exchange to:
- Extract and store new memories
- Detect changes in relationships
- Update the current scene description and location
- Identify new NPCs
- Check for memory contradictions

This happens silently in the background — there is no delay added to your conversation.

---

## The Status Page

Open the Status page by clicking **📊 Status** in the chat header, or by navigating to `/status/<session-id>`. It gives you a full live view of everything RP Utility is tracking for your session.

Click any section header to collapse or expand it. Click **↺ Refresh** in the top-right to reload all data from the server.

### Summary Bar

A row of quick-glance counters at the top:

- **Turns** — total number of exchanges in this session
- **Active Memories** — memories currently in the active pool
- **World State Entries** — tracked world facts
- **Relationships** — number of tracked character pairings
- **Archived Memories** — memories that have been consolidated
- **Contradictions** — flagged memory conflicts
- **Active Objectives** — current player goals
- **Bookmarks** — saved story moments
- **Known NPCs** — characters added to the roster
- **Locations Visited** — entries in the location registry
- **Story Beats** — narrative milestone events
- **Inventory Items** — items in the player's inventory
- **Status Effects** — active buffs/debuffs on the player character

---

### Current Scene

A snapshot of where the story is right now:

- **Location** — current setting
- **Characters Present** — who is in the scene
- **Scene Summary** — a rolling 1–3 sentence description of what is happening, updated after every turn by the AI

---

### Memory System

The memory system is the heart of RP Utility. After every exchange, the AI reads the conversation and extracts important facts, events, and details, storing them automatically.

**Memory types:**

| Type | What it captures |
|---|---|
| Event | Something that happened |
| World Fact | A fact about the world or setting |
| Character Detail | Something learned about a character |
| Relationship Change | A shift in how two characters feel about each other |
| World State | A change in the state of the world (e.g. "The bridge is destroyed") |
| Rumor | Unverified information heard second-hand |
| Suspicion | Something the character suspects but can't confirm |
| Consolidation | A summary memory created when older memories are merged |

**Importance levels:** Critical → High → Medium → Low

**Certainty levels:** Confirmed / Rumor / Suspicion / Lie / Myth

**Filtering:** Use the dropdowns above the memory list to filter by type, importance, or certainty.

**Memory consolidation:** When many memories of the same type accumulate, older ones are automatically summarized and moved to the Archived Memories section, keeping the active pool lean and relevant.

**Contradiction detection:** If a new memory contradicts an existing one, it is flagged automatically. You can review contradictions in the Contradiction Flags section.

---

### Relationships

Tracks how characters feel about each other on five axes, each scored from −1.0 to +1.0:

| Axis | Meaning |
|---|---|
| Trust | How much they believe and rely on each other |
| Fear | How much one fears the other |
| Respect | Professional or moral regard |
| Affection | Warmth and fondness |
| Hostility | Active antagonism or resentment |

Each relationship entry also shows a plain-English summary (e.g. "Deeply trusted ally" or "Feared and distrusted enemy") derived from the current scores.

**Filtering:** Filter by character name, or show only relationships where a character is the source or target.

Relationships are updated automatically after each turn when the AI detects that the exchange implied a shift.

---

### World State

A set of tracked facts about the state of the game world that can change over time — things like "The city gates are locked" or "The rebellion has started." These are distinct from memories: they represent the current state of things, not a record of events.

You can add, edit, and delete world state entries manually from this section.

---

### Player Objectives

Goals the player character is currently pursuing. Each objective has:

- **Name** and **description**
- **Priority** — Critical / High / Medium / Low
- **Status** — Active / Completed / Failed / Abandoned

Objectives can be added and managed manually. Completed or failed objectives can be updated in-place.

---

### Story Bookmarks

Key moments you've saved during the session using the ⭐ button on any message. Each bookmark stores the turn number, a label, and any notes you added. Useful for keeping track of pivotal scenes or major decisions.

---

### Contradiction Flags

When the memory extraction system detects that a new memory appears to contradict something already known, it creates a contradiction flag. Each flag shows:

- The two conflicting memory titles
- A brief explanation of the conflict
- The resolution applied (e.g. "marked uncertain")

Review these periodically to stay aware of narrative inconsistencies.

---

### Player Character State

Tracks the player character's emotional and physical state:

- **Emotional State** — current mood/feelings (e.g. "Anxious, determined")
- **Physical State** — current physical condition
- **Mental State** — cognitive or mental status
- **Notes** — free-form notes

This is updated manually or can be set via the API.

---

### Inventory

A list of items the player character is carrying. Each item has:

- **Name** and **description**
- **Quantity**
- **Tags** (e.g. weapon, consumable, quest item)
- **Equipped** status

Items can be added and removed manually.

---

### Status Effects

Active effects on the player character — buffs, debuffs, conditions (e.g. "Poisoned", "Inspired", "Exhausted"). Each effect has:

- **Name** and **description**
- **Duration** — how long it lasts
- **Potency** — strength (0.0–1.0)
- **Type** — buff, debuff, neutral, or permanent

---

### NPC Roster

A record of all named characters that have appeared in the session. Populated automatically from the conversation.

Each NPC entry includes:
- **Name**, **race**, **role/occupation**
- **Personality** notes
- **Last known location**
- **Disposition** toward the player character (friendly / neutral / hostile / unknown)
- **Faction** affiliation
- **Notes**

You can add, edit, or remove NPCs manually as well.

---

### Location Registry

Every location that appears in the session is tracked here — populated automatically from scene extraction. Each entry records:

- **Name** and **description**
- **Atmosphere** notes
- **Visit count** — how many times the player has been here
- **First visited** and **last visited** timestamps
- **Tags**

The starting location is registered automatically when a session is created.

---

### Story Beats

Significant narrative events or milestones — bigger than a single memory, marking moments that define the arc of the story. Examples: "Alliance formed with the Thornwood rebels", "The true identity of the Masked Merchant revealed."

Story beats are added manually.

---

### Quest Log

Active and completed quests with multi-stage tracking. Each quest has:

- **Name**, **description**, and **giver**
- **Status** — Active / Completed / Failed / Abandoned
- **Priority** — Critical / High / Medium / Low
- **Stages** — a checklist of steps, each completable individually
- **Reward** — what's promised on completion
- **Location** — where the quest was given

Mark individual stages complete using the checkboxes. Completing all stages does not automatically complete the quest — update the status manually when ready.

---

### Session Journal

A chronological log of notes about what happened during this session. Think of it as your personal DM notes or a player diary. Each entry has:

- **Title** and **content**
- **Turn number** — which exchange it was made at
- **Tags**

Journal entries are added manually and displayed newest-first.

---

### Lore Notes

A categorized collection of world-knowledge notes you've gathered or want to remember. Unlike memories (which are extracted automatically), lore notes are written manually and organized by category.

**Categories:** General / History / Magic / Faction / Character / Location / Rumor / Prophecy

Each lore note has a title, body text, source, tags, and a confidence level (Confirmed / Rumor / Speculation / Unknown).

---

### Character Stats

Numeric attributes for the player character — stats like Strength, Charisma, Perception, etc. Each stat has:

- **Name** and optional **description**
- **Value** (current) and **Max value**
- **Category** (e.g. "Attributes", "Skills", "Combat")
- **Is derived** flag — whether it's calculated from other stats

Stats are added and edited manually.

---

### Skill Check Log

A history of dice rolls and skill checks performed during the session. Each entry records:

- **Skill name** and **difficulty**
- **Roll result** and **modifier**
- **Outcome** — Critical Success / Success / Failure / Critical Failure
- **Context** — what the check was for

Skill checks can be performed directly from the Status page.

---

### Narrative Arc

A high-level view of the story's structure:

- **Act** — current act of the story (1, 2, 3...)
- **Tension level** — a 0.0–1.0 score with a label (Calm → Tense → Dramatic → Intense → Climactic)
- **Theme** — the overarching narrative theme
- **Inciting Incident**, **Rising Action**, **Climax**, **Resolution** — story structure notes
- **Tone** — the mood of the story (e.g. "grim", "hopeful", "mysterious")

The narrative arc is edited manually to help you track the shape of the story.

---

### Factions

Organizations, groups, or powers that exist in the world. Each faction has:

- **Name**, **description**, **ideology**
- **Leader** and **headquarters**
- **Power level** — a 0.0–1.0 score
- **Player standing** — the player character's relationship score with this faction (−1.0 to +1.0)
- **Tags**

Adjust a faction's standing using the **+** and **−** buttons in the Standing column.

---

### Archived Memories

Memories that have been consolidated into summaries. When many memories of the same type accumulate, the oldest ones are merged into a single summary memory and moved here. This keeps the active pool focused on recent, relevant information while preserving the full history.

Archived memories are read-only.

---

## Configuration

Settings are controlled via a `.env` file in the project root. Create one to override any defaults:

```
# Provider: "ollama" or "lmstudio"
RP_PROVIDER=ollama

# Model to use (Ollama)
RP_OLLAMA_MODEL=llama3.2

# LM Studio
RP_LMSTUDIO_BASE_URL=http://localhost:1234
RP_LMSTUDIO_MODEL=local-model

# Generation
RP_TEMPERATURE=0.8
RP_MAX_TOKENS=1024

# Memory
RP_MAX_RETRIEVED_MEMORIES=10
RP_CONSOLIDATION_THRESHOLD=10
RP_CONTRADICTION_DETECTION_ENABLED=true

# Debug (prints full prompt to terminal)
RP_DEBUG=false
RP_SHOW_PROMPT=false
```

All settings use the `RP_` prefix. You only need to set values you want to change — everything else uses the defaults shown above.

### Using LM Studio

1. Open LM Studio and load a model.
2. Start the local server (the server icon in the left sidebar).
3. Create a `.env` file with:
   ```
   RP_PROVIDER=lmstudio
   RP_LMSTUDIO_BASE_URL=http://localhost:1234
   ```
4. Launch RP Utility normally.

---

## Data & Privacy

All data is stored locally on your machine in `data/rp_utility.db` (a SQLite database). Nothing is ever sent to an external server. Your conversations, memories, and session data stay entirely on your computer.

The `.gitignore` is configured to exclude all personal game data if you use git. Only the two demo files are tracked by version control.

---

## Directory Structure

```
RP Utility/
├── Launch RP Utility.bat   # Double-click to start
├── requirements.txt
├── .env                    # Your local config (create if needed)
│
├── app/
│   ├── core/               # Engine, models, config, database
│   ├── sessions/           # Memory, relationships, quests, etc.
│   ├── scene/              # Scene tracking and extraction
│   ├── memory/             # Memory retrieval and consolidation
│   ├── relationships/      # Relationship delta extraction
│   ├── prompting/          # Prompt assembly
│   ├── providers/          # Ollama and LM Studio clients
│   ├── cards/              # Card loading (JSON and PNG)
│   ├── lorebooks/          # Lorebook loading and retrieval
│   └── web/
│       ├── server.py       # FastAPI web server and API
│       ├── templates/      # HTML pages
│       └── static/         # CSS and JavaScript
│
├── data/
│   ├── cards/              # Character card files (.json or .png)
│   ├── lorebooks/          # Lorebook files
│   └── rp_utility.db       # All session data (auto-created)
│
└── tests/                  # Automated test suite
```

---

## Advanced: CLI Usage

RP Utility can also be used entirely from the command line without the web UI.

```bash
# Check that your provider is running
python -m app.main check

# List available models
python -m app.main models

# Create a new session
python -m app.main new --name "Forest Run" --char "Lyra Ashveil" --location "The Ashfen"

# Chat in the terminal
python -m app.main chat --session <session-id>

# List all sessions
python -m app.main sessions

# View memories for a session
python -m app.main memory --session <session-id>

# View or update scene state
python -m app.main scene --session <session-id>
python -m app.main scene --session <session-id> --location "Old Temple Ruins"

# Start the web UI manually
python -m app.main serve
python -m app.main serve --port 8080 --reload  # dev mode
```

**In-chat slash commands** (terminal mode only):

| Command | Action |
|---|---|
| `/memory` | Print stored memories |
| `/scene` | Print current scene |
| `/rels` | Print relationship states |
| `/location <name>` | Update current location |
| `/debug` | Toggle debug output |
| `/help` | Show all commands |
| `/quit` | Exit |

---

## Running Tests

```bash
pytest
```

Or a specific test file:

```bash
pytest tests/test_memory.py -v
```

All tests are offline — they use SQLite in-memory databases and mock LLM providers, so no running Ollama instance is needed to run the test suite.
