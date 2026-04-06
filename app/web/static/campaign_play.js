/**
 * Campaign scene play interface.
 * Manages scene setup, AI streaming chat, and scene confirmation.
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

let _campaign = null;
let _scene = null;       // active scene or null
let _pc = null;
let _npcs = [];
let _threads = [];
let _facts = [];
let _streaming = false;
let _userName = "Player";

// ── Regenerate state ──────────────────────────────────────────────────────────
let _alternatives = [];      // all generated responses for the current exchange
let _altIdx = 0;             // index of the currently shown / DB-committed response
let _lastAiDiv = null;       // DOM node of the last AI bubble
let _regenControlsDiv = null; // sibling DOM node holding nav + regen button

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadWorld();
  loadSummaryModels();
  setupInput();
});

async function loadSummaryModels() {
  try {
    const res = await fetch("/api/models");
    if (!res.ok) return;
    const data = await res.json();
    const models = Array.isArray(data) ? data : (data.models || []);
    const sel = document.getElementById("summary-model-select");
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.name;
      opt.textContent = m.name;
      sel.appendChild(opt);
    });
  } catch { /* ignore — dropdown stays at default */ }
}

async function loadWorld() {
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _campaign = data.campaign;
    _pc = data.player_character;
    _npcs = data.npcs || [];
    _threads = (data.threads || []).filter(t => t.status === "active");
    _facts = (data.world_facts || []).filter(f => f.content);
    _scene = data.scenes?.find(s => !s.confirmed) || null;

    document.getElementById("back-link").href = `/campaigns/${CAMPAIGN_ID}`;
    document.getElementById("cancel-setup-link").href = `/campaigns/${CAMPAIGN_ID}`;
    document.getElementById("campaign-name-badge").textContent = _campaign?.name || "";

    // Initialise gen-settings sliders from campaign defaults
    gsInitFromCampaign();

    // Pre-select summary model dropdown from campaign settings
    // Use a small delay so loadSummaryModels() has time to populate the options
    const summaryModel = _campaign?.summary_model_name || "";
    if (summaryModel) {
      const trySet = () => {
        const sel = document.getElementById("summary-model-select");
        if (!sel) return;
        if ([...sel.options].some(o => o.value === summaryModel)) {
          sel.value = summaryModel;
        } else {
          // Options not yet loaded — retry once they arrive
          setTimeout(trySet, 200);
        }
      };
      trySet();
    }

    // Populate setup datalist with known locations
    const dl = document.getElementById("location-suggestions");
    (data.places || []).forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.name;
      dl.appendChild(opt);
    });

    // Populate NPC checkboxes
    renderNpcCheckboxes();

    const forceNew = new URLSearchParams(window.location.search).get("new") === "1";

    if (_scene && !forceNew) {
      // Resume existing active scene
      showChatMode();
      renderExistingTurns();
      renderSidebar();
    } else {
      // Show setup panel for new scene
      _scene = null;
      document.getElementById("scene-setup-panel").classList.remove("hidden");
    }

    // Load player scratchpad
    loadScratchpad();
  } catch (e) {
    showError(`Failed to load campaign: ${e.message}`);
  }
}

function renderNpcCheckboxes() {
  const container = document.getElementById("npc-checkboxes");
  container.innerHTML = "";
  if (!_npcs.length) {
    container.innerHTML = '<span class="muted">No NPCs yet — add them on the campaign overview page.</span>';
    return;
  }
  _npcs.filter(n => n.is_alive).forEach(n => {
    const label = document.createElement("label");
    label.className = "npc-checkbox-label";
    label.innerHTML = `<input type="checkbox" value="${n.id}"> ${escHtml(n.name)}${n.role ? ` <span class="muted">(${escHtml(n.role)})</span>` : ""}`;
    container.appendChild(label);
  });
}

// ── Scene setup quick-add helpers ────────────────────────────────────────────

async function qaGenerateNpc() {
  const desc = document.getElementById("qa-npc-desc").value.trim();
  if (!desc) return;
  const statusEl = document.getElementById("qa-npc-gen-status");
  const btn = document.getElementById("qa-npc-gen-btn");
  statusEl.textContent = "Generating…";
  statusEl.style.color = "";
  btn.disabled = true;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: desc }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const npc = await res.json();
    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    fill("qa-npc-name", npc.name);
    fill("qa-npc-role", npc.role);
    fill("qa-npc-gender", npc.gender);
    fill("qa-npc-age", npc.age);
    fill("qa-npc-appearance", npc.appearance);
    fill("qa-npc-personality", npc.personality);
    statusEl.textContent = "✓ Done";
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  } finally {
    btn.disabled = false;
  }
}

async function qaAddNpc() {
  const name = document.getElementById("qa-npc-name").value.trim();
  if (!name) { document.getElementById("qa-npc-status").textContent = "Name is required."; return; }
  const statusEl = document.getElementById("qa-npc-status");
  statusEl.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        role: document.getElementById("qa-npc-role").value.trim(),
        gender: document.getElementById("qa-npc-gender").value.trim(),
        age: document.getElementById("qa-npc-age").value.trim(),
        appearance: document.getElementById("qa-npc-appearance").value.trim(),
        personality: document.getElementById("qa-npc-personality").value.trim(),
      }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const saved = await res.json();
    // Add to local NPC list and re-render checkboxes
    _npcs.push(saved);
    renderNpcCheckboxes();
    // Auto-check the new NPC
    const checkbox = document.querySelector(`#npc-checkboxes input[value="${saved.id}"]`);
    if (checkbox) checkbox.checked = true;
    // Clear form and collapse
    ["qa-npc-desc","qa-npc-name","qa-npc-role","qa-npc-gender","qa-npc-age","qa-npc-appearance","qa-npc-personality"].forEach(id => {
      document.getElementById(id).value = "";
    });
    document.getElementById("qa-npc-gen-status").textContent = "";
    document.getElementById("qa-npc").removeAttribute("open");
    statusEl.textContent = `✓ ${name} added and selected.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

async function qaAddLocation() {
  const name = document.getElementById("qa-loc-name").value.trim();
  if (!name) { document.getElementById("qa-loc-status").textContent = "Name is required."; return; }
  const statusEl = document.getElementById("qa-loc-status");
  statusEl.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        description: document.getElementById("qa-loc-desc").value.trim(),
        current_state: document.getElementById("qa-loc-state").value.trim(),
      }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    const saved = await res.json();
    // Add to datalist and set as selected location
    const dl = document.getElementById("location-suggestions");
    const opt = document.createElement("option");
    opt.value = saved.name;
    dl.appendChild(opt);
    document.getElementById("setup-location").value = saved.name;
    // Clear form and collapse
    ["qa-loc-name","qa-loc-desc","qa-loc-state"].forEach(id => document.getElementById(id).value = "");
    document.getElementById("qa-location").removeAttribute("open");
    statusEl.textContent = `✓ "${name}" added and set as location.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

