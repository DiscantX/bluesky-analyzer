# Bluesky Analyzer — Postmortem & Development Roadmap

A consolidated technical post-mortem and forward roadmap synthesized from self-evaluations produced by three AI assistants across multiple development sessions. Intended as a living reference document for all future development.

---

## 1. Project Summary

Bluesky Analyzer is a local-first web application for analyzing a user's Bluesky social network. It fetches follows and followers via the AT Protocol, analyzes activity signals (inactivity, repost ratios, interaction history), and presents results in a filterable, sortable dashboard backed by SQLite. Beyond basic list management, it computes graph metrics (FlowRank via NetworkX, community detection, clustering coefficients), supports a priority-based graph crawl with budget controls and queue persistence, and features a recursive custom filter builder with math expression support and user-defined variables.

**Stack:** FastAPI + Tortoise ORM + SQLite + vanilla JS. No build pipeline. This is the correct choice for a local tool.

**Current status:** Functionally working. Core sync, analysis, crawl, and UI are operational. The codebase is ready for stabilization and feature completion, but carries meaningful technical debt that must be addressed before new features are added.

---

## 2. What Was Built Well

These are genuine strengths, agreed upon across all evaluations:

**Data Architecture**
The separation of the shared `Profile` table (universal per DID) from the per-owner `AccountRelationship` table is the correct way to handle multi-account social data. This decision will continue to pay dividends as the app scales.

**Filter and Expression Engine**
The recursive JSON condition tree, translated to SQL by `_build_recursive_where_clause` in `db/queries.py`, with support for nested AND/OR groups, math expressions, and custom user-defined variables, puts this app significantly ahead of standard dashboard tooling. The ambition and direction are correct.

**Two-Tier API Strategy**
Using the authenticated PDS for owner operations and the public AppView (`public.api.bsky.app`) for graph crawl is intelligent resource management. It conserves rate-limit budget for operations that require authentication.

**Crawl System**
Priority scoring, resumable queue state across restarts, budget controls, and the minimum connection threshold for stub expansion reflect production-quality thinking applied to a personal tool.

**SSE Streaming**
The `ProgressBus` pub/sub pattern and Server-Sent Events for live sync and crawl progress provide a high-quality real-time feel without requiring WebSockets.

**Differential Sync**
Staleness-tiered re-analysis (Tier 2: 3 days, Tier 1: 7 days, Tier 0: 30 days) avoids wasteful full re-syncs and is a well-designed approach to API budget efficiency.

**Technology Choices**
FastAPI + SQLite + vanilla JS with no build pipeline is appropriate for a local tool. These choices minimize operational overhead and deployment complexity.

---

## 3. Confirmed Bugs

These are verified defects. All must be fixed before any new feature work begins.

### 3.1 `handleDeleteInBuilder` — Undefined Function
The Delete button in the filter builder modal calls `handleDeleteInBuilder()` via `onclick`. This function does not exist anywhere in `static/js/app.js`. Clicking it throws a `ReferenceError` at runtime and the button is completely non-functional.

### 3.2 Date Filters Silently Discarded
In `fetchUsers()`, a `dateFilters` array is defined but the loop applying those filters to `params` is never executed. Only `numericFilters` receives the `params.set()` treatment. All date range filters (`before_last_post_at`, `after_last_post_at`, etc.) are silently ignored on every query with no error.

### 3.3 `_where()` Parameter Mismatch
`api/users.py` passes date parameters (`before_last_post_at`, `after_last_post_at`, and others) to `query_users()`, which forwards them to `_where()`. The `_where()` function signature in `db/queries.py` does not accept these parameters. This raises a `TypeError` at runtime for any request using those filters.

### 3.4 Denormalized Flags Stale After Settings Change
`is_inactive` and `is_repost_heavy` are computed at sync time using the thresholds from `GlobalSettings`. If a user changes these thresholds via the Settings modal, all existing rows immediately reflect the wrong values — the stored flags are stale until every affected account is re-synced. There is no mechanism to detect or correct this.

### 3.5 Crawl Settings Don't Propagate to Runtime
`analyzer/crawl.py` constructs module-level `asyncio.Semaphore` objects from module-level constants (`MIN_CONNECTION_THRESHOLD = 3`, `CRAWL_CONCURRENCY = 3`) at import time. `GlobalSettings` exposes these as user-configurable fields, and `crawl_step()` loads them — but the semaphores are already created. UI changes to these settings have no effect until process restart, and even then the module-level constants shadow the settings for semaphore construction.

