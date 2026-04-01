/* chat.js — roleplay chat interface */

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ── State ─────────────────────────────────────────────────────────────────────
const SESSION_ID = window.__SESSION_ID__;   // injected by server
let session = null;
let isGenerating = false;
let memoriesExpanded = false;
let elapsedTimer = null;    // interval ID for the elapsed-time counter
let _bookmarkedTurnIds = new Set();  // set of bookmarked turn IDs for O(1) lookup
let _allTurns = [];          // lightweight turn list (id + role only) for search/regen

// ── DOM cap — maximum messages kept rendered at once ──────────────────────────
const MAX_DOM_MESSAGES = 60;
let _totalTurnCount = 0;      // total turns fetched from server (for "load earlier" label)
let _loadedOffset = 0;        // how many earlier turns have been loaded via "load earlier"

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadSession();
  await loadBookmarkedIds();
  await loadHistory();
  setupInput();
  setupSearch();
  setupSidebarCollapse();
  await refreshSidebar();
  loadRecap();
  scrollToBottom();
});

// ── Load session info ─────────────────────────────────────────────────────────
async function loadSession() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}`);
    if (!res.ok) throw new Error("Session not found");
    session = await res.json();

    // Header
    $("#session-title").textContent = session.name;
    $("#char-name").textContent = session.character_name;
    $("#model-badge").textContent = session.model_name || "default model";
    if (session.scene?.location) {
      $("#location-badge").textContent = "📍 " + session.scene.location;
    }
  } catch (err) {
    showError("Could not load session: " + err.message);
  }
}

// ── Load conversation history ─────────────────────────────────────────────────
async function loadHistory() {
  try {
    // Fetch only the most recent MAX_DOM_MESSAGES turns for initial render.
    // The server endpoint already returns newest-last within the limit.
    const res = await fetch(`/api/session/${SESSION_ID}/turns?limit=${MAX_DOM_MESSAGES}`);
    const turns = await res.json();
    _allTurns = turns.map(t => ({ id: t.id, role: t.role }));
    _totalTurnCount = session?.turn_count ?? turns.length;

    if (turns.length === 0 && session?.first_message) {
      appendMessage("assistant", session.first_message, null, false);
      return;
    }

    const area = $("#messages-area");

    // If there are more turns than we rendered, show a load-earlier button
    if (_totalTurnCount > turns.length) {
      _loadedOffset = _totalTurnCount - turns.length;
      area.insertBefore(_makeLoadEarlierBtn(), area.firstChild);
    }

    for (const t of turns) {
      appendMessage(t.role, t.content, t.timestamp, false, t.id);
    }

    attachRegenerateButton();
  } catch {
    showError("Could not load conversation history.");
  }
}

function _makeLoadEarlierBtn() {
  const btn = document.createElement("button");
  btn.id = "load-earlier-btn";
  btn.className = "btn btn-ghost btn-sm";
  btn.style.cssText = "display:block;margin:8px auto;font-size:12px";
  btn.textContent = `↑ Load earlier messages`;
  btn.onclick = loadEarlierMessages;
  return btn;
}

async function loadEarlierMessages() {
  const btn = $("#load-earlier-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
  try {
    const batchSize = 20;
    const newOffset = Math.max(0, _loadedOffset - batchSize);
    const fetchCount = _loadedOffset - newOffset;
    const res = await fetch(`/api/session/${SESSION_ID}/turns?limit=${fetchCount}&offset=${newOffset}`);
    const turns = await res.json();
    if (!turns.length) { if (btn) btn.remove(); return; }

    const area = $("#messages-area");
    const anchor = btn ? btn.nextSibling : area.firstChild;

    // Insert older messages before the current oldest, preserving scroll position
    const scrollBefore = area.scrollHeight - area.scrollTop;
    const frag = document.createDocumentFragment();
    for (const t of turns) {
      const div = _buildMessageDiv(t.role, t.content, t.timestamp, false, t.id);
      frag.appendChild(div);
    }
    area.insertBefore(frag, anchor);
    area.scrollTop = area.scrollHeight - scrollBefore;  // keep viewport stable

    _loadedOffset = newOffset;
    if (btn) {
      if (_loadedOffset <= 0) {
        btn.remove();
      } else {
        btn.disabled = false;
        btn.textContent = `↑ Load earlier messages`;
      }
    }

    // Trim DOM from the bottom if we've grown past the cap
    _trimDomMessages();
  } catch {
    if (btn) { btn.disabled = false; btn.textContent = `↑ Load earlier messages`; }
  }
}

function _trimDomMessages() {
  const messages = $$(".message");
  if (messages.length <= MAX_DOM_MESSAGES) return;
  const excess = messages.length - MAX_DOM_MESSAGES;
  for (let i = messages.length - 1; i >= messages.length - excess; i--) {
    messages[i].remove();
  }
  // Ensure "load earlier" footer exists to reload the trimmed tail
  const area = $("#messages-area");
  if (!$("#load-more-btn")) {
    const btn2 = document.createElement("button");
    btn2.id = "load-more-btn";
    btn2.className = "btn btn-ghost btn-sm";
    btn2.style.cssText = "display:block;margin:8px auto;font-size:12px";
    btn2.textContent = "↓ Load more recent messages";
    btn2.onclick = () => window.location.reload();
    area.appendChild(btn2);
  }
}

// ── Input handling ────────────────────────────────────────────────────────────
function setupInput() {
  const input = $("#message-input");
  const sendBtn = $("#send-btn");

  // Auto-resize textarea
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  // Enter sends; Shift+Enter inserts newline
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);
  input.focus();
}

// ── Send message ──────────────────────────────────────────────────────────────
async function sendMessage() {
  if (isGenerating) return;
  const input = $("#message-input");
  const text = input.value.trim();
  if (!text) return;

  // Display user message immediately (no turnId yet — assigned by server)
  appendMessage("user", text);
  input.value = "";
  removeRegenerateButton();
  input.style.height = "auto";

  // Show typing indicator
  isGenerating = true;
  setInputEnabled(false);
  showTyping(true);
  scrollToBottom();

  try {
    const res = await fetch(`/api/session/${SESSION_ID}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    if (!res.ok) {
      let detail = `Server error ${res.status}`;
      try {
        const errBody = await res.json();
        detail = errBody.detail || detail;
      } catch {
        detail = await res.text().catch(() => detail);
      }
      throw new Error(detail);
    }

    showTyping(false);

    // Create the assistant message bubble immediately and stream into it
    const bubble = appendStreamingMessage();
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";
    let scrollPending = false;

    const scheduleScroll = () => {
      if (!scrollPending) {
        scrollPending = true;
        requestAnimationFrame(() => { scrollToBottom(); scrollPending = false; });
      }
    };

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();  // keep incomplete line for next chunk

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = JSON.parse(line.slice(6));

        if (payload.error) {
          throw new Error(payload.error);
        }

        if (payload.token !== undefined) {
          fullText += payload.token;
          appendToStreamingMessage(bubble, payload.token);
          scheduleScroll();
        }

        if (payload.done) {
          if (!fullText) {
            throw new Error("The model returned an empty response. Check that Ollama is running and the model is available.");
          }
          // Update sidebar with state captured before background extraction
          if (payload.scene) updateScene(payload.scene);
          updateMemoryCount(payload.memory_count ?? null);
          if (payload.scene?.location) {
            $("#location-badge").textContent = "📍 " + payload.scene.location;
          }
          finalizeStreamingMessage(bubble);
          hideError();
          // Reload turns to get server-assigned IDs then attach regenerate button
          reloadTurnsQuietly();
          scheduleBackgroundRefresh();
          break outer;
        }
      }
    }

  } catch (err) {
    showTyping(false);
    console.error("Chat error:", err);
    showError(err.message);
  } finally {
    isGenerating = false;
    setInputEnabled(true);
    stopElapsedTimer();
    $("#message-input").focus();
    scrollToBottom();
  }
}