async function qaAddFacts() {
  const raw = document.getElementById("qa-facts-input").value.trim();
  if (!raw) return;
  const newFacts = raw.split("\n").map(l => l.trim()).filter(Boolean);
  if (!newFacts.length) return;
  const statusEl = document.getElementById("qa-facts-status");
  statusEl.textContent = "Saving…";
  try {
    // Fetch existing facts, append new ones, replace all
    const existing = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`).then(r => r.json());
    const allFacts = [...existing.map(f => f.content), ...newFacts];
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts: allFacts }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
    document.getElementById("qa-facts-input").value = "";
    document.getElementById("qa-facts").removeAttribute("open");
    statusEl.textContent = `✓ ${newFacts.length} fact${newFacts.length > 1 ? "s" : ""} added.`;
    statusEl.style.color = "var(--green)";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    statusEl.style.color = "var(--red)";
  }
}

// ── Scene setup ───────────────────────────────────────────────────────────────

async function beginScene() {
  const title = document.getElementById("setup-title").value.trim();
  const location = document.getElementById("setup-location").value.trim();
  const intent = document.getElementById("setup-intent").value.trim();
  const tone = document.getElementById("setup-tone").value.trim();
  const npcIds = [...document.querySelectorAll("#npc-checkboxes input:checked")].map(c => c.value);
  const allowUnselectedNpcs = document.getElementById("setup-allow-unselected-npcs").checked;

  // Feature 3: conflict detection — warn about dead NPCs
  const deadNames = npcIds
    .map(id => _npcs.find(n => n.id === id))
    .filter(n => n && !n.is_alive)
    .map(n => n.name);
  if (deadNames.length) {
    const ok = confirm(
      `Warning: the following NPCs are marked as deceased in the world document:\n\n${deadNames.join(", ")}\n\nAdd them to this scene anyway?`
    );
    if (!ok) return;
  }

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, location, npc_ids: npcIds, intent, tone, allow_unselected_npcs: allowUnselectedNpcs }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _scene = await res.json();
    showChatMode();
    renderSidebar();
    await streamOpeningNarration();
  } catch (e) {
    showError(`Could not start scene: ${e.message}`);
  }
}

async function streamOpeningNarration() {
  _streaming = true;
  setSendEnabled(false);
  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/open`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(gsGetParams()),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "assistant", content: buffer });

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
    document.getElementById("user-input").focus();
  }
}

function showChatMode() {
  document.getElementById("scene-setup-panel").classList.add("hidden");
  document.getElementById("chat-body").style.display = "";
  document.getElementById("end-scene-btn").style.display = "";
  if (!_scene?.confirmed) {
    document.getElementById("delete-scene-btn").style.display = "";
  }

  // Update header
  const title = _scene?.title || `Scene ${_scene?.scene_number ?? ""}`;
  document.getElementById("scene-title").textContent = title;
  document.title = `${title} — RP Utility`;
  if (_scene?.location)
    document.getElementById("scene-location-badge").textContent = `📍 ${_scene.location}`;
  if (_scene?.scene_number)
    document.getElementById("scene-num-badge").textContent = `Scene ${_scene.scene_number}`;

  // Tone badge
  const toneBadge = document.getElementById("scene-tone-badge");
  if (_scene?.tone) {
    toneBadge.textContent = _scene.tone;
    toneBadge.classList.remove("hidden");
  } else {
    toneBadge.classList.add("hidden");
  }

  // Scene header image
  const sceneImgWrap = document.getElementById("scene-header-img-wrap");
  const sceneImg     = document.getElementById("scene-header-img");
  if (sceneImg && sceneImgWrap) {
    if (_scene?.scene_image) {
      sceneImg.src = _scene.scene_image;
      sceneImgWrap.classList.remove("hidden");
    } else {
      sceneImgWrap.classList.add("hidden");
    }
  }

  updateUndoButton();
  document.getElementById("user-input").focus();
}

function updateUndoButton() {
  const btn = document.getElementById("undo-btn");
  if (!btn) return;
  const hasTurns = (_scene?.turns?.length || 0) > 0;
  btn.style.display = (hasTurns && !_scene?.confirmed) ? "" : "none";
}

// ── Render existing scene turns ───────────────────────────────────────────────

function renderExistingTurns() {
  if (!_scene?.turns?.length) return;
  const area = document.getElementById("messages-area");
  area.innerHTML = "";
  _scene.turns.forEach((t, i) => {
    // Skip the silent continue nudge — it's not a real user message
    if (t.role === "user" && t.content === "(Continue the story.)") return;
    const div = appendMessage(t.role, t.content);
    _addEditButton(div, t.role, i);
  });
  scrollToBottom();
  updateUndoButton();
}

// ── Chat ──────────────────────────────────────────────────────────────────────

async function sendMessage() {
  if (_streaming) return;
  const input = document.getElementById("user-input");
  let text = input.value.trim();
  if (!text) return;
  input.value = "";
  input.style.height = "";

  // ── Dice roll command (/roll XdY or /roll XdY+Z) ─────────────────────────
  const diceMatch = text.match(/^\/roll\s+(\d*)d(\d+)([+-]\d+)?(.*)$/i);
  if (diceMatch) {
    const count  = parseInt(diceMatch[1] || "1");
    const sides  = parseInt(diceMatch[2]);
    const mod    = parseInt(diceMatch[3] || "0");
    const extra  = (diceMatch[4] || "").trim();
    if (count >= 1 && count <= 100 && sides >= 2 && sides <= 1000) {
      const rolls  = Array.from({ length: count }, () => Math.ceil(Math.random() * sides));
      const total  = rolls.reduce((a, b) => a + b, 0) + mod;
      const modStr = mod > 0 ? `+${mod}` : mod < 0 ? `${mod}` : "";
      const label  = `${count}d${sides}${modStr}`;
      const rollStr = rolls.length > 1 ? `[${rolls.join(", ")}]` : `${rolls[0]}`;
      const resultLine = `🎲 Roll ${label}: ${rollStr}${mod !== 0 ? ` ${mod > 0 ? "+" : ""}${mod}` : ""} = **${total}**`;
      appendDiceRoll(label, rolls, mod, total);
      // Build the message sent to AI — include roll result as context
      text = extra
        ? `${extra}\n\n*(${resultLine})*`
        : `*(${resultLine})*`;
    }
  }

  // Reset regenerate state — new exchange begins
  _clearRegenState();

  const userDiv = appendMessage("user", text);
  scrollToBottom();
  _streaming = true;
  setSendEnabled(false);

  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, user_name: _userName, ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    // Finalize and update local scene turns
    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "user", content: text });
    _scene.turns.push({ role: "assistant", content: buffer });

    // Attach edit buttons now that indices are known
    _addEditButton(userDiv, "user", _scene.turns.length - 2);
    _trackAiResponse(aiDiv, buffer, _scene.turns.length - 1);

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

