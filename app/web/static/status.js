/* status.js — session status / inspection page */

const $ = (sel, ctx = document) => ctx.querySelector(sel);

const SESSION_ID = window.__SESSION_ID__;

// Raw data cache for client-side filtering
let _allMemories = [];
let _allRelationships = [];

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => refreshAll());

async function refreshAll() {
  await Promise.allSettled([
    loadSession(),
    loadScene(),
    loadRelationships(),
    loadWorldState(),
    loadMemories(),
    loadContradictions(),
    loadArchived(),
    loadObjectives(),
    loadBookmarks(),
    loadNpcs(),
    loadLocations(),
    loadStoryBeats(),
    loadEmotionalState(),
    loadInventory(),
    loadStatusEffects(),
    loadStats(),
    loadSkillChecks(),
    loadNarrativeArc(),
    loadFactions(),
    loadQuests(),
    loadJournal(),
    loadLoreNotes(),
  ]);
}

// ── Session overview ──────────────────────────────────────────────────────────
async function loadSession() {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}`);
    const s = await res.json();
    $("#session-title").textContent = s.name;
    $("#session-sub").innerHTML =
      `<span>${esc(s.character_name)}</span>` +
      `<span class="badge" style="margin-left:8px">${esc(s.model_name || "default model")}</span>` +
      (s.lorebook_name ? `<span class="dim" style="margin-left:8px">📖 ${esc(s.lorebook_name)}</span>` : "");
    setStat("stat-turns", s.turn_count);
  } catch {
    $("#session-title").textContent = "Session";
  }
}

// ── Scene ─────────────────────────────────────────────────────────────────────
async function loadScene() {
  try {
    const scene = await fetch(`/api/session/${SESSION_ID}/scene`).then(r => r.json());
    const chars = scene.active_characters?.length
      ? scene.active_characters.map(c => `<span class="char-chip">${esc(c)}</span>`).join("")
      : `<span class="dim">None listed</span>`;

    const updated = scene.last_updated
      ? new Date(scene.last_updated).toLocaleString()
      : "—";

    $("#scene-body").innerHTML = `
      <div class="status-detail-grid">
        <div class="detail-item">
          <div class="detail-label">Location</div>
          <div class="detail-value">${esc(scene.location || "Unknown")}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Present Characters</div>
          <div class="detail-value chars-list">${chars}</div>
        </div>
        <div class="detail-item detail-item-full">
          <div class="detail-label">Scene Summary</div>
          <div class="detail-value dim">${esc(scene.summary || "(no summary yet)")}</div>
        </div>
        <div class="detail-item">
          <div class="detail-label">Last Updated</div>
          <div class="detail-value dim" style="font-size:12px">${updated}</div>
        </div>
      </div>`;
  } catch {
    $("#scene-body").innerHTML = `<div class="dim">Could not load scene.</div>`;
  }
}

// ── Relationships ─────────────────────────────────────────────────────────────
async function loadRelationships() {
  try {
    const rels = await fetch(`/api/session/${SESSION_ID}/relationships`).then(r => r.json());
    _allRelationships = rels;
    setStat("stat-relationships", rels.length);

    // Populate character filter with all unique names, sorted
    const names = [...new Set(rels.flatMap(r => [r.source, r.target]))].sort();
    const select = $("#filter-rel-character");
    const current = select.value;
    // Preserve any existing selection across refreshes
    select.innerHTML = `<option value="">All characters</option>` +
      names.map(n => `<option value="${esc(n)}"${n === current ? " selected" : ""}>${esc(n)}</option>`).join("");

    applyRelFilters();
  } catch {
    $("#rels-body").innerHTML = `<div class="dim">Could not load relationships.</div>`;
  }
}

function applyRelFilters() {
  const char = $("#filter-rel-character").value;
  const role = $("#filter-rel-role").value;

  let filtered = _allRelationships;
  if (char) {
    if (role === "source") {
      filtered = filtered.filter(r => r.source === char);
    } else if (role === "target") {
      filtered = filtered.filter(r => r.target === char);
    } else {
      filtered = filtered.filter(r => r.source === char || r.target === char);
    }
  }

  const total = _allRelationships.length;
  $("#rels-filter-count").textContent = filtered.length < total ? `${filtered.length} of ${total}` : `${total} total`;

  if (!filtered.length) {
    $("#rels-body").innerHTML = `<div class="dim">No relationships match the current filter.</div>`;
    return;
  }

  $("#rels-body").innerHTML = filtered.map(r => renderRelCard(r)).join("");
}

function renderRelCard(r) {
  const axes = [
    { name: "Trust",     val: r.trust,     symmetric: true  },
    { name: "Affection", val: r.affection,  symmetric: true  },
    { name: "Respect",   val: r.respect,    symmetric: true  },
    { name: "Fear",      val: r.fear,       symmetric: false },
    { name: "Hostility", val: r.hostility,  symmetric: false },
  ];

  const axesHtml = axes.map(a => {
    const numLabel = a.symmetric ? `${a.val >= 0 ? "+" : ""}${a.val.toFixed(2)}` : a.val.toFixed(2);
    let barHtml;
    if (a.symmetric) {
      const pct = Math.abs(a.val) * 50;
      const cls = a.val >= 0 ? "pos" : "neg";
      barHtml = `<div class="sbar-wrap">
        <div class="sbar-centre"></div>
        <div class="sbar-fill ${cls}" style="width:${pct}%;${a.val < 0 ? "right:50%" : "left:50%"}"></div>
      </div>`;
    } else {
      const pct = a.val * 100;
      barHtml = `<div class="sbar-wrap">
        <div class="sbar-fill pos" style="width:${pct}%;left:0"></div>
      </div>`;
    }
    return `
      <div class="rel-axis-row">
        <span class="rel-axis-name">${a.name}</span>
        ${barHtml}
        <span class="rel-axis-num ${a.val > 0.3 ? "pos-text" : a.val < -0.3 ? "neg-text" : "dim"}">${numLabel}</span>
      </div>`;
  }).join("");

  const summaryClass = summaryToClass(r.summary);
  return `
    <div class="rel-card">
      <div class="rel-card-header">
        <span class="rel-entity-from">${esc(r.source)}</span>
        <span class="rel-arrow">→</span>
        <span class="rel-entity-to">${esc(r.target)}</span>
        <span class="badge ${summaryClass}" style="margin-left:auto">${esc(r.summary || "neutral")}</span>
      </div>
      <div class="rel-axes-full">${axesHtml}</div>
    </div>`;
}

function summaryToClass(s) {
  if (!s || s === "neutral") return "";
  if (["enemy", "hostile"].includes(s)) return "red";
  if (["close ally", "loyal", "ally"].includes(s)) return "green";
  if (["fearful", "wary", "suspicious", "deeply distrustful"].includes(s)) return "yellow";
  return "";
}

// ── World State ───────────────────────────────────────────────────────────────
async function loadWorldState() {
  try {
    const entries = await fetch(`/api/session/${SESSION_ID}/world-state`).then(r => r.json());
    setStat("stat-world-state", entries.length);
    if (!entries.length) {
      $("#ws-body").innerHTML = `<div class="dim">No world state tracked yet.</div>`;
      return;
    }

    // Group by category
    const groups = {};
    for (const e of entries) {
      (groups[e.category] = groups[e.category] || []).push(e);
    }

    $("#ws-body").innerHTML = Object.entries(groups).map(([cat, items]) => `
      <div class="ws-group">
        <div class="ws-group-label">${esc(cat)}</div>
        ${items.map(e => {
          const isCrit = e.importance === "critical";
          return `
            <div class="ws-entry${isCrit ? " ws-entry-critical" : ""}">
              <div class="ws-entry-header">
                <span class="ws-entry-title">${esc(e.title)}</span>
                ${isCrit ? `<span class="badge red">critical</span>` : `<span class="badge ${impBadge(e.importance)}">${e.importance}</span>`}
              </div>
              <div class="ws-entry-content">${esc(e.content)}</div>
              ${e.entities?.length ? `<div class="ws-entry-meta">Entities: ${esc(e.entities.join(", "))}</div>` : ""}
              <div class="ws-entry-meta dim">Updated: ${new Date(e.updated_at).toLocaleString()}</div>
            </div>`;
        }).join("")}
      </div>`).join("");
  } catch {
    $("#ws-body").innerHTML = `<div class="dim">Could not load world state.</div>`;
  }
}

// ── Active Memories ───────────────────────────────────────────────────────────
async function loadMemories() {
  try {
    const mems = await fetch(`/api/session/${SESSION_ID}/memories`).then(r => r.json());
    _allMemories = mems;
    setStat("stat-memories", mems.length);
    renderMemories(mems);
  } catch {
    $("#mem-body").innerHTML = `<div class="dim">Could not load memories.</div>`;
  }
}

function applyMemoryFilters() {
  const type = $("#filter-type").value;
  const importance = $("#filter-importance").value;
  const certainty = $("#filter-certainty").value;
  let filtered = _allMemories;
  if (type)       filtered = filtered.filter(m => m.type === type);
  if (importance) filtered = filtered.filter(m => m.importance === importance);
  if (certainty)  filtered = filtered.filter(m => m.certainty === certainty);
  renderMemories(filtered);
}

function renderMemories(mems) {
  const count = mems.length;
  const total = _allMemories.length;
  $("#mem-filter-count").textContent = count < total ? `${count} of ${total}` : `${total} total`;

  if (!mems.length) {
    $("#mem-body").innerHTML = `<div class="dim" style="padding:12px">No memories match the current filters.</div>`;
    return;
  }

  $("#mem-body").innerHTML = mems.map(m => {
    const certUncertain = ["rumor", "suspicion", "lie", "myth"].includes(m.certainty);
    const certBadge = certUncertain ? `<span class="badge yellow">${esc(m.certainty)}</span>` : "";
    const confPct = Math.round(m.confidence * 100);
    const confClass = m.confidence >= 0.8 ? "pos-text" : m.confidence >= 0.5 ? "" : "neg-text";
    const created = new Date(m.created_at).toLocaleString();
    const referenced = m.last_referenced_at
      ? new Date(m.last_referenced_at).toLocaleDateString()
      : "never";

    return `
      <div class="mem-card ${memBorderClass(m)}">
        <div class="mem-card-header">
          <span class="mem-card-title">${esc(m.title)}</span>
          <div class="mem-card-badges">
            <span class="badge">${esc(m.type.replace("_", " "))}</span>
            <span class="badge ${impBadge(m.importance)}">${m.importance}</span>
            ${certBadge}
          </div>
        </div>
        <div class="mem-card-content">${esc(m.content)}</div>
        <div class="mem-card-meta">
          ${m.entities?.length ? `<span>👤 ${esc(m.entities.join(", "))}</span>` : ""}
          ${m.location ? `<span>📍 ${esc(m.location)}</span>` : ""}
          ${m.tags?.length ? `<span>🏷 ${esc(m.tags.join(", "))}</span>` : ""}
          <span class="${confClass}">confidence: ${confPct}%</span>
          <span class="dim">referenced: ${referenced}</span>
          <span class="dim">${created}</span>
        </div>
      </div>`;
  }).join("");
}

function memBorderClass(m) {
  if (m.importance === "critical") return "mem-critical";
  if (m.importance === "high") return "mem-high";
  if (m.certainty === "lie") return "mem-lie";
  if (["rumor", "suspicion", "myth"].includes(m.certainty)) return "mem-uncertain";
  return "";
}

// ── Contradiction Flags ───────────────────────────────────────────────────────
async function loadContradictions() {
  try {
    const flags = await fetch(`/api/session/${SESSION_ID}/contradictions`).then(r => r.json());
    setStat("stat-contradictions", flags.length);
    if (!flags.length) {
      $("#contra-body").innerHTML = `<div class="dim">No contradictions detected.</div>`;
      return;
    }

    $("#contra-body").innerHTML = flags.map(f => `
      <div class="contra-card" id="contra-${esc(f.id)}">
        <div class="contra-header">
          <span class="badge yellow">contradiction</span>
          <span class="dim">${new Date(f.detected_at).toLocaleString()}</span>
        </div>
        <div class="contra-description">${esc(f.description)}</div>
        <div class="contra-resolve-actions">
          <span class="dim" style="font-size:11px">Resolve:</span>
          <button class="btn btn-sm btn-secondary" onclick="resolveContradiction('${esc(f.id)}','keep_new')">Keep new</button>
          <button class="btn btn-sm btn-secondary" onclick="resolveContradiction('${esc(f.id)}','keep_old')">Keep old</button>
          <button class="btn btn-sm btn-ghost" onclick="resolveContradiction('${esc(f.id)}','dismiss')">Dismiss</button>
        </div>
      </div>`).join("");
  } catch {
    $("#contra-body").innerHTML = `<div class="dim">Could not load contradiction flags.</div>`;
  }
}

async function resolveContradiction(flagId, action) {
  try {
    const res = await fetch(`/api/session/${SESSION_ID}/contradictions/${flagId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!res.ok) throw new Error("Failed");
    // Remove the card from DOM and reload count
    const card = document.getElementById(`contra-${flagId}`);
    if (card) card.remove();
    await loadContradictions();
  } catch {
    alert("Failed to resolve contradiction. Please try again.");
  }
}

