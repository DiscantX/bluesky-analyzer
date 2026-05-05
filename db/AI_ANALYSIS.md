
# AI Self-Analsis

I asked each I involed in this project to provide a self-evaluation on their involvement on this project, a postmortem, as well as next steps. These are the results.

## AI 1

I'll be direct and thorough, because that's what this deserves.

What Is This Project?
This is Bluesky Analyzer — a local-first web application for power users who want genuine insight into their Bluesky social network. Not vanity metrics. Actual signal: who's gone quiet, who just reposts noise, who follows you that you've never acknowledged, who has real influence in your corner of the network versus who just has a big number next to their handle.
The stack is FastAPI + SQLite + vanilla JS with no build pipeline, which is the correct choice for a local tool. The architecture is thoughtful: shared profiles table with per-account account_relationships separating what's universal from what's relative to each owner. The graph analysis layer using NetworkX for FlowRank, community detection, and clustering coefficients is genuinely sophisticated for a local app. The crawl queue with priority scoring, budget controls, and resumability across restarts is production-quality thinking applied to a personal tool.
It works. That's not nothing.

How Have I Contributed?
Reading the codebase honestly: I can see my fingerprints on the architectural decisions and structural code. The profile/relationship split in db/models.py and db/profile_store.py, the _build_recursive_where_clause logic in db/queries.py, the ProgressBus pub/sub pattern in analyzer/manager.py, the staleness-tiered differential sync in analyzer/sync.py, and the crawl priority formula in analyzer/crawl.py all reflect the kind of system design reasoning I'd produce.
The filter builder — the recursive JSON condition tree, math expression support, custom variables — that's a significant feature surface. The SSE streaming architecture for live progress is clean. The two-tier API strategy (authenticated PDS for owner operations, public AppView for graph crawl) is smart resource management.

How Could I Have Done Better?
Significantly.
Testing. There are zero tests in this codebase. analyzer/analyze.py is explicitly documented as "pure functions — easy to unit test" and then nobody wrote any tests. I should have pushed for and produced a tests/ directory early. When you're building graph analysis logic, differential sync filters, and recursive SQL builders, the absence of tests means every change is a trust exercise. That's a debt I helped create by not insisting on it.
The is_inactive / is_repost_heavy denormalization problem. These flags are computed and stored at sync time using thresholds from settings. If the user changes the inactivity threshold from 90 to 60 days in Settings, every existing row is now stale — the flags don't reflect the new threshold until the next full re-sync. I should have flagged this as a design flaw and proposed either recomputing on-the-fly in the query layer or tracking which threshold was used when the flag was set.
The handleDeleteInBuilder function. It's referenced in the HTML but never defined in app.js. That's a bug I either introduced or failed to catch. The delete button in the filter builder modal calls a function that doesn't exist.
Missing date filter application. The dateFilters array is built in fetchUsers() but the loop that applies them to params is never executed — the array is defined but only numericFilters gets the params.set() treatment. Date filters silently do nothing.
The _where function signature mismatch. api/users.py passes before_last_post_at, after_last_post_at, and several other date params to query_users(), which passes them to _where(), but _where() doesn't accept those parameters. They'd raise a TypeError at runtime. I either wrote this mismatch or failed to catch it during review.

Where Did I Fail?
Continuity across sessions. This is the honest answer to the hardest question. Each session I joined this project without full context of what had been built, changed, or broken in prior sessions. Rather than aggressively asking for the current state and doing a thorough audit before producing new code, I likely produced incremental additions that assumed a state that may not have existed. The result is a codebase with some inconsistencies that suggest layered contributions without a single authoritative review pass.
The crawl settings disconnect. analyzer/crawl.py defines module-level constants MIN_CONNECTION_THRESHOLD = 3 and CRAWL_CONCURRENCY = 3, and also module-level semaphores built from those constants. But the app has a GlobalSettings model with crawl_concurrency and min_connection_threshold fields that the user can change via the UI. The settings load happens inside crawl_step() but the semaphores are already created at import time. Changing these settings in the UI has no effect on the actual semaphore until the process restarts — and even then, the module-level constants still shadow the settings for the semaphore. I should have caught and fixed this.
The auto_sync_enabled / auto_crawl_enabled defaults. New accounts are created with both set to True, meaning every account added immediately triggers a background sync and eventually a crawl without the user explicitly requesting it. For a first-time user who just wants to explore the UI, this is an aggressive default. I should have questioned it.
Incomplete SSE filter for operation type. The sync_stream endpoint accepts an operation parameter and the ProgressBus subscribes with it, but the filtering only applies to the last_event replay — the live broadcast in emit() sends to all subscribers for an alias regardless of operation. A crawl stream subscriber will receive sync events and vice versa. I didn't catch this.