async function continueStory() {
  if (_streaming) return;

  // Inject a silent system nudge — no user bubble shown in the chat
  const continueMsg = "(Continue the story.)";

  // Reset regenerate state — new exchange begins
  _clearRegenState();

  _streaming = true;
  setSendEnabled(false);

  const aiDiv = appendStreamingMessage();
  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: continueMsg, user_name: "__continue__", ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      aiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(aiDiv, buffer);
    if (!_scene.turns) _scene.turns = [];
    _scene.turns.push({ role: "user", content: continueMsg });
    _scene.turns.push({ role: "assistant", content: buffer });

    _trackAiResponse(aiDiv, buffer, _scene.turns.length - 1);

  } catch (e) {
    aiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

// ── Regenerate helpers ────────────────────────────────────────────────────────

function _clearRegenState() {
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }
  _alternatives = [];
  _altIdx = 0;
  _lastAiDiv = null;
}

function _trackAiResponse(aiDiv, buffer, turnIndex = -1) {
  _lastAiDiv = aiDiv;
  _alternatives = [buffer];
  _altIdx = 0;
  if (turnIndex >= 0) _addEditButton(aiDiv, "assistant", turnIndex);
  _renderRegenControls();
}

// ── Inline turn editing ───────────────────────────────────────────────────────

function _addEditButton(bubbleDiv, role, turnIndex) {
  bubbleDiv.querySelector(".turn-edit-btn")?.remove();
  const btn = document.createElement("button");
  btn.className = "turn-edit-btn";
  btn.title = "Edit this message";
  btn.textContent = "✎";
  btn.onclick = (e) => { e.stopPropagation(); startTurnEdit(bubbleDiv, turnIndex, role); };
  bubbleDiv.appendChild(btn);
}

function startTurnEdit(bubbleDiv, turnIndex, role) {
  const originalContent = _scene?.turns?.[turnIndex]?.content ?? "";

  bubbleDiv.classList.add("bubble-edit-mode");
  bubbleDiv.innerHTML = "";

  const ta = document.createElement("textarea");
  ta.className = "turn-edit-textarea";
  ta.value = originalContent;
  // Auto-grow
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; });

  const btnRow = document.createElement("div");
  btnRow.className = "turn-edit-actions";

  const saveBtn = document.createElement("button");
  saveBtn.className = "btn btn-sm btn-primary";
  saveBtn.textContent = "Save";
  saveBtn.onclick = async () => {
    const newContent = ta.value.trim();
    if (!newContent) return;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    await saveTurnEdit(bubbleDiv, turnIndex, role, newContent, originalContent);
  };

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn btn-sm";
  cancelBtn.textContent = "Cancel";
  cancelBtn.onclick = () => _restoreBubble(bubbleDiv, role, originalContent, turnIndex);

  btnRow.append(saveBtn, cancelBtn);
  bubbleDiv.append(ta, btnRow);

  // Size textarea to content, focus
  requestAnimationFrame(() => {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + "px";
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  });
}

function _restoreBubble(bubbleDiv, role, content, turnIndex) {
  bubbleDiv.classList.remove("bubble-edit-mode");
  if (role === "assistant") {
    bubbleDiv.innerHTML = marked.parse(content);
    colorizeAiProse(bubbleDiv);
  } else {
    bubbleDiv.textContent = content;
  }
  _addEditButton(bubbleDiv, role, turnIndex);
}

async function saveTurnEdit(bubbleDiv, turnIndex, role, newContent, originalContent) {
  try {
    const res = await fetch(
      `/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/${turnIndex}`,
      { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: newContent }) }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // Update local state
    if (_scene.turns?.[turnIndex]) _scene.turns[turnIndex].content = newContent;

    _restoreBubble(bubbleDiv, role, newContent, turnIndex);

    // Keep regen alternatives in sync if this is the tracked AI div
    if (role === "assistant" && bubbleDiv === _lastAiDiv) {
      _alternatives[_altIdx] = newContent;
    }
  } catch (e) {
    showError(`Could not save edit: ${e.message}`);
    _restoreBubble(bubbleDiv, role, originalContent, turnIndex);
  }
}

function _renderRegenControls() {
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }
  if (!_lastAiDiv) return;

  const div = document.createElement("div");
  div.className = "regen-controls";

  if (_alternatives.length > 1) {
    const prev = document.createElement("button");
    prev.className = "btn btn-ghost btn-xs";
    prev.textContent = "←";
    prev.title = "Previous response";
    prev.disabled = _altIdx === 0;
    prev.onclick = () => showAlternative(_altIdx - 1);

    const counter = document.createElement("span");
    counter.className = "regen-counter";
    counter.textContent = `${_altIdx + 1} / ${_alternatives.length}`;

    const next = document.createElement("button");
    next.className = "btn btn-ghost btn-xs";
    next.textContent = "→";
    next.title = "Next response";
    next.disabled = _altIdx === _alternatives.length - 1;
    next.onclick = () => showAlternative(_altIdx + 1);

    div.appendChild(prev);
    div.appendChild(counter);
    div.appendChild(next);
  }

  const regenBtn = document.createElement("button");
  regenBtn.className = "btn btn-ghost btn-xs";
  regenBtn.textContent = "↺ Regenerate";
  regenBtn.title = "Generate a new response for this message";
  regenBtn.onclick = regenerate;
  div.appendChild(regenBtn);

  _lastAiDiv.after(div);
  _regenControlsDiv = div;
}

async function showAlternative(idx) {
  if (idx < 0 || idx >= _alternatives.length || idx === _altIdx || !_lastAiDiv) return;
  _altIdx = idx;
  _lastAiDiv.innerHTML = marked.parse(_alternatives[idx]);
  colorizeAiProse(_lastAiDiv);
  _renderRegenControls();

  // Update the last assistant turn in the DB to match selection
  try {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/last-assistant`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: _alternatives[idx] }),
    });
  } catch (e) {
    showError(`Could not save selection: ${e.message}`);
  }

  // Keep local turns in sync
  if (_scene.turns && _scene.turns.length > 0) {
    const last = _scene.turns[_scene.turns.length - 1];
    if (last.role === "assistant") {
      _scene.turns[_scene.turns.length - 1] = { role: "assistant", content: _alternatives[idx] };
    }
  }
}

async function regenerate() {
  if (_streaming || !_lastAiDiv || !_scene) return;

  // Remove controls while streaming
  if (_regenControlsDiv) { _regenControlsDiv.remove(); _regenControlsDiv = null; }

  _lastAiDiv.classList.add("streaming");
  _lastAiDiv.innerHTML = '<span class="typing-dot"></span>';

  _streaming = true;
  setSendEnabled(false);

  let buffer = "";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...gsGetParams() }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      _lastAiDiv.innerHTML = marked.parse(buffer);
      scrollToBottom();
    }

    finalizeStreamingMessage(_lastAiDiv, buffer);

    // Add to alternatives and update local turns
    _alternatives.push(buffer);
    _altIdx = _alternatives.length - 1;

    if (_scene.turns && _scene.turns.length > 0 &&
        _scene.turns[_scene.turns.length - 1].role === "assistant") {
      _scene.turns[_scene.turns.length - 1] = { role: "assistant", content: buffer };
    }

    _renderRegenControls();

  } catch (e) {
    _lastAiDiv.classList.remove("streaming");
    _lastAiDiv.innerHTML = `<span class="error-text">Error: ${escHtml(e.message)}</span>`;
    showError(e.message);
    _renderRegenControls(); // restore the controls even on error
  } finally {
    _streaming = false;
    setSendEnabled(true);
    updateUndoButton();
    scrollToBottom();
  }
}

async function deleteScene() {
  if (!_scene) return;
  if (_scene.confirmed) {
    showError("Cannot delete a confirmed scene.");
    return;
  }
  if (!confirm("Delete this scene? This cannot be undone.")) return;

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}`, {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 204) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    window.location.href = `/campaigns/${CAMPAIGN_ID}`;
  } catch (e) {
    showError(`Delete failed: ${e.message}`);
  }
}