// ── Archived Memories ─────────────────────────────────────────────────────────
async function loadArchived() {
  try {
    const mems = await fetch(`/api/session/${SESSION_ID}/memories/archived`).then(r => r.json());
    setStat("stat-archived", mems.length);
    if (!mems.length) {
      $("#arch-body").innerHTML = `<div class="dim">No archived (consolidated) memories yet.</div>`;
      return;
    }

    $("#arch-body").innerHTML = `
      <p class="dim" style="font-size:12px;margin-bottom:12px">
        These memories were merged into consolidations and soft-deleted. They are kept for reference but are no longer injected into prompts.
      </p>` +
      mems.map(m => `
        <div class="mem-card mem-archived">
          <div class="mem-card-header">
            <span class="mem-card-title">${esc(m.title)}</span>
            <div class="mem-card-badges">
              <span class="badge">${esc(m.type.replace("_", " "))}</span>
              <span class="badge ${impBadge(m.importance)}">${m.importance}</span>
            </div>
          </div>
          <div class="mem-card-content">${esc(m.content)}</div>
          <div class="mem-card-meta">
            <span class="dim">confidence: ${Math.round(m.confidence * 100)}%</span>
            ${m.consolidated_from?.length ? `<span class="dim">merged from ${m.consolidated_from.length} memories</span>` : ""}
            <span class="dim">${new Date(m.created_at).toLocaleString()}</span>
          </div>
        </div>`).join("");
  } catch {
    $("#arch-body").innerHTML = `<div class="dim">Could not load archived memories.</div>`;
  }
}

