/**
 * campaign_imggen.js
 * Shared ComfyUI image generation modal for campaign pages.
 * Included by both campaign_overview.html and campaign_play.html.
 *
 * Entry points:
 *   openImgGen("campaign")                          — from overview
 *   openImgGen("npc", { npcId, npcName })           — from NPC card
 *   openImgGen("scene", { sceneId })                — from play header
 *   openImgGen("chat",  { sceneId, lastMessage })   — from input area
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

const IMGGEN_COMFY_KEY = "rp_comfy_settings_v2";

let _imggenCtx = null;   // { type, npcId?, npcName?, sceneId?, lastMessage? }

// ── Open / close ──────────────────────────────────────────────────────────────

function openImgGen(type, opts = {}) {
  _imggenCtx = { type, ...opts };

  const titles = {
    campaign: "Generate Campaign Image",
    pc:       "Generate Player Character Portrait",
    npc:      `Generate Portrait — ${opts.npcName || "Character"}`,
    scene:    "Generate Scene Image",
    chat:     "Generate In-Text Image",
  };
  document.getElementById("imggen-title").textContent = titles[type] || "Generate Image";

  const sourceHints = {
    campaign: "Prompt will be built from the world document and campaign description.",
    pc:       "Prompt will be built from the player character's appearance and personality.",
    npc:      `Prompt will be built from ${opts.npcName || "the character"}'s appearance and personality.`,
    scene:    "Prompt will be built from the scene summary, location, and NPCs present.",
    chat:     "Prompt will be built from the last AI response in the chat.",
  };
  document.getElementById("imggen-source-hint").textContent = sourceHints[type] || "";

  // Show/hide "Insert into Chat" button (only available on play page)
  const insertBtn = document.getElementById("imggen-insert-btn");
  if (insertBtn) {
    insertBtn.classList.toggle("hidden",
      type !== "chat" && type !== "scene");
  }

  // Reset state
  document.getElementById("imggen-prompt").value = "";
  document.getElementById("imggen-gen-status").textContent = "";
  document.getElementById("imggen-status").textContent = "";
  document.getElementById("imggen-result").classList.add("hidden");
  const uploadInput = document.getElementById("imggen-upload");
  if (uploadInput) uploadInput.value = "";

  // Load models into dropdown
  _loadImgGenModels();

  // Restore saved ComfyUI settings
  _restoreComfySettings();

  openModal("imggen-modal");
}

// ── Model loading ─────────────────────────────────────────────────────────────

async function _loadImgGenModels() {
  const sel = document.getElementById("imggen-model-select");
  try {
    const res = await fetch("/api/models");
    const models = await res.json();
    const list = Array.isArray(models) ? models : (models.models || []);
    sel.innerHTML = '<option value="">Default model</option>' +
      list.map(m => `<option value="${escImgGen(m.name)}">${escImgGen(m.name)}</option>`).join("");
  } catch {
    sel.innerHTML = '<option value="">Default model</option>';
  }
}

// ── Prompt generation ─────────────────────────────────────────────────────────

async function generateImgPrompt() {
  if (!_imggenCtx) return;
  const btn      = document.getElementById("imggen-gen-prompt-btn");
  const statusEl = document.getElementById("imggen-gen-status");
  const promptEl = document.getElementById("imggen-prompt");

  btn.disabled = true;
  btn.textContent = "Generating…";
  statusEl.textContent = "Analysing context…";

  const body = {
    source_type:  _imggenCtx.type,
    scene_id:     _imggenCtx.sceneId     || null,
    npc_id:       _imggenCtx.npcId       || null,
    last_message: _imggenCtx.lastMessage || null,
    model_name:   document.getElementById("imggen-model-select").value || null,
  };

  try {
    const res = await fetch(`/api/campaigns/${CAMPAIGN_ID}/image-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    const prompt = (data.prompt || "").trim();
    if (!prompt) {
      statusEl.textContent = "⚠ The AI returned an empty response. Try a different model or add more detail to the world document.";
      return;
    }
    promptEl.value = prompt;
    statusEl.textContent = "Prompt generated — edit as needed.";
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Generate Prompt";
  }
}

// ── ComfyUI generation ────────────────────────────────────────────────────────

async function submitImgGen() {
  const promptEl   = document.getElementById("imggen-prompt");
  const basePrompt = promptEl.value.trim();
  if (!basePrompt) {
    document.getElementById("imggen-status").textContent = "Please enter a prompt or click ✨ Generate Prompt.";
    return;
  }

  const styleTags = (document.getElementById("imggen-style-tags").value || "").trim();
  const prompt    = styleTags ? `${basePrompt}, ${styleTags}` : basePrompt;

  const btn      = document.getElementById("imggen-submit-btn");
  const statusEl = document.getElementById("imggen-status");

  btn.disabled = true;
  btn.textContent = "Generating…";
  statusEl.textContent = "Sending to ComfyUI… this may take a minute.";

  const settings = _getComfySettings();
  _saveComfySettings();   // persist current field values

  try {
    const res = await fetch("/api/comfyui/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        negative_prompt: document.getElementById("imggen-negative").value || "lowres, bad anatomy, blurry, watermark",
        width:      parseInt(document.getElementById("imggen-width").value)  || 512,
        height:     parseInt(document.getElementById("imggen-height").value) || 768,
        steps:      parseInt(document.getElementById("imggen-steps").value)  || 20,
        cfg:        parseFloat(document.getElementById("imggen-cfg").value)  || 7,
        checkpoint: document.getElementById("imggen-checkpoint").value.trim() || "",
        comfyui_url: document.getElementById("imggen-comfy-url").value.trim() || "http://localhost:8188",
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    statusEl.textContent = "";
    _showImgGenResult(data.data_url, prompt);

  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "🎨 Generate Image";
  }
}

function _showImgGenResult(dataUrl, prompt) {
  const resultEl  = document.getElementById("imggen-result");
  const imgEl     = document.getElementById("imggen-result-img");
  const insertBtn = document.getElementById("imggen-insert-btn");
  const saveBtn   = document.getElementById("imggen-save-btn");
  const dlBtn     = document.getElementById("imggen-download-btn");

  imgEl.src      = dataUrl;
  imgEl.alt      = prompt;
  imgEl._dataUrl = dataUrl;
  imgEl._prompt  = prompt;

  // Download link always available
  dlBtn.href     = dataUrl;
  dlBtn.download = `image_${Date.now()}.png`;

  // Reset save button
  if (saveBtn) {
    saveBtn.disabled    = false;
    saveBtn.textContent = "💾 Save";
  }

  // "Insert into Chat" only on play page for chat/scene types
  if (insertBtn) {
    const canInsert = _imggenCtx &&
      (_imggenCtx.type === "chat" || _imggenCtx.type === "scene") &&
      typeof insertImgGenToChat_impl === "function";
    insertBtn.classList.toggle("hidden", !canInsert);
  }

  resultEl.classList.remove("hidden");
  resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function saveImgGen() {
  const imgEl  = document.getElementById("imggen-result-img");
  const saveBtn = document.getElementById("imggen-save-btn");
  if (!imgEl || !imgEl._dataUrl || !_imggenCtx) return;

  saveBtn.disabled    = true;
  saveBtn.textContent = "Saving…";

  const type = _imggenCtx.type;
  let url = null;

  if (type === "campaign") {
    url = `/api/campaigns/${CAMPAIGN_ID}/cover-image`;
  } else if (type === "pc") {
    url = `/api/campaigns/${CAMPAIGN_ID}/player-character/portrait`;
  } else if (type === "npc" && _imggenCtx.npcId) {
    url = `/api/campaigns/${CAMPAIGN_ID}/npcs/${_imggenCtx.npcId}/portrait`;
  } else if (type === "scene" && _imggenCtx.sceneId) {
    url = `/api/campaigns/${CAMPAIGN_ID}/scenes/${_imggenCtx.sceneId}/scene-image`;
  } else if (type === "chat") {
    // For in-text, "Save" inserts into chat stream
    insertImgGenToChat();
    saveBtn.disabled    = false;
    saveBtn.textContent = "💾 Save";
    return;
  }

  if (!url) {
    saveBtn.disabled    = false;
    saveBtn.textContent = "💾 Save";
    return;
  }

  try {
    const res = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data_url: imgEl._dataUrl }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    saveBtn.textContent = "✓ Saved";
    // Update the in-page display after saving
    _onImageSaved(type, _imggenCtx, imgEl._dataUrl);
  } catch (e) {
    saveBtn.disabled    = false;
    saveBtn.textContent = "💾 Save";
    document.getElementById("imggen-status").textContent = `Save failed: ${e.message}`;
  }
}

/** Update the in-page display immediately after a successful save. */
function _onImageSaved(type, ctx, dataUrl) {
  if (type === "campaign") {
    const el = document.getElementById("campaign-cover-img");
    if (el) { el.src = dataUrl; el.classList.remove("hidden"); }
    const placeholder = document.getElementById("campaign-cover-placeholder");
    if (placeholder) placeholder.classList.add("hidden");
  } else if (type === "pc") {
    const el = document.getElementById("pc-portrait-img");
    if (el) { el.src = dataUrl; el.classList.remove("hidden"); }
    const placeholder = document.getElementById("pc-portrait-placeholder");
    if (placeholder) placeholder.classList.add("hidden");
    if (typeof _pc !== "undefined" && _pc) _pc.portrait_image = dataUrl;
  } else if (type === "npc" && ctx.npcId) {
    // Update portrait in the NPC list (avatar element set by renderNpcList)
    const avatar = document.querySelector(`[data-npc-avatar="${ctx.npcId}"]`);
    if (avatar) { avatar.src = dataUrl; avatar.classList.remove("hidden"); }
    // Also update in-memory so re-renders pick it up
    if (typeof _npcs !== "undefined") {
      const npc = _npcs.find(n => n.id === ctx.npcId);
      if (npc) npc.portrait_image = dataUrl;
    }
  } else if (type === "scene" && ctx.sceneId) {
    const el   = document.getElementById("scene-header-img");
    const wrap = document.getElementById("scene-header-img-wrap");
    if (el) { el.src = dataUrl; }
    if (wrap) { wrap.classList.remove("hidden"); }
    if (typeof _scene !== "undefined" && _scene) _scene.scene_image = dataUrl;
  }
}

