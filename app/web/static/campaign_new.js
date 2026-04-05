/**
 * World Builder — New Campaign page
 * Manages world generation, section-by-section review/editing,
 * iterative refinement, and final confirmation.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

let _world = {
  premise: "",
  world_facts: [],
  magic_system: "",
  factions: [],
  player_character: {},
  places: [],
  npcs: [],
  narrative_threads: [],
};
let _activeSection = "premise";
let _refineTarget = null;

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadModels();
  checkStatus();
});

async function loadModels() {
  try {
    const res = await fetch("/api/models");
    const data = await res.json();
    const sel = document.getElementById("model-select");
    sel.innerHTML = '<option value="">Default model</option>';
    // API returns a plain array
    const models = Array.isArray(data) ? data : (data.models || []);
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.name;
      opt.textContent = m.name;
      sel.appendChild(opt);
    });
  } catch {/* ignore */}
}

async function checkStatus() {
  try {
    const res = await fetch("/api/provider");
    const data = await res.json();
    const dot = document.getElementById("status-dot");
    const lbl = document.getElementById("status-label");
    if (data.available) {
      dot.className = "status-dot online";
      lbl.textContent = `${data.provider} · ${data.default_model}`;
    } else {
      dot.className = "status-dot offline";
      lbl.textContent = `${data.provider} offline`;
    }
  } catch {/* ignore */}
}

// ── Create mode switcher ──────────────────────────────────────────────────────

function switchCreateMode(mode) {
  document.getElementById("mode-describe").classList.toggle("hidden", mode !== "describe");
  document.getElementById("mode-cards").classList.toggle("hidden", mode !== "cards");
  document.getElementById("mode-empty").classList.toggle("hidden", mode !== "empty");
  document.querySelectorAll("#step-describe .tab-btn").forEach(btn => {
    const btnMode = btn.getAttribute("onclick").match(/'(\w+)'/)?.[1];
    btn.classList.toggle("active", btnMode === mode);
  });
}

// ── Card/Lorebook Import ──────────────────────────────────────────────────────

let _importedCards = [];
let _importedLoreEntries = [];

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("card-import-files")?.addEventListener("change", function () {
    _importedCards = [];
    document.getElementById("card-import-preview").innerHTML = "";
    Array.from(this.files).forEach(f => parseCardFile(f));
  });
  document.getElementById("lorebook-import-files")?.addEventListener("change", function () {
    _importedLoreEntries = [];
    document.getElementById("lorebook-import-preview").innerHTML = "";
    Array.from(this.files).forEach(f => parseLorebookFile(f));
  });
});

function parseCardFile(file) {
  const isPng = /\.png$/i.test(file.name) || file.type === "image/png";
  if (isPng) {
    _parsePngCardFile(file);
  } else {
    _parseJsonCardFile(file);
  }
}

function _parseJsonCardFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const data = JSON.parse(e.target.result);
      // Support both top-level and SillyTavern wrapped format
      const card = data.data || data;
      const name = card.name || card.char_name || file.name.replace(/\.json$/i, "");
      _importedCards.push({
        name,
        description:   card.description   || "",
        personality:   card.personality   || "",
        scenario:      card.scenario      || "",
        creator_notes: card.creator_notes || "",
      });
      _updateImportInfo();
      const chip = document.createElement("div");
      chip.className = "badge";
      chip.textContent = `👤 ${name}`;
      document.getElementById("card-import-preview").appendChild(chip);
    } catch {
      showBanner(`Could not parse ${file.name} as JSON.`, "warning");
    }
  };
  reader.readAsText(file);
}