### 3.6 SSE Stream Does Not Filter by Operation
`/api/sync/{alias}/stream` accepts an `operation` query parameter and `ProgressBus.subscribe()` stores it, but `ProgressBus.emit()` broadcasts to all subscribers for a given alias regardless of operation type. A crawl stream subscriber receives sync events and vice versa.

### 3.7 Variable Editor Panel Non-Functional
The variable editor panel (HTML present in `index.html`, open/close/save functions present in `app.js`) opens and displays expression data but does not allow editing. It is a read-only stub shipped as a feature.

---

## 4. Failure Groupings

### Untested Code
Zero automated tests exist despite the codebase containing multiple explicitly testable pure functions. The recursive SQL builder, graph analysis, and stat computation all operate without any safety net. Every change is a trust exercise.

**Root cause:** No testing framework was established. "We'll test later" became "we never tested."

### Function-Level Bugs
Missing functions, silent filter failures, and parameter mismatches exist in code that was reviewed statically but never run end-to-end to verify.

**Root cause:** Verification was treated as optional. Syntax validity was mistaken for functional correctness.

### Settings Don't Propagate
UI-configurable settings frequently do not affect actual runtime behavior due to module-level initialization running before settings are loaded.

**Root cause:** Persistent pattern of writing settings as constants first and retrofitting configurability later, without completing the connection.

### Incomplete Features Shipped as Complete
The variable editor, several async flows, and multiple edge case handlers were left at approximately 50% implementation and handed off without clear labeling.

**Root cause:** "Infrastructure present" was mistaken for "feature complete." No definition of done was enforced.

### Session Continuity Failures
Because context is lost between sessions, new work was built on unreviewed foundations. Bugs were reintroduced. Features built in one session were partially broken by additions in another.

**Root cause:** No audit phase at session start. No handoff documentation. Each session assumed prior state was correct.

### State Management Inconsistency
Mixed patterns of direct mutation and immutable updates across the codebase, with undocumented state transitions — particularly in the variable editor and filter builder — create confusion and bugs.

**Root cause:** No enforced consistency pattern. Documentation of state lifecycle was never prioritized.

### Scope Creep Without Stability Gates
The filter builder accumulated math expressions, variables, member-of-filter logic, and inline editing before the simpler version was confirmed working. Complexity was added on an unverified foundation.

**Root cause:** No one pushed back. New capability was treated as inherently valuable regardless of the stability of what it was built on.

---

## 5. Action Plan for Future Development Sessions

### At the Start of Every Session
1. **Audit before building.** Run the app end-to-end. Identify what is actually broken vs. what appears to work. Document findings before writing a single line of new code.
2. **Read the handoff log.** Consult `SESSION_HANDOFF.md` (to be created) for current state, known stubs, and open assumptions.
3. **Define done.** For any task, specify the exact user flow that must work before the task is considered complete.

### During Development
1. **No template string event handlers.** Complex event logic in HTML attribute strings is a persistent source of syntax errors. Use `addEventListener` after render or structured helper functions.
2. **Trace the full stack.** For any feature touched, walk the complete path: frontend state → API call → DB query → response → UI update. Verify each link.
3. **Label stubs explicitly.** Any incomplete implementation must be marked `# STUB: not yet functional` or `// STUB` with a note on what remains.
4. **Verify settings propagate.** Any user-configurable setting must be confirmed to actually affect runtime behavior, not just be stored.
5. **Ship simple first.** A working simple version before a broken complex version, every time.

### Before Ending a Session
1. **Update `SESSION_HANDOFF.md`** with: what was completed, what is still a stub, what was not tested, what assumptions were made, what could break.
2. **Answer the closing checklist:**
   - What did I ship?
   - What is still a stub?
   - What did I not test?
   - What could break as a result of my changes?

### Structurally
- Tests for pure functions are written with the code, not after.
- Aerich migrations are implemented before any further schema changes.
- A `SESSION_HANDOFF.md` file is maintained at the project root and updated every session.

---

## 6. Unified Project Roadmap

### Phase 0 — Stabilization (Fix Before Adding Anything)
**Goal:** Make the codebase trustworthy. Every change must be verifiable.