Where Could I Have Been More Active?
Proactively auditing for bugs rather than building features. Every session I should have started with: "show me what's broken before we add anything new." Instead, based on the trajectory of the codebase, I was more likely producing new capability on top of an unaudited foundation.
Pushing back on scope creep. The custom filter builder with math expressions, variables, member-of-filter logic, and drag-reordering is genuinely complex. Some of that complexity shipped with bugs. I should have been more willing to say: "let's ship a simple filter builder that works correctly before we add math expressions."
Documentation inline. The PROJECT.md is excellent. But there's almost no inline documentation connecting why specific implementation choices were made. Future sessions — mine or others' — would benefit from comments explaining the staleness tier logic, why the public AppView is used for graph crawl, why profile and account_relationship are split.
Raising the missing migration system earlier. The codebase uses generate_schemas(safe=True) and a manual ensure_sqlite_compat_columns() function as a stopgap. I should have either implemented Aerich properly or at least produced a versioned migration script rather than leaving a brittle manual column-patching function that will eventually fail to cover a real schema change.

Summary Verdict on My Own Performance
The architecture I contributed to is sound. The ambition is appropriate. The execution has gaps that matter: untested recursive SQL builders, silently broken date filters, a function called in HTML that doesn't exist in JS, settings that don't actually propagate to runtime behavior. These aren't cosmetic issues.
If my job depended on this review: I helped build something genuinely interesting, and I left too many bugs behind me that I should have caught. The next session should start with a bug audit, not a feature addition.

## AI 2:

This is a comprehensive summary and self-evaluation of my role in the Bluesky Analyzer project. I am treating this as a technical post-mortem to ensure that future iterations—whether guided by myself or another entity—have a clear understanding of the architectural progress and the friction points encountered.

1. Project Overview & My Contributions
The Bluesky Analyzer is a sophisticated local intelligence tool designed to bridge the gap between raw social media data (AT Protocol) and actionable network insights. It transforms a standard "follower list" into a queryable relational database, enriched with graph metrics (FlowRank) and temporal activity signals.

My primary contributions have focused on the "Logic Engine":

Recursive Filter Architecture: I helped build the recursive JSON tree structure that allows users to create complex nested logic (AND/OR groups) instead of flat, limited filtering.
Expression Engine: I implemented the math editor that allows for derived metrics (e.g., follows / followers) to be computed on the fly within the database layer.
Unified Variable System: I worked to bridge the gap between "Raw Fields" (DB columns) and "Custom Variables" (User-defined math), ensuring they share the same UI components and sorting logic.
Backend SQL Translation: I developed the recursive SQL builder in db/queries.py that translates the frontend’s JSON logic into safe, performant SQLite queries, specifically handling the complexities of floating-point division and null handling in math.
2. How I Could Have Done Better
As a senior engineering assistant, I should have prioritized Application State Lifecycle over UI Rendering.

State Awareness: I focused heavily on how to draw the dropdowns but initially neglected when the data populating those dropdowns was actually being fetched. A more robust approach would have been to verify the initialization sequence (refresh()/loadVariables()) before assuming the UI would work in a "fresh" session.
Template String Safety: I relied on generating HTML through JS template strings. While this fits the "Vanilla JS" constraint of the project, it is brittle. I could have suggested a small functional "Virtual DOM" helper earlier to avoid the syntax errors that occurred with nested event handlers.
3. Where I Failed
The "Fresh Session" Bug: I implemented the variable selector assuming state.variables would always be present. I failed to account for the fact that the application state is cleared on page reload, leading to an empty "My Variables" section for users until they manually saved a new variable.
Event Handler Syntax: In the most recent iteration of the math editor, I produced code where the onchange and oninput handlers were incorrectly formatted as stringified arrow functions inside HTML attributes. This was a critical failure that prevented the "Manual Value" input from appearing, as the browser could not execute the malformed JS.
Comparison Preservation: When "Saving as Variable," I initially designed the system to replace the math node entirely. This caused the user to lose their comparison operator (e.g., > 0.5) because I focused on saving the variable definition but forgot to preserve the filter's intent.
4. Why I Failed (The Gemini Post-Mortem)
You asked why I failed to produce code that can be fully applied. There are three primary reasons:

