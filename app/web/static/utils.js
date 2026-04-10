/**
 * utils.js — shared frontend utilities for RP Utility.
 * Loaded as a regular (non-module) script before each page's main JS.
 * All exports are global.
 */

"use strict";

/**
 * Fetch a JSON endpoint with consistent error surfacing.
 *
 * On network failure or non-OK HTTP status, extracts the best available
 * error message (FastAPI `detail` field → response text → HTTP status) and
 * throws an Error with that message. Callers are responsible for catching
 * and displaying to the user with their page's error/banner function.
 *
 * @param {string} url
 * @param {RequestInit} [opts]
 * @returns {Promise<any>} Parsed JSON response body.
 */
async function fetchJSON(url, opts = {}) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (networkErr) {
    throw new Error(`Network error: ${networkErr.message}`);
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.clone().json();
      if (body && body.detail) {
        detail = typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
      }
    } catch {
      try {
        const text = await res.text();
        if (text) detail = text;
      } catch { /* ignore */ }
    }
    throw new Error(detail);
  }
  return res.json();
}