// Called by campaign_play.js context — inserts image into the messages area
function insertImgGenToChat() {
  const imgEl = document.getElementById("imggen-result-img");
  if (!imgEl || !imgEl._dataUrl) return;
  if (typeof insertImgGenToChat_impl === "function") {
    insertImgGenToChat_impl(imgEl._dataUrl, imgEl._prompt);
    closeModal("imggen-modal");
  }
}

// ── ComfyUI checkpoint listing ────────────────────────────────────────────────

async function fetchImgGenCheckpoints() {
  const url    = (document.getElementById("imggen-comfy-url").value || "http://localhost:8188").trim();
  const listEl = document.getElementById("imggen-checkpoint-list");
  listEl.textContent = "Fetching…";
  try {
    const res  = await fetch("/api/comfyui/checkpoints?comfyui_url=" + encodeURIComponent(url));
    const data = await res.json();
    if (data.checkpoints && data.checkpoints.length) {
      listEl.innerHTML = data.checkpoints.map(ck =>
        `<a href="#" class="checkpoint-link" onclick="document.getElementById('imggen-checkpoint').value='${ck.replace(/'/g,"\\'")}';return false">${escImgGen(ck)}</a>`
      ).join(" · ");
    } else {
      listEl.textContent = "No checkpoints found.";
    }
  } catch {
    listEl.textContent = "Could not reach ComfyUI.";
  }
}