// ── Message rendering ─────────────────────────────────────────────────────────
function _buildMessageDiv(role, content, timestamp = null, animate = false, turnId = null) {
  const isAssistant = role === "assistant";
  const avatar = isAssistant
    ? (session?.character_name?.[0] ?? "?").toUpperCase()
    : "You";
  const time = timestamp
    ? new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const isBookmarked = turnId && _bookmarkedTurnIds.has(turnId);
  const starIcon = isBookmarked ? "★" : "☆";
  const starClass = isBookmarked ? "bookmarked" : "";

  const div = document.createElement("div");
  div.className = `message ${role}`;
  if (turnId) div.dataset.turnId = turnId;
  if (animate) div.style.animation = "fadeIn 0.2s ease";
  div.innerHTML = `
    <div class="msg-avatar">${esc(avatar)}</div>
    <div style="flex:1;min-width:0">
      <div class="msg-bubble">${esc(content)}</div>
      <div class="msg-meta">
        <span>${time}</span>
        <span class="msg-actions">
          ${turnId ? `<button class="msg-action-btn bookmark-btn ${starClass}" title="Bookmark this moment" onclick="toggleBookmark('${turnId}', this)">${starIcon}</button>` : ""}
        </span>
      </div>
    </div>`;
  return div;
}

function appendMessage(role, content, timestamp = null, animate = true, turnId = null) {
  const div = _buildMessageDiv(role, content, timestamp, animate, turnId);
  $("#messages-area").appendChild(div);
  return div;
}