// ── Objectives ────────────────────────────────────────────────────────────────
async function loadObjectives() {
  try {
    const objectives = await fetch(`/api/session/${SESSION_ID}/objectives`).then(r => r.json());
    const active = objectives.filter(o => o.status === "active");
    setStat("stat-objectives", active.length);
    renderObjectives(objectives);
  } catch {
    $("#objectives-body").innerHTML = `<div class="dim">Could not load objectives.</div>`;
  }
}

function renderObjectives(objectives) {
  const body = $("#objectives-body");
  const statusClass = { active: "", completed: "green", failed: "red" };
  const statusLabel = { active: "active", completed: "completed", failed: "failed" };

  body.innerHTML = `
    <div class="objective-add-form">
      <input type="text" id="status-new-obj-title" placeholder="New objective title…" style="flex:1">
      <input type="text" id="status-new-obj-desc" placeholder="Description (optional)…" style="flex:1">
      <button class="btn btn-secondary btn-sm" onclick="statusAddObjective()">Add</button>
    </div>` +
    (!objectives.length
      ? `<div class="dim" style="padding:12px">No objectives yet.</div>`
      : objectives.map(o => `
        <div class="objective-status-card">
          <div class="objective-status-header">
            <span class="objective-status-title">${esc(o.title)}</span>
            <span class="badge ${statusClass[o.status] || ""}">${statusLabel[o.status] || o.status}</span>
          </div>
          ${o.description ? `<div class="dim" style="font-size:12px;margin-top:4px">${esc(o.description)}</div>` : ""}
          <div class="objective-status-actions">
            ${o.status === "active" ? `
              <button class="btn btn-sm btn-secondary" onclick="statusUpdateObjective('${o.id}','completed')">✓ Complete</button>
              <button class="btn btn-sm btn-secondary" onclick="statusUpdateObjective('${o.id}','failed')">✗ Failed</button>` : `
              <button class="btn btn-sm btn-secondary" onclick="statusUpdateObjective('${o.id}','active')">↺ Reopen</button>`}
            <button class="btn btn-sm btn-danger" onclick="statusDeleteObjective('${o.id}')">Delete</button>
          </div>
        </div>`).join(""));
}

async function statusAddObjective() {
  const title = $("#status-new-obj-title").value.trim();
  const desc = $("#status-new-obj-desc").value.trim();
  if (!title) return;
  await fetch(`/api/session/${SESSION_ID}/objectives`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description: desc }),
  });
  await loadObjectives();
}

async function statusUpdateObjective(id, status) {
  await fetch(`/api/session/${SESSION_ID}/objectives/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await loadObjectives();
}

async function statusDeleteObjective(id) {
  await fetch(`/api/session/${SESSION_ID}/objectives/${id}`, { method: "DELETE" });
  await loadObjectives();
}

// ── Bookmarks ─────────────────────────────────────────────────────────────────
async function loadBookmarks() {
  try {
    const bookmarks = await fetch(`/api/session/${SESSION_ID}/bookmarks`).then(r => r.json());
    setStat("stat-bookmarks", bookmarks.length);
    renderBookmarks(bookmarks);
  } catch {
    $("#bookmarks-body").innerHTML = `<div class="dim">Could not load bookmarks.</div>`;
  }
}

function renderBookmarks(bookmarks) {
  const body = $("#bookmarks-body");
  if (!bookmarks.length) {
    body.innerHTML = `<div class="dim">No bookmarks yet. Star any message in the chat to bookmark it.</div>`;
    return;
  }
  body.innerHTML = bookmarks.map(b => `
    <div class="bookmark-card">
      <div class="bookmark-header">
        <span class="badge">${esc(b.role)}</span>
        <span class="dim" style="font-size:12px">Turn ${b.turn_number}</span>
        <span class="dim" style="font-size:12px;margin-left:auto">${new Date(b.created_at).toLocaleString()}</span>
        <button class="msg-action-btn" title="Remove bookmark" onclick="removeBookmark('${b.id}')">✕</button>
      </div>
      <div class="bookmark-preview">${esc(b.content_preview)}${b.content_preview.length >= 200 ? "…" : ""}</div>
      ${b.note ? `<div class="bookmark-note">📝 ${esc(b.note)}</div>` : ""}
    </div>`).join("");
}

async function removeBookmark(id) {
  await fetch(`/api/session/${SESSION_ID}/bookmarks/${id}`, { method: "DELETE" });
  await loadBookmarks();
}

// ── Emotional State ───────────────────────────────────────────────────────────
async function loadEmotionalState() {
  try {
    const state = await fetch(`/api/session/${SESSION_ID}/emotional-state`).then(r => r.json());
    renderEmotionalState(state);
  } catch {
    $("#emotional-body").innerHTML = `<div class="dim">Could not load emotional state.</div>`;
  }
}

function renderEmotionalState(state) {
  const stressBar = Math.round(state.stress * 100);
  const stressClass = state.stress >= 0.7 ? "neg-text" : state.stress >= 0.4 ? "" : "pos-text";
  $("#emotional-body").innerHTML = `
    <div class="emotional-state-panel">
      <div class="emotional-row">
        <div class="emotional-field">
          <label>Mood</label>
          <input type="text" id="mood-input" value="${esc(state.mood)}" placeholder="neutral">
        </div>
        <div class="emotional-field" style="flex:2">
          <label>Motivation</label>
          <input type="text" id="motivation-input" value="${esc(state.motivation)}" placeholder="What drives the character right now…">
        </div>
      </div>
      <div class="emotional-field" style="margin-top:10px">
        <label>Stress — <span class="${stressClass}">${esc(state.stress_label)} (${stressBar}%)</span></label>
        <input type="range" id="stress-input" min="0" max="100" value="${stressBar}" style="width:100%">
      </div>
      <div class="emotional-field" style="margin-top:10px">
        <label>Notes</label>
        <input type="text" id="emotional-notes-input" value="${esc(state.notes)}" placeholder="Optional context…">
      </div>
      <div style="margin-top:10px">
        <button class="btn btn-secondary btn-sm" onclick="saveEmotionalState()">Save State</button>
      </div>
    </div>`;
}

async function saveEmotionalState() {
  const mood = $("#mood-input").value.trim() || "neutral";
  const stress = parseFloat($("#stress-input").value) / 100;
  const motivation = $("#motivation-input").value.trim();
  const notes = $("#emotional-notes-input").value.trim();
  await fetch(`/api/session/${SESSION_ID}/emotional-state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mood, stress, motivation, notes }),
  });
  await loadEmotionalState();
}