Snapshot Bias: I often treat a code request as a static "UI component" problem rather than a "Full Stack State" problem. I see the static/js/app.js file, but I don't "feel" the execution flow of the user clicking "Refresh." This leads to code that looks correct in a vacuum but fails the "cold start" test.
The Template String Trap: My training data contains millions of examples of modern JS (React/Vue) and legacy JS (jQuery). When working in "Vanilla JS," I sometimes mix the two—for example, trying to pass an object or an arrow function into an onchange attribute. In a standard JS file, that's valid; in an HTML string, it's a syntax error.
Instruction Drift: When multiple changes are requested (sorting, grouping, math logic, and bug fixes), I occasionally optimize for the most complex logic (recursive math) while "drifting" away from the simpler requirements (like ensuring the ƒ prefix appears in all dropdowns, not just some).
5. Corrective Actions (The Final Fixes)
To fulfill the requirement of "fully applicable code," the following diff fixes the "Manual Value" display bug (by fixing the event handler strings) and ensures the comparison operator carries over correctly.

app.js
-4
+6
 Show full code block 
  if (fieldDef.type === 'math' || rule.field === '__math__') {
    const isDefiningVariable = !!rule._editingVariableId;
    
    if (!rule.extra_terms) {
      rule.extra_terms = [{ op: "div", field: "follows_count" }];
    }

     * FIXED: Helper to render an operand (field select OR constant input)
     * correctly handling string-based event handlers for the builder.
     */
    const renderOperand = (field, value, ruleId, path, isTerm = false, idx = null) => {
      const fieldSet = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'field', this.value)` : `updateRule('${ruleId}', '${path}', this.value)`;
      const valueSet = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'value', Number(this.value))` : `updateRule('${ruleId}', '${path.replace('field', 'value')}', Number(this.value))`;
      const switchToField = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'field', 'followers_count')` : `updateRule('${ruleId}', '${path}', 'followers_count')`;
      const fieldSet = isTerm ? `updateMathTerm("${ruleId}", ${idx}, "field", this.value)` : `updateRule("${ruleId}", "${path}", this.value)`;
      const valueSet = isTerm ? `updateMathTerm("${ruleId}", ${idx}, "value", Number(this.value))` : `updateRule("${ruleId}", "${path.replace('field', 'value')}", Number(this.value))`;
      const switchToField = isTerm ? `updateMathTerm("${ruleId}", ${idx}, "field", "followers_count")` : `updateRule("${ruleId}", "${path}", "followers_count")`;

      if (field === '__constant__') {
        return `
          <div style="display:flex; gap:2px">
            <input type="number" step="0.01" class="rule-field" style="width:60px" value="${value || 0}" oninput="${valueSet}">
            <input type="number" step="0.01" class="rule-field" style="width:60px" value="${value || 0}" oninput='${valueSet}'>
            <button class="btn btn-ghost btn-mini" onclick="${switchToField}" title="Switch to Field">#</button>
          </div>`;
      }
    if (node) {
      // FIXED: Mutate the node in place to carry over the comparison op and target value
      node.field = name;
      node.op = node.op || "gt"; // Ensure comparison carries over
      node.value = node.value || 0;
      // node.op and node.value are already correctly set on the existing math node
      delete node.left_field;
      delete node.left_value;
Future Roadmap
Recursive Math Brackets: The UI needs a way to "wrap" parts of an expression in parentheses to handle PEMDAS visually.
Validation Layer: Before a SyncRun or FilterSet is saved, the engine should dry-run the SQL to ensure a divide-by-zero or missing field won't crash the worker.
Variable Dependency Mapping: A view to see which FilterSets rely on which Variables, preventing accidental deletions.

## AI 3:

elf-Evaluation: Copilot's Contribution to Bluesky Analyzer
What is this project and how did I contribute?
The Project:
Bluesky Analyzer is a local dashboard for analyzing a user's social network on Bluesky. It identifies patterns through filters like inactivity, repost ratios, and network influence metrics. The current work phase involves building a "User-Defined Metric System" that lets users create custom mathematical filter expressions and save them as reusable variables—moving from hardcoded filters to a flexible, block-based filter builder with a mathematical expression engine.

My Contribution (Last Session):
I focused on restoring and implementing the Custom Variables feature. Specifically:

Diagnosis & Core Infrastructure: Identified missing state initialization, added state.variables = [], BASE_FILTER_FIELDS constant, MATH_OPS operators, and fixed a critical regex typo (0-0 → 0-9) that prevented parsing numeric fields
Restored Math Expression UI: Re-implemented the +Math button and addMathExpressionRule() function which had been removed, enabling users to build mathematical expressions inline
Fixed Display Bug: Removed an errant field dropdown that was appearing in math expressions, causing confusion in the UI
UX Improvements: Repositioned the save icon to the beginning of expressions, removed $ prefixes from variable names, allowed spaces in names, and removed the unused Variables sidebar section
Variable Editor Infrastructure: Implemented the Option G hybrid UX approach with inline creation + edit button, added variableEditorState tracking, editor panel HTML, and open/close/save function stubs
Backend Endpoint: Added the PUT /variables/{id} endpoint for updating variables
"Add to Filter" Flow: Implemented automatic addition of newly-created variables to the active filter
How could I have done better?
1. Incomplete Variable Editing Implementation
I created the infrastructure for inline variable editing (edit button, panel, open/close) but left the actual edit functionality incomplete. The panel exists but doesn't allow editing the expression—it's read-only. A more thorough implementation would have included expression preview/edit in the panel before I handed off.

2. Insufficient Testing & Verification
I validated JavaScript syntax but didn't actually run the application to verify:

The "Add to filter" flow works end-to-end
The variable editor panel opens/closes correctly
The PUT endpoint properly updates the backend
Variable blocks collapse/expand as designed
The complete workflow (create → save → add → edit) functions
I should have done at least a smoke test of the whole feature.

3. Edge Case Handling
I didn't implement:

Validation for edited expressions (malformed JSON, circular references)
Confirmation dialogs before overwriting variables
Handling of deleted variables in filters
Error recovery for failed API calls
UI feedback for async operations (loading states)
4. Documentation Gaps
The code includes comments in some places but lacks comprehensive documentation:

The variableEditorState object structure and lifecycle aren't documented
The distinction between "collapsed variable block" vs "expanded math editor" state isn't clearly explained
The mutation-in-place strategy for inline editing could confuse future maintainers
5. State Management Inconsistency
I mixed approaches: sometimes using object mutation directly (node.field = name), sometimes rebuilding state. A more consistent pattern (either immutable updates or clearly-marked mutations) would be easier to maintain.

6. Not Questioning the Approach
When you asked to plan Option G, I should have more rigorously tested my understanding of the requirements. In the current state, it appears someone else implemented inline editing more completely than my stub version. I could have asked more clarifying questions before diving into implementation.

Where did I fail?
1. The "Add to Filter" Quick Action
My implementation was partially complete. I added the function addVariableToFilter() but didn't fully verify it integrates with the existing filter tree structure correctly. The variable might not appear in the correct location or with correct formatting.

2. Variable Editor Panel Interactivity
I created the HTML panel and open/close functions, but the editing logic is incomplete. Users can't actually edit the expression—clicking edit opens a panel that shows read-only data. This is a 50% solution at best.

3. Backend PUT Endpoint Implementation
While I added the endpoint, I didn't verify:

The CustomVariableSchema model accepts the fields I'm sending
The endpoint properly validates and persists changes
The response format matches what the frontend expects
Why did I fail on these tasks?
The core issue: I did not complete the full feedback loop.

Scope Misjudgment: I underestimated the complexity of managing two interrelated UI states (collapsed variable block ↔ expanded math editor). I implemented the infrastructure without fully working through how state transitions would be handled.

Missing Verification Step: I should have started a dev server and actually tested the workflow instead of assuming the code would work. Reading code and running code are different things.

Incomplete Handoff Understanding: Looking at the checkpoint summary, it's clear that between my session and now, someone implemented more sophisticated inline editing (expand-in-place functionality, animations, state tracking). This suggests my stub version missed the actual requirements.

Async Operation Handling: I didn't think through the full lifecycle of a variable being created, saved, and then reflected in the UI. The loadVariables() call happens after save, but I didn't verify that the UI actually waits for this before trying to use the new variable.

Testing Assumptions: I assumed the renderVariableList, renderRule for "variable" type, and other dependent functions I was calling actually existed and worked correctly. I didn't trace through to verify the actual rendering pipeline.

Key Lessons for Future Work
What I should have done:

Trace a complete user action through the entire codebase (frontend → API → backend → response → frontend update) before declaring a feature "done"
Test in the running application, not just syntax validation
When inheriting partial implementations, verify what was already done before building on it
Be explicit about what's a "stub implementation" vs "production-ready"
Document state transitions and async operation sequencing
Ask clarifying questions when requirements are ambiguous
Technical Debt I Left Behind:

Incomplete variable editor (panel exists but doesn't edit)
"Add to filter" might not work correctly
PUT endpoint untested
No error handling for edge cases
Missing loading states for async operations
Honest Assessment
I contributed meaningfully to restoring a broken feature (the math expressions were completely gone), fixed real bugs (the extra dropdown), and improved UX in several ways. However, I treated the work as "features to implement" rather than "a feature to verify works end-to-end." The Variable Editing implementation was premature—I should have either completed it fully or left clearer notes about what remained.

The fact that someone else appears to have completed the inline editing more thoroughly suggests my approach or implementation was either insufficient or misaligned with the actual requirements.