// ── Streaming message helpers ─────────────────────────────────────────────────
function appendStreamingMessage() {
  const area = $("#messages-area");
  const avatar = (session?.character_name?.[0] ?? "?").toUpperCase();
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const div = document.createElement("div");
  div.className = "message assistant";
  div.style.animation = "fadeIn 0.2s ease";
  div.innerHTML = `
    <div class="msg-avatar">${esc(avatar)}</div>
    <div>
      <div class="msg-bubble"></div>
      <div class="msg-meta">${time}</div>
    </div>`;
  area.appendChild(div);
  return div.querySelector(".msg-bubble");
}

function appendToStreamingMessage(bubble, token) {
  bubble.appendChild(document.createTextNode(token));
}

function finalizeStreamingMessage(bubble) {
  // Text nodes are already in place — nothing extra needed.
}

// ── Typing indicator ──────────────────────────────────────────────────────────
function showTyping(show) {
  const indicator = $("#typing-indicator");
  indicator.style.display = show ? "flex" : "none";
  if (show) {
    startElapsedTimer();
    scrollToBottom();
  } else {
    stopElapsedTimer();
  }
}

function startElapsedTimer() {
  const label = $("#char-name-typing");
  const charName = session?.character_name || "AI";
  let seconds = 0;
  stopElapsedTimer();
  elapsedTimer = setInterval(() => {
    seconds++;
    if (label) label.textContent = `${charName} is thinking… ${seconds}s`;
  }, 1000);
  if (label) label.textContent = `${charName} is thinking…`;
}

function stopElapsedTimer() {
  if (elapsedTimer !== null) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// ── Background extraction polling ─────────────────────────────────────────────
function scheduleBackgroundRefresh() {
  // Poll twice: once after a short delay (fast models) and once later (slow models)
  setTimeout(() => refreshSidebar(), 5000);
  setTimeout(() => refreshSidebar(), 15000);
}

// Auto-refresh sidebar every 30 seconds when idle.
// Background extraction already fires targeted refreshes at 5s and 15s after each turn,
// so this interval is just a safety net to catch anything that was missed.
setInterval(() => {
  if (!isGenerating) {
    refreshMemories();
    refreshRelationships();
    refreshWorldState();
    refreshObjectives();
  }
}, 30000);

// ── Scene sidebar ─────────────────────────────────────────────────────────────
async function refreshSidebar() {
  await Promise.allSettled([
    refreshScene(),
    refreshMemories(),
    refreshRelationships(),
    refreshWorldState(),
    refreshObjectives(),
    refreshClock(),
    refreshStatusEffects(),
    refreshEmotionalState(),
  ]);
}

async function refreshScene() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/scene`);
    updateScene(await res.json());
  } catch {}
}

async function refreshStatusEffects() {
  try {
    const effects = await fetch(`/api/session/${SESSION_ID}/status-effects`).then(r => r.json());
    const container = $("#scene-status-effects");
    const item = $("#status-effects-item");
    if (!container || !item) return;
    if (!effects.length) { item.style.display = "none"; return; }
    item.style.display = "";
    const icon = { buff: "✦", debuff: "✖", neutral: "◆" };
    const cls = { buff: "effect-chip-buff", debuff: "effect-chip-debuff", neutral: "" };
    container.innerHTML = effects.map(e =>
      `<span class="effect-chip ${cls[e.effect_type] || ""}" title="${esc(e.description)}">${icon[e.effect_type] || "◆"} ${esc(e.name)}</span>`
    ).join(" ");
  } catch {}
}

async function refreshEmotionalState() {
  try {
    const state = await fetch(`/api/session/${SESSION_ID}/emotional-state`).then(r => r.json());
    const el = $("#scene-mood");
    const item = $("#mood-item");
    if (!el || !item) return;
    if (state.mood === "neutral" && !state.motivation) { item.style.display = "none"; return; }
    item.style.display = "";
    const parts = [`mood: ${state.mood}`];
    if (state.stress > 0.2) parts.push(`stress: ${state.stress_label}`);
    if (state.motivation) parts.push(`motivation: ${state.motivation}`);
    el.textContent = parts.join(" · ");
  } catch {}
}

async function refreshClock() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/clock`);
    const clock = await res.json();
    const el = $("#scene-clock");
    const item = $("#clock-item");
    if (el && item) {
      el.textContent = clock.display || "";
      item.style.display = clock.display ? "" : "none";
    }
  } catch {}
}