// ── Message rendering ─────────────────────────────────────────────────────────

function appendMessage(role, content) {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = `message-bubble ${role === "user" ? "user-bubble" : "ai-bubble"}`;
  div.style.animation = "fadeIn 0.2s ease";

  if (role === "assistant") {
    div.innerHTML = marked.parse(content);
  } else {
    // Use textContent first to safely escape HTML, then colorize in-place
    div.textContent = content;
    // Re-set as a single text node so the walker can process it
  }
  colorizeAiProse(div);
  area.appendChild(div);
  return div;
}

function appendStreamingMessage() {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = "message-bubble ai-bubble streaming";
  div.style.animation = "fadeIn 0.2s ease";
  div.innerHTML = '<span class="typing-dot"></span>';
  area.appendChild(div);
  return div;
}

function finalizeStreamingMessage(div, content) {
  div.classList.remove("streaming");
  div.innerHTML = marked.parse(content);
  colorizeAiProse(div);
}

/**
 * Walk all text nodes inside an AI bubble and wrap:
 *   "quoted speech"   → <span class="prose-dialogue">
 *   *emote text*      → <span class="prose-emote">  (if not already inside an <em>)
 * Normal narration stays unstyled (white).
 */
function colorizeAiProse(container) {
  // Process every text-bearing leaf node (skip <code>, <pre>)
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const tag = node.parentElement?.tagName?.toUpperCase();
      if (["CODE", "PRE", "SCRIPT", "STYLE"].includes(tag)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });

  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  nodes.forEach(textNode => {
    const raw = textNode.nodeValue;
    // Only process nodes that contain a quote or asterisk
    if (!raw.includes('"') && !raw.includes("*") && !raw.includes("\u2018") && !raw.includes("\u201C")) return;

    // Build a fragment replacing matches with coloured spans
    // Pattern: "quoted" → dialogue, *emote* → emote (avoid double-wrapping <em>)
    const frag = document.createDocumentFragment();
    // Combined regex: "..." or *...*
    const re = /("(?:[^"\\]|\\.)*"|\u201C[^\u201D]*\u201D|\*[^*\n]+\*)/g;
    let last = 0, m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) frag.appendChild(document.createTextNode(raw.slice(last, m.index)));
      const span = document.createElement("span");
      const isEmote = m[0].startsWith("*");
      span.className = isEmote ? "prose-emote" : "prose-dialogue";
      // Strip the surrounding * for emote (marked already handles <em> in block elements;
      // this handles inline *text* that wasn't wrapped)
      span.textContent = isEmote ? m[0].slice(1, -1) : m[0];
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    if (last < raw.length) frag.appendChild(document.createTextNode(raw.slice(last)));
    if (last > 0) textNode.replaceWith(frag);
  });
}

// ── End scene ─────────────────────────────────────────────────────────────────

function openEndScene() {
  document.getElementById("scene-summary-input").value = _scene?.proposed_summary || "";
  openModal("end-scene-modal");
}

async function suggestSummary() {
  document.getElementById("suggest-loading").style.display = "";
  document.querySelector("#end-scene-suggest-row .btn").disabled = true;
  const modelName = document.getElementById("summary-model-select").value || null;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/suggest-summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.summary) document.getElementById("scene-summary-input").value = data.summary;
  } catch (e) {
    showError(`Could not generate summary: ${e.message}`);
  } finally {
    document.getElementById("suggest-loading").style.display = "none";
    document.querySelector("#end-scene-suggest-row .btn").disabled = false;
  }
}

async function confirmEndScene() {
  const summary = document.getElementById("scene-summary-input").value.trim();
  if (!summary) {
    alert("Please write a summary before confirming.");
    return;
  }
  const confirmBtn = document.querySelector("#end-scene-modal .btn-primary");
  confirmBtn.disabled = true;
  confirmBtn.textContent = "Saving…";
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposed_summary: summary }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    closeModal("end-scene-modal");
    await loadWorldUpdateSuggestions();
  } catch (e) {
    showError(`Could not confirm scene: ${e.message}`);
    confirmBtn.disabled = false;
    confirmBtn.textContent = "✓ Confirm & Close Scene";
  }
}

// ── World update suggestions (Feature 2) ──────────────────────────────────────

let _pendingSuggestions = null;