function _parsePngCardFile(file) {
  let portraitDataUrl = null;
  let cardData = null;  // null = not yet loaded; false = failed/not found

  function _tryFinish() {
    if (portraitDataUrl === null || cardData === null) return; // still loading
    if (cardData === false) {
      showBanner(`${file.name}: no character data found in PNG.`, "warning");
      return;
    }
    const name = cardData.name || cardData.char_name || file.name.replace(/\.png$/i, "");
    _importedCards.push({
      name,
      description:   cardData.description   || "",
      personality:   cardData.personality   || "",
      scenario:      cardData.scenario      || "",
      creator_notes: cardData.creator_notes || "",
      portrait_data_url: portraitDataUrl,
    });
    _updateImportInfo();
    const chip = document.createElement("div");
    chip.className = "badge";
    chip.style.cssText = "display:flex;align-items:center;gap:6px";
    chip.innerHTML = `<img src="${portraitDataUrl}" style="width:24px;height:24px;object-fit:cover;border-radius:3px"> 👤 ${escHtml(name)}`;
    document.getElementById("card-import-preview").appendChild(chip);
  }

  // Read as data URL for portrait storage
  const urlReader = new FileReader();
  urlReader.onload = e => {
    portraitDataUrl = e.target.result;
    _tryFinish();
  };

  // Read as ArrayBuffer to parse PNG tEXt chunk
  const bufReader = new FileReader();
  bufReader.onload = e => {
    const parsed = _parsePngChara(e.target.result);
    cardData = parsed || false;
    _tryFinish();
  };

  urlReader.readAsDataURL(file);
  bufReader.readAsArrayBuffer(file);
}

/**
 * Parse a PNG file's tEXt chunks looking for the SillyTavern "chara" keyword.
 * Returns the parsed card JSON (unwrapping .data if present), or null.
 */
function _parsePngChara(arrayBuffer) {
  try {
    const view = new DataView(arrayBuffer);
    // Verify PNG signature: 0x89 50 4E 47 0D 0A 1A 0A
    if (view.getUint32(0) !== 0x89504E47) return null;
    let offset = 8;
    while (offset + 12 <= view.byteLength) {
      const length = view.getUint32(offset);
      const type = String.fromCharCode(
        view.getUint8(offset + 4),
        view.getUint8(offset + 5),
        view.getUint8(offset + 6),
        view.getUint8(offset + 7)
      );
      if (type === "tEXt" && length > 0) {
        const data = new Uint8Array(arrayBuffer, offset + 8, length);
        // Find null byte separating keyword from value
        let sep = -1;
        for (let i = 0; i < data.length; i++) {
          if (data[i] === 0) { sep = i; break; }
        }
        if (sep !== -1) {
          const keyword = new TextDecoder().decode(data.slice(0, sep));
          if (keyword === "chara") {
            // Value is base64-encoded JSON; decode using latin1 to handle raw bytes
            const b64 = new TextDecoder("latin1").decode(data.slice(sep + 1));
            try {
              const json = JSON.parse(atob(b64));
              return json.data || json; // unwrap SillyTavern v2 wrapper if present
            } catch { return null; }
          }
        }
      }
      offset += 12 + length;
      if (type === "IEND") break;
    }
  } catch { /* ignore malformed PNG */ }
  return null;
}

function parseLorebookFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const data = JSON.parse(e.target.result);
      // Support {entries: [...]} and {entries: {0: {...}, 1: {...}}} formats
      let entries = data.entries || data.items || [];
      if (!Array.isArray(entries)) entries = Object.values(entries);
      entries.forEach(entry => {
        const keys = entry.keys || entry.key || [];
        const content = entry.content || entry.text || "";
        if (content) _importedLoreEntries.push({ keys: Array.isArray(keys) ? keys : [keys], content });
      });
      _updateImportInfo();
      const chip = document.createElement("div");
      chip.className = "badge";
      chip.textContent = `📖 ${file.name.replace(/\.json$/i, "")} (${entries.length} entries)`;
      document.getElementById("lorebook-import-preview").appendChild(chip);
    } catch {
      showBanner(`Could not parse ${file.name} as JSON.`, "warning");
    }
  };
  reader.readAsText(file);
}