function updateScene(scene) {
  $("#scene-location").textContent = scene.location || "Unknown";

  const charsEl = $("#scene-chars");
  if (scene.active_characters?.length) {
    charsEl.innerHTML = scene.active_characters
      .map(c => `<span class="char-chip">${esc(c)}</span>`)
      .join("");
  } else {
    charsEl.innerHTML = `<span class="dim">None listed</span>`;
  }

  const summaryEl = $("#scene-summary");
  summaryEl.textContent = scene.summary || "(no summary yet)";
}

// Location edit
$("#scene-location").addEventListener &&
document.addEventListener("DOMContentLoaded", () => {
  const saveBtn = $("#save-location-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const input = $("#location-edit-input");
      const newLocation = input.value.trim();
      if (!newLocation) return;
      try {
        await fetch(`/api/session/${SESSION_ID}/scene`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ location: newLocation }),
        });
        await refreshScene();
        $("#location-badge").textContent = "📍 " + newLocation;
        input.value = "";
      } catch {}
    });
  }
});

// ── Memory sidebar ────────────────────────────────────────────────────────────
let lastMemoryCount = 0;

async function refreshMemories() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/memories`);
    const memories = await res.json();
    lastMemoryCount = memories.length;
    updateMemoryCount(memories.length);
    renderMemoryList(memories);
  } catch {}
}

function updateMemoryCount(count) {
  if (count !== null) {
    $("#memory-count").textContent = count;
  }
}

function renderMemoryList(memories) {
  const list = $("#memory-list");
  if (!memories.length) {
    list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No memories stored yet</div>`;
    return;
  }

  list.innerHTML = memories.slice(0, 20).map(m => {
    const typeClass = m.type === "rumor" ? "rumor"
                    : m.importance === "critical" ? "critical"
                    : m.importance === "high" ? "high"
                    : "";
    const uncertain = ["rumor", "suspicion", "lie", "myth"].includes(m.certainty);
    const certBadge = uncertain ? ` <span class="badge">${esc(m.certainty)}</span>` : "";
    const conf = uncertain ? ` · ${Math.round(m.confidence * 100)}% confidence` : "";
    return `
      <div class="memory-item ${typeClass}">
        <div class="memory-item-title">${esc(m.title)}${certBadge}</div>
        <div class="memory-item-content">${esc(m.content)}</div>
        <div class="memory-item-meta">
          <span class="badge">${m.type}</span>
          <span class="badge ${impClass(m.importance)}">${m.importance}</span>
          <span class="dim">${conf}${m.location ? " · " + m.location : ""}</span>
        </div>
      </div>`;
  }).join("");

  if (memories.length > 20) {
    list.innerHTML += `<div class="dim" style="font-size:12px;text-align:center;padding:6px">+${memories.length - 20} more</div>`;
  }
}

function impClass(imp) {
  return imp === "critical" ? "red" : imp === "high" ? "yellow" : "";
}