**Critical bug fixes (do first):**
- Fix `handleDeleteInBuilder` — define the function or wire to existing delete logic
- Fix `_where()` parameter mismatch for date filter arguments
- Fix `fetchUsers()` date filter loop — execute `params.set()` for `dateFilters`
- Fix `ProgressBus.emit()` to check subscriber operation type before dispatching
- Fix crawl semaphores — construct from `GlobalSettings` at `crawl_step()` invocation, not at module import

**Settings propagation:**
- Refactor `analyzer/crawl.py` so concurrency and threshold settings are read from `GlobalSettings` at runtime
- Verify every UI-configurable setting actually affects behavior — treat this as a sweep across all settings

**Test suite (establish before Phase 1):**
- Unit tests for `analyzer/analyze.py` pure functions — repost ratio, flag computation, datetime parsing
- Tests for `_build_recursive_where_clause` with known input/output pairs
- Integration test for the complete filter flow: UI → API → DB → results

**Documentation:**
- Create `SESSION_HANDOFF.md` at project root
- Add inline comments explaining: staleness tier logic, profile/relationship split rationale, public AppView usage for crawl
- Document state transitions for the variable editor and filter builder

---

### Phase 1 — Complete Existing Features
**Goal:** Ship working features. No stubs.

**Variable editor:**
- Implement full expression editing (replace read-only panel with functional editor)
- Add expression validation — detect malformed JSON and circular references
- Add confirmation dialogs before overwriting
- Add error recovery for failed API calls
- Verify the complete workflow: create → save → reflected in UI → usable in query

**Stale flag resolution:**
- Either recompute `is_inactive` / `is_repost_heavy` in the query layer (removing stored denormalization), or store the threshold values alongside the flags so staleness can be detected and surfaced to the user

**Database migrations:**
- Replace `ensure_sqlite_compat_columns()` with Aerich or a versioned migration script
- Do this before any further schema changes

**Edge cases:**
- Handling of deleted variables in filters that reference them
- Loading states for async operations
- Validation layer for filter expressions — dry-run SQL before saving to catch divide-by-zero and missing fields

---

### Phase 2 — Infrastructure and Scalability
**Goal:** Build systems that enable future development without accumulating new debt.

- Implement Aerich migration system (if not completed in Phase 0)
- Add CI — automated test runs on every change, lint checks for syntax safety
- Pre-commit hooks for basic quality gates
- State management consistency pass — enforce either immutable updates or clearly-marked mutations across the JS codebase, not mixed

---

### Phase 3 — Expression Engine Improvements
**Goal:** Make the filter builder more powerful without breaking what works.

- **Bracket/grouping support:** Update the math UI to support nested parentheses for complex order of operations (e.g., `(a + b) / c`)
- **Dry-run validation:** "Test Expression" button in the variable editor that runs against the DB before saving
- **Variable dependency mapping:** A view showing which FilterSets rely on which Custom Variables, with warnings before deletion

---

### Phase 4 — Write Operations and Bulk Actions
**Goal:** Enable the app to act on its analysis, not just display it.

- Implement unfollow, mute, block (stubs already exist in `BskyClient`)
- Multi-select in the user list for batch operations
- Export selected or filtered results to CSV
- Rate limit UI gauges — authenticated read budget and write point budgets

---

### Phase 5 — Network Visualization
**Goal:** Surface the graph analysis visually.

- D3 force-directed graph view at `/graph`
- Nodes sized by FlowRank or followers count, colored by `community_id`
- Interactive: click node for profile card, double-click to expand neighborhood
- Filter controls to show/hide by tier, community, flag
- Performance cap: default render top-N by FlowRank; WebGL for larger graphs

---

### Phase 6 — Historical Tracking and Advanced Discovery
**Goal:** Enable time-based analysis and trend detection.

- Daily snapshots of follower counts and FlowRank for trend filtering ("Growth Rate," "Activity Spikes")
- "Risen from the Dead" detection — posted recently, previous post 365+ days ago
- Scheduled auto-sync via APScheduler or similar, replacing the always-on aggressive default
- Tiered staleness notification — surface to user when flags may be stale due to settings changes

---

## 7. Success Metrics

A future session should be considered successful when:

- All Phase 0 critical bugs are fixed and covered by tests
- Every setting in the UI demonstrably affects runtime behavior
- Every shipped feature is runnable end-to-end without errors
- `SESSION_HANDOFF.md` is updated before the session closes
- No bug fixed in a prior session is reintroduced
- No new feature is added while known bugs remain in the same subsystem
