/**
 * static/js/filter-builder.js
 *
 * Self-contained filter builder component. Manages:
 *   - FilterSet CRUD (create, edit, save, delete)
 *   - Custom Variable CRUD (create, edit, delete)
 *   - The condition tree builder UI
 *   - The variable manager modal
 *   - Field/variable resolution for use by other modules (chart studio, etc.)
 *
 * Public surface
 * ──────────────
 * All functions listed under "── Public API ──" below are assigned to
 * window.* so that existing HTML onclick="fn()" attributes continue to work
 * without any changes to index.html.
 *
 * Initialisation (call once from app.js DOMContentLoaded):
 *   FilterBuilder.init({
 *     api,          // async fn(path, opts) — shared API helper from app.js
 *     toast,        // fn(msg, type)        — shared toast helper from app.js
 *     logError,     // fn(msg, err)         — shared error logger from app.js
 *     getAlias,     // fn() → string        — returns state.activeAlias
 *     onFiltersChanged,  // fn(customFilters) — called after loadFilterSets()
 *     onVariablesChanged, // fn(variables)   — called after loadVariables()
 *   });
 *
 * Data accessors (call from app.js):
 *   FilterBuilder.getCustomFilters()   → array of saved FilterSets
 *   FilterBuilder.getVariables()       → array of saved CustomVariables
 *   FilterBuilder.getFilterFields()    → FILTER_FIELDS map (includes variables)
 *   FilterBuilder.renderFieldOptions(selectedValue, numericOnly) → HTML string
 */

// ── Injected dependencies (set by FilterBuilder.init) ────────────────────────
let _api       = null;
let _toast     = null;
let _logError  = null;
let _getAlias  = null;
let _onFiltersChanged  = null;
let _onVariablesChanged = null;

// ── Module-private state ──────────────────────────────────────────────────────
let _customFilters = [];
let _variables     = [];

let _builderState = {
    name: "",
    icon: "🔍",
    color: "#3b82f6",
    id: null,
    tree: { id: "root", op: "AND", conditions: [] },
};

let _variableEditorState = {
    isOpen: false,
    editingVariableId: null,
    editingExpression: null,
};

let _pendingVariableSaveRuleId  = null;
let _currentMathExpressionForVar = null;

// ── Field definitions ─────────────────────────────────────────────────────────

const BASE_FILTER_FIELDS = {
    // ── Relationship booleans ──
    "i_follow_them":         { label: "I Follow Them",       type: "boolean", group: "Relationship" },
    "they_follow_me":        { label: "They Follow Me",      type: "boolean", group: "Relationship" },
    "interacted_with_owner": { label: "Has Interacted",      type: "boolean", group: "Relationship" },
    "is_one_sided_follow":   { label: "One-Sided Follow",    type: "boolean", group: "Relationship" },
    "is_follower_only":      { label: "Follower Only",       type: "boolean", group: "Relationship" },
    "muted":                 { label: "Muted",               type: "boolean", group: "Relationship" },
    "blocked":               { label: "Blocked",             type: "boolean", group: "Relationship" },
    "__member__":            { label: "Member of Filter...", type: "member",  group: "Relationship" },

    // ── Activity booleans ──
    "is_inactive":           { label: "Is Inactive",         type: "boolean", group: "Activity" },
    "is_repost_heavy":       { label: "Is Repost Heavy",     type: "boolean", group: "Activity" },

    // ── Profile counts ──
    "followers_count":       { label: "Followers",           type: "number",  group: "Profile" },
    "follows_count":         { label: "Follows",             type: "number",  group: "Profile" },
    "posts_count":           { label: "Total Posts",         type: "number",  group: "Profile" },

    // ── Activity numbers ──
    "days_since_post":       { label: "Days Since Post",     type: "number",  group: "Activity" },
    "repost_ratio":          { label: "Repost Ratio",        type: "number",  group: "Activity" },
    "sampled_post_count":    { label: "Sampled Posts",       type: "number",  group: "Activity" },
    "repost_count":          { label: "Repost Count",        type: "number",  group: "Activity" },
    "original_post_count":   { label: "Original Posts",      type: "number",  group: "Activity" },

    // ── Graph / network metrics ──
    "flowrank_score":        { label: "FlowRank",            type: "number",  group: "Network" },
    "in_subgraph_degree":    { label: "In-Subgraph Degree",  type: "number",  group: "Network" },
    "clustering_coefficient":{ label: "Clustering Coeff.",   type: "number",  group: "Network" },
    "crawl_priority":        { label: "Crawl Priority",      type: "number",  group: "Network" },
    "community_id":          { label: "Community ID",        type: "number",  group: "Network" },

    // ── String fields ──
    "handle":                { label: "Handle",              type: "string",  group: "Profile" },
    "display_name":          { label: "Name",                type: "string",  group: "Profile" },
};