// ── Relationship sidebar ──────────────────────────────────────────────────────
async function refreshRelationships() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/relationships`);
    updateRelationships(await res.json());
  } catch {}
}

function updateRelationships(rels) {
  const container = $("#rels-container");
  if (!rels.length) {
    container.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No relationships tracked yet</div>`;
    return;
  }

  container.innerHTML = rels.map(r => {
    const axes = [
      { name: "Trust",     val: r.trust,     symmetric: true  },
      { name: "Affection", val: r.affection,  symmetric: true  },
      { name: "Respect",   val: r.respect,    symmetric: true  },
      { name: "Fear",      val: r.fear,       symmetric: false },
      { name: "Hostility", val: r.hostility,  symmetric: false },
    ].filter(a => Math.abs(a.val) > 0.05);

    if (!axes.length) return "";

    const axesHtml = axes.map(a => {
      if (a.symmetric) {
        const pct = Math.abs(a.val) * 50;
        const isPos = a.val >= 0;
        const barClass = isPos ? "pos" : "neg";
        const barHtml = isPos
          ? `<div class="rel-bar pos" style="width:${pct}%"></div>`
          : `<div class="rel-bar neg" style="width:${pct}%"></div>`;
        return `
          <span class="rel-axis-name">${a.name}</span>
          <div class="rel-bar-wrap">${barHtml}</div>`;
      } else {
        const pct = a.val * 100;
        return `
          <span class="rel-axis-name">${a.name}</span>
          <div class="rel-bar-wrap"><div class="rel-bar pos" style="width:${pct}%"></div></div>`;
      }
    }).join("");

    const summaryBadge = r.summary && r.summary !== "neutral"
      ? `<span class="badge" style="font-size:10px;margin-left:6px;opacity:0.8">${esc(r.summary)}</span>`
      : "";

    return `
      <div class="rel-item">
        <div class="rel-header">
          <span class="rel-from">${esc(r.source)}</span>
          <span class="rel-arrow">→</span>
          <span class="rel-to">${esc(r.target)}</span>
          ${summaryBadge}
        </div>
        <div class="rel-axes">${axesHtml}</div>
      </div>`;
  }).join("");
}

// ── World-state sidebar ───────────────────────────────────────────────────────
async function refreshWorldState() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/world-state`);
    renderWorldStateList(await res.json());
  } catch {}
}

function renderWorldStateList(entries) {
  const list = $("#world-state-list");
  if (!entries.length) {
    list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No world state tracked yet</div>`;
    return;
  }

  list.innerHTML = entries.map(e => {
    const isCritical = e.importance === "critical";
    const critClass = isCritical ? " critical" : "";
    const critBadge = isCritical ? ` <span class="badge red" style="font-size:10px">critical</span>` : "";
    return `
      <div class="world-state-item${critClass}">
        <div class="world-state-item-title">${esc(e.title)}${critBadge}</div>
        <div class="world-state-item-content">${esc(e.content)}</div>
        <div class="world-state-item-meta">
          <span class="badge">${esc(e.category)}</span>
          ${e.entities?.length ? `<span class="dim">${esc(e.entities.join(", "))}</span>` : ""}
        </div>
      </div>`;
  }).join("");
}

// ── Regenerate ────────────────────────────────────────────────────────────────
function attachRegenerateButton() {
  removeRegenerateButton();
  const messages = $$(".message.assistant");
  if (!messages.length) return;
  const last = messages[messages.length - 1];
  const meta = last.querySelector(".msg-meta");
  if (!meta) return;

  const lastUserMsg = $$(".message.user");
  const userText = lastUserMsg.length ? lastUserMsg[lastUserMsg.length - 1].querySelector(".msg-bubble")?.textContent : "";

  const btn = document.createElement("button");
  btn.className = "msg-action-btn regen-btn";
  btn.id = "regen-btn";
  btn.title = "Regenerate response";
  btn.textContent = "↺ Regenerate";
  btn.onclick = () => regenerateResponse(userText);
  meta.querySelector(".msg-actions")?.appendChild(btn);
}

function removeRegenerateButton() {
  const btn = document.getElementById("regen-btn");
  if (btn) btn.remove();
}