async function loadWorldUpdateSuggestions() {
  const footer = document.getElementById("world-updates-footer");
  const body = document.getElementById("world-updates-body");
  openModal("world-updates-modal");
  body.querySelector("p").textContent = "Analysing story impact…";
  document.getElementById("wu-npc-section").classList.add("hidden");
  document.getElementById("wu-facts-section").classList.add("hidden");
  document.getElementById("wu-threads-section").classList.add("hidden");
  document.getElementById("wu-new-npcs-section").classList.add("hidden");
  document.getElementById("wu-new-locations-section").classList.add("hidden");
  document.getElementById("wu-history-section").classList.add("hidden");
  document.getElementById("wu-forms-section").classList.add("hidden");
  document.getElementById("wu-none-msg").classList.add("hidden");
  footer.style.display = "none";

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/suggest-updates`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _pendingSuggestions = await res.json();
  } catch (e) {
    body.querySelector("p").textContent = `Could not generate suggestions: ${e.message}`;
    footer.style.display = "";
    document.getElementById("wu-none-msg").classList.remove("hidden");
    _pendingSuggestions = null;
    return;
  }

  body.querySelector("p").textContent =
    "Based on what happened in this scene, the following world document updates are suggested. Uncheck any you want to skip, then click Apply.";
  footer.style.display = "";

  const { npc_updates = [], new_facts = [], thread_updates = [], new_npcs = [], new_locations = [],
          history_updates = [], form_transitions = [],
          _model, _parse_ok, _raw } = _pendingSuggestions;
  const hasAny = npc_updates.length || new_facts.length || thread_updates.length || new_npcs.length
    || new_locations.length || history_updates.length || form_transitions.length;

  if (!hasAny) {
    const noneEl = document.getElementById("wu-none-msg");
    noneEl.classList.remove("hidden");
    const modelLabel = _model ? `<strong>${escHtml(_model)}</strong>` : "the model";
    const rawHtml = _raw
      ? `<details style="margin-top:10px;text-align:left"><summary style="cursor:pointer;color:var(--text-muted);font-size:0.8rem">▶ Show raw model output (debug)</summary>` +
        `<pre style="font-size:0.75rem;white-space:pre-wrap;max-height:200px;overflow-y:auto;margin-top:6px;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px">${escHtml(_raw)}</pre></details>`
      : "";
    if (_parse_ok === false) {
      noneEl.innerHTML = `${modelLabel} did not return valid JSON. Try a different Summary Model in Campaign Settings.${rawHtml}`;
    } else {
      noneEl.innerHTML = `No updates detected by ${modelLabel}. If this is wrong, check the raw output below — the model may be incorrectly deciding nothing qualifies.${rawHtml}`;
    }
    return;
  }

  if (npc_updates.length) {
    document.getElementById("wu-npc-section").classList.remove("hidden");
    document.getElementById("wu-npc-list").innerHTML = npc_updates.map((u, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-npc-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(u.npc_name)}</strong> —
          <span class="muted">${escHtml(u.field)}</span>:
          <span class="wu-old">${escHtml(String(u.current_value))}</span> →
          <span class="wu-new">${escHtml(String(u.suggested_value))}</span>
          <div class="wu-reason muted">${escHtml(u.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (new_facts.length) {
    document.getElementById("wu-facts-section").classList.remove("hidden");
    document.getElementById("wu-facts-list").innerHTML = new_facts.map((f, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-fact-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          ${escHtml(f.content)}
          <div class="wu-reason muted">${escHtml(f.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (thread_updates.length) {
    document.getElementById("wu-threads-section").classList.remove("hidden");
    document.getElementById("wu-threads-list").innerHTML = thread_updates.map((t, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-thread-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(t.thread_title)}</strong> → mark as
          <span class="wu-new">${escHtml(t.new_status)}</span>
          <div class="wu-reason muted">${escHtml(t.reason)}</div>
        </div>
      </label>`).join("");
  }

  if (new_npcs.length) {
    document.getElementById("wu-new-npcs-section").classList.remove("hidden");
    const list = document.getElementById("wu-new-npcs-list");
    list.innerHTML = "";
    new_npcs.forEach((n, i) => list.appendChild(_buildNpcProposalCard(n, i)));
  }

  if (new_locations.length) {
    document.getElementById("wu-new-locations-section").classList.remove("hidden");
    document.getElementById("wu-new-locations-list").innerHTML = new_locations.map((l, i) => `
      <label class="wu-item wu-new-entity">
        <input type="checkbox" class="wu-new-loc-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(l.name)}</strong>
          ${l.description ? `<div class="wu-entity-detail">${escHtml(l.description)}</div>` : ""}
          <div class="wu-reason muted">${escHtml(l.significance || "")}</div>
        </div>
      </label>`).join("");
  }

  if (history_updates.length) {
    document.getElementById("wu-history-section").classList.remove("hidden");
    document.getElementById("wu-history-list").innerHTML = history_updates.map((h, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-history-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(h.npc_name)}</strong> — history update
          <div class="wu-entity-detail">${escHtml(h.new_history)}</div>
          <div class="wu-reason muted">${escHtml(h.reason || "")}</div>
        </div>
      </label>`).join("");
  }

  if (form_transitions.length) {
    document.getElementById("wu-forms-section").classList.remove("hidden");
    document.getElementById("wu-forms-list").innerHTML = form_transitions.map((t, i) => `
      <label class="wu-item">
        <input type="checkbox" class="wu-form-cb" data-index="${i}" checked>
        <div class="wu-item-text">
          <strong>${escHtml(t.npc_name)}</strong> — active form →
          <span class="wu-new">${escHtml(t.new_active_form || "(base)")}</span>
          <div class="wu-reason muted">${escHtml(t.reason || "")}</div>
        </div>
      </label>`).join("");
  }
}

function _buildNpcProposalCard(n, i) {
  const card = document.createElement("div");
  card.className = "wu-npc-proposal-card";
  card.dataset.index = i;

  // Field helper: renders a label + input or textarea
  const field = (label, key, value, multiline = false) => {
    const row = document.createElement("div");
    row.className = "wu-npc-field-row";
    const lbl = document.createElement("label");
    lbl.className = "wu-npc-field-label";
    lbl.textContent = label;
    let input;
    if (multiline) {
      input = document.createElement("textarea");
      input.rows = 2;
    } else {
      input = document.createElement("input");
      input.type = "text";
    }
    input.className = "wu-npc-field-input wb-field";
    input.dataset.field = key;
    input.value = value || "";
    row.append(lbl, input);
    return row;
  };

  // Header: name + accept/reject buttons
  const header = document.createElement("div");
  header.className = "wu-npc-proposal-header";
  const titleEl = document.createElement("div");
  titleEl.className = "wu-npc-proposal-title";
  titleEl.innerHTML = `<strong>${escHtml(n.name)}</strong>${n.role ? ` <span class="muted">— ${escHtml(n.role)}</span>` : ""}`;

  const actions = document.createElement("div");
  actions.className = "wu-npc-proposal-actions";
  const acceptBtn = document.createElement("button");
  acceptBtn.className = "btn btn-sm btn-primary";
  acceptBtn.textContent = "✓ Accept";
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "btn btn-sm btn-ghost";
  rejectBtn.textContent = "✕ Reject";
  acceptBtn.onclick = () => { card.classList.remove("rejected"); acceptBtn.classList.add("active-accept"); };
  rejectBtn.onclick = () => { card.classList.toggle("rejected"); };
  actions.append(acceptBtn, rejectBtn);
  header.append(titleEl, actions);

  // Significance note
  const sig = document.createElement("div");
  sig.className = "wu-npc-significance muted";
  sig.textContent = n.significance || "";

  // Fields grid
  const grid = document.createElement("div");
  grid.className = "wu-npc-fields-grid";
  grid.append(
    field("Name",                   "name",                   n.name),
    field("Role / Occupation",      "role",                   n.role),
    field("Gender",                 "gender",                 n.gender),
    field("Age",                    "age",                    n.age),
    field("Appearance",             "appearance",             n.appearance,             true),
    field("Personality",            "personality",            n.personality,            true),
    field("Relationship to Player", "relationship_to_player", n.relationship_to_player),
    field("Current Location",       "current_location",       n.current_location),
    field("Current State",          "current_state",          n.current_state),
    field("Short-term Goal",        "short_term_goal",        n.short_term_goal),
    field("Long-term Goal",         "long_term_goal",         n.long_term_goal),
    field("Secrets / Hidden Info",  "secrets",                n.secrets,                true),
  );

  card.append(header, sig, grid);
  return card;
}

async function applyWorldUpdates() {
  if (!_pendingSuggestions) { skipWorldUpdates(); return; }
  const applyBtn = document.querySelector("#world-updates-modal .btn-primary");
  applyBtn.disabled = true;
  applyBtn.textContent = "Applying…";

  const { npc_updates = [], new_facts = [], thread_updates = [], new_npcs = [], new_locations = [],
          history_updates = [], form_transitions = [] } = _pendingSuggestions;

  // Apply checked NPC updates
  const checkedNpcs = [...document.querySelectorAll(".wu-npc-cb:checked")].map(cb => npc_updates[+cb.dataset.index]);
  for (const u of checkedNpcs) {
    const npc = _npcs.find(n => n.id === u.npc_id);
    if (!npc) continue;
    const updated = { ...npc, [u.field]: u.suggested_value };
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }).catch(() => {});
  }

  // Apply checked new facts — append to existing facts
  const checkedFacts = [...document.querySelectorAll(".wu-fact-cb:checked")].map(cb => new_facts[+cb.dataset.index]);
  if (checkedFacts.length) {
    const existingContents = _facts.map(f => f.content);
    const allFacts = [...existingContents, ...checkedFacts.map(f => f.content)];
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/world-facts`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facts: allFacts }),
    }).catch(() => {});
  }

  // Apply checked thread status updates
  const checkedThreads = [...document.querySelectorAll(".wu-thread-cb:checked")].map(cb => thread_updates[+cb.dataset.index]);
  for (const u of checkedThreads) {
    const thread = _threads.find(t => t.id === u.thread_id)
      || (await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`).then(r => r.json()).catch(() => []))
          .find(t => t.id === u.thread_id);
    if (!thread) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/threads`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...thread, status: u.new_status }),
    }).catch(() => {});
  }

  // Create approved new NPCs — read values from editable card inputs
  const acceptedNpcCards = [...document.querySelectorAll(".wu-npc-proposal-card:not(.rejected)")];
  for (const card of acceptedNpcCards) {
    const f = (id) => card.querySelector(`[data-field="${id}"]`)?.value?.trim() || "";
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:                   f("name"),
        role:                   f("role"),
        gender:                 f("gender"),
        age:                    f("age"),
        appearance:             f("appearance"),
        personality:            f("personality"),
        relationship_to_player: f("relationship_to_player"),
        current_location:       f("current_location"),
        current_state:          f("current_state"),
        short_term_goal:        f("short_term_goal"),
        long_term_goal:         f("long_term_goal"),
        secrets:                f("secrets"),
      }),
    }).catch(() => {});
  }

  // Create approved new locations
  const checkedNewLocs = [...document.querySelectorAll(".wu-new-loc-cb:checked")].map(cb => new_locations[+cb.dataset.index]);
  for (const l of checkedNewLocs) {
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/places`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: l.name,
        description: l.description || "",
        current_state: l.current_state || "",
      }),
    }).catch(() => {});
  }

  // Apply checked history updates
  const checkedHistory = [...document.querySelectorAll(".wu-history-cb:checked")].map(cb => history_updates[+cb.dataset.index]);
  for (const h of checkedHistory) {
    const npc = _npcs.find(n => n.id === h.npc_id);
    if (!npc) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...npc, history_with_player: h.new_history }),
    }).catch(() => {});
  }

  // Apply checked form transitions
  const checkedForms = [...document.querySelectorAll(".wu-form-cb:checked")].map(cb => form_transitions[+cb.dataset.index]);
  for (const t of checkedForms) {
    const npc = _npcs.find(n => n.id === t.npc_id);
    if (!npc) continue;
    await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...npc, active_form: t.new_active_form || null }),
    }).catch(() => {});
  }

  skipWorldUpdates();
}

function skipWorldUpdates() {
  closeModal("world-updates-modal");
  window.location.href = `/campaigns/${CAMPAIGN_ID}`;
}

// ── Sidebar rendering ─────────────────────────────────────────────────────────

function renderSidebar() {
  // NPCs in scene
  const npcContainer = document.getElementById("sidebar-npcs");
  const sceneNpcIds = new Set(_scene?.npc_ids || []);
  const sceneNpcs = _npcs.filter(n => sceneNpcIds.has(n.id));
  if (sceneNpcs.length) {
    npcContainer.innerHTML = sceneNpcs.map(n => {
      const portraitHtml = n.portrait_image
        ? `<img src="${escHtml(n.portrait_image)}" class="sidebar-npc-portrait" alt="${escHtml(n.name)}" onclick="openPortraitLightbox('${escHtml(n.portrait_image)}','${escHtml(n.name)}')" title="Click to enlarge">`
        : `<div class="sidebar-npc-portrait sidebar-npc-portrait-placeholder">👤</div>`;
      return `
        <div class="sidebar-item sidebar-npc-item">
          ${portraitHtml}
          <div style="min-width:0">
            <div class="sidebar-item-name">${escHtml(n.name)}</div>
            ${n.role ? `<div class="sidebar-item-sub muted">${escHtml(n.role)}</div>` : ""}
            ${n.current_state ? `<div class="sidebar-item-sub">${escHtml(n.current_state)}</div>` : ""}
          </div>
        </div>`;
    }).join("");
  } else {
    npcContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No NPCs in this scene.</div>';
  }

  // Threads
  const threadContainer = document.getElementById("sidebar-threads");
  if (_threads.length) {
    threadContainer.innerHTML = _threads.map(t => `
      <div class="sidebar-item">
        <div class="sidebar-item-name">${escHtml(t.title)}</div>
        ${t.description ? `<div class="sidebar-item-sub muted">${escHtml(t.description.substring(0, 80))}${t.description.length > 80 ? "…" : ""}</div>` : ""}
      </div>
    `).join("");
  } else {
    threadContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No active threads.</div>';
  }

  // World facts (first 5)
  const factsContainer = document.getElementById("sidebar-facts");
  const displayFacts = _facts.slice(0, 5);
  if (displayFacts.length) {
    factsContainer.innerHTML = displayFacts.map(f => `
      <div class="sidebar-item sidebar-fact">• ${escHtml(f.content.substring(0, 100))}${f.content.length > 100 ? "…" : ""}</div>
    `).join("");
  } else {
    factsContainer.innerHTML = '<div class="muted" style="font-size:0.8rem">No world facts.</div>';
  }

  // Scene context modal
  buildContextModal();
}

function buildContextModal() {
  const body = document.getElementById("scene-context-body");
  const pc = _pc;
  const sceneNpcIds = new Set(_scene?.npc_ids || []);

  body.innerHTML = `
    ${pc ? `
      <div class="world-section">
        <h4>Player Character</h4>
        <div><strong>${escHtml(pc.name)}</strong></div>
        ${pc.personality ? `<div class="muted">${escHtml(pc.personality)}</div>` : ""}
      </div>` : ""}

    ${_scene?.intent ? `
      <div class="world-section">
        <h4>Scene Intent</h4>
        <div>${escHtml(_scene.intent)}</div>
      </div>` : ""}

    <div class="world-section">
      <h4>World Facts</h4>
      <ul style="margin:0;padding-left:20px">
        ${_facts.map(f => `<li>${escHtml(f.content)}</li>`).join("")}
      </ul>
    </div>

    ${_threads.length ? `
      <div class="world-section">
        <h4>Active Narrative Threads</h4>
        ${_threads.map(t => `
          <div style="margin-bottom:8px">
            <strong>${escHtml(t.title)}</strong>
            ${t.description ? `<div class="muted">${escHtml(t.description)}</div>` : ""}
          </div>`).join("")}
      </div>` : ""}

    ${_npcs.filter(n => sceneNpcIds.has(n.id)).length ? `
      <div class="world-section">
        <h4>NPCs in Scene</h4>
        ${_npcs.filter(n => sceneNpcIds.has(n.id)).map(n => `
          <div style="margin-bottom:8px">
            <strong>${escHtml(n.name)}</strong>${n.role ? ` — ${escHtml(n.role)}` : ""}
            ${n.personality ? `<div class="muted">${escHtml(n.personality)}</div>` : ""}
          </div>`).join("")}
      </div>` : ""}
  `;
}

// ── Dice roll bubble ──────────────────────────────────────────────────────────

function appendDiceRoll(label, rolls, mod, total) {
  const area = document.getElementById("messages-area");
  const div = document.createElement("div");
  div.className = "message-bubble dice-bubble";
  div.style.animation = "fadeIn 0.2s ease";
  const modStr = mod > 0 ? ` + ${mod}` : mod < 0 ? ` − ${Math.abs(mod)}` : "";
  const rollStr = rolls.length > 1 ? rolls.join(" + ") : rolls[0];
  div.innerHTML = `<span class="dice-label">🎲 ${escHtml(label)}</span><span class="dice-rolls">${rollStr}${modStr}</span><span class="dice-total">${total}</span>`;
  area.appendChild(div);
  scrollToBottom();
}

// ── Scene search ──────────────────────────────────────────────────────────────

function openSceneSearch() {
  document.getElementById("scene-search-input").value = "";
  document.getElementById("scene-search-results").innerHTML =
    '<div class="muted" style="font-size:0.85rem">Type to search within this scene\'s turns.</div>';
  openModal("scene-search-modal");
  setTimeout(() => document.getElementById("scene-search-input").focus(), 50);
}

function runSceneSearch() {
  const q = document.getElementById("scene-search-input").value.toLowerCase().trim();
  const container = document.getElementById("scene-search-results");
  if (q.length < 2) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">Type at least 2 characters.</div>';
    return;
  }
  const turns = _scene?.turns || [];
  const matches = [];
  turns.forEach((t, i) => {
    const pos = t.content.toLowerCase().indexOf(q);
    if (pos === -1) return;
    const start = Math.max(0, pos - 60);
    const end   = Math.min(t.content.length, pos + q.length + 60);
    matches.push({ turn: t, index: i, pos, start, end, excerpt: t.content.slice(start, end) });
  });

  if (!matches.length) {
    container.innerHTML = '<div class="muted" style="font-size:0.85rem">No matches in this scene.</div>';
    return;
  }
  container.innerHTML = "";
  matches.forEach(m => {
    const div = document.createElement("div");
    div.className = "search-result";
    const role = m.turn.role === "user" ? "Player" : "Narrator";
    const localPos = m.pos - m.start;
    const before = escHtml(m.excerpt.slice(0, localPos));
    const match  = escHtml(m.excerpt.slice(localPos, localPos + q.length));
    const after  = escHtml(m.excerpt.slice(localPos + q.length));
    div.innerHTML = `
      <div class="search-result-meta"><span class="muted">${role} · Turn ${m.index + 1}</span></div>
      <div class="search-result-excerpt">${before}<mark class="search-highlight">${match}</mark>${after}</div>
    `;
    container.appendChild(div);
  });
}

// ── Undo last turn ────────────────────────────────────────────────────────────

async function undoLastTurn() {
  if (_streaming || !_scene) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/turns/last`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    _scene = await res.json();
    _clearRegenState();
    // Re-render the messages area from the updated turn list
    const area = document.getElementById("messages-area");
    area.innerHTML = "";
    renderExistingTurns();
    updateUndoButton();
    showToast("Last exchange removed.", "info");
  } catch (e) {
    showError(`Undo failed: ${e.message}`);
  }
}

