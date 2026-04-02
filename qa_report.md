# QA Evaluation & Beta Testing Report: RP Utility

**Date:** April 2, 2026
**Target Application:** RP Utility (Local-first AI roleplay engine)
**Reviewed By:** Antigravity QA

---

## 📋 Executive Summary
RP Utility is a robust, well-architected framework for local LLM roleplay. The core functionality—including prompt generation, context handling, memory tracking, and state management—is stable and performs admirably against its own specifications. The test suite is surprisingly thorough (374 passing tests). However, there are a few areas concerning data integrity, background processing latency, and dependency bloat that require developer attention prior to a full 1.0 release.

---

## 1. Functionality
- **Status:** **PASS**
- **Assessment:** The core application features work as advertised. The roleplay engine successfully connects to local LLM providers (Ollama/LM Studio). The engine correctly manages memory summarization, relationships, NPC tracking, and lorebook injections. 
- **Recommendation:** None for core logic. The engine's separation of concerns (memory, scene, relationships) is very effective.

## 2. Requirements Compliance
- **Status:** **PASS**
- **Assessment:** The application accurately fulfills the requirements outlined in the `README.md`. It runs completely offline without external APIs and successfully implements the SillyTavern character card spec (JSON and PNG natively).
- **Recommendation:** No major deviations found. 

## 3. User Experience & Usability
- **Status:** **PASS (with notes)**
- **Assessment:** The inclusion of a FastAPI web UI (`localhost:7860`) and a simple `.bat` launcher file makes onboarding extremely easy for non-technical users. The interface accurately updates scene and relationship changes automatically.
- **Recommendation:** 
  - If a user deletes a character card or image from the `data/cards` folder while a session is active, the UI might fall out of sync or throw generic 404s. Implement better graceful degradation with placeholder images if a card's PNG is missing.

## 4. Performance
- **Status:** **NEEDS REVIEW**
- **Assessment:** SQLite is configured well for concurrent access (`PRAGMA journal_mode=WAL`). However, the memory extraction logic and context window processing rely on LLM generation. While the UI streams the main chat response smoothly via Server-Sent Events (SSE), heavy background operations (like memory contradiction detection and consolidation) may induce latency.
- **Recommendation:** Consider decoupling post-turn analysis (memory extraction, relationship updates) into asynchronous background tasks (e.g., using `asyncio` tasks or a lightweight task queue) instead of blocking or running sequentially with the request lifecycle. 

## 5. Security
- **Status:** **PASS**
- **Assessment:** It is designed as a local-first, single-tenant tool. As such, lacking authentication/authorization is an acceptable design choice. 
- **Recommendation:** 
  - **Prompt Injection:** Since user input parses directly to the underlying LLM, it's susceptible to prompt injections. This is typical for local roleplay, but consider adding a systemic failsafe if users share malicious character cards.
  - **Path Traversal:** Ensure that character/lorebook filename parsing in the API endpoints (`/api/cards/{card_name}/image`) explicitly prevents path traversal (e.g., passing `../../` in the URL).

## 6. Compatibility
- **Status:** **PASS**
- **Assessment:** 
  - Integrates seamlessly with Ollama (`/api/tags`, `/api/chat`).
  - Readily accommodates standard roleplay structures (SillyTavern PNGs).
- **Recommendation:** Continue ensuring LLM prompt templates remain agnostic enough to support shifting models (like `llama3`, `mistral`, etc.) without hardcoding model-specific stop tokens.

## 7. Reliability & Stability
- **Status:** **PASS**
- **Assessment:** The API gracefully logs errors and returns `500/503` codes when the LLM provider times out or crashes. The FastAPI structure is sound.
- **Recommendation:** Ensure frontend handles 503 errors gracefully (by displaying a user-friendly "Ollama is down" banner instead of silent failures).

## 8. Integration
- **Status:** **PASS**
- **Assessment:** The `httpx` HTTP client used to interact with Ollama has a 120-second timeout, which is reasonable for local generation, preventing infinite hangs on massive context generations.
- **Recommendation:** Check integration stability with LM Studio, as parameter schemas change often for local OpenAI-compatible endpoints compared to Ollama's native API.

## 9. Data Integrity
- **Status:** **NEEDS REVIEW**
- **Assessment:** 
  - The SQLite database (`database.py`) heavily utilizes JSON text strings for storing list data (like `entities` and `tags`). This is fine for SQLite, but the schema explicitly omits foreign keys on `session_id` within the `memories` table to allow easier unit testing. 
  - **Technical Debt:** `aiosqlite` is listed in `requirements.txt`, but a standard synchronous `sqlite3` driver is actually used across the app (`import sqlite3`). This means the `requirements.txt` has dead dependencies.
- **Recommendation:** 
  - Enforce Foreign Key constraints for integrity in production. Using lack of constraints to "make testing easier" creates a risk of orphaned data.
  - Remove `aiosqlite` from `requirements.txt` or refactor the DB layer to actually use it for non-blocking I/O.

## 10. Regression
- **Status:** **PASS (with warnings)**
- **Assessment:** The test suite is excellent. Executing `pytest` resulted in **374 tests passing** in ~25 seconds. 
- **Recommendation:** The test execution yielded **1,093 warnings**. While the tests pass, this suggests widespread use of deprecated methods (either from Pydantic v1 vs v2, or SQLAlchemy/SQLite patterns). The team must clear these deprecation warnings before major upstream library updates break the system.

---

### Actionable Developer Takeaways:
1. **Remove `aiosqlite`** from dependencies or migrate database operations to be asynchronous.
2. **Clear the 1,000+ pytest warnings**, likely caused by Pydantic v2 migrations or deprecations.
3. **Add Foreign Key constraints** back into the database schema (`app/core/database.py`) to prevent orphaned memories when a session is deleted.
4. **Audit API asset routes** to guarantee protection against directory traversal attacks. 