// Live copy — extended with user variables whenever they load
let FILTER_FIELDS = { ...BASE_FILTER_FIELDS };

const MATH_OPS = [
    { val: "add", label: "+" },
    { val: "sub", label: "−" },
    { val: "mul", label: "×" },
    { val: "div", label: "÷" },
];

const OPERATORS_BY_TYPE = {
    "boolean":  [{ val: "eq", label: "is" }],
    "number":   [
        { val: "eq", label: "=" }, { val: "neq", label: "≠" },
        { val: "gt", label: ">" }, { val: "gte", label: "≥" },
        { val: "lt", label: "<" }, { val: "lte", label: "≤" },
    ],
    "string":   [
        { val: "eq", label: "is" }, { val: "contains", label: "contains" },
        { val: "starts_with", label: "starts with" },
    ],
    "math":     [
        { val: "eq", label: "=" }, { val: "neq", label: "≠" },
        { val: "gt", label: ">" }, { val: "gte", label: "≥" },
        { val: "lt", label: "<" }, { val: "lte", label: "≤" },
    ],
    "variable": [
        { val: "eq", label: "=" }, { val: "neq", label: "≠" },
        { val: "gt", label: ">" }, { val: "gte", label: "≥" },
        { val: "lt", label: "<" }, { val: "lte", label: "≤" },
    ],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function _el(id) { return document.getElementById(id); }

function _alias() { return _getAlias(); }

function _findNode(tree, id) {
    if (tree.id === id) return tree;
    for (const c of tree.conditions) {
        if (c.id === id) return c;
        if (c.conditions) {
            const found = _findNode(c, id);
            if (found) return found;
        }
    }
    return null;
}

function _removeNodeRecursive(parent, id) {
    parent.conditions = parent.conditions.filter(c => c.id !== id);
    parent.conditions.forEach(c => { if (c.conditions) _removeNodeRecursive(c, id); });
}

function _generateId() {
    return Math.random().toString(36).substr(2, 9);
}

// ── Field option rendering ────────────────────────────────────────────────────
// This is public — chart studio and any future consumers call
// FilterBuilder.renderFieldOptions() directly.

function renderFieldOptions(selectedValue, numericOnly = false) {
    const vars = [];
    const groupedRaws = {};

    Object.entries(FILTER_FIELDS).forEach(([k, v]) => {
        if (k === "__math__") return;
        if (numericOnly && v.type !== "number" && v.type !== "variable" && v.type !== "math") return;

        if (v.type === "variable") {
            vars.push({ key: k, ...v });
        } else {
            const g = v.group || "Other";
            if (!groupedRaws[g]) groupedRaws[g] = [];
            groupedRaws[g].push({ key: k, ...v });
        }
    });

    const varOpts = vars
        .sort((a, b) => a.label.localeCompare(b.label))
        .map(v => `<option value="${v.key}" ${selectedValue === v.key ? "selected" : ""}>ƒ ${v.label}</option>`)
        .join("");

    const groupOrder = ["Relationship", "Profile", "Activity", "Network"];
    const sortedGroupNames = Object.keys(groupedRaws).sort((a, b) => {
        const iA = groupOrder.indexOf(a), iB = groupOrder.indexOf(b);
        if (iA !== -1 && iB !== -1) return iA - iB;
        if (iA !== -1) return -1;
        if (iB !== -1) return 1;
        return a.localeCompare(b);
    });

    const rawGroupsHtml = sortedGroupNames.map(g => {
        const opts = groupedRaws[g]
            .sort((a, b) => a.label.localeCompare(b.label))
            .map(v => `<option value="${v.key}" ${selectedValue === v.key ? "selected" : ""}>${v.label}</option>`)
            .join("");
        return `<optgroup label="${g}">${opts}</optgroup>`;
    }).join("");

    return `
        ${varOpts ? `<optgroup label="My Variables">${varOpts}</optgroup>` : ""}
        ${rawGroupsHtml}
        ${numericOnly ? `<optgroup label="Other"><option value="__constant__" ${selectedValue === "__constant__" ? "selected" : ""}>Manual Value (#)</option></optgroup>` : ""}
    `;
}

// Kept for backward compat — app.js called this name before the refactor
function renderNumericFieldOptions(selectedValue) {
    return renderFieldOptions(selectedValue, true);
}

// ── Variables ─────────────────────────────────────────────────────────────────

function updateFilterFieldsWithVariables() {
    FILTER_FIELDS = { ...BASE_FILTER_FIELDS };
    _variables.forEach(v => {
        FILTER_FIELDS[v.name] = { label: v.name, type: "variable", editable: true };
    });
}

async function loadVariables() {
    const alias = _alias();
    if (!alias) return;
    try {
        _variables = await _api(`/api/filters/${encodeURIComponent(alias)}/variables`);
        updateFilterFieldsWithVariables();
        _renderVariableList();
        if (_onVariablesChanged) _onVariablesChanged(_variables);
    } catch (e) {
        _logError("loadVariables failed:", e);
    }
}

function _renderVariableList() {
    const list = _el("variable-list");
    if (!list) return;
    list.innerHTML = _variables.map(v => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding: 0.4rem; border-bottom: 1px solid var(--border);">
            <span style="font-family: var(--mono); font-size: 0.8rem;">${v.name}</span>
            <button class="btn btn-danger btn-mini" onclick="deleteVariable(${v.id})">Delete</button>
        </div>
    `).join("") || '<div class="state-box" style="padding:1rem">No variables yet.</div>';
}

function openVariableManager() {
    _el("variable-modal").classList.add("open");
}

function closeVariableManager() {
    _el("variable-modal").classList.remove("open");
    _currentMathExpressionForVar = null;
    const btn = _el("var-save-btn");
    if (btn) btn.disabled = true;
}

function addVariableToFilter(variableName) {
    const newRule = {
        id: _generateId(),
        field: variableName,
        op: "gt",
        value: 0,
    };
    _builderState.tree.conditions.push(newRule);
    _renderBuilder();
    _toast(`"${variableName}" added to filter`);
}

async function deleteVariable(id) {
    if (!confirm("Delete variable? Filters using it will break.")) return;
    try {
        await _api(`/api/filters/${encodeURIComponent(_alias())}/variables/${id}`, { method: "DELETE" });
        await loadVariables();
    } catch (e) {
        _logError("deleteVariable failed:", e);
        _toast(e.message, "error");
    }
}

// Legacy stubs — kept so any lingering calls don't throw
function openVariableEditor(variableId, ruleId) {
    if (ruleId) { inlineEditVariable(ruleId); return; }
    openVariableManager();
}
function closeVariableEditor() { closeVariableManager(); }
function saveVariableEdits()   { closeVariableManager(); }

// ── FilterSet CRUD ────────────────────────────────────────────────────────────

async function loadFilterSets() {
    const alias = _alias();
    if (!alias) return;
    try {
        _customFilters = await _api(`/api/filters/${encodeURIComponent(alias)}`);
        if (_onFiltersChanged) _onFiltersChanged(_customFilters);
    } catch (e) {
        _logError("loadFilterSets failed:", e);
    }
}

async function deleteFilterSet(e, id) {
    e.stopPropagation();
    if (!confirm("Delete this filter?")) return;
    try {
        await _api(`/api/filters/${encodeURIComponent(_alias())}/${id}`, { method: "DELETE" });
        await loadFilterSets();
    } catch (e) {
        _logError("deleteFilterSet failed:", e);
        _toast(e.message, "error");
    }
}

async function saveFilterSet() {
    const name = _el("filter-name").value.trim();
    if (!name) return _toast("Name required", "error");

    const payload = {
        name,
        icon:           _el("filter-icon").value,
        color:          _el("filter-color").value,
        condition_tree: JSON.stringify(_builderState.tree),
    };

    try {
        if (_builderState.id) {
            await _api(`/api/filters/${encodeURIComponent(_alias())}/${_builderState.id}`, {
                method: "PUT",
                body: JSON.stringify(payload),
            });
            _toast("Filter updated!");
        } else {
            await _api(`/api/filters/${encodeURIComponent(_alias())}`, {
                method: "POST",
                body: JSON.stringify(payload),
            });
            _toast("Filter saved!");
        }
        closeFilterBuilder();
        await loadFilterSets();
    } catch (e) {
        _logError("saveFilterSet failed:", e);
        _toast(e.message, "error");
    }
}

async function handleDeleteInBuilder() {
    if (!_builderState.id) return;
    if (!confirm("Delete this filter?")) return;
    try {
        await _api(`/api/filters/${encodeURIComponent(_alias())}/${_builderState.id}`, { method: "DELETE" });
        await loadFilterSets();
        closeFilterBuilder();
    } catch (e) {
        _logError("handleDeleteInBuilder failed:", e);
        _toast(e.message, "error");
    }
}

// ── Builder modal open/close ──────────────────────────────────────────────────

function openFilterBuilder() {
    if (!_builderState.id) {
        _builderState = {
            name: "", icon: "🔍", color: "#3b82f6", id: null,
            tree: { id: "root", op: "AND", conditions: [] },
        };
    }

    _el("filter-name").value  = _builderState.name;
    _el("filter-icon").value  = _builderState.icon;
    _el("filter-color").value = _builderState.color;

    const deleteBtn = _el("filter-delete-btn");
    if (deleteBtn) deleteBtn.style.display = _builderState.id ? "block" : "none";

    _renderBuilder();
    _el("filter-modal").classList.add("open");
}

function editFilterSet(e, id) {
    e.stopPropagation();
    const f = _customFilters.find(x => x.id === id);
    if (!f) return;
    _builderState = {
        name: f.name,
        icon: f.icon,
        color: f.color,
        id: f.id,
        tree: typeof f.condition_tree === "string"
            ? JSON.parse(f.condition_tree)
            : f.condition_tree,
    };
    openFilterBuilder();
}

function closeFilterBuilder() {
    _el("filter-modal").classList.remove("open");
    // Reset id so next open() starts fresh
    _builderState.id = null;
}

// ── Tree rendering ────────────────────────────────────────────────────────────

function _renderBuilder() {
    const root = _el("builder-root");
    if (root) root.innerHTML = _renderGroup(_builderState.tree);
}

function _renderGroup(group) {
    return `
        <div class="builder-group" data-id="${group.id}">
            <div class="group-header">
                <select onchange="updateGroupOp('${group.id}', this.value)">
                    <option value="AND" ${group.op === "AND" ? "selected" : ""}>AND</option>
                    <option value="OR"  ${group.op === "OR"  ? "selected" : ""}>OR</option>
                </select>
                <button class="btn btn-ghost btn-mini" onclick="addRule('${group.id}')">+ Rule</button>
                <button class="btn btn-ghost btn-mini" onclick="addMathExpressionRule('${group.id}')" title="Create math expression">+ Math</button>
                <button class="btn btn-ghost btn-mini" onclick="addGroup('${group.id}')">+ Group</button>
                ${group.id !== "root"
                    ? `<button class="btn btn-danger btn-mini" onclick="removeNode('${group.id}')">×</button>`
                    : ""}
            </div>
            <div class="group-content">
                ${group.conditions.map(c =>
                    c.conditions ? _renderGroup(c) : _renderRule(c, group.id)
                ).join("")}
            </div>
        </div>`;
}

function _renderRule(rule, _groupId) {
    const fieldDef = FILTER_FIELDS[rule.field] || { type: "string" };
    const ops = OPERATORS_BY_TYPE[fieldDef.type] || [];

    // ── Member of Filter ──────────────────────────────────────────────────────
    if (fieldDef.type === "member") {
        const filterOpts = _customFilters
            .map(f => `<option value="${f.id}" ${rule.value == f.id ? "selected" : ""}>${f.icon} ${f.name}</option>`)
            .join("");
        return `
            <div class="builder-rule" data-id="${rule.id}">
                <select class="rule-field" onchange="updateRule('${rule.id}', 'field', this.value)">
                    ${renderFieldOptions(rule.field)}
                </select>
                <select class="rule-value" onchange="updateRule('${rule.id}', 'value', Number(this.value))" style="flex:1">
                    <option value="">Select a Filter...</option>
                    ${filterOpts}
                </select>
                <button class="btn btn-ghost btn-mini" onclick="removeNode('${rule.id}')">×</button>
            </div>`;
    }

    // ── Variable chip ─────────────────────────────────────────────────────────
    if (fieldDef.type === "variable") {
        const isEditable = !!fieldDef.editable;
        const pencilBtn = isEditable
            ? `<button class="var-chip-edit" onclick="inlineEditVariable('${rule.id}')" title="Edit expression">
                   <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                       <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
                   </svg>
               </button>`
            : "";
        return `
            <div class="builder-rule builder-rule--variable" data-id="${rule.id}">
                <div class="var-chip">
                    <span class="var-chip-icon">${isEditable ? "ƒ" : "#"}</span>
                    <select class="var-chip-select" onchange="updateRule('${rule.id}', 'field', this.value)">
                        ${renderFieldOptions(rule.field, true)}
                    </select>
                    ${pencilBtn}
                </div>
                <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
                    ${ops.map(o => `<option value="${o.val}" ${rule.op === o.val ? "selected" : ""}>${o.label}</option>`).join("")}
                </select>
                <input class="rule-value" type="number" step="0.01" value="${rule.value || ""}"
                       oninput="updateRule('${rule.id}', 'value', Number(this.value))">
                <button class="btn btn-ghost btn-mini" onclick="removeNode('${rule.id}')">×</button>
            </div>`;
    }

    // ── Math expression ───────────────────────────────────────────────────────
    if (fieldDef.type === "math" || rule.field === "__math__") {
        if (!rule.extra_terms) {
            rule.extra_terms = [{ op: "div", field: "follows_count" }];
        }

        const isDefiningVariable = !!rule._editingVariableId;

        const renderOperand = (field, value, ruleId, path, isTerm = false, idx = null) => {
            const fieldSet  = isTerm
                ? `updateMathTerm('${ruleId}', ${idx}, 'field', this.value)`
                : `updateRule('${ruleId}', '${path}', this.value)`;
            const valueSet  = isTerm
                ? `updateMathTerm('${ruleId}', ${idx}, 'value', Number(this.value))`
                : `updateRule('${ruleId}', '${path.replace("field", "value")}', Number(this.value))`;
            const switchToField = isTerm
                ? `updateMathTerm('${ruleId}', ${idx}, 'field', 'followers_count')`
                : `updateRule('${ruleId}', '${path}', 'followers_count')`;

            if (field === "__constant__") {
                return `
                    <div style="display:flex; gap:2px">
                        <input type="number" step="0.01" class="rule-field" style="width:60px"
                               value="${value || 0}" oninput="${valueSet}">
                        <button class="btn btn-ghost btn-mini" onclick="${switchToField}" title="Switch to Field">#</button>
                    </div>`;
            }
            return `
                <select class="rule-field" style="width:110px" onchange="${fieldSet}">
                    ${renderFieldOptions(field, true)}
                </select>`;
        };

        const termsHtml = rule.extra_terms.map((term, idx) => {
            const mathOpts = MATH_OPS
                .map(o => `<option value="${o.val}" ${term.op === o.val ? "selected" : ""}>${o.label}</option>`)
                .join("");
            return `
                <select class="rule-field" style="width:40px; font-weight:bold"
                        onchange="updateMathTerm('${rule.id}', ${idx}, 'op', this.value)">
                    ${mathOpts}
                </select>
                ${renderOperand(term.field, term.value, rule.id, null, true, idx)}
                ${rule.extra_terms.length > 1
                    ? `<button class="btn btn-ghost btn-mini" onclick="removeMathTerm('${rule.id}', ${idx})">×</button>`
                    : ""}`;
        }).join("");

        const saveBtn = rule._editingVariableId
            ? `<button class="btn btn-primary btn-mini" onclick="saveEditedVariable('${rule.id}', ${rule._editingVariableId})" title="Save changes">✓ Save</button>
               <button class="btn btn-ghost btn-mini"   onclick="cancelVariableEdit('${rule.id}', ${rule._editingVariableId})" title="Cancel">✕</button>`
            : `<button class="btn btn-ghost btn-mini" onclick="prepareVariableSave('${rule.id}')" title="Save as Variable">💾</button>`;

        const comparisonHtml = isDefiningVariable ? "" : `
            <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
                ${(OPERATORS_BY_TYPE["math"] || []).map(o =>
                    `<option value="${o.val}" ${rule.op === o.val ? "selected" : ""}>${o.label}</option>`
                ).join("")}
            </select>
            <input class="rule-value" type="number" step="0.01" value="${rule.value || ""}"
                   oninput="updateRule('${rule.id}', 'value', Number(this.value))">`;

        return `
            <div class="builder-rule builder-rule--math builder-rule--expanded" data-id="${rule.id}" style="flex-wrap: wrap;">
                ${saveBtn}
                ${renderOperand(rule.left_field, rule.left_value, rule.id, "left_field")}
                ${termsHtml}
                <button class="btn btn-ghost btn-mini" onclick="addMathTerm('${rule.id}')" title="Add term">+</button>
                ${comparisonHtml}
                <button class="btn btn-danger btn-mini" onclick="removeNode('${rule.id}')">×</button>
            </div>`;
    }

    // ── Standard rule ─────────────────────────────────────────────────────────
    return `
        <div class="builder-rule" data-id="${rule.id}">
            <select class="rule-field" onchange="updateRule('${rule.id}', 'field', this.value)">
                ${renderFieldOptions(rule.field)}
            </select>
            <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
                ${ops.map(o => `<option value="${o.val}" ${rule.op === o.val ? "selected" : ""}>${o.label}</option>`).join("")}
            </select>
            ${fieldDef.type === "boolean"
                ? `<select class="rule-value" onchange="updateRule('${rule.id}', 'value', this.value === 'true')">
                       <option value="true"  ${rule.value === true  ? "selected" : ""}>True</option>
                       <option value="false" ${rule.value === false ? "selected" : ""}>False</option>
                   </select>`
                : `<input class="rule-value"
                          type="${fieldDef.type === "number" ? "number" : "text"}"
                          value="${rule.value || ""}"
                          oninput="updateRule('${rule.id}', 'value', ${fieldDef.type === "number" ? "Number(this.value)" : "this.value"})">`}
            <button class="btn btn-ghost btn-mini" onclick="removeNode('${rule.id}')">×</button>
        </div>`;
}

// ── Tree mutation (all called from HTML onclicks) ─────────────────────────────

function addRule(groupId) {
    const group = _findNode(_builderState.tree, groupId);
    group.conditions.push({ id: _generateId(), field: "handle", op: "contains", value: "" });
    _renderBuilder();
}

function addMathExpressionRule(groupId) {
    const group = _findNode(_builderState.tree, groupId);
    group.conditions.push({
        id: _generateId(),
        field: "__math__",
        left_field: "followers_count",
        extra_terms: [{ op: "div", field: "follows_count" }],
        op: "lt",
        value: 0.5,
    });
    _renderBuilder();
    requestAnimationFrame(() => {
        const nodes = document.querySelectorAll(".builder-rule--math");
        const last = nodes[nodes.length - 1];
        if (last) {
            last.classList.add("builder-rule--animate-in");
            setTimeout(() => last.classList.remove("builder-rule--animate-in"), 400);
        }
    });
}

function addGroup(groupId) {
    const group = _findNode(_builderState.tree, groupId);
    group.conditions.push({ id: _generateId(), op: "AND", conditions: [] });
    _renderBuilder();
}

function removeNode(id) {
    _removeNodeRecursive(_builderState.tree, id);
    _renderBuilder();
}

function updateGroupOp(id, op) {
    _findNode(_builderState.tree, id).op = op;
}

function updateRule(id, key, val) {
    const node = _findNode(_builderState.tree, id);
    node[key] = val;
    if (key === "field") {
        const fieldDef = FILTER_FIELDS[val] || { type: "string" };
        node.op = "eq";
        if (fieldDef.type === "boolean")          node.value = true;
        else if (fieldDef.type === "number" || fieldDef.type === "variable") node.value = 0;
        else if (fieldDef.type === "math") {
            node.left_field  = "followers_count";
            node.extra_terms = [{ op: "div", field: "follows_count" }];
            node.op    = "lt";
            node.value = 0.5;
        } else node.value = "";
        _renderBuilder();
    }
}

function updateMathTerm(ruleId, termIdx, key, val) {
    const node = _findNode(_builderState.tree, ruleId);
    if (node.extra_terms?.[termIdx]) {
        node.extra_terms[termIdx][key] = val;
        _renderBuilder();
    }
}

function addMathTerm(ruleId) {
    const node = _findNode(_builderState.tree, ruleId);
    if (node.extra_terms) {
        node.extra_terms.push({ op: "mul", field: "followers_count" });
        _renderBuilder();
    }
}

function removeMathTerm(ruleId, termIdx) {
    const node = _findNode(_builderState.tree, ruleId);
    if (node.extra_terms?.length > 1) {
        node.extra_terms.splice(termIdx, 1);
        _renderBuilder();
    }
}

// ── Inline variable editing ───────────────────────────────────────────────────

function inlineEditVariable(ruleId) {
    const node = _findNode(_builderState.tree, ruleId);
    if (!node) return;

    const variable = _variables.find(v => v.name === node.field);
    if (!variable) return _toast("Variable not found", "error");

    let expr;
    try { expr = JSON.parse(variable.expression_tree); }
    catch { return _toast("Could not parse variable expression", "error"); }

    const savedOp    = node.op    || "gt";
    const savedValue = node.value || 0;

    node.field      = "__math__";
    node.left_field = expr.left_field || "followers_count";
    node.extra_terms = expr.extra_terms || [{ op: "div", field: "follows_count" }];
    node.op    = savedOp;
    node.value = savedValue;
    node._editingVariableId   = variable.id;
    node._editingVariableName = variable.name;

    _renderBuilder();
    requestAnimationFrame(() => {
        const ruleEl = document.querySelector(`.builder-rule[data-id="${ruleId}"]`);
        if (ruleEl) {
            ruleEl.classList.add("builder-rule--animate-in");
            setTimeout(() => ruleEl.classList.remove("builder-rule--animate-in"), 400);
        }
    });
}

async function saveEditedVariable(ruleId, variableId) {
    const node = _findNode(_builderState.tree, ruleId);
    if (!node) return;

    const variable = _variables.find(v => v.id === variableId);
    if (!variable) return;

    const newExpression = { left_field: node.left_field, extra_terms: node.extra_terms };

    try {
        await _api(`/api/filters/${encodeURIComponent(_alias())}/variables/${variableId}`, {
            method: "PUT",
            body: JSON.stringify({ name: variable.name, expression_tree: JSON.stringify(newExpression) }),
        });
        await loadVariables();

        const savedOp    = node.op;
        const savedValue = node.value;
        const varName    = node._editingVariableName || variable.name;

        node.field = varName;
        node.op    = savedOp;
        node.value = savedValue;
        delete node.left_field;
        delete node.extra_terms;
        delete node._editingVariableId;
        delete node._editingVariableName;

        _renderBuilder();
        requestAnimationFrame(() => {
            const ruleEl = document.querySelector(`.builder-rule[data-id="${ruleId}"]`);
            if (ruleEl) {
                ruleEl.classList.add("builder-rule--animate-in");
                setTimeout(() => ruleEl.classList.remove("builder-rule--animate-in"), 400);
            }
        });
        _toast(`Variable "${varName}" updated`);
    } catch (e) {
        _logError("saveEditedVariable failed:", e);
        _toast("Failed to save variable: " + e.message, "error");
    }
}

function cancelVariableEdit(ruleId, _variableId) {
    const node = _findNode(_builderState.tree, ruleId);
    if (!node) return;

    const varName = node._editingVariableName;
    if (!varName) { removeNode(ruleId); return; }

    const savedOp    = node.op;
    const savedValue = node.value;
    node.field = varName;
    node.op    = savedOp;
    node.value = savedValue;
    delete node.left_field;
    delete node.extra_terms;
    delete node._editingVariableId;
    delete node._editingVariableName;

    _renderBuilder();
}

// ── Variable save flow ────────────────────────────────────────────────────────

function prepareVariableSave(ruleId) {
    const node = _findNode(_builderState.tree, ruleId);
    _currentMathExpressionForVar = { left_field: node.left_field, extra_terms: node.extra_terms };
    _pendingVariableSaveRuleId   = ruleId;
    const btn = _el("var-save-btn");
    if (btn) btn.disabled = false;
    openVariableManager();
    _toast("Expression captured. Give it a name to save.");
}

async function saveCurrentExpressionAsVariable() {
    const nameRaw = _el("var-name-input").value.trim().replace(/[^a-zA-Z0-9 ]/g, "").trim();
    if (!nameRaw)                       return _toast("Name required (letters, numbers, spaces)", "error");
    if (!_currentMathExpressionForVar)  return;

    try {
        await _api(`/api/filters/${encodeURIComponent(_alias())}/variables`, {
            method: "POST",
            body: JSON.stringify({ name: nameRaw, expression_tree: JSON.stringify(_currentMathExpressionForVar) }),
        });

        _el("var-name-input").value = "";
        await loadVariables();

        const originRuleId = _pendingVariableSaveRuleId;
        if (originRuleId) {
            const node = _findNode(_builderState.tree, originRuleId);
            if (node) {
                node.field = nameRaw;
                delete node.left_field;
                delete node.left_value;
                delete node.extra_terms;
                delete node._editingVariableId;
                delete node._editingVariableName;
            }
            _pendingVariableSaveRuleId = null;
        }

        _renderBuilder();
        requestAnimationFrame(() => {
            const varRules = document.querySelectorAll(".builder-rule--variable");
            const last = varRules[varRules.length - 1];
            if (last) {
                last.classList.add("builder-rule--animate-in");
                setTimeout(() => last.classList.remove("builder-rule--animate-in"), 400);
            }
        });

        closeVariableManager();
        _toast(`Variable "${nameRaw}" saved!`);
    } catch (e) {
        _logError("saveCurrentExpressionAsVariable failed:", e);
        _toast(e.message, "error");
    }
}

// ── Public namespace ──────────────────────────────────────────────────────────

const FilterBuilder = {
    /**
     * Must be called once from app.js DOMContentLoaded before any other use.
     */
    init({ api, toast, logError, getAlias, onFiltersChanged, onVariablesChanged }) {
        _api                = api;
        _toast              = toast;
        _logError           = logError;
        _getAlias           = getAlias;
        _onFiltersChanged   = onFiltersChanged;
        _onVariablesChanged = onVariablesChanged;
    },

    // Data accessors ─────────────────────────────────────────────────────────
    getCustomFilters()      { return _customFilters; },
    getVariables()          { return _variables; },
    getFilterFields()       { return FILTER_FIELDS; },

    // These are also global functions (see window assignments below), but
    // exposing them on the namespace object lets the chart studio call them
    // without relying on globals.
    renderFieldOptions,
    loadFilterSets,
    loadVariables,
    updateFilterFieldsWithVariables,
};

window.FilterBuilder = FilterBuilder;

// ── Global function exposure ──────────────────────────────────────────────────
// Every function below is referenced by an onclick="..." attribute in
// index.html. They must remain on window. Do not remove any entry here
// without first updating the corresponding HTML.

Object.assign(window, {
    // Builder modal
    openFilterBuilder,
    editFilterSet,
    closeFilterBuilder,
    saveFilterSet,
    handleDeleteInBuilder,

    // Tree mutations
    addRule,
    addMathExpressionRule,
    addGroup,
    removeNode,
    updateRule,
    updateGroupOp,
    updateMathTerm,
    addMathTerm,
    removeMathTerm,

    // Inline variable editing
    inlineEditVariable,
    saveEditedVariable,
    cancelVariableEdit,

    // Variable save flow
    prepareVariableSave,
    saveCurrentExpressionAsVariable,

    // Variable manager modal
    openVariableManager,
    closeVariableManager,
    addVariableToFilter,
    deleteVariable,

    // FilterSet list actions (called from renderCustomFilters HTML in app.js)
    deleteFilterSet,

    // Legacy stubs
    openVariableEditor,
    closeVariableEditor,
    saveVariableEdits,
    renderNumericFieldOptions,
});