// ── Inventory ─────────────────────────────────────────────────────────────────
async function loadInventory() {
  try {
    const items = await fetch(`/api/session/${SESSION_ID}/inventory`).then(r => r.json());
    setStat("stat-items", items.length);
    renderInventory(items);
  } catch {
    $("#inventory-body").innerHTML = `<div class="dim">Could not load inventory.</div>`;
  }
}

function renderInventory(items) {
  const conditionBadge = { pristine: "green", good: "", worn: "yellow", damaged: "yellow", broken: "red" };
  $("#inventory-body").innerHTML = `
    <div class="objective-add-form" style="flex-wrap:wrap;gap:6px">
      <input type="text" id="item-new-name" placeholder="Item name…" style="flex:2;min-width:150px">
      <input type="text" id="item-new-desc" placeholder="Description (optional)…" style="flex:2;min-width:150px">
      <select id="item-new-condition" style="flex:1;min-width:100px">
        ${["good","pristine","worn","damaged","broken"].map(c => `<option value="${c}">${c}</option>`).join("")}
      </select>
      <input type="number" id="item-new-qty" value="1" min="1" style="width:60px">
      <label style="display:flex;align-items:center;gap:4px;font-size:13px">
        <input type="checkbox" id="item-new-equipped"> equipped
      </label>
      <button class="btn btn-secondary btn-sm" onclick="statusAddItem()">Add</button>
    </div>` +
    (!items.length
      ? `<div class="dim" style="padding:12px">No items in inventory.</div>`
      : items.map(i => `
        <div class="inventory-card${i.is_equipped ? " inventory-equipped" : ""}">
          <div class="inventory-card-header">
            ${i.is_equipped ? `<span title="Equipped">⚔️</span>` : ""}
            <span class="inventory-name">${esc(i.name)}</span>
            ${i.quantity > 1 ? `<span class="badge">×${i.quantity}</span>` : ""}
            <span class="badge ${conditionBadge[i.condition] || ""}">${esc(i.condition)}</span>
            <button class="msg-action-btn" style="margin-left:auto" onclick="statusToggleEquip('${i.id}',${!i.is_equipped})" title="${i.is_equipped ? "Unequip" : "Equip"}">${i.is_equipped ? "🔓" : "🔒"}</button>
            <button class="msg-action-btn" title="Remove" onclick="statusDeleteItem('${i.id}')">✕</button>
          </div>
          ${i.description ? `<div class="inventory-desc">${esc(i.description)}</div>` : ""}
        </div>`).join(""));
}

async function statusAddItem() {
  const name = $("#item-new-name").value.trim();
  if (!name) return;
  await fetch(`/api/session/${SESSION_ID}/inventory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      description: $("#item-new-desc").value.trim(),
      condition: $("#item-new-condition").value,
      quantity: parseInt($("#item-new-qty").value) || 1,
      is_equipped: $("#item-new-equipped").checked,
    }),
  });
  $("#item-new-name").value = "";
  $("#item-new-desc").value = "";
  await loadInventory();
}

async function statusToggleEquip(id, equip) {
  await fetch(`/api/session/${SESSION_ID}/inventory/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_equipped: equip }),
  });
  await loadInventory();
}

async function statusDeleteItem(id) {
  await fetch(`/api/session/${SESSION_ID}/inventory/${id}`, { method: "DELETE" });
  await loadInventory();
}

// ── Status Effects ─────────────────────────────────────────────────────────────
async function loadStatusEffects() {
  try {
    const effects = await fetch(`/api/session/${SESSION_ID}/status-effects`).then(r => r.json());
    setStat("stat-effects", effects.length);
    renderStatusEffects(effects);
  } catch {
    $("#effects-body").innerHTML = `<div class="dim">Could not load status effects.</div>`;
  }
}

function renderStatusEffects(effects) {
  const typeIcon = { buff: "✦", debuff: "✖", neutral: "◆" };
  const typeClass = { buff: "green", debuff: "red", neutral: "" };
  $("#effects-body").innerHTML = `
    <div class="objective-add-form" style="flex-wrap:wrap;gap:6px">
      <input type="text" id="effect-new-name" placeholder="Effect name (e.g. Bleeding)…" style="flex:2;min-width:160px">
      <input type="text" id="effect-new-desc" placeholder="Description (optional)…" style="flex:2;min-width:160px">
      <select id="effect-new-type" style="flex:1;min-width:100px">
        <option value="debuff">debuff</option>
        <option value="buff">buff</option>
        <option value="neutral">neutral</option>
      </select>
      <select id="effect-new-severity" style="flex:1;min-width:100px">
        <option value="mild">mild</option>
        <option value="moderate">moderate</option>
        <option value="severe">severe</option>
      </select>
      <input type="number" id="effect-new-duration" value="0" min="0" placeholder="turns" style="width:70px" title="Duration in turns (0 = permanent)">
      <button class="btn btn-secondary btn-sm" onclick="statusAddEffect()">Add</button>
    </div>` +
    (!effects.length
      ? `<div class="dim" style="padding:12px">No active status effects.</div>`
      : effects.map(e => `
        <div class="effect-card effect-${e.effect_type}">
          <div class="effect-card-header">
            <span class="effect-icon">${typeIcon[e.effect_type] || "◆"}</span>
            <span class="effect-name">${esc(e.name)}</span>
            <span class="badge ${typeClass[e.effect_type] || ""}">${esc(e.effect_type)}</span>
            <span class="badge">${esc(e.severity)}</span>
            ${e.duration_turns > 0 ? `<span class="dim" style="font-size:12px">${e.duration_turns} turns</span>` : `<span class="dim" style="font-size:12px">permanent</span>`}
            <button class="msg-action-btn" style="margin-left:auto" title="Remove effect" onclick="statusDeleteEffect('${e.id}')">✕</button>
          </div>
          ${e.description ? `<div class="effect-desc">${esc(e.description)}</div>` : ""}
        </div>`).join(""));
}

