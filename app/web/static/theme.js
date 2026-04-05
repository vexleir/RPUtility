"use strict";

const _THEME_KEY = "rp_theme";
const _THEMES = [
  { id: "dark",     label: "Dark (default)" },
  { id: "midnight", label: "Midnight" },
  { id: "sepia",    label: "Parchment" },
  { id: "forest",   label: "Forest" },
  { id: "light",    label: "Light" },
];

function setTheme(name) {
  document.documentElement.setAttribute("data-theme", name || "dark");
  try { localStorage.setItem(_THEME_KEY, name); } catch(_) {}
  // keep any select in sync
  const sel = document.getElementById("theme-select");
  if (sel) sel.value = name;
}

function _initTheme() {
  let saved = "dark";
  try { saved = localStorage.getItem(_THEME_KEY) || "dark"; } catch(_) {}
  document.documentElement.setAttribute("data-theme", saved);
}

// Apply immediately before any paint
_initTheme();

// After DOM ready: populate select and sync its value
document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("theme-select");
  if (!sel) return;
  let saved = "dark";
  try { saved = localStorage.getItem(_THEME_KEY) || "dark"; } catch(_) {}
  _THEMES.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = t.label;
    sel.appendChild(opt);
  });
  sel.value = saved;
});
