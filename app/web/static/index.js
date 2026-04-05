/* index.js — session list and new-session form */

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ── State ─────────────────────────────────────────────────────────────────────
let cards = [];
let lorebooks = [];
let models = [];

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([
    loadCampaigns(),
    loadSessions(),
    loadCards(),
    loadLorebooks(),
    loadModels(),
    checkProvider(),
    loadLibrary(),
  ]);

  // Wire up form
  $("#char-select").addEventListener("change", onCardChange);
  $("#create-form").addEventListener("submit", onCreateSession);
});

// ── Provider status ───────────────────────────────────────────────────────────
async function checkProvider() {
  try {
    const res = await fetch("/api/provider");
    const data = await res.json();
    const dot = $("#status-dot");
    const label = $("#status-label");
    if (data.available) {
      dot.className = "status-dot online";
      label.textContent = `${data.provider} · ${data.default_model}`;
    } else {
      dot.className = "status-dot offline";
      label.textContent = `${data.provider} offline`;
      showBanner("warn", `⚠ ${data.provider} is not running. Start it before creating a session.`);
    }
  } catch {
    showBanner("error", "Could not reach the RP Utility server.");
  }
}

// ── Campaigns ─────────────────────────────────────────────────────────────────
async function loadCampaigns() {
  const list = document.getElementById("campaign-list");
  if (!list) return;
  try {
    const res = await fetch("/api/campaigns");
    const campaigns = await res.json();
    if (!campaigns.length) {
      list.innerHTML = `
        <div class="empty-state">
          <div style="font-size:40px">🌍</div>
          <p>No campaigns yet.<br>Create one above →</p>
        </div>`;
      return;
    }
    list.innerHTML = campaigns.map(c => campaignCard(c)).join("");
  } catch {
    list.innerHTML = `<div class="banner banner-error">Failed to load campaigns.</div>`;
  }
}

function campaignCard(c) {
  const model = c.model_name || "default";
  const age = timeAgo(c.updated_at);
  return `
    <div class="session-card" id="campaign-${c.id}" data-campaign-name="${esc(c.name)}">
      <div class="session-avatar" style="background:var(--accent-dim);color:var(--accent)">🌍</div>
      <div class="session-info">
        <div class="session-name">${esc(c.name)}</div>
        <div class="session-meta">
          <span>🤖 <code style="font-size:11px">${esc(model)}</code></span>
          <span class="dim">${age}</span>
        </div>
      </div>
      <div class="session-actions">
        <a href="/campaigns/${c.id}/play" class="btn btn-primary btn-sm" style="text-decoration:none">▶ Play</a>
        <a href="/campaigns/${c.id}" class="btn btn-sm" style="text-decoration:none">World</a>
        <button class="btn btn-sm" onclick="cloneCampaign('${c.id}', '${esc(c.name)}')">Clone</button>
        <button class="btn btn-danger btn-sm" onclick="deleteCampaign('${c.id}')">Delete</button>
      </div>
    </div>`;
}

async function cloneCampaign(id, sourceName) {
  const name = prompt(`New campaign name (clone of "${sourceName}"):`, `${sourceName} — Copy`);
  if (!name?.trim()) return;
  try {
    const res = await fetch(`/api/campaigns/${id}/save-as-template`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    showBanner("success", `Campaign "${data.name}" created. Redirecting…`);
    setTimeout(() => { window.location.href = `/campaigns/${data.campaign_id}`; }, 1200);
  } catch (err) {
    showBanner("error", "Could not clone campaign: " + err.message);
  }
}

function openImportTemplateModal() {
  document.getElementById("import-template-name").value = "";
  document.getElementById("import-template-file").value = "";
  document.getElementById("import-template-status").textContent = "";
  document.getElementById("import-template-modal").classList.remove("hidden");
  setTimeout(() => document.getElementById("import-template-name").focus(), 50);
}

function closeImportTemplateModal() {
  document.getElementById("import-template-modal").classList.add("hidden");
}

async function runImportTemplate() {
  const name = document.getElementById("import-template-name").value.trim();
  const file = document.getElementById("import-template-file").files[0];
  const statusEl = document.getElementById("import-template-status");

  if (!name) { statusEl.textContent = "Please enter a campaign name."; return; }
  if (!file) { statusEl.textContent = "Please select a template file."; return; }

  statusEl.textContent = "Importing…";
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const res = await fetch("/api/campaigns/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, campaign_name: name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server returned ${res.status}`);
    }
    const result = await res.json();
    closeImportTemplateModal();
    showBanner("success", `Campaign "${result.name}" created. Redirecting…`);
    setTimeout(() => { window.location.href = `/campaigns/${result.campaign_id}`; }, 1200);
  } catch (e) {
    statusEl.textContent = `Import failed: ${e.message}`;
  }
}