function _updateImportInfo() {
  const el = document.getElementById("cards-import-info");
  if (el) el.textContent =
    `${_importedCards.length} character card(s) · ${_importedLoreEntries.length} lorebook entr${_importedLoreEntries.length === 1 ? "y" : "ies"} loaded`;
}

async function generateFromCards() {
  if (!_importedCards.length) {
    showBanner("Please import at least one character card.", "warning");
    return;
  }
  const modelName = document.getElementById("model-select").value;
  const extra     = document.getElementById("cards-extra-details").value.trim();

  document.getElementById("step-describe").classList.add("hidden");
  document.getElementById("step-stream").classList.remove("hidden");
  document.getElementById("stream-output-heading").textContent = "Synthesising World from Cards…";

  const outputEl  = document.getElementById("stream-output");
  const countEl   = document.getElementById("stream-char-count");
  const doneMsgEl = document.getElementById("stream-done-msg");

  // Full reset of stream view state
  outputEl.textContent = "";
  countEl.textContent  = "";
  countEl.style.color  = "";
  doneMsgEl.classList.add("hidden");
  doneMsgEl.style.color = "";
  doneMsgEl.innerHTML   = "✓ Generation complete — loading review…";

  try {
    const res = await fetch("/api/campaigns/world-builder/from-cards/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cards: _importedCards,
        lorebook_entries: _importedLoreEntries,
        additional_details: extra,
        model_name: modelName || null,
      }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let fullText  = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      fullText += chunk;
      outputEl.textContent = fullText;
      countEl.textContent  = `${fullText.length} chars`;
    }

    // Check for server-side error signal anywhere in the stream
    const errMatch = fullText.match(/\n\n\[ERROR:\s*([\s\S]*?)\]$/);
    if (errMatch) throw new Error(errMatch[1].trim());

    const data = _extractJson(fullText);
    if (!data) {
      // Leave the raw output visible so the user can see what went wrong
      countEl.textContent = `${fullText.length} chars — parse failed`;
      countEl.style.color = "var(--red)";
      doneMsgEl.innerHTML =
        '⚠ Could not parse output as JSON — the model may have cut off early or returned unexpected text. ' +
        'Scroll up to inspect the output. ' +
        '<button class="btn btn-sm" style="margin-left:8px" onclick="retryFromCards()">↺ Try Again</button>';
      doneMsgEl.style.color = "var(--yellow)";
      doneMsgEl.classList.remove("hidden");
      return;
    }

    _world = data;
    doneMsgEl.classList.remove("hidden");
    await new Promise(r => setTimeout(r, 800));
    document.getElementById("step-stream").classList.add("hidden");
    document.getElementById("step-review").classList.remove("hidden");
    populateAllSections();
    showSection("premise");
  } catch (e) {
    doneMsgEl.innerHTML =
      `⚠ Synthesis failed: ${escHtml(e.message)} ` +
      '<button class="btn btn-sm" style="margin-left:8px" onclick="retryFromCards()">↺ Try Again</button>';
    doneMsgEl.style.color = "var(--red)";
    doneMsgEl.classList.remove("hidden");
  }
}

function retryFromCards() {
  document.getElementById("step-stream").classList.add("hidden");
  document.getElementById("step-describe").classList.remove("hidden");
  switchCreateMode("cards");
}

// ── World Generation ──────────────────────────────────────────────────────────

