/* chat.js — roleplay chat interface */

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

/* chat.js — roleplay chat interface */

// ── Template variable resolution ─────────────────────────────────────────────
function resolveVars(text) {
  if (!text) return text;
  const charName = session?.character_name ?? "Character";
  const userName = _getPersona().name || "Player";
  return text
    .replace(/\{\{char\}\}/gi, charName)
    .replace(/\{\{user\}\}/gi, userName);
}

// ── Configure marked.js ───────────────────────────────────────────────────────
if (typeof marked !== "undefined") {
  marked.setOptions({ breaks: true, gfm: true });
}
function renderMarkdown(text) {
  if (typeof marked === "undefined") return escHtml(text);
  try { return marked.parse(text); } catch { return escHtml(text); }
}
function escHtml(t) {
  return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── State ─────────────────────────────────────────────────────────────────────
const SESSION_ID = window.__SESSION_ID__;   // injected by server
let session = null;
let isGenerating = false;
let memoriesExpanded = false;
let elapsedTimer = null;    // interval ID for the elapsed-time counter
let _bookmarkedTurnIds = new Set();  // set of bookmarked turn IDs for O(1) lookup
let _allTurns = [];          // lightweight turn list (id + role only) for search/regen
let _charAvatarUrl = null;  // card image URL for the AI character

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
  applyStoredBackground();
  loadGenSettings();
  loadPersona();
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

    // Try to load the character's card image (PNG cards carry one)
    if (session.character_name) {
      try {
        const imgRes = await fetch(`/api/cards/${encodeURIComponent(session.character_name)}/image`);
        if (imgRes.ok) {
          const blob = await imgRes.blob();
          _charAvatarUrl = URL.createObjectURL(blob);
        }
      } catch { /* no image — use letter fallback */ }
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
      body: JSON.stringify({ message: text, user_name: _getPersona().name || "Player", ..._getGenParams() }),
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
          finalizeStreamingMessage(bubble, fullText);
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
function _buildAvatarEl(role) {
  const el = document.createElement("div");
  el.className = "msg-avatar";
  if (role === "assistant" && _charAvatarUrl) {
    const img = document.createElement("img");
    img.src = _charAvatarUrl;
    img.alt = session?.character_name ?? "Character";
    el.appendChild(img);
  } else if (role === "user") {
    const persona = _getPersona();
    if (persona.avatarDataUrl) {
      const img = document.createElement("img");
      img.src = persona.avatarDataUrl;
      img.alt = persona.name || "You";
      el.appendChild(img);
    } else {
      el.textContent = (persona.name?.[0] ?? "Y").toUpperCase();
    }
  } else {
    el.textContent = (session?.character_name?.[0] ?? "?").toUpperCase();
  }
  return el;
}

function _buildMessageDiv(role, content, timestamp = null, animate = false, turnId = null) {
  const isAssistant = role === "assistant";
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

  const avatarEl = _buildAvatarEl(role);

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.dataset.rawText = content;
  if (isAssistant) {
    bubble.innerHTML = renderMarkdown(resolveVars(content));
    bubble.classList.add("md-content");
  } else {
    bubble.textContent = resolveVars(content);
  }

  const metaEl = document.createElement("div");
  metaEl.className = "msg-meta";
  metaEl.innerHTML = `<span>${time}</span><span class="msg-actions">${
    turnId ? `<button class="msg-action-btn bookmark-btn ${starClass}" title="Bookmark this moment" onclick="toggleBookmark('${esc(turnId)}', this)">${starIcon}</button>` : ""
  }${
    turnId ? `<button class="msg-action-btn edit-turn-btn" title="Edit this message" onclick="openTurnEditor('${esc(turnId)}', this)">✏</button>` : ""
  }</span>`;

  const inner = document.createElement("div");
  inner.style.cssText = "flex:1;min-width:0";
  inner.appendChild(bubble);
  inner.appendChild(metaEl);

  div.appendChild(avatarEl);
  div.appendChild(inner);
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
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const div = document.createElement("div");
  div.className = "message assistant";
  div.style.animation = "fadeIn 0.2s ease";

  div.appendChild(_buildAvatarEl("assistant"));

  const inner = document.createElement("div");
  inner.style.cssText = "flex:1;min-width:0";   // must match _buildMessageDiv
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = time;
  inner.appendChild(bubble);
  inner.appendChild(meta);
  div.appendChild(inner);

  area.appendChild(div);
  return bubble;
}

function appendToStreamingMessage(bubble, token) {
  bubble.appendChild(document.createTextNode(token));
}

function finalizeStreamingMessage(bubble, fullText) {
  // Convert accumulated plain text to rendered markdown
  if (fullText && typeof marked !== "undefined") {
    bubble.innerHTML = renderMarkdown(resolveVars(fullText));
    bubble.classList.add("md-content");
  }
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
    refreshObjectives();
    refreshSidebarInventory();
    refreshSidebarEffects();
    refreshSidebarQuests();
  }
}, 30000);