async function regenerateResponse(originalMessage) {
  if (isGenerating || !originalMessage) return;

  // Delete last exchange from server
  try {
    await fetch(`/api/session/${SESSION_ID}/turns/last`, { method: "DELETE" });
  } catch (e) {
    showError("Could not delete last turn: " + e.message);
    return;
  }

  // Remove last assistant + user bubbles from DOM
  const msgs = $$(".message");
  for (let i = msgs.length - 1; i >= 0; i--) {
    msgs[i].remove();
    if (msgs[i].classList.contains("user")) break;
  }

  // Re-send the original message via streaming
  removeRegenerateButton();
  appendMessage("user", originalMessage);
  isGenerating = true;
  setInputEnabled(false);
  showTyping(true);
  scrollToBottom();

  try {
    const res = await fetch(`/api/session/${SESSION_ID}/chat/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: originalMessage }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    showTyping(false);
    const bubble = appendStreamingMessage();
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", fullText = "";
    let scrollPending2 = false;
    const scheduleScroll2 = () => {
      if (!scrollPending2) {
        scrollPending2 = true;
        requestAnimationFrame(() => { scrollToBottom(); scrollPending2 = false; });
      }
    };

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = JSON.parse(line.slice(6));
        if (payload.error) throw new Error(payload.error);
        if (payload.token !== undefined) { fullText += payload.token; appendToStreamingMessage(bubble, payload.token); scheduleScroll2(); }
        if (payload.done) { finalizeStreamingMessage(bubble); reloadTurnsQuietly(); scheduleBackgroundRefresh(); break outer; }
      }
    }
  } catch (err) {
    showTyping(false);
    showError(err.message);
  } finally {
    isGenerating = false;
    setInputEnabled(true);
    stopElapsedTimer();
    $("#message-input").focus();
  }
}

async function reloadTurnsQuietly() {
  try {
    // Fetch only the last few turns — enough to update IDs and attach regen button.
    // We do NOT reload the full history; that would re-grow with every turn.
    const res = await fetch(`/api/session/${SESSION_ID}/turns?limit=10`);
    const recent = await res.json();
    // Merge into _allTurns (lightweight id+role list) without duplicates
    const existingIds = new Set(_allTurns.map(t => t.id));
    for (const t of recent) {
      if (!existingIds.has(t.id)) {
        _allTurns.push({ id: t.id, role: t.role });
        existingIds.add(t.id);
      }
    }
    _totalTurnCount = (_totalTurnCount || 0) + 1;
    // Stamp turn IDs onto the DOM messages that don't have them yet
    // (the two most recent messages: the user one we just appended and the assistant streaming bubble)
    const untagged = $$(".message:not([data-turn-id])");
    const freshByRole = { user: null, assistant: null };
    for (const t of [...recent].reverse()) {
      if (!freshByRole[t.role]) freshByRole[t.role] = t;
    }
    for (const el of [...untagged].reverse()) {
      const role = el.classList.contains("assistant") ? "assistant" : "user";
      if (freshByRole[role] && !el.dataset.turnId) {
        el.dataset.turnId = freshByRole[role].id;
        freshByRole[role] = null;
        // Add bookmark button now that we have the turn ID
        const meta = el.querySelector(".msg-meta");
        if (meta && !el.querySelector(".bookmark-btn")) {
          const tid = el.dataset.turnId;
          const span = document.createElement("span");
          span.className = "msg-actions";
          span.innerHTML = `<button class="msg-action-btn bookmark-btn" title="Bookmark this moment" onclick="toggleBookmark('${tid}', this)">☆</button>`;
          meta.appendChild(span);
        }
      }
    }
    attachRegenerateButton();
  } catch {}
}

// ── Bookmarks ─────────────────────────────────────────────────────────────────
async function loadBookmarkedIds() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/bookmarks`);
    const bookmarks = await res.json();
    _bookmarkedTurnIds = new Set(bookmarks.map(b => b.turn_id));
  } catch {}
}

async function toggleBookmark(turnId, btn) {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/turns/${turnId}/bookmark`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: "" }),
    });
    const data = await res.json();
    if (data.removed) {
      _bookmarkedTurnIds.delete(turnId);
      btn.textContent = "☆";
      btn.classList.remove("bookmarked");
    } else {
      _bookmarkedTurnIds.add(turnId);
      btn.textContent = "★";
      btn.classList.add("bookmarked");
    }
  } catch {}
}

// ── Recap banner ──────────────────────────────────────────────────────────────
async function loadRecap() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/recap`);
    const data = await res.json();
    if (!data.recap) return;
    const banner = document.createElement("div");
    banner.className = "recap-banner";
    banner.innerHTML = `
      <span class="recap-label">Previously…</span>
      <span class="recap-text">${esc(data.recap)}</span>
      <button class="recap-dismiss" onclick="this.closest('.recap-banner').remove()">✕</button>`;
    const area = $("#messages-area");
    area.insertBefore(banner, area.firstChild);
  } catch {}
}