async function statusAddEffect() {
  const name = $("#effect-new-name").value.trim();
  if (!name) return;
  await fetch(`/api/session/${SESSION_ID}/status-effects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      description: $("#effect-new-desc").value.trim(),
      effect_type: $("#effect-new-type").value,
      severity: $("#effect-new-severity").value,
      duration_turns: parseInt($("#effect-new-duration").value) || 0,
    }),
  });
  $("#effect-new-name").value = "";
  $("#effect-new-desc").value = "";
  await loadStatusEffects();
}

async function statusDeleteEffect(id) {
  await fetch(`/api/session/${SESSION_ID}/status-effects/${id}`, { method: "DELETE" });
  await loadStatusEffects();
}

// ── NPC Roster ────────────────────────────────────────────────────────────────
async function loadNpcs() {
  try {
    const npcs = await fetch(`/api/session/${SESSION_ID}/npcs`).then(r => r.json());
    setStat("stat-npcs", npcs.length);
    renderNpcs(npcs);
  } catch {
    $("#npcs-body").innerHTML = `<div class="dim">Could not load NPCs.</div>`;
  }
}

function renderNpcs(npcs) {
  const body = $("#npcs-body");
  body.innerHTML = `
    <div class="objective-add-form">
      <input type="text" id="npc-new-name" placeholder="NPC name…" style="flex:1">
      <input type="text" id="npc-new-role" placeholder="Role (e.g. blacksmith)…" style="flex:1">
      <button class="btn btn-secondary btn-sm" onclick="statusAddNpc()">Add</button>
    </div>` +
    (!npcs.length
      ? `<div class="dim" style="padding:12px">No NPCs tracked yet.</div>`
      : npcs.map(n => `
        <div class="npc-card${n.is_alive ? "" : " npc-dead"}">
          <div class="npc-card-header">
            <span class="npc-name">${esc(n.name)}</span>
            ${n.role ? `<span class="badge">${esc(n.role)}</span>` : ""}
            ${!n.is_alive ? `<span class="badge red">deceased</span>` : ""}
            <button class="msg-action-btn" style="margin-left:auto" title="Delete NPC" onclick="statusDeleteNpc('${n.id}')">✕</button>
          </div>
          ${n.description ? `<div class="npc-desc">${esc(n.description)}</div>` : ""}
          ${n.personality_notes ? `<div class="dim" style="font-size:12px;font-style:italic">${esc(n.personality_notes)}</div>` : ""}
          ${n.last_known_location ? `<div class="dim" style="font-size:12px">📍 Last seen: ${esc(n.last_known_location)}</div>` : ""}
          <div class="npc-actions">
            ${n.is_alive
              ? `<button class="btn btn-sm btn-secondary" onclick="statusToggleNpcAlive('${n.id}', false)">Mark deceased</button>`
              : `<button class="btn btn-sm btn-secondary" onclick="statusToggleNpcAlive('${n.id}', true)">Mark alive</button>`}
          </div>
        </div>`).join(""));
}

async function statusAddNpc() {
  const name = $("#npc-new-name").value.trim();
  const role = $("#npc-new-role").value.trim();
  if (!name) return;
  await fetch(`/api/session/${SESSION_ID}/npcs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role }),
  });
  $("#npc-new-name").value = "";
  $("#npc-new-role").value = "";
  await loadNpcs();
}