// ── Scene sidebar ─────────────────────────────────────────────────────────────
async function refreshSidebar() {
  await Promise.allSettled([
    refreshScene(),
    refreshObjectives(),
    refreshClock(),
    refreshEmotionalState(),
    refreshSidebarInventory(),
    refreshSidebarEffects(),
    refreshSidebarQuests(),
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
    const el = $("#memory-count");
    if (el) el.textContent = count;
  }
}

async function deleteMemory(memoryId) {
  if (!confirm("Delete this memory? The AI will no longer know this fact.")) return;
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/memories/${memoryId}`, { method: "DELETE" });
    if (!res.ok) throw new Error();
    const el = document.getElementById(`mem-${memoryId}`);
    if (el) el.remove();
    const count = parseInt($("#memory-count")?.textContent || "0") - 1;
    updateMemoryCount(Math.max(0, count));
  } catch {
    showError("Failed to delete memory.");
  }
}

async function addCorrection() {
  const input = $("#correction-input");
  const text = input.value.trim();
  if (!text) return;

  // Derive a short title from the first ~60 chars
  const title = text.length > 60 ? text.slice(0, 57) + "…" : text;

  try {
    const res = await fetch(`/api/session/${SESSION_ID}/memories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: "Correction: " + title,
        content: text,
        type: "world_fact",
        importance: "critical",
        certainty: "confirmed",
      }),
    });
    if (!res.ok) throw new Error();
    input.value = "";
    await refreshMemories();
  } catch {
    showError("Failed to save correction.");
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
      <div class="memory-item ${typeClass}" id="mem-${esc(m.id)}">
        <div class="memory-item-header">
          <div class="memory-item-title">${esc(m.title)}${certBadge}</div>
          <button class="mem-delete-btn" title="Delete this memory" onclick="deleteMemory('${esc(m.id)}')">✕</button>
        </div>
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

// ── Inventory sidebar ─────────────────────────────────────────────────────────
async function refreshSidebarInventory() {
  const list = $("#sidebar-inventory-list");
  if (!list) return;
  try {
    const items = await fetch(`/api/session/${SESSION_ID}/inventory`).then(r => r.json());
    if (!items.length) {
      list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No items in inventory</div>`;
      return;
    }
    list.innerHTML = items.map(item => {
      const equipped = item.is_equipped ? ` <span class="badge" style="background:var(--accent-dim)">equipped</span>` : "";
      const qty = item.quantity > 1 ? ` ×${item.quantity}` : "";
      const condBad = item.condition && item.condition !== "good"
        ? ` <span class="badge" style="background:#7f1d1d;color:#fca5a5">${esc(item.condition)}</span>` : "";
      const desc = item.description ? `<div class="sidebar-item-desc">${esc(item.description)}</div>` : "";
      return `<div class="sidebar-inv-item">
        <div class="sidebar-inv-name">${esc(item.name)}${qty}${equipped}${condBad}</div>
        ${desc}
      </div>`;
    }).join("");
  } catch {
    list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">—</div>`;
  }
}

// ── Status effects sidebar ────────────────────────────────────────────────────
async function refreshSidebarEffects() {
  const list = $("#sidebar-effects-list");
  if (!list) return;
  try {
    const effects = await fetch(`/api/session/${SESSION_ID}/status-effects`).then(r => r.json());
    if (!effects.length) {
      list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No active effects</div>`;
      // Also clear the compact scene chips
      const chips = $("#scene-status-effects");
      const item = $("#status-effects-item");
      if (chips) chips.innerHTML = "";
      if (item) item.style.display = "none";
      return;
    }
    const icon = { buff: "✦", debuff: "✖", neutral: "◆" };
    const typeColor = { buff: "#4ade80", debuff: "#f87171", neutral: "var(--text-muted)" };
    list.innerHTML = effects.map(e => {
      const dur = e.duration_turns > 0 ? `<span class="dim"> · ${e.duration_turns} turn${e.duration_turns !== 1 ? "s" : ""} left</span>` : "";
      const desc = e.description ? `<div class="sidebar-item-desc">${esc(e.description)}</div>` : "";
      return `<div class="sidebar-effect-item">
        <div class="sidebar-effect-name" style="color:${typeColor[e.effect_type] || "var(--text)"}">
          ${icon[e.effect_type] || "◆"} ${esc(e.name)}${dur}
        </div>
        <div class="sidebar-effect-meta"><span class="badge">${esc(e.effect_type)}</span> <span class="dim">${esc(e.severity)}</span></div>
        ${desc}
      </div>`;
    }).join("");
    // Also update the compact scene chips
    const chips = $("#scene-status-effects");
    const item = $("#status-effects-item");
    if (chips && item) {
      const cls = { buff: "effect-chip-buff", debuff: "effect-chip-debuff", neutral: "" };
      chips.innerHTML = effects.map(e =>
        `<span class="effect-chip ${cls[e.effect_type] || ""}" title="${esc(e.description)}">${icon[e.effect_type] || "◆"} ${esc(e.name)}</span>`
      ).join(" ");
      item.style.display = "";
    }
  } catch {
    list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">—</div>`;
  }
}

// ── Quest log sidebar ─────────────────────────────────────────────────────────
async function refreshSidebarQuests() {
  const list = $("#sidebar-quests-list");
  if (!list) return;
  try {
    const quests = await fetch(`/api/session/${SESSION_ID}/quests`).then(r => r.json());
    const active = quests.filter(q => q.status === "active");
    if (!active.length) {
      list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">No active quests</div>`;
      return;
    }
    list.innerHTML = active.map(q => {
      const giver = q.giver_npc_name ? `<span class="dim"> · from ${esc(q.giver_npc_name)}</span>` : "";
      const stages = q.stages?.length ? `<div class="quest-stages">${
        q.stages.map(s => `<div class="quest-stage ${s.completed ? "done" : ""}">
          <span class="quest-check">${s.completed ? "✓" : "○"}</span>
          <span>${esc(s.description)}</span>
        </div>`).join("")
      }</div>` : "";
      const desc = q.description ? `<div class="sidebar-item-desc">${esc(q.description)}</div>` : "";
      return `<div class="sidebar-quest-item">
        <div class="sidebar-quest-name">${esc(q.title)}${giver}</div>
        ${desc}${stages}
      </div>`;
    }).join("");
  } catch {
    list.innerHTML = `<div class="dim" style="font-size:12px;text-align:center;padding:8px">—</div>`;
  }
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
      body: JSON.stringify({ message: originalMessage, user_name: _getPersona().name || "Player" }),
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
        if (payload.done) { finalizeStreamingMessage(bubble, fullText); reloadTurnsQuietly(); scheduleBackgroundRefresh(); break outer; }
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

// ── Turn edit / delete ────────────────────────────────────────────────────────
function openTurnEditor(turnId, btn) {
  // Find the bubble sibling of the clicked button
  const msgDiv = btn.closest(".message");
  if (!msgDiv) return;
  const bubble = msgDiv.querySelector(".msg-bubble");
  if (!bubble) return;

  // Don't open a second editor on the same turn
  if (msgDiv.querySelector(".turn-edit-form")) return;

  const originalText = bubble.dataset.rawText || bubble.textContent;
  const role = msgDiv.classList.contains("assistant") ? "assistant" : "user";

  const form = document.createElement("div");
  form.className = "turn-edit-form";
  form.innerHTML = `
    <textarea class="turn-edit-textarea">${esc(originalText)}</textarea>
    <div class="turn-edit-actions">
      <button class="btn btn-secondary btn-sm" onclick="saveTurnEdit('${esc(turnId)}', this)">Save</button>
      <button class="btn btn-ghost btn-sm" onclick="cancelTurnEdit(this)">Cancel</button>
      <button class="btn btn-danger btn-sm" onclick="deleteTurn('${esc(turnId)}', this)" style="margin-left:auto">Delete</button>
    </div>`;
  bubble.after(form);
  form.querySelector("textarea").focus();
}

function cancelTurnEdit(btn) {
  btn.closest(".turn-edit-form").remove();
}

async function saveTurnEdit(turnId, btn) {
  const form = btn.closest(".turn-edit-form");
  const textarea = form.querySelector("textarea");
  const newContent = textarea.value.trim();
  if (!newContent) return;

  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/turns/${turnId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newContent }),
    });
    if (!res.ok) throw new Error("Save failed");
    // Update the bubble in-place
    const msgDiv = form.closest(".message");
    const bubble = msgDiv.querySelector(".msg-bubble");
    const role = msgDiv.classList.contains("assistant") ? "assistant" : "user";
    bubble.dataset.rawText = newContent;
    if (role === "assistant") {
      bubble.innerHTML = renderMarkdown(resolveVars(newContent));
    } else {
      bubble.textContent = resolveVars(newContent);
    }
    form.remove();
  } catch {
    btn.disabled = false;
    btn.textContent = "Save";
    showError("Failed to save turn.");
  }
}