async function deleteCampaign(id) {
  const card = document.getElementById(`campaign-${id}`);
  const name = card?.dataset.campaignName || "this campaign";
  if (!confirm(`Delete campaign "${name}"?\nThis cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/campaigns/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    card?.remove();
    if (!document.querySelector(`[id^='campaign-']`)) loadCampaigns();
  } catch (err) {
    showBanner("error", "Could not delete campaign: " + err.message);
  }
}

// ── Sessions ──────────────────────────────────────────────────────────────────
async function loadSessions() {
  const list = $("#session-list");
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();

    if (!sessions.length) {
      list.innerHTML = `
        <div class="empty-state">
          <div style="font-size:40px">🎭</div>
          <p>No sessions yet.<br>Create your first one →</p>
        </div>`;
      return;
    }

    list.innerHTML = sessions.map(s => sessionCard(s)).join("");
  } catch {
    list.innerHTML = `<div class="banner banner-error">Failed to load sessions.</div>`;
  }
}

function sessionCard(s) {
  const model = s.model_name || "default";
  const turns = s.turn_count === 1 ? "1 turn" : `${s.turn_count} turns`;
  const age = timeAgo(s.last_active);
  const initial = (s.character_name[0] || "?").toUpperCase();
  const modeTag = s.scenario_text
    ? `<span title="Scenario session">📝 Scenario</span>`
    : `<span>🎭 ${esc(s.character_name)}</span>`;

  return `
    <div class="session-card" id="session-${s.id}" data-session-name="${esc(s.name)}">
      <div class="session-avatar">${initial}</div>
      <div class="session-info">
        <div class="session-name">${esc(s.name)}</div>
        <div class="session-meta">
          ${modeTag}
          <span>🤖 <code style="font-size:11px">${esc(model)}</code></span>
          <span>💬 ${turns}</span>
          <span class="dim">${age}</span>
          ${s.lorebook_name ? `<span>📖 ${esc(s.lorebook_name)}</span>` : ""}
        </div>
      </div>
      <div class="session-actions">
        <a href="/chat/${s.id}" class="btn btn-primary btn-sm">Resume →</a>
        <button class="btn btn-danger btn-sm" onclick="deleteSession('${s.id}')">Delete</button>
      </div>
    </div>`;
}

async function deleteSession(id) {
  const card = document.getElementById(`session-${id}`);
  const name = card?.dataset.sessionName || "this session";
  if (!confirm(`Delete session "${name}"?\nThis cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const card = document.getElementById(`session-${id}`);
    if (card) card.remove();
    // If list is now empty, reload to show empty state
    if (!document.querySelector(".session-card")) loadSessions();
  } catch (err) {
    showBanner("error", "Could not delete session: " + err.message);
  }
}

// ── Cards ─────────────────────────────────────────────────────────────────────
async function loadCards() {
  const sel = $("#char-select");
  try {
    const res = await fetch("/api/cards");
    cards = await res.json();

    sel.innerHTML = `<option value="">— Select character —</option>` +
      cards.map(c => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
  } catch {
    sel.innerHTML = `<option value="">Failed to load cards</option>`;
  }
}

function onCardChange() {
  const sel = $("#char-select");
  const preview = $("#card-preview");
  const card = cards.find(c => c.name === sel.value);

  if (!card) {
    preview.classList.add("hidden");
    return;
  }

  const desc = card.description || "(no description)";
  const truncated = desc.length > 220 ? desc.slice(0, 220) + "…" : desc;
  preview.innerHTML = `<strong>${esc(card.name)}</strong>${esc(truncated)}`;
  preview.classList.remove("hidden");
}

// ── Lorebooks ─────────────────────────────────────────────────────────────────
async function loadLorebooks() {
  const sel = $("#lorebook-select");
  try {
    const res = await fetch("/api/lorebooks");
    lorebooks = await res.json();

    sel.innerHTML = `<option value="">— None —</option>` +
      lorebooks.map(l => `<option value="${esc(l.name)}">${esc(l.name)} (${l.entries} entries)</option>`).join("");
  } catch {
    sel.innerHTML = `<option value="">Failed to load lorebooks</option>`;
  }
}

// ── Models ────────────────────────────────────────────────────────────────────
async function loadModels() {
  const sel = $("#model-select");
  sel.innerHTML = `<option value="">Loading models…</option>`;

  try {
    const res = await fetch("/api/models");
    models = await res.json();

    if (!models.length) {
      sel.innerHTML = `<option value="">— Use default from config —</option>`;
      return;
    }

    sel.innerHTML = `<option value="">— Use default from config —</option>` +
      models.map(m => {
        const size = m.size_formatted ? ` (${m.size_formatted})` : "";
        return `<option value="${esc(m.name)}">${esc(m.name)}${size}</option>`;
      }).join("");

  } catch {
    sel.innerHTML = `<option value="">— Use default from config —</option>`;
  }
}

// ── Legacy section toggle ─────────────────────────────────────────────────────
function toggleLegacy() {
  const body = document.getElementById("legacy-body");
  const toggle = document.getElementById("legacy-toggle");
  const isOpen = !body.classList.contains("hidden");
  body.classList.toggle("hidden", isOpen);
  toggle.textContent = isOpen
    ? "Single-session mode (legacy) →"
    : "Single-session mode (legacy) ▾";
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  $$(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $("#tab-card").classList.toggle("hidden", name !== "card");
  $("#tab-scenario").classList.toggle("hidden", name !== "scenario");
}

// ── Create session ────────────────────────────────────────────────────────────
async function onCreateSession(e) {
  e.preventDefault();

  const btn = $("#create-btn");
  const name = $("#session-name").value.trim();
  const modelName = $("#model-select").value || null;
  const location = $("#location-input").value.trim() || "Unknown";
  const isScenario = !$("#tab-scenario").classList.contains("hidden");

  if (!name) return flashError("Session name is required.");

  let payload;
  if (isScenario) {
    const charName = $("#scenario-char-name").value.trim() || "Character";
    const scenarioText = $("#scenario-text").value.trim();
    if (!scenarioText) return flashError("Please describe the world and situation.");
    payload = { name, character_name: charName, model_name: modelName, location, scenario_text: scenarioText };
  } else {
    const charName = $("#char-select").value;
    const lorebookName = $("#lorebook-select").value || null;
    if (!charName) return flashError("Please select a character.");
    payload = { name, character_name: charName, lorebook_name: lorebookName, model_name: modelName, location };
  }

  btn.disabled = true;
  btn.innerHTML = `<div class="spinner"></div> Creating…`;

  try {
    const res = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to create session");
    }

    const session = await res.json();
    window.location.href = `/chat/${session.id}`;

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = "Create Session →";
    flashError(err.message);
  }
}

function flashError(msg) {
  showBanner("error", msg);
  setTimeout(() => hideBanners(), 4000);
}

// ── Banners ───────────────────────────────────────────────────────────────────
function showBanner(type, msg) {
  const container = $("#banner-container");
  container.innerHTML = `<div class="banner banner-${type}">${esc(msg)}</div>`;
}

function hideBanners() {
  const container = $("#banner-container");
  if (container) container.innerHTML = "";
}

// ── Library ───────────────────────────────────────────────────────────────────
async function loadLibrary() {
  await Promise.all([loadCardLibrary(), loadLorebookLibrary()]);
}

async function loadCardLibrary() {
  const grid = $("#card-library-grid");
  try {
    const res = await fetch("/api/cards");
    const cards = await res.json();
    if (!cards.length) {
      grid.innerHTML = `<p class="dim" style="font-size:13px">No cards found. Import one above.</p>`;
      return;
    }
    grid.innerHTML = cards.map(c => {
      const thumb = c.has_image !== false
        ? `<div class="card-thumb" style="background-image:url('/api/cards/${encodeURIComponent(c.name)}/image')" onerror="this.style.backgroundImage='none';this.classList.add('card-thumb-placeholder')"><span class="card-thumb-initial">${esc(c.name[0]?.toUpperCase()||'?')}</span></div>`
        : `<div class="card-thumb card-thumb-placeholder"><span class="card-thumb-initial">${esc(c.name[0]?.toUpperCase()||'?')}</span></div>`;
      const desc = c.description ? (c.description.length > 80 ? c.description.slice(0,80)+'…' : c.description) : '';
      return `<div class="card-lib-tile">
        ${thumb}
        <div class="card-lib-info">
          <div class="card-lib-name">${esc(c.name)}</div>
          ${desc ? `<div class="card-lib-desc dim">${esc(desc)}</div>` : ''}
        </div>
        <button class="btn btn-sm card-lib-view-btn" onclick="showCardDetail('${esc(c.name)}')">View</button>
      </div>`;
    }).join('');
  } catch {
    grid.innerHTML = `<p class="dim">Failed to load cards.</p>`;
  }
}

async function loadLorebookLibrary() {
  const list = $("#lorebook-library-list");
  try {
    const res = await fetch("/api/lorebooks");
    const books = await res.json();
    if (!books.length) {
      list.innerHTML = `<p class="dim" style="font-size:13px">No lorebooks found. Import one above.</p>`;
      return;
    }
    list.innerHTML = books.map(b => `
      <div class="lorebook-lib-row">
        <div>
          <div class="lorebook-lib-name">${esc(b.name)}</div>
          ${b.description ? `<div class="dim" style="font-size:12px">${esc(b.description)}</div>` : ''}
        </div>
        <span class="dim" style="font-size:12px;white-space:nowrap">${b.entries} entries</span>
        <button class="btn btn-sm" onclick="showLorebookDetail('${esc(b.name)}')">View</button>
      </div>`).join('');
  } catch {
    list.innerHTML = `<p class="dim">Failed to load lorebooks.</p>`;
  }
}

// ── Detail modals ─────────────────────────────────────────────────────────────
async function showCardDetail(name) {
  const modal = $("#detail-modal");
  const content = $("#modal-content");
  content.innerHTML = `<div style="padding:20px;color:var(--text-muted)">Loading…</div>`;
  modal.classList.remove("hidden");

  try {
    const card = await fetch(`/api/cards/${encodeURIComponent(name)}/details`).then(r => r.json());

    const imgHtml = card.has_image
      ? `<img src="/api/cards/${encodeURIComponent(name)}/image" class="modal-card-image" alt="${esc(name)}">`
      : '';

    const fields = [
      ["Description", card.description],
      ["Personality", card.personality],
      ["Scenario", card.scenario],
      ["First Message", card.first_message],
      ["Example Dialogue", card.example_dialogue],
      ["System Prompt", card.system_prompt],
      ["Creator Notes", card.creator_notes],
      ["Voice Tone", card.voice_tone],
      ["Speech Patterns", card.speech_patterns],
      ["Verbal Tics", card.verbal_tics],
      ["Vocabulary Level", card.vocabulary_level],
      ["Accent Notes", card.accent_notes],
    ].filter(([, v]) => v);

    const tagsHtml = card.tags?.length
      ? `<div style="margin-bottom:14px">${card.tags.map(t=>`<span class="char-chip">${esc(t)}</span>`).join('')}</div>`
      : '';

    const fieldsHtml = fields.map(([label, value]) => `
      <div class="modal-field">
        <div class="modal-field-label">${esc(label)}</div>
        <div class="modal-field-value">${esc(value)}</div>
      </div>`).join('');

    content.innerHTML = `
      <div class="modal-card-layout">
        ${imgHtml}
        <div class="modal-card-body">
          <h2 style="margin:0 0 6px">${esc(card.name)}</h2>
          ${tagsHtml}
          ${fieldsHtml}
        </div>
      </div>`;
  } catch {
    content.innerHTML = `<p style="padding:20px;color:var(--red)">Failed to load card details.</p>`;
  }
}

async function showLorebookDetail(name) {
  const modal = $("#detail-modal");
  const content = $("#modal-content");
  content.innerHTML = `<div style="padding:20px;color:var(--text-muted)">Loading…</div>`;
  modal.classList.remove("hidden");

  try {
    const book = await fetch(`/api/lorebooks/${encodeURIComponent(name)}/details`).then(r => r.json());

    const entriesHtml = book.entries.length
      ? `<table class="lore-detail-table">
          <thead><tr><th>Keys</th><th>Content</th><th>Pri</th><th>On</th></tr></thead>
          <tbody>${book.entries.map(e => `
            <tr class="${e.enabled ? '' : 'lore-disabled'}">
              <td class="lore-keys">${e.keys.map(k=>`<code>${esc(k)}</code>`).join(' ')}</td>
              <td class="lore-content-cell">${esc(e.content)}</td>
              <td>${e.priority}</td>
              <td>${e.enabled ? '✓' : '—'}</td>
            </tr>`).join('')}
          </tbody>
        </table>`
      : `<p class="dim">No entries.</p>`;

    content.innerHTML = `
      <h2 style="margin:0 0 6px">${esc(book.name)}</h2>
      ${book.description ? `<p class="dim" style="margin:0 0 14px">${esc(book.description)}</p>` : ''}
      <div class="dim" style="font-size:12px;margin-bottom:14px">${book.entries.length} entries</div>
      ${entriesHtml}`;
  } catch {
    content.innerHTML = `<p style="padding:20px;color:var(--red)">Failed to load lorebook details.</p>`;
  }
}

function closeDetailModal() {
  $("#detail-modal").classList.add("hidden");
}
function closeModal(e) {
  if (e.target === $("#detail-modal")) closeDetailModal();
}

// ── Import ────────────────────────────────────────────────────────────────────
function triggerImport(type) {
  $(`#${type}-file-input`).click();
}

async function uploadFile(type, input) {
  const file = input.files[0];
  if (!file) return;
  input.value = "";

  const endpoint = type === 'card' ? '/api/cards/upload' : '/api/lorebooks/upload';
  const fd = new FormData();
  fd.append("file", file);

  showLibraryBanner("info", `Uploading ${file.name}…`);
  try {
    const res = await fetch(endpoint, { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Upload failed (${res.status})`);
    }
    const data = await res.json();
    showLibraryBanner("success", `✓ Imported: ${data.name}`);
    // Refresh all dropdowns and library
    await Promise.all([loadCards(), loadLorebooks(), loadLibrary()]);
  } catch (err) {
    showLibraryBanner("error", `✗ ${err.message}`);
  }
}

async function reloadAssets() {
  const btn = $("#reload-btn");
  btn.disabled = true;
  btn.textContent = "↺ Reloading…";
  try {
    const res = await fetch("/api/reload", { method: "POST" });
    const data = await res.json();
    showLibraryBanner("success", `✓ Reloaded — ${data.cards} cards, ${data.lorebooks} lorebooks`);
    await Promise.all([loadCards(), loadLorebooks(), loadLibrary()]);
  } catch {
    showLibraryBanner("error", "Reload failed.");
  } finally {
    btn.disabled = false;
    btn.textContent = "↺ Reload";
  }
}

function showLibraryBanner(type, msg) {
  const el = $("#library-banner");
  const cls = type === "error" ? "banner-error" : type === "success" ? "banner-success" : "banner-warn";
  el.innerHTML = `<div class="banner ${cls}" style="margin:0">${esc(msg)}</div>`;
  if (type !== "error") setTimeout(() => { el.innerHTML = ""; }, 4000);
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function timeAgo(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