async function statusToggleNpcAlive(id, isAlive) {
  await fetch(`/api/session/${SESSION_ID}/npcs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_alive: isAlive }),
  });
  await loadNpcs();
}

async function statusDeleteNpc(id) {
  await fetch(`/api/session/${SESSION_ID}/npcs/${id}`, { method: "DELETE" });
  await loadNpcs();
}

// ── Location Registry ─────────────────────────────────────────────────────────
async function loadLocations() {
  try {
    const locs = await fetch(`/api/session/${SESSION_ID}/locations`).then(r => r.json());
    setStat("stat-locations", locs.length);
    renderLocations(locs);
  } catch {
    $("#locations-body").innerHTML = `<div class="dim">Could not load locations.</div>`;
  }
}

function renderLocations(locs) {
  const body = $("#locations-body");
  if (!locs.length) {
    body.innerHTML = `<div class="dim" style="padding:12px">No locations registered yet. Locations are auto-registered when the scene changes.</div>`;
    return;
  }
  body.innerHTML = locs.map(l => `
    <div class="location-card">
      <div class="location-card-header">
        <span class="location-name">📍 ${esc(l.name)}</span>
        <span class="badge dim">${l.visit_count} visit${l.visit_count !== 1 ? "s" : ""}</span>
        <span class="dim" style="font-size:12px;margin-left:auto">Last: ${new Date(l.last_visited).toLocaleDateString()}</span>
        <button class="msg-action-btn" title="Remove location" onclick="statusDeleteLocation('${l.id}')">✕</button>
      </div>
      ${l.description ? `<div class="location-desc">${esc(l.description)}</div>` : ""}
      ${l.atmosphere ? `<div class="dim" style="font-size:12px;font-style:italic">"${esc(l.atmosphere)}"</div>` : ""}
      ${l.notes ? `<div class="dim" style="font-size:12px">📝 ${esc(l.notes)}</div>` : ""}
    </div>`).join("");
}

async function statusDeleteLocation(id) {
  await fetch(`/api/session/${SESSION_ID}/locations/${id}`, { method: "DELETE" });
  await loadLocations();
}

// ── Story Beats ───────────────────────────────────────────────────────────────
async function loadStoryBeats() {
  try {
    const beats = await fetch(`/api/session/${SESSION_ID}/story-beats`).then(r => r.json());
    setStat("stat-beats", beats.length);
    renderStoryBeats(beats);
  } catch {
    $("#beats-body").innerHTML = `<div class="dim">Could not load story beats.</div>`;
  }
}

function renderStoryBeats(beats) {
  const body = $("#beats-body");
  const beatTypeIcon = {
    introduction: "🌅", revelation: "💡", climax: "⚔️", resolution: "🏁",
    twist: "🌀", encounter: "👥", milestone: "🏆", tragedy: "💔",
  };
  body.innerHTML = `
    <div class="objective-add-form" style="flex-wrap:wrap;gap:6px">
      <input type="text" id="beat-new-title" placeholder="Beat title…" style="flex:2;min-width:160px">
      <input type="text" id="beat-new-desc" placeholder="Description (optional)…" style="flex:2;min-width:160px">
      <select id="beat-new-type" style="flex:1;min-width:120px">
        ${["milestone","introduction","revelation","climax","resolution","twist","encounter","tragedy"]
          .map(t => `<option value="${t}">${t}</option>`).join("")}
      </select>
      <select id="beat-new-importance" style="flex:1;min-width:100px">
        <option value="medium">medium</option>
        <option value="high">high</option>
        <option value="critical">critical</option>
        <option value="low">low</option>
      </select>
      <button class="btn btn-secondary btn-sm" onclick="statusAddBeat()">Add Beat</button>
    </div>` +
    (!beats.length
      ? `<div class="dim" style="padding:12px">No story beats recorded yet.</div>`
      : beats.map(b => `
        <div class="beat-card">
          <div class="beat-card-header">
            <span class="beat-icon">${beatTypeIcon[b.beat_type] || "📌"}</span>
            <span class="beat-title">${esc(b.title)}</span>
            <span class="badge">${esc(b.beat_type)}</span>
            <span class="badge ${impBadge(b.importance)}">${b.importance}</span>
            <span class="dim" style="font-size:12px;margin-left:4px">Turn ${b.turn_number}</span>
            <button class="msg-action-btn" style="margin-left:auto" title="Delete beat" onclick="statusDeleteBeat('${b.id}')">✕</button>
          </div>
          ${b.description ? `<div class="beat-desc">${esc(b.description)}</div>` : ""}
          <div class="dim" style="font-size:11px">${new Date(b.created_at).toLocaleString()}</div>
        </div>`).join(""));
}

async function statusAddBeat() {
  const title = $("#beat-new-title").value.trim();
  const description = $("#beat-new-desc").value.trim();
  const beat_type = $("#beat-new-type").value;
  const importance = $("#beat-new-importance").value;
  if (!title) return;
  await fetch(`/api/session/${SESSION_ID}/story-beats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description, beat_type, importance }),
  });
  $("#beat-new-title").value = "";
  $("#beat-new-desc").value = "";
  await loadStoryBeats();
}

async function statusDeleteBeat(id) {
  await fetch(`/api/session/${SESSION_ID}/story-beats/${id}`, { method: "DELETE" });
  await loadStoryBeats();
}

// ── Quest Log ─────────────────────────────────────────────────────────────────
async function loadQuests() {
  const body = $("#quests-body");
  try {
    const quests = await fetch(`/api/session/${SESSION_ID}/quests`).then(r => r.json());
    const statusOrder = { active: 0, hidden: 1, completed: 2, failed: 3 };
    quests.sort((a, b) => (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9));

    let html = `<div style="margin-bottom:8px">
      <button class="action-btn" onclick="showAddQuestModal()">+ Add Quest</button>
    </div>`;
    if (!quests.length) { html += `<p class="dim">No quests tracked.</p>`; body.innerHTML = html; return; }

    const statusIcon = { active: '⚔', completed: '✓', failed: '✗', hidden: '?' };
    const statusCls = { active: 'quest-active', completed: 'quest-completed', failed: 'quest-failed', hidden: 'quest-hidden' };

    for (const q of quests) {
      const icon = statusIcon[q.status] || '?';
      const cls = statusCls[q.status] || '';
      const giver = q.giver_npc_name ? ` <span class="dim">from ${esc(q.giver_npc_name)}</span>` : '';
      const loc = q.location_name ? ` <span class="dim">@ ${esc(q.location_name)}</span>` : '';
      const progress = q.progress_label ? ` <span class="dim">[${esc(q.progress_label)}]</span>` : '';

      html += `<div class="quest-card ${cls}">
        <div class="quest-header">
          <span class="quest-icon">${icon}</span>
          <strong>${esc(q.title)}</strong>${giver}${loc}${progress}
          <span class="quest-status-badge ${cls}">${esc(q.status)}</span>
        </div>`;
      if (q.description) html += `<div class="dim" style="font-size:12px;margin:4px 0">${esc(q.description)}</div>`;
      if (q.stages?.length) {
        html += `<div class="quest-stages">`;
        for (const s of q.stages.sort((a,b) => a.order - b.order)) {
          html += `<div class="quest-stage ${s.completed ? 'stage-done' : ''}">
            <button class="stage-check-btn ${s.completed ? 'checked' : ''}"
              onclick="completeStage('${q.id}','${s.id}')"
              ${s.completed ? 'disabled' : ''}>
              ${s.completed ? '✓' : '○'}
            </button>
            <span>${esc(s.description)}</span>
          </div>`;
        }
        html += `</div>`;
      }
      if (q.reward_notes) html += `<div class="quest-reward">🏆 ${esc(q.reward_notes)}</div>`;
      html += `<div class="quest-actions">
        ${q.status === 'active' ? `<button class="action-btn" onclick="updateQuestStatus('${q.id}','completed')">Complete</button>` : ''}
        ${q.status === 'active' ? `<button class="action-btn" onclick="updateQuestStatus('${q.id}','failed')">Fail</button>` : ''}
        ${q.status !== 'active' ? `<button class="action-btn" onclick="updateQuestStatus('${q.id}','active')">Reactivate</button>` : ''}
        <button class="icon-btn" onclick="deleteQuest('${q.id}')" title="Delete">✕</button>
      </div></div>`;
    }
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load quests.</p>`; }
}

function showAddQuestModal() {
  const title = prompt("Quest title:");
  if (!title?.trim()) return;
  const description = prompt("Description (optional):", "") || "";
  const giver = prompt("Quest giver NPC (optional):", "") || "";
  const reward = prompt("Reward notes (optional):", "") || "";
  fetch(`/api/session/${SESSION_ID}/quests`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title.trim(), description, giver_npc_name: giver, reward_notes: reward }),
  }).then(() => loadQuests());
}

async function completeStage(questId, stageId) {
  await fetch(`/api/session/${SESSION_ID}/quests/${questId}/complete-stage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage_id: stageId }),
  });
  await loadQuests();
}