async function deleteTurn(turnId, btn) {
  if (!confirm("Delete this message? This cannot be undone.")) return;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/turns/${turnId}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Delete failed");
    const msgDiv = btn.closest(".message");
    msgDiv.remove();
  } catch {
    btn.disabled = false;
    showError("Failed to delete turn.");
  }
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

// ══════════════════════════════════════════════════════════════════════════════
// PERSONA
// ══════════════════════════════════════════════════════════════════════════════

const PERSONA_KEY = "rp_persona";

function _getPersona() {
  try { return JSON.parse(localStorage.getItem(PERSONA_KEY)) || {}; } catch { return {}; }
}

function loadPersona() {
  const p = _getPersona();
  const nameEl = document.getElementById("persona-name-input");
  if (nameEl && p.name) nameEl.value = p.name;
  _renderPersonaPreview(p.avatarDataUrl);
}

function _renderPersonaPreview(dataUrl) {
  const el = document.getElementById("persona-avatar-preview");
  if (!el) return;
  if (dataUrl) {
    el.innerHTML = `<img src="${dataUrl}" style="width:100%;height:100%;object-fit:cover;border-radius:50%">`;
  } else {
    const p = _getPersona();
    el.textContent = (p.name || "Y")[0].toUpperCase();
    el.innerHTML = ""; // reset
    el.textContent = (p.name || "Y")[0].toUpperCase();
  }
}

function handlePersonaAvatarFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => _renderPersonaPreview(e.target.result);
  reader.readAsDataURL(file);
}

function clearPersonaAvatar() {
  const fi = document.getElementById("persona-avatar-file");
  if (fi) fi.value = "";
  _renderPersonaPreview(null);
}

function savePersona() {
  const nameEl = document.getElementById("persona-name-input");
  const name = nameEl ? nameEl.value.trim() || "Player" : "Player";
  const fileInput = document.getElementById("persona-avatar-file");
  const existing = _getPersona();

  function persist(dataUrl) {
    localStorage.setItem(PERSONA_KEY, JSON.stringify({ name, avatarDataUrl: dataUrl || null }));
    closeModal("persona-modal");
  }

  if (fileInput && fileInput.files[0]) {
    const reader = new FileReader();
    reader.onload = e => persist(e.target.result);
    reader.readAsDataURL(fileInput.files[0]);
  } else {
    persist(existing.avatarDataUrl || null);
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// GENERATION SETTINGS
// ══════════════════════════════════════════════════════════════════════════════

const GEN_SETTINGS_KEY = "rp_gen_settings_" + SESSION_ID;
const GEN_DEFAULTS = {
  temperature: 0.80, top_p: 0.95, top_k: 0, min_p: 0.05,
  repeat_penalty: 1.10, max_tokens: 1024, seed: -1,
};
const COMFY_DEFAULTS = {
  comfyui_url: "http://localhost:8188", checkpoint: "",
  steps: 20, cfg: 7.0,
};

function _getGenSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(GEN_SETTINGS_KEY)) || {};
    return { ...GEN_DEFAULTS, ...saved };
  } catch { return { ...GEN_DEFAULTS }; }
}