// ── Search ────────────────────────────────────────────────────────────────────
function setupSearch() {
  const toggleBtn = $("#search-toggle-btn");
  const bar = $("#search-bar");
  const input = $("#search-input");
  const clearBtn = $("#search-clear-btn");

  if (!toggleBtn) return;

  toggleBtn.addEventListener("click", () => {
    const hidden = bar.classList.toggle("hidden");
    if (!hidden) { input.focus(); }
    else { clearSearch(); }
  });

  clearBtn.addEventListener("click", clearSearch);

  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (!q) { clearSearch(); return; }
    runSearch(q);
  });

  input.addEventListener("keydown", e => {
    if (e.key === "Escape") { bar.classList.add("hidden"); clearSearch(); }
  });
}

async function runSearch(query) {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/turns/search?q=${encodeURIComponent(query)}`);
    const turns = await res.json();
    const count = $("#search-count");
    if (count) count.textContent = `${turns.length} result${turns.length !== 1 ? "s" : ""}`;

    // Highlight matching messages
    $$(".message").forEach(el => el.classList.remove("search-match", "search-no-match"));
    if (!turns.length) { $$(".message").forEach(el => el.classList.add("search-no-match")); return; }

    const matchIds = new Set(turns.map(t => t.id));
    $$(".message[data-turn-id]").forEach(el => {
      const match = matchIds.has(el.dataset.turnId);
      el.classList.toggle("search-match", match);
      el.classList.toggle("search-no-match", !match);
    });

    // Scroll to first match
    const first = $(".message.search-match");
    if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch {}
}

function clearSearch() {
  $("#search-input").value = "";
  const count = $("#search-count");
  if (count) count.textContent = "";
  $$(".message").forEach(el => el.classList.remove("search-match", "search-no-match"));
}

// ── Objectives sidebar ────────────────────────────────────────────────────────
async function refreshObjectives() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/objectives`);
    renderObjectivesList(await res.json());
  } catch {}
}

function renderObjectivesList(objectives) {
  const container = $("#objectives-list");
  if (!container) return;
  const active = objectives.filter(o => o.status === "active");
  if (!active.length) {
    container.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No active objectives</div>`;
    return;
  }
  container.innerHTML = active.map(o => `
    <div class="objective-item" data-id="${o.id}">
      <span class="objective-title">${esc(o.title)}</span>
      <div class="objective-actions">
        <button class="msg-action-btn" title="Mark complete" onclick="markObjective('${o.id}','completed',this)">✓</button>
        <button class="msg-action-btn" title="Mark failed" onclick="markObjective('${o.id}','failed',this)">✗</button>
      </div>
    </div>`).join("");
}

async function markObjective(id, status, btn) {
  try {
    await fetch(`/api/session/${SESSION_ID}/objectives/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await refreshObjectives();
  } catch {}
}

async function addObjective() {
  const input = $("#new-objective-input");
  const title = input?.value.trim();
  if (!title) return;
  try {
    await fetch(`/api/session/${SESSION_ID}/objectives`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    input.value = "";
    await refreshObjectives();
  } catch {}
}

// ── Collapsible sidebar sections ──────────────────────────────────────────────
function setupSidebarCollapse() {
  $$(".sidebar-section-header").forEach(header => {
    header.addEventListener("click", () => {
      header.closest(".sidebar-section").classList.toggle("collapsed");
    });
  });

  // Refresh memory list button
  const refreshBtn = $("#refresh-memories-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", refreshMemories);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function scrollToBottom() {
  const area = $("#messages-area");
  requestAnimationFrame(() => { area.scrollTop = area.scrollHeight; });
}

function setInputEnabled(enabled) {
  $("#message-input").disabled = !enabled;
  $("#send-btn").disabled = !enabled;
  if (enabled) {
    $("#send-btn").textContent = "Send";
  } else {
    $("#send-btn").innerHTML = `<div class="spinner" style="width:16px;height:16px;border-width:2px"></div>`;
  }
}

function showError(msg) {
  const banner = $("#error-banner");
  // Persistent — stays until dismissed. User must click ✕ or a successful reply hides it.
  banner.innerHTML = `<span style="flex:1">⚠ ${esc(msg)}</span>
    <button onclick="hideError()" style="background:none;border:none;color:inherit;cursor:pointer;font-size:16px;padding:0 0 0 12px;line-height:1">✕</button>`;
  banner.style.display = "flex";
  console.error("RP Utility error:", msg);
}

function hideError() {
  const banner = $("#error-banner");
  if (banner) banner.style.display = "none";
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