async function updateQuestStatus(questId, status) {
  await fetch(`/api/session/${SESSION_ID}/quests/${questId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await loadQuests();
}

async function deleteQuest(id) {
  await fetch(`/api/session/${SESSION_ID}/quests/${id}`, { method: "DELETE" });
  await loadQuests();
}

// ── Session Journal ───────────────────────────────────────────────────────────
async function loadJournal() {
  const body = $("#journal-body");
  try {
    const entries = await fetch(`/api/session/${SESSION_ID}/journal`).then(r => r.json());
    let html = `<div style="margin-bottom:8px">
      <button class="action-btn" onclick="showAddJournalModal()">+ Write Entry</button>
    </div>`;
    if (!entries.length) { html += `<p class="dim">No journal entries yet.</p>`; body.innerHTML = html; return; }
    for (const e of entries) {
      const date = new Date(e.created_at).toLocaleString();
      const tags = e.tags?.length ? e.tags.map(t => `<span class="char-chip">${esc(t)}</span>`).join('') : '';
      html += `<div class="journal-card">
        <div class="journal-header">
          <strong>${esc(e.title)}</strong>
          <span class="dim" style="font-size:11px">${date}</span>
          <button class="icon-btn" onclick="deleteJournalEntry('${e.id}')" title="Delete">✕</button>
        </div>
        ${tags ? `<div style="margin:4px 0">${tags}</div>` : ''}
        <div class="journal-content">${esc(e.content)}</div>
      </div>`;
    }
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load journal.</p>`; }
}

function showAddJournalModal() {
  const title = prompt("Entry title:");
  if (!title?.trim()) return;
  const content = prompt("Entry content:");
  if (!content?.trim()) return;
  fetch(`/api/session/${SESSION_ID}/journal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title.trim(), content: content.trim() }),
  }).then(() => loadJournal());
}

async function deleteJournalEntry(id) {
  await fetch(`/api/session/${SESSION_ID}/journal/${id}`, { method: "DELETE" });
  await loadJournal();
}

// ── Lore Notes ────────────────────────────────────────────────────────────────
async function loadLoreNotes() {
  const body = $("#lore-body");
  try {
    const notes = await fetch(`/api/session/${SESSION_ID}/lore-notes`).then(r => r.json());
    let html = `<div style="margin-bottom:8px">
      <button class="action-btn" onclick="showAddLoreNoteModal()">+ Add Note</button>
    </div>`;
    if (!notes.length) { html += `<p class="dim">No lore notes yet.</p>`; body.innerHTML = html; return; }

    // Group by category
    const groups = {};
    for (const n of notes) {
      (groups[n.category] = groups[n.category] || []).push(n);
    }
    for (const [cat, items] of Object.entries(groups).sort()) {
      html += `<div class="lore-group"><strong class="lore-category">${esc(cat)}</strong>`;
      for (const n of items) {
        const src = n.source ? `<span class="dim"> — ${esc(n.source)}</span>` : '';
        html += `<div class="lore-card">
          <div class="lore-header">
            <strong>${esc(n.title)}</strong>${src}
            <button class="icon-btn" onclick="deleteLoreNote('${n.id}')" title="Delete">✕</button>
          </div>
          <div class="lore-content dim">${esc(n.content)}</div>
        </div>`;
      }
      html += `</div>`;
    }
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load lore notes.</p>`; }
}

function showAddLoreNoteModal() {
  const title = prompt("Note title:");
  if (!title?.trim()) return;
  const content = prompt("Content:");
  if (!content?.trim()) return;
  const category = prompt("Category (general/history/magic/faction/character/location/rumor/prophecy):", "general") || "general";
  const source = prompt("Source/discovered from (optional):", "") || "";
  fetch(`/api/session/${SESSION_ID}/lore-notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title.trim(), content: content.trim(), category, source }),
  }).then(() => loadLoreNotes());
}

async function deleteLoreNote(id) {
  await fetch(`/api/session/${SESSION_ID}/lore-notes/${id}`, { method: "DELETE" });
  await loadLoreNotes();
}

// ── Character Stats ───────────────────────────────────────────────────────────
async function loadStats() {
  const body = $("#stats-body");
  try {
    const stats = await fetch(`/api/session/${SESSION_ID}/stats`).then(r => r.json());
    if (!stats.length) { body.innerHTML = `<p class="dim">No stats defined.</p>`; return; }

    // Group by category
    const groups = {};
    for (const s of stats) {
      (groups[s.category] = groups[s.category] || []).push(s);
    }

    let html = `<div style="margin-bottom:8px">
      <button class="action-btn" onclick="showAddStatModal()">+ Add Stat</button>
    </div>`;
    for (const [cat, items] of Object.entries(groups).sort()) {
      html += `<div class="stat-group"><strong>${esc(cat)}</strong><div class="stat-grid">`;
      for (const s of items.sort((a,b) => a.name.localeCompare(b.name))) {
        const mod = s.effective_modifier;
        const modStr = mod !== 0 ? ` <span class="dim">(${mod >= 0 ? '+' : ''}${mod})</span>` : '';
        html += `<div class="stat-card">
          <div class="stat-name">${esc(s.name)}</div>
          <div class="stat-value">${s.value}${modStr}</div>
          <div class="stat-actions">
            <button class="icon-btn" onclick="statusDeleteStat('${s.id}')" title="Delete">✕</button>
          </div>
        </div>`;
      }
      html += `</div></div>`;
    }
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load stats.</p>`; }
}