async function generateWorld() {
  const description = document.getElementById("world-description").value.trim();
  if (!description) {
    showBanner("Please describe your world first.", "warning");
    return;
  }

  const modelName = document.getElementById("model-select").value;

  // Switch to the streaming panel so the user can read along
  document.getElementById("step-describe").classList.add("hidden");
  document.getElementById("step-stream").classList.remove("hidden");
  document.getElementById("stream-output-heading").textContent = "Generating World…";

  const outputEl   = document.getElementById("stream-output");
  const countEl    = document.getElementById("stream-char-count");
  const doneMsgEl  = document.getElementById("stream-done-msg");
  outputEl.textContent = "";
  countEl.textContent  = "";
  countEl.style.color  = "";
  doneMsgEl.classList.add("hidden");
  doneMsgEl.style.color = "";
  doneMsgEl.innerHTML   = "✓ Generation complete — loading review…";

  try {
    const res = await fetch("/api/campaigns/world-builder/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, model_name: modelName || null }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });

      if (chunk.startsWith("\n\n[ERROR:")) {
        throw new Error(chunk.replace(/^\n\n\[ERROR:\s*/, "").replace(/\]$/, "").trim());
      }

      fullText += chunk;
      outputEl.textContent = fullText;
      // Auto-scroll to bottom so user follows the output
      outputEl.scrollTop = outputEl.scrollHeight;
      countEl.textContent = `${fullText.length.toLocaleString()} chars`;
    }

    // Parse the accumulated JSON
    const data = _extractJson(fullText);
    if (!data) {
      // Keep the raw output visible so the user can see what went wrong.
      // The most common cause is truncation — output ends before the JSON closes.
      countEl.textContent = `${fullText.length.toLocaleString()} chars — parse failed`;
      countEl.style.color = "var(--red)";
      doneMsgEl.innerHTML =
        '⚠ Could not parse output as JSON — the model may have cut off early. ' +
        'Scroll up to inspect the output. ' +
        '<button class="btn btn-sm" style="margin-left:8px" onclick="retryGenerate()">↺ Try Again</button>';
      doneMsgEl.style.color = "var(--yellow)";
      doneMsgEl.classList.remove("hidden");
      return;
    }

    _world = data;
    doneMsgEl.classList.remove("hidden");
    // Brief pause so the user sees the "complete" message before switching
    await new Promise(r => setTimeout(r, 800));
    document.getElementById("step-stream").classList.add("hidden");
    showReviewStep();
  } catch (e) {
    doneMsgEl.innerHTML =
      `⚠ Generation failed: ${escHtml(e.message)} ` +
      '<button class="btn btn-sm" style="margin-left:8px" onclick="retryGenerate()">↺ Try Again</button>';
    doneMsgEl.style.color = "var(--red)";
    doneMsgEl.classList.remove("hidden");
  }
}

function retryGenerate() {
  document.getElementById("step-stream").classList.add("hidden");
  document.getElementById("step-describe").classList.remove("hidden");
  switchCreateMode("describe");
}