function _getComfySettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(GEN_SETTINGS_KEY)) || {};
    return { ...COMFY_DEFAULTS, ...(saved.comfy || {}) };
  } catch { return { ...COMFY_DEFAULTS }; }
}

function _getGenParams() {
  const s = _getGenSettings();
  const params = {};
  params.temperature    = s.temperature;
  params.top_p          = s.top_p;
  params.max_tokens     = s.max_tokens;
  if (s.top_k > 0)            params.top_k          = s.top_k;
  if (s.min_p > 0)            params.min_p          = s.min_p;
  if (s.repeat_penalty !== 1) params.repeat_penalty  = s.repeat_penalty;
  if (s.seed >= 0)            params.seed            = s.seed;
  return params;
}

function syncLabel(key, value, decimals) {
  const el = document.getElementById("lbl-" + key);
  if (el) el.textContent = parseFloat(value).toFixed(decimals);
}

function syncLabelDirect(id, value) {
  const el = document.getElementById("lbl-" + id);
  if (el) {
    const v = parseFloat(value);
    el.textContent = Number.isInteger(v) ? String(v) : v.toFixed(1);
  }
}

function loadGenSettings() {
  const s = _getGenSettings();
  const pairs = [
    ["temperature", 2], ["top_p", 2], ["top_k", 0],
    ["min_p", 2], ["repeat_penalty", 2], ["max_tokens", 0], ["seed", 0],
  ];
  for (const [key, dec] of pairs) {
    const slider = document.getElementById("sl-" + key);
    if (slider) {
      slider.value = s[key];
      syncLabel(key, s[key], dec);
    }
  }
  const c = _getComfySettings();
  const urlEl = document.getElementById("comfyui-url-input");
  if (urlEl) urlEl.value = c.comfyui_url;
  const ckEl = document.getElementById("comfyui-checkpoint-input");
  if (ckEl) ckEl.value = c.checkpoint;
  const stepsEl = document.getElementById("sl-comfy-steps");
  if (stepsEl) { stepsEl.value = c.steps; syncLabelDirect("comfy-steps", c.steps); }
  const cfgEl = document.getElementById("sl-comfy-cfg");
  if (cfgEl) { cfgEl.value = c.cfg; syncLabelDirect("comfy-cfg", c.cfg); }
}

function saveGenSettings() {
  const v = id => parseFloat(document.getElementById("sl-" + id).value);
  const settings = {
    temperature:    v("temperature"),
    top_p:          v("top_p"),
    top_k:          v("top_k"),
    min_p:          v("min_p"),
    repeat_penalty: v("repeat_penalty"),
    max_tokens:     v("max_tokens"),
    seed:           v("seed"),
    comfy: {
      comfyui_url: document.getElementById("comfyui-url-input").value || "http://localhost:8188",
      checkpoint:  document.getElementById("comfyui-checkpoint-input").value || "",
      steps:       v("comfy-steps"),
      cfg:         v("comfy-cfg"),
    },
  };
  localStorage.setItem(GEN_SETTINGS_KEY, JSON.stringify(settings));
  closeModal("gen-settings-modal");
}