function showAddStatModal() {
  const name = prompt("Stat name (e.g. Strength):");
  if (!name?.trim()) return;
  const value = parseInt(prompt("Value (default 10):", "10") || "10", 10);
  const category = prompt("Category (attribute / skill / derived):", "attribute") || "attribute";
  fetch(`/api/session/${SESSION_ID}/stats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name.trim(), value, category }),
  }).then(() => loadStats());
}

async function statusDeleteStat(id) {
  await fetch(`/api/session/${SESSION_ID}/stats/${id}`, { method: "DELETE" });
  await loadStats();
}

// ── Skill Check Log ───────────────────────────────────────────────────────────
async function loadSkillChecks() {
  const body = $("#checks-body");
  try {
    const checks = await fetch(`/api/session/${SESSION_ID}/skill-checks?n=20`).then(r => r.json());
    if (!checks.length) { body.innerHTML = `<p class="dim">No skill checks yet.</p>`; return; }

    const outcomeIcon = { critical_success: "⭐", success: "✓", failure: "✗", critical_failure: "💀" };
    const outcomeClass = { critical_success: "outcome-crit-success", success: "outcome-success",
                           failure: "outcome-failure", critical_failure: "outcome-crit-failure" };

    let html = `<table class="check-table"><thead><tr>
      <th>Stat</th><th>Roll</th><th>Mod</th><th>Total</th><th>DC</th><th>Outcome</th><th>Context</th>
    </tr></thead><tbody>`;
    for (const c of checks) {
      const icon = outcomeIcon[c.outcome] || "?";
      const cls = outcomeClass[c.outcome] || "";
      html += `<tr>
        <td>${esc(c.stat_name)}</td>
        <td>${c.roll}</td>
        <td>${c.modifier >= 0 ? '+' : ''}${c.modifier}</td>
        <td><strong>${c.total}</strong></td>
        <td>${c.difficulty}</td>
        <td class="${cls}">${icon} ${esc(c.outcome.replace(/_/g, ' '))}</td>
        <td class="dim" style="font-size:11px">${esc(c.narrative_context || '—')}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load skill checks.</p>`; }
}

// ── Narrative Arc ─────────────────────────────────────────────────────────────
async function loadNarrativeArc() {
  const body = $("#arc-body");
  try {
    const arc = await fetch(`/api/session/${SESSION_ID}/narrative-arc`).then(r => r.json());
    const tensionPct = Math.round(arc.tension * 100);
    const themes = arc.themes?.length ? arc.themes.map(t => `<span class="char-chip">${esc(t)}</span>`).join('') : '<span class="dim">None</span>';
    body.innerHTML = `
      <div class="arc-panel">
        <div class="arc-row"><span class="arc-label">Act</span><span><strong>${arc.current_act}</strong> — ${esc(arc.act_label)}</span></div>
        <div class="arc-row"><span class="arc-label">Tension</span>
          <span>${esc(arc.tension_label)} (${tensionPct}%)
            <div class="tension-bar"><div class="tension-fill" style="width:${tensionPct}%"></div></div>
          </span>
        </div>
        <div class="arc-row"><span class="arc-label">Pacing</span><span>${esc(arc.pacing)}</span></div>
        <div class="arc-row"><span class="arc-label">Themes</span><span>${themes}</span></div>
        ${arc.arc_notes ? `<div class="arc-row"><span class="arc-label">Notes</span><span class="dim">${esc(arc.arc_notes)}</span></div>` : ''}
      </div>
      <button class="action-btn" onclick="showEditArcModal(${JSON.stringify(arc).replace(/"/g,'&quot;')})">Edit Arc</button>`;
  } catch { body.innerHTML = `<p class="dim">Failed to load narrative arc.</p>`; }
}

function showEditArcModal(arc) {
  const actLabel = prompt("Act label:", arc.act_label) ?? arc.act_label;
  const act = parseInt(prompt("Act number:", arc.current_act) || arc.current_act, 10);
  const tension = parseFloat(prompt("Tension 0.0–1.0:", arc.tension) || arc.tension);
  const pacing = prompt("Pacing (building/steady/climactic/falling):", arc.pacing) ?? arc.pacing;
  const themes = prompt("Themes (comma-separated):", (arc.themes || []).join(', ')) ?? '';
  const arc_notes = prompt("Notes:", arc.arc_notes) ?? '';
  fetch(`/api/session/${SESSION_ID}/narrative-arc`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_act: act, act_label: actLabel, tension: isNaN(tension) ? arc.tension : tension,
      pacing, themes: themes.split(',').map(t => t.trim()).filter(Boolean), arc_notes,
    }),
  }).then(() => loadNarrativeArc());
}

// ── Factions ──────────────────────────────────────────────────────────────────
async function loadFactions() {
  const body = $("#factions-body");
  try {
    const factions = await fetch(`/api/session/${SESSION_ID}/factions`).then(r => r.json());
    let html = `<div style="margin-bottom:8px">
      <button class="action-btn" onclick="showAddFactionModal()">+ Add Faction</button>
    </div>`;
    if (!factions.length) { html += `<p class="dim">No factions tracked.</p>`; body.innerHTML = html; return; }
    const standingClass = { allied: "standing-allied", friendly: "standing-friendly",
      neutral: "", unfriendly: "standing-unfriendly", hostile: "standing-hostile" };
    for (const f of factions) {
      const cls = standingClass[f.standing_label] || '';
      const align = f.alignment ? ` <span class="dim">(${esc(f.alignment)})</span>` : '';
      html += `<div class="faction-card">
        <div class="faction-header">
          <strong>${esc(f.name)}</strong>${align}
          <span class="faction-standing ${cls}">${esc(f.standing_label)} (${f.standing >= 0 ? '+' : ''}${f.standing.toFixed(2)})</span>
        </div>
        ${f.description ? `<div class="dim" style="font-size:12px;margin:4px 0">${esc(f.description)}</div>` : ''}
        <div class="faction-actions">
          <button class="action-btn" onclick="adjustStanding('${f.id}', 0.1)">+0.1</button>
          <button class="action-btn" onclick="adjustStanding('${f.id}', -0.1)">−0.1</button>
          <button class="action-btn" onclick="adjustStanding('${f.id}', 0.25)">+0.25</button>
          <button class="action-btn" onclick="adjustStanding('${f.id}', -0.25)">−0.25</button>
          <button class="icon-btn" onclick="statusDeleteFaction('${f.id}')" title="Delete">✕</button>
        </div>
      </div>`;
    }
    body.innerHTML = html;
  } catch { body.innerHTML = `<p class="dim">Failed to load factions.</p>`; }
}

function showAddFactionModal() {
  const name = prompt("Faction name:");
  if (!name?.trim()) return;
  const description = prompt("Description (optional):", "") || "";
  const alignment = prompt("Alignment (e.g. lawful neutral, chaotic evil):", "") || "";
  const standing = parseFloat(prompt("Initial standing −1.0 to 1.0:", "0.0") || "0.0");
  fetch(`/api/session/${SESSION_ID}/factions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name.trim(), description, alignment, standing: isNaN(standing) ? 0.0 : standing }),
  }).then(() => loadFactions());
}

async function adjustStanding(id, delta) {
  await fetch(`/api/session/${SESSION_ID}/factions/${id}/standing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delta }),
  });
  await loadFactions();
}

async function statusDeleteFaction(id) {
  await fetch(`/api/session/${SESSION_ID}/factions/${id}`, { method: "DELETE" });
  await loadFactions();
}

// ── Section collapse ──────────────────────────────────────────────────────────
function toggleSection(id) {
  document.getElementById(id).classList.toggle("status-section-collapsed");
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStat(id, value) {
  const el = document.getElementById(id);
  if (el) el.querySelector(".summary-stat-value").textContent = value;
}

function impBadge(imp) {
  return imp === "critical" ? "red" : imp === "high" ? "yellow" : "";
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