// ── Prompt preview ────────────────────────────────────────────────────────────

async function openPromptPreview() {
  if (!_scene) {
    showToast("No active scene to preview.", "info");
    return;
  }
  document.getElementById("prompt-preview-loading").style.display = "";
  document.getElementById("prompt-preview-text").style.display = "none";
  document.getElementById("prompt-preview-stats").textContent = "";
  openModal("prompt-preview-modal");
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}/prompt-preview`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    document.getElementById("prompt-preview-text").textContent = data.system_prompt;
    document.getElementById("prompt-preview-text").style.display = "";
    const chars = data.system_prompt.length;
    document.getElementById("prompt-preview-stats").textContent =
      `${chars.toLocaleString()} chars · ${data.total_messages - 2} history turns`;
  } catch (e) {
    document.getElementById("prompt-preview-loading").textContent = `Error: ${e.message}`;
  } finally {
    document.getElementById("prompt-preview-loading").style.display = "none";
  }
}

// ── Toast notifications ───────────────────────────────────────────────────────

function showToast(msg, type = "info", duration = 4000) {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  // Trigger fade-in
  requestAnimationFrame(() => toast.classList.add("toast-visible"));
  setTimeout(() => {
    toast.classList.remove("toast-visible");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  }, duration);
}

// ── Input helpers ─────────────────────────────────────────────────────────────

function setupInput() {
  const input = document.getElementById("user-input");
  if (!input) return;
  input.addEventListener("keydown", e => {
    // Enter (without Shift) sends; Ctrl/Cmd+Enter also sends
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
  });

  // Global keyboard shortcuts
  document.addEventListener("keydown", e => {
    // Esc → close topmost visible modal
    if (e.key === "Escape") {
      const modals = [...document.querySelectorAll(".modal-backdrop:not(.hidden)")];
      if (modals.length) {
        e.preventDefault();
        modals[modals.length - 1].classList.add("hidden");
      }
    }
    // / → focus chat input (when not already in a text field and chat is visible)
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = document.activeElement?.tagName;
      if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
        const chatBody = document.getElementById("chat-body");
        if (chatBody && chatBody.style.display !== "none") {
          e.preventDefault();
          input.focus();
        }
      }
    }
  });
}

function setSendEnabled(enabled) {
  document.getElementById("send-btn").disabled = !enabled;
  const continueBtn = document.getElementById("continue-btn");
  if (continueBtn) continueBtn.disabled = !enabled;
}

function scrollToBottom() {
  const area = document.getElementById("messages-area");
  area.scrollTop = area.scrollHeight;
}

function showError(msg) {
  const el = document.getElementById("error-banner");
  el.textContent = msg;
  el.style.display = "";
  setTimeout(() => { el.style.display = "none"; }, 8000);
}

// ── Modals ────────────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

// ── Quick-add NPC ─────────────────────────────────────────────────────────────

function openQuickAddNpc() {
  document.getElementById("qnpc-name").value = "";
  document.getElementById("qnpc-role").value = "";
  document.getElementById("qnpc-personality").value = "";
  document.getElementById("qnpc-state").value = "";
  document.getElementById("qnpc-add-to-scene").checked = true;
  openModal("quick-npc-modal");
  setTimeout(() => document.getElementById("qnpc-name").focus(), 50);
}

async function saveQuickNpc() {
  const name = document.getElementById("qnpc-name").value.trim();
  if (!name) {
    document.getElementById("qnpc-name").focus();
    return;
  }
  const body = {
    name,
    role: document.getElementById("qnpc-role").value.trim(),
    personality: document.getElementById("qnpc-personality").value.trim(),
    current_state: document.getElementById("qnpc-state").value.trim(),
    current_location: _scene?.location || "",
    appearance: "",
    relationship_to_player: "",
    is_alive: true,
  };

  try {
    // 1. Save NPC to world document
    const npcRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/npcs`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!npcRes.ok) throw new Error(`HTTP ${npcRes.status}`);
    const newNpc = await npcRes.json();

    // Add to local NPC list
    _npcs = [..._npcs.filter(n => n.id !== newNpc.id), newNpc];

    // 2. Optionally add to current scene's npc_ids
    const addToScene = document.getElementById("qnpc-add-to-scene").checked;
    if (addToScene && _scene) {
      const updatedIds = [...(_scene.npc_ids || []), newNpc.id];
      const sceneRes = await fetch(`/api/campaigns/${CAMPAIGN_ID}/scenes/${_scene.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ npc_ids: updatedIds }),
      });
      if (sceneRes.ok) {
        _scene = await sceneRes.json();
      }
    }

    closeModal("quick-npc-modal");
    renderSidebar();
  } catch (e) {
    showError(`Could not save NPC: ${e.message}`);
  }
}

// ── Player scratchpad ─────────────────────────────────────────────────────────

let _scratchpadTimer = null;

function loadScratchpad() {
  const notes = _campaign?.notes || "";
  const el = document.getElementById("scratchpad");
  if (!el) return;
  el.value = notes;
  el.addEventListener("input", () => {
    clearTimeout(_scratchpadTimer);
    document.getElementById("scratchpad-status").textContent = "Unsaved…";
    _scratchpadTimer = setTimeout(saveScratchpad, 1200);
  });
}

async function saveScratchpad() {
  const el = document.getElementById("scratchpad");
  const statusEl = document.getElementById("scratchpad-status");
  if (!el) return;
  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: el.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (_campaign) _campaign.notes = el.value;
    statusEl.textContent = "Saved";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  } catch (e) {
    statusEl.textContent = "Save failed";
  }
}

// ── Image generation bridge (used by campaign_imggen.js) ─────────────────────

// ── Gen-settings helpers ──────────────────────────────────────────────────────

function gsSync(key, value, decimals) {
  const lbl = document.getElementById(`gs-lbl-${key}`);
  if (lbl) lbl.textContent = decimals > 0 ? parseFloat(value).toFixed(decimals) : value;
}

function gsGetParams() {
  return {
    temperature:    parseFloat(document.getElementById("gs-temperature")?.value    ?? 0.8),
    top_p:          parseFloat(document.getElementById("gs-top_p")?.value          ?? 0.95),
    top_k:          parseInt(document.getElementById("gs-top_k")?.value            ?? 0),
    min_p:          parseFloat(document.getElementById("gs-min_p")?.value          ?? 0.05),
    repeat_penalty: parseFloat(document.getElementById("gs-repeat_penalty")?.value ?? 1.10),
    max_tokens:     parseInt(document.getElementById("gs-max_tokens")?.value       ?? 1024),
    seed:           parseInt(document.getElementById("gs-seed")?.value             ?? -1),
  };
}

function gsInitFromCampaign() {
  const gs = _campaign?.gen_settings || {};
  const defaults = { temperature:0.80, top_p:0.95, top_k:0, min_p:0.05, repeat_penalty:1.10, max_tokens:1024, seed:-1 };
  for (const [k, def] of Object.entries(defaults)) {
    const v = gs[k] ?? def;
    const el = document.getElementById(`gs-${k}`);
    if (el) { el.value = v; gsSync(k, v, ["temperature","top_p","min_p","repeat_penalty"].includes(k) ? 2 : 0); }
  }
}

function gsResetDefaults() {
  gsInitFromCampaign();
}

function openSceneImgGen() {
  if (!_scene) { showToast("No active scene.", 3000); return; }
  openImgGen("scene", { sceneId: _scene.id });
}

function openChatImgGen() {
  if (!_scene) { showToast("No active scene.", 3000); return; }
  // Find the last assistant turn in the local scene state
  const turns = _scene.turns || [];
  const lastAi = [...turns].reverse().find(t => t.role === "assistant");
  if (!lastAi) { showToast("No AI response yet to base the image on.", 3000); return; }
  openImgGen("chat", { sceneId: _scene.id, lastMessage: lastAi.content });
}

/** Called by campaign_imggen.js when the user clicks "Insert into Chat" */
function insertImgGenToChat_impl(dataUrl, prompt) {
  const area = document.getElementById("messages-area");
  if (!area) return;
  const div = document.createElement("div");
  div.className = "message-bubble ai-bubble imggen-inline";
  div.style.animation = "fadeIn 0.2s ease";

  const delBtn = document.createElement("button");
  delBtn.className = "imggen-del-btn";
  delBtn.textContent = "✕";
  delBtn.title = "Remove image";
  delBtn.onclick = () => div.remove();

  const caption = document.createElement("div");
  caption.className = "imggen-caption";
  caption.textContent = prompt;

  const img = document.createElement("img");
  img.src = dataUrl;
  img.alt = prompt;
  img.className = "imggen-inline-img";
  img.title = "Click to expand";
  img.onclick = () => img.classList.toggle("imggen-inline-img-full");

  const hint = document.createElement("div");
  hint.className = "muted";
  hint.style.cssText = "font-size:11px;margin-top:4px";
  hint.textContent = "Click image to expand · Generated by ComfyUI";

  div.appendChild(delBtn);
  div.appendChild(caption);
  div.appendChild(img);
  div.appendChild(hint);
  area.appendChild(div);
  scrollToBottom();
}

// ── Portrait lightbox ─────────────────────────────────────────────────────────

function openPortraitLightbox(src, name) {
  document.getElementById("portrait-lightbox-img").src = src;
  document.getElementById("portrait-lightbox-img").alt = name || "";
  document.getElementById("portrait-lightbox").classList.remove("hidden");
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