/** Extract the first JSON object from raw LLM output (mirrors Python _extract_json). */
function _extractJson(text) {
  // Strip <think>...</think> blocks from reasoning models (Qwen3, DeepSeek-R1, etc.)
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>/gi, "");
  // Strip plain-text preamble heuristic (e.g. "Thinking Process: ...")
  const preambleMatch = cleaned.match(/^[^\{]*?(?=\{)/s);
  if (preambleMatch && preambleMatch[0].includes("\n")) {
    cleaned = cleaned.slice(preambleMatch[0].length);
  }
  // Strip markdown fences
  cleaned = cleaned.replace(/```json\s*/g, "").replace(/```/g, "");
  // Find outermost { ... }
  const start = cleaned.indexOf("{");
  const end   = cleaned.lastIndexOf("}");
  if (start !== -1 && end > start) {
    try { return JSON.parse(cleaned.slice(start, end + 1)); } catch {}
  }
  try { return JSON.parse(cleaned.trim()); } catch {}
  return null;
}

// ── Review step ───────────────────────────────────────────────────────────────

function showReviewStep() {
  document.getElementById("step-describe").classList.add("hidden");
  document.getElementById("step-review").classList.remove("hidden");
  populateAllSections();
  showSection("premise");
}

function backToDescribe() {
  document.getElementById("step-review").classList.add("hidden");
  document.getElementById("step-describe").classList.remove("hidden");
}

function showSection(name) {
  _activeSection = name;
  document.querySelectorAll(".wb-section").forEach(el => el.classList.add("hidden"));
  document.getElementById(`section-${name}`).classList.remove("hidden");
  document.querySelectorAll(".wb-nav-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.section === name));
}

// ── Populate sections from _world ─────────────────────────────────────────────

function populateAllSections() {
  // Premise
  document.getElementById("field-premise").value = _world.premise || "";

  // Player character
  const pc = _world.player_character || {};
  document.getElementById("pc-name").value = pc.name || "";
  document.getElementById("pc-role").value = pc.role || "";
  document.getElementById("pc-appearance").value = pc.appearance || "";
  document.getElementById("pc-personality").value = pc.personality || "";
  document.getElementById("pc-background").value = pc.background || "";
  document.getElementById("pc-wants").value = pc.wants || "";
  document.getElementById("pc-fears").value = pc.fears || "";
  document.getElementById("pc-how-seen").value = pc.how_seen || "";

  // Magic system
  document.getElementById("field-magic_system").value = _world.magic_system || "";

  // Lists
  renderFactsList();
  renderPlacesList();
  renderNpcsList();
  renderThreadsList();
  renderFactionsList();
}

// ── Facts ─────────────────────────────────────────────────────────────────────

function renderFactsList() {
  const container = document.getElementById("facts-list");
  container.innerHTML = "";
  (_world.world_facts || []).forEach((fact, i) => {
    const row = document.createElement("div");
    row.className = "wb-list-row";
    row.innerHTML = `
      <textarea class="wb-field" rows="2" oninput="_world.world_facts[${i}]=this.value">${escHtml(fact)}</textarea>
      <button class="btn-icon wb-delete-btn" onclick="removeFact(${i})" title="Remove">✕</button>
    `;
    container.appendChild(row);
  });
}

function addFact() {
  _world.world_facts = _world.world_facts || [];
  _world.world_facts.push("");
  renderFactsList();
  // Focus the new textarea
  const rows = document.querySelectorAll("#facts-list .wb-list-row");
  if (rows.length) rows[rows.length - 1].querySelector("textarea").focus();
}

function removeFact(i) {
  _world.world_facts.splice(i, 1);
  renderFactsList();
}

// ── Places ─────────────────────────────────────────────────────────────────────

function renderPlacesList() {
  const container = document.getElementById("places-list");
  container.innerHTML = "";
  (_world.places || []).forEach((p, i) => {
    const div = document.createElement("div");
    div.className = "wb-card";
    div.innerHTML = `
      <div class="wb-card-header">
        <input type="text" class="wb-field" placeholder="Place name"
          value="${escHtml(p.name || '')}"
          oninput="_world.places[${i}].name=this.value">
        <button class="btn-icon wb-delete-btn" onclick="removePlace(${i})" title="Remove">✕</button>
      </div>
      <div class="form-group" style="margin-top:8px">
        <label class="small-label">Description</label>
        <textarea class="wb-field" rows="2"
          oninput="_world.places[${i}].description=this.value">${escHtml(p.description || '')}</textarea>
      </div>
      <div class="form-group">
        <label class="small-label">Current State</label>
        <textarea class="wb-field" rows="2"
          oninput="_world.places[${i}].current_state=this.value">${escHtml(p.current_state || '')}</textarea>
      </div>
    `;
    container.appendChild(div);
  });
}

function addPlace() {
  _world.places = _world.places || [];
  _world.places.push({ name: "", description: "", current_state: "" });
  renderPlacesList();
}

function removePlace(i) {
  _world.places.splice(i, 1);
  renderPlacesList();
}

// ── NPCs ──────────────────────────────────────────────────────────────────────

function renderNpcsList() {
  const container = document.getElementById("npcs-list");
  container.innerHTML = "";
  (_world.npcs || []).forEach((n, i) => {
    const div = document.createElement("div");
    div.className = "wb-card";
    div.innerHTML = `
      <div class="wb-card-header">
        <input type="text" class="wb-field" placeholder="NPC name"
          value="${escHtml(n.name || '')}"
          oninput="_world.npcs[${i}].name=this.value">
        <button class="btn-icon wb-delete-btn" onclick="removeNpc(${i})" title="Remove">✕</button>
      </div>
      <div class="wb-grid-2" style="margin-top:8px">
        <div class="form-group">
          <label class="small-label">Role</label>
          <input type="text" class="wb-field"
            value="${escHtml(n.role || '')}"
            oninput="_world.npcs[${i}].role=this.value">
        </div>
        <div class="form-group">
          <label class="small-label">Relationship to Player</label>
          <input type="text" class="wb-field"
            value="${escHtml(n.relationship_to_player || '')}"
            oninput="_world.npcs[${i}].relationship_to_player=this.value">
        </div>
      </div>
      <div class="form-group">
        <label class="small-label">Appearance</label>
        <textarea class="wb-field" rows="2"
          oninput="_world.npcs[${i}].appearance=this.value">${escHtml(n.appearance || '')}</textarea>
      </div>
      <div class="form-group">
        <label class="small-label">Personality</label>
        <textarea class="wb-field" rows="2"
          oninput="_world.npcs[${i}].personality=this.value">${escHtml(n.personality || '')}</textarea>
      </div>
      <div class="wb-grid-2">
        <div class="form-group">
          <label class="small-label">Current Location</label>
          <input type="text" class="wb-field"
            value="${escHtml(n.current_location || '')}"
            oninput="_world.npcs[${i}].current_location=this.value">
        </div>
        <div class="form-group">
          <label class="small-label">Current State</label>
          <input type="text" class="wb-field"
            value="${escHtml(n.current_state || '')}"
            oninput="_world.npcs[${i}].current_state=this.value">
        </div>
      </div>
    `;
    container.appendChild(div);
  });
}

function addNpc() {
  _world.npcs = _world.npcs || [];
  _world.npcs.push({ name: "", role: "", appearance: "", personality: "",
    relationship_to_player: "", current_location: "", current_state: "" });
  renderNpcsList();
}

function removeNpc(i) {
  _world.npcs.splice(i, 1);
  renderNpcsList();
}

// ── Narrative Threads ─────────────────────────────────────────────────────────

function renderThreadsList() {
  const container = document.getElementById("threads-list");
  container.innerHTML = "";
  (_world.narrative_threads || []).forEach((t, i) => {
    const div = document.createElement("div");
    div.className = "wb-card";
    div.innerHTML = `
      <div class="wb-card-header">
        <input type="text" class="wb-field" placeholder="Thread title"
          value="${escHtml(t.title || '')}"
          oninput="_world.narrative_threads[${i}].title=this.value">
        <button class="btn-icon wb-delete-btn" onclick="removeThread(${i})" title="Remove">✕</button>
      </div>
      <div class="form-group" style="margin-top:8px">
        <label class="small-label">Description / Tension</label>
        <textarea class="wb-field" rows="3"
          oninput="_world.narrative_threads[${i}].description=this.value">${escHtml(t.description || '')}</textarea>
      </div>
    `;
    container.appendChild(div);
  });
}

function addThread() {
  _world.narrative_threads = _world.narrative_threads || [];
  _world.narrative_threads.push({ title: "", description: "" });
  renderThreadsList();
}

function removeThread(i) {
  _world.narrative_threads.splice(i, 1);
  renderThreadsList();
}

// ── Factions ──────────────────────────────────────────────────────────────────

function renderFactionsList() {
  const container = document.getElementById("factions-list");
  container.innerHTML = "";
  (_world.factions || []).forEach((f, i) => {
    const div = document.createElement("div");
    div.className = "wb-card";
    div.innerHTML = `
      <div class="wb-card-header">
        <input type="text" class="wb-field" placeholder="Faction name"
          value="${escHtml(f.name || '')}"
          oninput="_world.factions[${i}].name=this.value">
        <button class="btn-icon wb-delete-btn" onclick="removeFaction(${i})" title="Remove">✕</button>
      </div>
      <div class="form-group" style="margin-top:8px">
        <label class="small-label">Description</label>
        <textarea class="wb-field" rows="2"
          oninput="_world.factions[${i}].description=this.value">${escHtml(f.description || '')}</textarea>
      </div>
      <div class="wb-grid-2">
        <div class="form-group">
          <label class="small-label">Goals</label>
          <textarea class="wb-field" rows="2"
            oninput="_world.factions[${i}].goals=this.value">${escHtml(f.goals || '')}</textarea>
        </div>
        <div class="form-group">
          <label class="small-label">Methods</label>
          <textarea class="wb-field" rows="2"
            oninput="_world.factions[${i}].methods=this.value">${escHtml(f.methods || '')}</textarea>
        </div>
      </div>
    `;
    container.appendChild(div);
  });
}

function addFaction() {
  _world.factions = _world.factions || [];
  _world.factions.push({ name: "", description: "", goals: "", methods: "" });
  renderFactionsList();
}

function removeFaction(i) {
  _world.factions.splice(i, 1);
  renderFactionsList();
}

// ── Sync editable fields into _world before submitting ────────────────────────

function syncWorldFromForm() {
  _world.premise = document.getElementById("field-premise").value.trim();
  _world.magic_system = document.getElementById("field-magic_system").value.trim();
  _world.player_character = {
    name: document.getElementById("pc-name").value.trim() || "The Protagonist",
    role: document.getElementById("pc-role").value.trim(),
    appearance: document.getElementById("pc-appearance").value.trim(),
    personality: document.getElementById("pc-personality").value.trim(),
    background: document.getElementById("pc-background").value.trim(),
    wants: document.getElementById("pc-wants").value.trim(),
    fears: document.getElementById("pc-fears").value.trim(),
    how_seen: document.getElementById("pc-how-seen").value.trim(),
  };
  // List fields are updated via oninput handlers, no sync needed
}

// ── Refine ────────────────────────────────────────────────────────────────────

const SECTION_LABELS = {
  premise: "Premise",
  world_facts: "World Facts",
  magic_system: "Magic / Technology System",
  factions: "Factions",
  player_character: "Player Character",
  places: "Places",
  npcs: "NPCs",
  narrative_threads: "Narrative Threads",
};

function refineSection(section) {
  _refineTarget = section;
  document.getElementById("refine-title").textContent =
    `Refine: ${SECTION_LABELS[section] || section}`;
  document.getElementById("refine-instructions").value = "";
  document.getElementById("refine-modal").classList.remove("hidden");
  setTimeout(() => document.getElementById("refine-instructions").focus(), 50);
}

function closeRefine() {
  document.getElementById("refine-modal").classList.add("hidden");
  _refineTarget = null;
}

async function submitRefine() {
  const instructions = document.getElementById("refine-instructions").value.trim();
  if (!instructions) return;
  const section = _refineTarget;
  closeRefine();
  syncWorldFromForm();

  const modelName = document.getElementById("model-select").value;
  showLoading(`Refining: ${SECTION_LABELS[section] || section}…`, "");

  try {
    const res = await fetch("/api/campaigns/world-builder/refine/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current: _world,
        section,
        instructions,
        model_name: modelName || null,
      }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      if (chunk.startsWith("\n\n[ERROR:")) {
        throw new Error(chunk.replace(/^\n\n\[ERROR:\s*/, "").replace(/\]$/, "").trim());
      }
      fullText += chunk;
    }

    const data = _extractJson(fullText);
    if (!data) throw new Error("Could not parse refinement output. Try again.");

    _world = data;
    hideLoading();
    populateAllSections();
    showSection(section);
  } catch (e) {
    hideLoading();
    showBanner(`Refinement failed: ${e.message}`, "error");
  }
}

// ── Confirm & Create ──────────────────────────────────────────────────────────

async function confirmWorld() {
  syncWorldFromForm();
  const campaignName = document.getElementById("campaign-name-input").value.trim();
  if (!campaignName) {
    showBanner("Please enter a campaign name before confirming.", "warning");
    backToDescribe();
    document.getElementById("campaign-name-input").focus();
    return;
  }

  const modelName = document.getElementById("model-select").value;
  showLoading("Creating campaign…", "Saving your world document.");

  try {
    const res = await fetch("/api/campaigns/world-builder/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        world: _world,
        campaign_name: campaignName,
        model_name: modelName || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      const detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    // Patch portraits for any PNG character cards
    const cardsWithPortraits = _importedCards.filter(c => c.portrait_data_url);
    if (cardsWithPortraits.length) {
      showLoading("Saving portraits…", "Associating card images with NPCs.");
      await _patchNpcPortraits(data.campaign_id, cardsWithPortraits);
    }

    hideLoading();
    window.location.href = `/campaigns/${data.campaign_id}`;
  } catch (e) {
    hideLoading();
    showBanner(`Could not create campaign: ${e.message}`, "error");
  }
}

async function createEmptyCampaign() {
  const campaignName = document.getElementById("campaign-name-input").value.trim();
  if (!campaignName) {
    showBanner("Please enter a campaign name.", "warning");
    document.getElementById("campaign-name-input").focus();
    return;
  }

  const modelName = document.getElementById("model-select").value;
  showLoading("Creating campaign…", "");

  const emptyWorld = {
    premise: "",
    world_facts: [],
    magic_system: "",
    factions: [],
    player_character: { name: "The Protagonist", appearance: "", personality: "", background: "", wants: "", fears: "" },
    places: [],
    npcs: [],
    narrative_threads: [],
  };

  try {
    const res = await fetch("/api/campaigns/world-builder/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        world: emptyWorld,
        campaign_name: campaignName,
        model_name: modelName || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      const detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    hideLoading();
    window.location.href = `/campaigns/${data.campaign_id}`;
  } catch (e) {
    hideLoading();
    showBanner(`Could not create campaign: ${e.message}`, "error");
  }
}

async function _patchNpcPortraits(campaignId, cards) {
  try {
    const res = await fetch(`/api/campaigns/${campaignId}/npcs`);
    if (!res.ok) return;
    const npcs = await res.json();
    const npcByName = {};
    npcs.forEach(n => { npcByName[n.name.toLowerCase()] = n; });
    for (const card of cards) {
      const npc = npcByName[card.name.toLowerCase()];
      if (npc) {
        await fetch(`/api/campaigns/${campaignId}/npcs/${npc.id}/portrait`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data_url: card.portrait_data_url }),
        });
      }
    }
  } catch { /* non-fatal — portraits can be set manually */ }
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function showLoading(msg, detail) {
  document.getElementById("wb-loading-msg").textContent = msg;
  document.getElementById("wb-loading-detail").textContent = detail || "";
  document.getElementById("wb-loading").classList.remove("hidden");
}

function hideLoading() {
  document.getElementById("wb-loading").classList.add("hidden");
}

function showBanner(msg, type = "info") {
  const container = document.getElementById("banner-container");
  const banner = document.createElement("div");
  banner.className = `banner banner-${type}`;
  banner.textContent = msg;
  const close = document.createElement("button");
  close.className = "banner-close";
  close.textContent = "✕";
  close.onclick = () => banner.remove();
  banner.appendChild(close);
  container.innerHTML = "";
  container.appendChild(banner);
  if (type !== "error") setTimeout(() => banner.remove(), 6000);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