function resetGenSettings() {
  localStorage.removeItem(GEN_SETTINGS_KEY);
  loadGenSettings();
}

async function fetchComfyCheckpoints() {
  const urlEl = document.getElementById("comfyui-url-input");
  const url = (urlEl ? urlEl.value : "") || "http://localhost:8188";
  const listEl = document.getElementById("comfyui-checkpoint-list");
  if (listEl) listEl.textContent = "Fetching…";
  try {
    const res = await fetch("/api/comfyui/checkpoints?comfyui_url=" + encodeURIComponent(url));
    const data = await res.json();
    if (data.checkpoints && data.checkpoints.length) {
      if (listEl) listEl.innerHTML = data.checkpoints.map(c =>
        "<a href='#' style='display:block;padding:2px 0' onclick=\"document.getElementById('comfyui-checkpoint-input').value='" +
        c.replace(/'/g, "\\'") + "';return false\">" + esc(c) + "</a>"
      ).join("");
    } else {
      if (listEl) listEl.textContent = "No checkpoints found.";
    }
  } catch {
    if (listEl) listEl.textContent = "Could not reach ComfyUI.";
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// CHAT BACKGROUND
// ══════════════════════════════════════════════════════════════════════════════

const BG_KEY = "rp_bg_" + SESSION_ID;
const BG_OVERLAY_KEY = "rp_bg_overlay_" + SESSION_ID;

function applyStoredBackground() {
  const bg = localStorage.getItem(BG_KEY);
  const overlay = parseFloat(localStorage.getItem(BG_OVERLAY_KEY) || "0.5");
  if (bg) _applyBackground(bg, overlay);
  const slider = document.getElementById("bg-overlay-slider");
  if (slider) {
    slider.value = overlay;
    const label = document.getElementById("bg-overlay-label");
    if (label) label.textContent = overlay.toFixed(2);
  }
}

function _applyBackground(value, overlay) {
  const area = document.getElementById("messages-area");
  if (!area) return;
  if (value.startsWith("linear-gradient") || value.startsWith("#")) {
    area.style.backgroundImage = "";
    area.style.background = value;
  } else {
    area.style.background = "";
    area.style.backgroundImage = "url('" + value + "')";
    area.style.backgroundSize = "cover";
    area.style.backgroundPosition = "center";
  }
  area.style.setProperty("--bg-overlay-opacity", String(overlay));
  area.classList.add("has-custom-bg");
}

function handleBgFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {
    const overlay = parseFloat(document.getElementById("bg-overlay-slider").value || "0.5");
    localStorage.setItem(BG_KEY, e.target.result);
    _applyBackground(e.target.result, overlay);
  };
  reader.readAsDataURL(file);
}

function applyBgUrl() {
  const url = (document.getElementById("bg-url-input") || {}).value;
  if (!url || !url.trim()) return;
  const overlay = parseFloat((document.getElementById("bg-overlay-slider") || {}).value || "0.5");
  localStorage.setItem(BG_KEY, url.trim());
  _applyBackground(url.trim(), overlay);
}

function applyBgGradient(gradient) {
  const overlay = parseFloat((document.getElementById("bg-overlay-slider") || {}).value || "0.5");
  localStorage.setItem(BG_KEY, gradient);
  _applyBackground(gradient, overlay);
}

function applyBgOverlay(value) {
  const v = parseFloat(value);
  localStorage.setItem(BG_OVERLAY_KEY, String(v));
  const label = document.getElementById("bg-overlay-label");
  if (label) label.textContent = v.toFixed(2);
  const area = document.getElementById("messages-area");
  if (area) area.style.setProperty("--bg-overlay-opacity", String(v));
}

function clearBackground() {
  localStorage.removeItem(BG_KEY);
  localStorage.removeItem(BG_OVERLAY_KEY);
  const area = document.getElementById("messages-area");
  if (area) {
    area.style.background = "";
    area.style.backgroundImage = "";
    area.classList.remove("has-custom-bg");
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// COMFYUI IMAGE GENERATION
// ══════════════════════════════════════════════════════════════════════════════

function openImageGenDialog() {
  // Clear status; let user hit "Generate Prompt" when ready
  const statusEl = document.getElementById("gen-prompt-status");
  if (statusEl) statusEl.textContent = "";
  openModal("img-gen-modal");
}

async function generateImagePrompt() {
  const btn = document.getElementById("gen-prompt-btn");
  const statusEl = document.getElementById("gen-prompt-status");
  const promptEl = document.getElementById("img-gen-prompt");
  if (btn) { btn.disabled = true; btn.textContent = "Generating…"; }
  if (statusEl) statusEl.textContent = "Analysing scene, memories and characters…";
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/image-prompt`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Server error" }));
      throw new Error(err.detail || "Server error " + res.status);
    }
    const data = await res.json();
    if (promptEl) promptEl.value = data.prompt || "";
    if (statusEl) statusEl.textContent = "Prompt generated — edit as needed.";
  } catch (err) {
    if (statusEl) statusEl.textContent = "Error: " + err.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "✨ Generate Prompt"; }
  }
}

async function submitImageGen() {
  const promptEl = document.getElementById("img-gen-prompt");
  const basePrompt = promptEl ? promptEl.value.trim() : "";
  if (!basePrompt) { alert("Please enter a prompt or click ✨ Generate Prompt."); return; }

  // Inject selected style tags
  const styleInput = document.querySelector('input[name="img-style"]:checked');
  const styleTags = styleInput ? styleInput.value.trim() : "";
  const prompt = styleTags ? `${basePrompt}, ${styleTags}` : basePrompt;

  const btn = document.getElementById("img-gen-submit-btn");
  const statusEl = document.getElementById("img-gen-status");
  if (btn) { btn.disabled = true; btn.textContent = "Generating\u2026"; }
  if (statusEl) statusEl.textContent = "Sending to ComfyUI\u2026 this may take a minute.";

  const comfy = _getComfySettings();
  const widthEl  = document.getElementById("img-gen-width");
  const heightEl = document.getElementById("img-gen-height");
  const negEl    = document.getElementById("img-gen-negative");
  const width  = parseInt((widthEl  || {}).value || "512");
  const height = parseInt((heightEl || {}).value || "512");

  try {
    const res = await fetch("/api/comfyui/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        negative_prompt: (negEl || {}).value || "",
        width, height,
        steps: comfy.steps,
        cfg: comfy.cfg,
        checkpoint: comfy.checkpoint,
        comfyui_url: comfy.comfyui_url,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(function() { return { detail: "Unknown error" }; });
      throw new Error(err.detail || "Server error " + res.status);
    }

    const data = await res.json();
    closeModal("img-gen-modal");
    _insertGeneratedImage(data.data_url, prompt);
    if (promptEl) promptEl.value = "";
    if (statusEl) statusEl.textContent = "";
  } catch (err) {
    if (statusEl) statusEl.textContent = "Error: " + err.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Generate"; }
  }
}

function _insertGeneratedImage(dataUrl, prompt) {
  const area = document.getElementById("messages-area");
  if (!area) return;

  const div = document.createElement("div");
  div.className = "message assistant";
  div.style.animation = "fadeIn 0.2s ease";

  const avatarEl = _buildAvatarEl("assistant");

  const inner = document.createElement("div");
  inner.style.cssText = "flex:1;min-width:0";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble generated-image-bubble";

  // Delete button
  const delBtn = document.createElement("button");
  delBtn.className = "img-delete-btn";
  delBtn.title = "Remove image";
  delBtn.textContent = "✕";
  delBtn.onclick = function() { div.remove(); };

  const caption = document.createElement("div");
  caption.className = "gen-image-prompt";
  caption.textContent = prompt;

  const img = document.createElement("img");
  img.src = dataUrl;
  img.alt = prompt;
  img.className = "gen-image";
  img.title = "Click to expand";
  img.onclick = function() { this.classList.toggle("gen-image-fullscreen"); };

  const hint = document.createElement("div");
  hint.style.cssText = "font-size:11px;color:var(--text-dim);margin-top:6px";
  hint.textContent = "Click image to expand \u00b7 Generated by ComfyUI";

  bubble.appendChild(delBtn);
  bubble.appendChild(caption);
  bubble.appendChild(img);
  bubble.appendChild(hint);
  inner.appendChild(bubble);
  div.appendChild(avatarEl);
  div.appendChild(inner);
  area.appendChild(div);
  scrollToBottom();
}



// ══════════════════════════════════════════════════════════════════════════════
// MODAL HELPERS
// ══════════════════════════════════════════════════════════════════════════════

function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = "flex";
  if (id === "gen-settings-modal") loadGenSettings();
  if (id === "persona-modal") loadPersona();
  if (id === "bg-modal") applyStoredBackground();
  if (id === "skill-check-modal") loadSkillCheckStats();
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function backdropClose(event, id) {
  if (event.target === event.currentTarget) closeModal(id);
}

// ── Skill Checks ──────────────────────────────────────────────────────────────
async function loadSkillCheckStats() {
  const sel = document.getElementById("skill-check-stat");
  if (!sel) return;
  try {
    const stats = await fetch(`/api/session/${SESSION_ID}/stats`).then(r => r.json());
    // Reset options
    sel.innerHTML = `<option value="">— free roll (no modifier) —</option>`;
    for (const s of stats) {
      const mod = s.modifier >= 0 ? `+${s.modifier}` : s.modifier;
      sel.add(new Option(`${s.name} (${mod})`, s.name));
    }
  } catch {}
  // Clear previous result
  const resultEl = document.getElementById("skill-check-result");
  if (resultEl) resultEl.style.display = "none";
}

async function rollSkillCheck() {
  const statName = document.getElementById("skill-check-stat").value;
  const dc = parseInt(document.getElementById("skill-check-dc").value) || 15;
  const dice = document.getElementById("skill-check-dice").value.trim() || "d20";
  const context = document.getElementById("skill-check-context").value.trim();

  const resultEl = document.getElementById("skill-check-result");
  resultEl.style.display = "none";

  try {
    const res = await fetch(`/api/session/${SESSION_ID}/stats/roll`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stat_name: statName || "free", difficulty: dc, dice, narrative_context: context }),
    });
    if (!res.ok) throw new Error("Roll failed");
    const r = await res.json();

    const outcomeColors = {
      critical_success: "#4ade80",
      success: "#86efac",
      failure: "#fca5a5",
      critical_failure: "#f87171",
    };
    const color = outcomeColors[r.outcome] || "var(--text)";
    const modStr = r.modifier !== 0 ? ` ${r.modifier >= 0 ? "+" : ""}${r.modifier}` : "";
    const label = r.outcome.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

    resultEl.innerHTML = `
      <div class="skill-check-result-card">
        <div class="skill-check-outcome" style="color:${color}">${label}</div>
        <div class="skill-check-roll-detail">
          Rolled <strong>${r.roll}</strong>${modStr} = <strong>${r.total}</strong> vs DC <strong>${dc}</strong>
          ${statName ? `<span class="dim"> (${esc(statName)})</span>` : ""}
        </div>
        ${context ? `<div class="dim" style="font-size:12px;margin-top:4px">${esc(context)}</div>` : ""}
      </div>`;
    resultEl.style.display = "block";
  } catch {
    resultEl.innerHTML = `<div class="dim">Roll failed. Make sure the server is running.</div>`;
    resultEl.style.display = "block";
  }
}