// ── Settings persistence ──────────────────────────────────────────────────────

function _getComfySettings() {
  try { return JSON.parse(localStorage.getItem(IMGGEN_COMFY_KEY)) || {}; } catch { return {}; }
}

function _restoreComfySettings() {
  const s = _getComfySettings();
  if (s.comfyui_url) document.getElementById("imggen-comfy-url").value  = s.comfyui_url;
  if (s.checkpoint)  document.getElementById("imggen-checkpoint").value  = s.checkpoint;
  if (s.width)       document.getElementById("imggen-width").value       = s.width;
  if (s.height)      document.getElementById("imggen-height").value      = s.height;
  if (s.steps)       document.getElementById("imggen-steps").value       = s.steps;
  if (s.cfg)         document.getElementById("imggen-cfg").value         = s.cfg;
  if (s.negative)    document.getElementById("imggen-negative").value    = s.negative;
  if (s.style_tags)  document.getElementById("imggen-style-tags").value  = s.style_tags;
}

function _saveComfySettings() {
  const s = {
    comfyui_url: document.getElementById("imggen-comfy-url").value.trim(),
    checkpoint:  document.getElementById("imggen-checkpoint").value.trim(),
    width:       document.getElementById("imggen-width").value,
    height:      document.getElementById("imggen-height").value,
    steps:       document.getElementById("imggen-steps").value,
    cfg:         document.getElementById("imggen-cfg").value,
    negative:    document.getElementById("imggen-negative").value,
    style_tags:  document.getElementById("imggen-style-tags").value,
  };
  localStorage.setItem(IMGGEN_COMFY_KEY, JSON.stringify(s));
}

// ── Upload ────────────────────────────────────────────────────────────────────

function uploadImgFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => _showImgGenResult(e.target.result, file.name);
  reader.readAsDataURL(file);
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escImgGen(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
