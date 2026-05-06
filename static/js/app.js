/* static/js/app.js */

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  accounts: [],
  activeAlias: null,
  stats: {},
  users: [],
  total: 0,
  loading: false,
  syncing: false,
  crawling: false,
  syncStream: null,
  crawlStream: null,
  statusTimer: null,
  customFilters: [],
  variables: [],
  lastUserFetch: 0,
  settings: {},

  // Filter / sort state — any new filter just gets added here
  filters: {
    search: "",
    // tab preset flags
    is_inactive: null,
    is_repost_heavy: null,
    is_one_sided_follow: null,
    is_follower_only: null,
    interacted_with_owner: null,
    i_follow_them: null,
    they_follow_me: null,
    muted: null,
    blocked: null,
    exclude_stubs: false,
    exclude_unanalyzed: false,
    is_stub: null, // New
    filter_tree: null,
    // numeric ranges
    min_days_inactive: null,
    min_repost_ratio: null,
    max_repost_ratio: null,
    min_followers: null,
    max_followers: null,
    min_sampled_post_count: null, // New
    max_sampled_post_count: null, // New
    min_repost_count: null, // New
    max_repost_count: null, // New
    min_original_post_count: null, // New
    max_original_post_count: null, // New
    min_crawl_priority: null, // New
    max_crawl_priority: null, // New
    min_clustering_coefficient: null, // New
    max_clustering_coefficient: null, // New
    // date ranges
    before_last_post_at: null, // New
    after_last_post_at: null, // New
    before_last_analyzed_at: null, // New
    after_last_analyzed_at: null, // New
    before_last_hydrated_at: null, // New
    after_last_hydrated_at: null, // New
    before_last_crawled_at: null, // New
    after_last_crawled_at: null, // New
    before_first_seen_at: null, // New
    after_first_seen_at: null, // New
  },
  sort: { by: "handle", dir: "asc" },
  pagination: { limit: 50, offset: 0 },
  activeTab: "all",
};

// Tab definitions — each sets a filter preset
const TABS = [
  { id: "all",        label: "All Profiles",     icon: "🌐", statKey: "graph_size",     filters: {} },
  { id: "follows",    label: "Follows",          icon: "👤", statKey: "total_follows",  filters: { i_follow_them: true } },
  { id: "followers",  label: "Followers",        icon: "👥", statKey: "total_followers",filters: { they_follow_me: true } },
  { id: "stubs",      label: "Stubs",            icon: "🔍", statKey: "stubs_count",    filters: { is_stub: true } },
  { id: "inactive",   label: "Inactive",          icon: "⏸", statKey: "inactive",       filters: { i_follow_them: true, is_inactive: true } },
  { id: "repost",     label: "Repost Heavy",      icon: "🔁", statKey: "repost_heavy",   filters: { i_follow_them: true, is_repost_heavy: true } },
  { id: "onesided",   label: "One-Sided",         icon: "↗",  statKey: "one_sided",      filters: { is_one_sided_follow: true } },
  { id: "followersonly", label: "Followers Only", icon: "↙",  statKey: "follower_only",  filters: { is_follower_only: true } },
  { id: "nointeract", label: "No Interactions",   icon: "💤", statKey: "no_interaction", filters: { i_follow_them: true, interacted_with_owner: false } },
];

const SORT_OPTIONS = [
  { value: "handle",          label: "Handle" },
  { value: "display_name",    label: "Name" },
  { value: "followers_count", label: "Followers" },
  { value: "follows_count",   label: "Following" },
  { value: "posts_count",     label: "Post Count" },
  { value: "sampled_post_count", label: "Sampled Posts" },
  { value: "repost_count",    label: "Reposts" },
  { value: "original_post_count", label: "Original Posts" },
  { value: "days_since_post", label: "Days Inactive" },
  { value: "repost_ratio",    label: "Repost %" },
  { value: "flowrank_score",  label: "FlowRank" },
  { value: "clustering_coefficient", label: "Clustering Coeff." },
  { value: "in_subgraph_degree", label: "In-Subgraph Degree" },
  { value: "crawl_priority",  label: "Crawl Priority" },
  { value: "last_post_at",    label: "Last Post" },
  { value: "last_analyzed_at",label: "Last Analyzed" },
  { value: "last_hydrated_at",label: "Last Hydrated" },
  { value: "last_crawled_at", label: "Last Crawled" },
  { value: "first_seen_at",   label: "First Seen" },
];

// Raw fields are built-in DB columns — not user-editable expressions.
// User-defined variables get { type: "variable", editable: true } added by updateFilterFieldsWithVariables().
const BASE_FILTER_FIELDS = {
  // ── Relationship booleans ──
  "i_follow_them":        { label: "I Follow Them",      type: "boolean", group: "Relationship" },
  "they_follow_me":       { label: "They Follow Me",     type: "boolean", group: "Relationship" },
  "interacted_with_owner":{ label: "Has Interacted",     type: "boolean", group: "Relationship" },
  "is_one_sided_follow":  { label: "One-Sided Follow",   type: "boolean", group: "Relationship" },
  "is_follower_only":     { label: "Follower Only",      type: "boolean", group: "Relationship" },
  "muted":                { label: "Muted",              type: "boolean", group: "Relationship" },
  "blocked":              { label: "Blocked",            type: "boolean", group: "Relationship" },
  "__member__":           { label: "Member of Filter...", type: "member",  group: "Relationship" },

  // ── Activity booleans (server-computed flags) ──
  "is_inactive":          { label: "Is Inactive",        type: "boolean", group: "Activity" },
  "is_repost_heavy":      { label: "Is Repost Heavy",    type: "boolean", group: "Activity" },

  // ── Profile counts (raw numbers) ──
  "followers_count":      { label: "Followers",          type: "number",  group: "Profile" },
  "follows_count":        { label: "Follows",            type: "number",  group: "Profile" },
  "posts_count":          { label: "Total Posts",        type: "number",  group: "Profile" },

  // ── Activity numbers ──
  "days_since_post":      { label: "Days Since Post",    type: "number",  group: "Activity" },
  "repost_ratio":         { label: "Repost Ratio",       type: "number",  group: "Activity" },
  "sampled_post_count":   { label: "Sampled Posts",      type: "number",  group: "Activity" },
  "repost_count":         { label: "Repost Count",       type: "number",  group: "Activity" },
  "original_post_count":  { label: "Original Posts",     type: "number",  group: "Activity" },

  // ── Graph / network metrics ──
  "flowrank_score":       { label: "FlowRank",           type: "number",  group: "Network" },
  "in_subgraph_degree":   { label: "In-Subgraph Degree", type: "number",  group: "Network" },
  "clustering_coefficient":{ label: "Clustering Coeff.", type: "number",  group: "Network" },
  "crawl_priority":       { label: "Crawl Priority",     type: "number",  group: "Network" },
  "community_id":         { label: "Community ID",       type: "number",  group: "Network" },

  // ── String fields ──
  "handle":               { label: "Handle",             type: "string",  group: "Profile" },
  "display_name":         { label: "Name",               type: "string",  group: "Profile" },
};

let FILTER_FIELDS = { ...BASE_FILTER_FIELDS };

const MATH_OPS = [
  { val: "add", label: "+" },
  { val: "sub", label: "−" },
  { val: "mul", label: "×" },
  { val: "div", label: "÷" }
];

const OPERATORS_BY_TYPE = {
  "boolean": [{ val: "eq", label: "is" }],
  "number": [
    { val: "eq", label: "=" }, { val: "neq", label: "≠" },
    { val: "gt", label: ">" }, { val: "gte", label: "≥" },
    { val: "lt", label: "<" }, { val: "lte", label: "≤" }
  ],
  "string": [
    { val: "eq", label: "is" }, { val: "contains", label: "contains" },
    { val: "starts_with", label: "starts with" }
  ],
  "math": [
    { val: "eq", label: "=" }, { val: "neq", label: "≠" },
    { val: "gt", label: ">" }, { val: "gte", label: "≥" },
    { val: "lt", label: "<" }, { val: "lte", label: "≤" }
  ],
  
  "variable": [
    { val: "eq", label: "=" }, { val: "neq", label: "≠" },
    { val: "gt", label: ">" }, { val: "gte", label: "≥" },
    { val: "lt", label: "<" }, { val: "lte", label: "≤" }
  ]
};

let builderState = {
  name: "",
  icon: "🔍",
  id: null, // New: to track if we're editing an existing filter
  color: "#3b82f6",
  tree: { id: "root", op: "AND", conditions: [] }
};

let variableEditorState = {
  isOpen: false,
  editingVariableId: null,
  editingExpression: null
};

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const error = new Error(err.detail || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

async function logError(msg, err) {
  console.error(msg, err);
  try {
    await fetch("/api/client-log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        level: "error",
        message: msg,
        context: {
          error: err?.message || err?.toString(),
          alias: state.activeAlias
        }
      })
    });
  } catch (e) {}
}

// ── Rendering helpers ─────────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
function fmt(n) { return n == null ? "—" : Number(n).toLocaleString(); }
function pct(r) { return r == null ? "—" : Math.round(r * 100) + "%"; }

function avatar(u) {
  if (u.avatar_url) {
    return `<img class="avatar" src="${u.avatar_url}" alt="" loading="lazy">`;
  }
  const letter = (u.display_name || u.handle || "?")[0].toUpperCase();
  return `<div class="avatar-placeholder">${letter}</div>`;
}

function badges(u) {
  const b = [];
  if (u.is_inactive)        b.push(`<span class="badge badge-inactive">⏸ ${u.days_since_post ?? "?"}d</span>`);
  if (u.is_repost_heavy)    b.push(`<span class="badge badge-repost">🔁 ${pct(u.repost_ratio)}</span>`);
  if (u.is_one_sided_follow)b.push(`<span class="badge badge-onesided">↗ one-sided</span>`);
  if (u.is_follower_only)   b.push(`<span class="badge badge-follower">↙ follows you</span>`);
  if (!u.interacted_with_owner && u.i_follow_them)
                            b.push(`<span class="badge badge-nointeract">💤 no interact</span>`);
  
  return b.join("");
}

function userRow(u) {
  return `
    <a class="user-row" href="${u.profile_url}" target="_blank" rel="noopener">
      <div class="user-grid">
        ${avatar(u)}
        <div class="user-name" title="${u.display_name}" style="min-width:0">${u.display_name || "—"}</div>
        <div class="user-handle" title="${u.handle}" style="min-width:0">@${u.handle}</div>
        <div class="col-stat">${fmt(u.followers_count)}</div>
        <div class="col-stat">${fmt(u.follows_count)}</div>
        <div class="col-stat">${u.days_since_post != null ? u.days_since_post + "d" : "—"}</div>
        <div class="col-stat">${pct(u.repost_ratio)}</div>
        <div class="col-stat">${fmt(u.posts_count)}</div>
        <div class="col-stat">${fmt(u.sampled_post_count)}</div>
        <div class="col-stat">${fmt(u.repost_count)}</div>
        <div class="col-stat">${fmt(u.original_post_count)}</div>
        <div class="col-stat" title="FlowRank Influence">💎 ${u.flowrank_score > 0 ? (u.flowrank_score * 1000).toFixed(4) : "—"}</div>
        <div class="col-stat" title="Community ID">🌐 ${u.community_id != null ? u.community_id : "—"}</div>
        <div class="col-date">${shortDate(u.last_post_at)}</div>
        <div class="col-date">${shortDate(u.last_analyzed_at)}</div>
      </div>
      <div class="badges-row">${badges(u)}</div>
    </a>`;
}

function shortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
}

// ── Stats strip ───────────────────────────────────────────────────────────────
function renderStats() {
  const s = state.stats;
  el("stat-follows").textContent   = fmt(s.total_follows);
  el("stat-followers").textContent = fmt(s.total_followers);
  el("stat-inactive").textContent  = fmt(s.inactive);
  el("stat-repost").textContent    = fmt(s.repost_heavy);
  el("stat-onesided").textContent  = fmt(s.one_sided);
  el("stat-nointeract").textContent= fmt(s.no_interaction);
  el("stat-discovered").textContent= fmt(s.graph_size);
  el("stat-stubs").textContent     = fmt(s.stubs_count); // New stat
  el("stat-analysed").textContent  = fmt(s.analysed);
  el("stat-pending").textContent   = fmt(s.pending);

  const synced = s.last_synced_at
    ? new Date(s.last_synced_at).toLocaleString()
    : "Never";
  el("last-synced").textContent = `Last synced: ${synced}`;

  // Prevent crawling until initial sync provides a seed
  const canCrawl = !!s.last_synced_at;
  el("crawl-btn").disabled = !canCrawl;
  el("crawl-btn").textContent = state.crawling ? "■ Stop Crawl" : "✨ Crawl";
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────
function renderNav() {
  const s = state.stats;
  const nav = el("nav-items");
  nav.innerHTML = TABS.map(tab => {
    const count = s[tab.statKey] ?? "";
    const active = state.activeTab === tab.id ? "active" : "";
    return `
      <div class="nav-item ${active}" data-tab="${tab.id}" onclick="selectTab('${tab.id}')">
        <span>${tab.icon}</span>
        <span>${tab.label}</span>
        ${count !== "" ? `<span class="nav-count">${fmt(count)}</span>` : ""}
      </div>`;
  }).join("") + `
    <div class="sidebar-label" style="margin-top: 1rem;">Visualization</div>
    <a class="nav-item" href="/graph/${state.activeAlias || ''}" style="text-decoration: none;">
      <span>🕸️</span>
      <span>Network Graph</span>
    </a>
  `;
}

function renderCustomFilters() {
  const wrap = el("custom-filters");
  if (!wrap) return;
  wrap.innerHTML = state.customFilters.map(f => `
    <div class="nav-item ${state.activeTab === 'custom-' + f.id ? 'active' : ''}" 
         onclick="selectCustomFilter(${f.id})">
      <span style="color:${f.color}">${f.icon || '🔍'}</span>
      <span style="flex:1;">${f.name}</span>
      <button class="btn-mini btn-ghost" onclick="editFilterSet(event, ${f.id})" style="margin-left:auto; border:none; opacity:0.4">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
      </button>
      <button class="btn-mini btn-ghost" onclick="deleteFilterSet(event, ${f.id})" style="margin-left:auto; border:none; opacity:0.4">×</button>
    </div>
  `).join("");
}

function renderHeader(label, field, isStat = false) {
  const active = state.sort.by === field;
  const dir = state.sort.dir === "asc" ? "↑" : "↓";
  return `
    <div class="header-col ${active ? 'active' : ''} ${isStat ? 'col-stat' : ''}" 
         onclick="sortByHeader('${field}')">
      ${label} ${active ? dir : ''}
    </div>`;
}

function sortByHeader(field) {
  if (state.sort.by === field) {
    state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
  } else {
    state.sort.by = field;
    // Default to DESC for numbers/dates, ASC for names
    const descDefaults = ["followers_count", "follows_count", "posts_count", "sampled_post_count", "repost_count", "original_post_count", "days_since_post", "repost_ratio", "flowrank_score", "clustering_coefficient", "in_subgraph_degree", "crawl_priority", "last_post_at", "last_analyzed_at", "last_hydrated_at", "last_crawled_at", "first_seen_at", "community_id"];
    state.sort.dir = descDefaults.includes(field) ? "desc" : "asc";
  }
  state.pagination.offset = 0;
  fetchUsers();
}

/**
 * Setup the infinite scroll listener for the user list.
 */
function initLazyLoading() {
  const list = el("user-list");
  if (!list) return;

  list.addEventListener("scroll", () => {
    // If we're already loading or have reached the end, do nothing
    if (state.loading || state.users.length >= state.total) return;

    const { scrollTop, scrollHeight, clientHeight } = list;
    
    // Trigger when user is within 200px of the bottom
    if (scrollTop + clientHeight >= scrollHeight - 200) {
      loadMoreUsers();
    }
  });
}

async function loadMoreUsers() {
  if (state.loading || state.users.length >= state.total) return;
  
  // Increment offset and fetch next batch
  state.pagination.offset += state.pagination.limit;
  await fetchUsers(true);
}

// ── User list ─────────────────────────────────────────────────────────────────
function renderUsers() {
  const list = el("user-list");

  if (state.loading && state.users.length === 0) {
    list.innerHTML = `<div class="state-box">Loading…</div>`;
    return;
  }
  if (state.users.length === 0) {
    list.innerHTML = `<div class="state-box">No users found. Try syncing or changing filters.</div>`;
    el("result-count").textContent = "0 results";
    return;
  }

  const headers = `
    <div class="user-list-header user-grid">
      <div></div>
      ${renderHeader("Name", "display_name")}
      ${renderHeader("Handle", "handle")}
      ${renderHeader("Followers", "followers_count", true)}
      ${renderHeader("Following", "follows_count", true)}
      ${renderHeader("Inactive", "days_since_post", true)}
      ${renderHeader("Repost %", "repost_ratio", true)}
      ${renderHeader("Posts", "posts_count", true)}
      ${renderHeader("Sampled", "sampled_post_count", true)}
      ${renderHeader("Reposts", "repost_count", true)}
      ${renderHeader("Originals", "original_post_count", true)}
      ${renderHeader("Rank", "flowrank_score", true)}
      ${renderHeader("Grp", "community_id", true)}
      ${renderHeader("Last Post", "last_post_at", true)}
      ${renderHeader("Analyzed", "last_analyzed_at", true)}
    </div>
  `;

  list.innerHTML = headers + state.users.map(userRow).join("");
  el("result-count").textContent = `${fmt(state.total)} results`;
}

// ── Account switcher pills ────────────────────────────────────────────────────
function renderAccountPills() {
  const wrap = el("account-pills");
  if (state.accounts.length === 0) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = state.accounts.map(a => `
    <button class="account-pill ${a.alias === state.activeAlias ? "active" : ""}"
            onclick="switchAccount('${a.alias}')"
            title="Alias: ${a.alias}">
      @${a.handle}
    </button>`).join("");
  
  const activeAcc = state.accounts.find(a => a.alias === state.activeAlias);
  if (activeAcc) {
    el("auto-crawl-toggle").checked = activeAcc.auto_crawl_enabled;
  }
}

// ── Fetch data from API ───────────────────────────────────────────────────────
async function fetchStats() {
  if (!state.activeAlias) return;
  try {
    state.stats = await api(`/api/users/${state.activeAlias}/stats`);
    renderStats();
    renderNav();
  } catch (e) {
    logError("fetchStats failed:", e);
  }
}

async function fetchUsers(append = false, silent = false) {
  if (!state.activeAlias) return;
  state.loading = true;
  state.lastUserFetch = Date.now();
  
  // Hard reset: only clear and reset offset if it's not an append or a silent refresh
  if (!append && !silent) {
    state.pagination.offset = 0;
    state.users = [];
    renderUsers();
  }

  const params = new URLSearchParams();
  const limit = append ? state.pagination.limit : Math.max(state.pagination.limit, state.users.length);
  const offset = append ? state.pagination.offset : 0;

  if (state.filters.filter_tree) {
    params.set("filter_tree", JSON.stringify(state.filters.filter_tree));
  }

  if (state.filters.search) params.set("search", state.filters.search);
  params.set("sort_by", state.sort.by);
  params.set("sort_dir", state.sort.dir);
  params.set("limit", limit);
  params.set("offset", offset);

  // Boolean filters — only send when not null
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner","muted","blocked", 
    "exclude_stubs", "exclude_unanalyzed", "is_stub"
  ];
  for (const key of boolFlags) {
    if (state.filters[key] !== null && state.filters[key] !== undefined) {
      params.set(key, state.filters[key]);
    }
  }

  // Numeric range filters
  const numericFilters = [
    "min_days_inactive","min_repost_ratio","max_repost_ratio",
    "min_followers","max_followers",
    "min_sampled_post_count","max_sampled_post_count", // New
    "min_repost_count","max_repost_count", // New
    "min_original_post_count","max_original_post_count", // New
    "min_crawl_priority","max_crawl_priority", // New
    "min_clustering_coefficient","max_clustering_coefficient", // New
  ];
  const dateFilters = [
    "before_last_post_at","after_last_post_at",
    "before_last_analyzed_at","after_last_analyzed_at",
    "before_last_hydrated_at","after_last_hydrated_at", // New
    "before_last_crawled_at","after_last_crawled_at", // New
    "before_first_seen_at","after_first_seen_at", // New
  ];
  for (const key of numericFilters) {
    if (state.filters[key] != null) params.set(key, state.filters[key]);
  }
  for (const key of dateFilters) {
    if (state.filters[key] != null) params.set(key, state.filters[key]);
  }

  try {
    const data = await api(`/api/users/${state.activeAlias}?${params}`);
    
    if (append) {
      state.users = [...state.users, ...data.users];
    } else {
      state.users = data.users;
    }
    state.total = data.total;
  } catch (e) {
    logError("fetchUsers failed:", e);
    toast(e.message, "error");
  }

  state.loading = false;
  renderUsers();
}

async function refresh() {
  await fetchStats();
  await loadFilterSets();
  await loadVariables();
  await fetchUsers(false, true);
}

async function reconcileOperationStatus() {
  if (!state.activeAlias) return;
  try {
    const status = await api(`/api/sync/${state.activeAlias}/status`);
    const sync = status.sync;
    const crawl = status.crawl;

    if (sync?.status === "running" && status.sync_running && !state.syncing) {
      state.syncing = true;
      el("sync-btn").disabled = true;
      showSyncBar("Sync running…", null);
      attachSyncStream();
    } else if (!status.sync_running && state.syncing) {
      state.syncing = false;
      if (state.syncStream) {
        state.syncStream.close();
        state.syncStream = null;
      }
      el("sync-btn").disabled = false;
    }

    if (crawl?.status === "running" && crawl?.is_running) {
      state.crawling = true;
      showSyncBar(crawl.last_message || "Expanding network (Discovery)…", null);
      if (!state.crawlStream) attachCrawlStream();
      renderStats();
    } else if (!crawl?.is_running && state.crawling) {
      state.crawling = false;
      if (state.crawlStream) {
        state.crawlStream.close();
        state.crawlStream = null;
      }
      renderStats();
    }
  } catch (e) {
    logError("reconcileOperationStatus failed:", e);
  }
}

function startStatusWatcher() {
  clearInterval(state.statusTimer);
  state.statusTimer = setInterval(reconcileOperationStatus, 2500);
}

// ── Tab selection ─────────────────────────────────────────────────────────────
function selectTab(tabId) {
  const tab = TABS.find(t => t.id === tabId);
  if (!tab) return;

  state.activeTab = tabId;
  state.pagination.offset = 0;

  // Reset all filter flags and logic trees, then apply tab preset
  state.filters.filter_tree = null;
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner","muted","blocked",
    "is_stub", // New
  ];
  for (const key of boolFlags) state.filters[key] = null;
  Object.assign(state.filters, tab.filters);

  renderCustomFilters();
  renderNav();
  fetchUsers();
}

function selectCustomFilter(id) {
  const f = state.customFilters.find(x => x.id === id);
  if (!f) return;
  state.activeTab = 'custom-' + id;
  for (let k in state.filters) state.filters[k] = null;
  state.filters.filter_tree = typeof f.condition_tree === 'string' ? JSON.parse(f.condition_tree) : f.condition_tree;
  renderNav();
  renderCustomFilters();
  fetchUsers();
}

function onToggleExcludeStubs(enabled) {
  state.filters.exclude_stubs = enabled;
  state.pagination.offset = 0;
  fetchUsers();
}

function onToggleExcludeUnanalyzed(enabled) {
  state.filters.exclude_unanalyzed = enabled;
  state.pagination.offset = 0;
  fetchUsers();
}

// ── Account switching ─────────────────────────────────────────────────────────
async function switchAccount(alias) {
  state.activeAlias = alias;
  state.users = [];
  state.stats = {};
  state.activeTab = "follows";

  // Reset filters to "all follows" default
  for (const key of Object.keys(state.filters)) state.filters[key] = null;
  state.filters.i_follow_them = true;
  state.filters.exclude_stubs = false;
  state.filters.exclude_unanalyzed = false;
  state.filters.is_stub = null; // New
  if (el("exclude-stubs-toggle")) el("exclude-stubs-toggle").checked = false;
  if (el("exclude-unanalyzed-toggle")) el("exclude-unanalyzed-toggle").checked = false;

  renderAccountPills();
  renderNav();
  renderUsers();
  await refresh();
  await reconcileOperationStatus();
}

async function toggleAutoCrawl(enabled) {
  if (!state.activeAlias) return;
  try {
    await api(`/api/accounts/${state.activeAlias}/settings?auto_crawl=${enabled}`, { method: "PATCH" });
    const acc = state.accounts.find(a => a.alias === state.activeAlias);
    if (acc) acc.auto_crawl_enabled = enabled;
    toast(`Auto-crawl ${enabled ? "enabled" : "disabled"} for ${state.activeAlias}`);
  } catch (e) {
    logError("toggleAutoCrawl failed:", e);
    toast(e.message, "error");
    el("auto-crawl-toggle").checked = !enabled;
  }
}

// ── Sync ──────────────────────────────────────────────────────────────────────
async function startSync() {
  if (!state.activeAlias || state.syncing) return;
  state.syncing = true;

  el("sync-btn").disabled = true;
  showSyncBar("Starting sync…", 0);

  try {
    await api(`/api/sync/${state.activeAlias}`, { method: "POST" });
  } catch (e) {
    if (e.status !== 409) {
        logError("startSync failed:", e);
        toast(e.message, "error");
        endSync();
        return;
    }
    // If 409, it's already running, so just connect to the stream
    toast("Sync already in progress, attaching to stream...");
  }

  attachSyncStream();
}

function attachSyncStream() {
  if (state.syncStream) {
    state.syncStream.close();
  }

  const es = new EventSource(`/api/sync/${state.activeAlias}/stream?operation=sync`);
  state.syncStream = es;

  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);

    if (data.kind === "progress") {
      showSyncBar(data.message, data.pct);
      fetchStats();
      // Throttle user list updates during sync to once every 2 seconds
      if (Date.now() - state.lastUserFetch > 2000) {
        fetchUsers(false, true);
      }
    } else if (data.kind === "phase") {
      showSyncBar(data.message, null);
    } else if (data.kind === "done") {
      es.close();
      state.syncStream = null;
      showSyncBar("Sync complete!", 100);
      setTimeout(() => {
        hideSyncBar();
        endSync();
        refresh();
        reconcileOperationStatus();
        toast("Sync complete!");
      }, 800);
    } else if (data.kind === "error") {
      es.close();
      state.syncStream = null;
      hideSyncBar();
      endSync();
      toast("Sync error: " + data.message, "error");
    }
  };

  es.onerror = () => {
    es.close();
    state.syncStream = null;
    hideSyncBar();
    endSync();
    toast("Lost connection to sync stream.", "error");
  };
}

function endSync() {
  state.syncing = false;
  el("sync-btn").disabled = false;
}

function showSyncBar(message, pct) {
  const bar = el("sync-bar");
  bar.classList.add("visible");
  el("sync-bar-text").textContent = message;
  if (pct != null) {
    el("progress-fill").style.width = pct + "%";
  }
}

function hideSyncBar() {
  el("sync-bar").classList.remove("visible");
  el("progress-fill").style.width = "0%";
}

async function startCrawl() {
  if (!state.activeAlias) return;
  if (state.crawling) {
    await stopCrawl();
    return;
  }
  state.crawling = true;

  renderStats();
  showSyncBar("Expanding network (Discovery)…", 0);

  try {
    await api(`/api/sync/${state.activeAlias}/crawl`, { method: "POST" });
  } catch (e) {
    if (e.status !== 409) {
        logError("startCrawl failed:", e);
        toast(e.message, "error");
        state.crawling = false;
        renderStats();
        return;
    }
    toast("Crawl already in progress, attaching to stream...");
  }

  attachCrawlStream();
}

function attachCrawlStream() {
  if (state.crawlStream) {
    state.crawlStream.close();
  }

  const es = new EventSource(`/api/sync/${state.activeAlias}/stream?operation=crawl`);
  state.crawlStream = es;
  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.kind === "progress" || data.kind === "phase") {
      showSyncBar(data.message, data.pct ?? null);
      fetchStats();
      if (Date.now() - state.lastUserFetch > 2000) {
        fetchUsers(false, true);
      }
    } else if (data.kind === "done") {
      es.close();
      state.crawlStream = null;
      showSyncBar("Crawl complete!", 100);
      setTimeout(() => {
        hideSyncBar();
        state.crawling = false;
        renderStats();
        refresh();
        toast("Network expansion complete!");
      }, 800);
    } else if (data.kind === "error") {
      es.close();
      state.crawlStream = null;
      hideSyncBar();
      state.crawling = false;
      renderStats();
      toast("Crawl error: " + data.message, "error");
    }
  };

  es.onerror = () => {
    es.close();
    state.crawlStream = null;
    hideSyncBar();
    state.crawling = false;
    renderStats();
    toast("Lost connection to crawl stream.", "error");
  };
}

async function stopCrawl() {
  if (!state.activeAlias) return;
  try {
    await api(`/api/sync/${state.activeAlias}/crawl/stop`, { method: "POST" });
    toast("Crawl stopped.");
  } catch (e) {
    logError("stopCrawl failed:", e);
    toast(e.message, "error");
  } finally {
    if (state.crawlStream) {
      state.crawlStream.close();
      state.crawlStream = null;
    }
    state.crawling = false;
    hideSyncBar();
    renderStats();
  }
}

// ── Add Account modal ─────────────────────────────────────────────────────────
function openAddAccount() {
  el("modal").classList.add("open");
  el("modal-alias").focus();
}

function closeAddAccount() {
  el("modal").classList.remove("open");
  el("modal-alias").value = "";
  el("modal-handle").value = "";
  el("modal-password").value = "";
}

async function submitAddAccount() {
  const alias    = el("modal-alias").value.trim();
  const handle   = el("modal-handle").value.trim().replace(/^@/, "");
  const password = el("modal-password").value.trim();

  if (!alias || !handle || !password) {
    toast("All fields are required.", "error");
    return;
  }

  try {
    await api("/api/accounts/", {
      method: "POST",
      body: JSON.stringify({ alias, handle, app_password: password }),
    });
    closeAddAccount();
    toast(`Account @${handle} saved.`);
    await loadAccounts();
    if (!state.activeAlias) switchAccount(alias);
  } catch (e) {
    logError("submitAddAccount failed:", e);
    toast(e.message, "error");
  }
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function openSettings() {
  try {
    state.settings = await api("/api/settings/");
    el("set-inactivity").value = state.settings.inactivity_threshold_days;
    el("set-repost").value     = state.settings.repost_ratio_threshold;
    el("set-sample").value     = state.settings.feed_sample_size;
    el("set-staleness").value  = state.settings.sync_staleness_hours;
    el("set-sweep").value      = state.settings.worker_sweep_interval_seconds;
    el("set-min-conn").value   = state.settings.min_connection_threshold;
    el("set-crawl-conc").value = state.settings.crawl_concurrency;
    el("set-budget").value     = state.settings.crawl_budget_mb;

    el("settings-modal").classList.add("open");
  } catch (e) {
    toast("Failed to load settings", "error");
  }
}

function closeSettings() {
  el("settings-modal").classList.remove("open");
}

async function submitSettings() {
  const payload = {
    inactivity_threshold_days:     parseInt(el("set-inactivity").value),
    repost_ratio_threshold:        parseFloat(el("set-repost").value),
    feed_sample_size:              parseInt(el("set-sample").value),
    sync_staleness_hours:          parseInt(el("set-staleness").value),
    worker_sweep_interval_seconds: parseInt(el("set-sweep").value),
    min_connection_threshold:      parseInt(el("set-min-conn").value),
    crawl_concurrency:             parseInt(el("set-crawl-conc").value),
    crawl_budget_mb:               parseInt(el("set-budget").value),
  };
  try {
    await api("/api/settings/", { method: "PATCH", body: JSON.stringify(payload) });
    toast("Settings saved (restart may be required for some values)");
    closeSettings();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ── Accounts loading ──────────────────────────────────────────────────────────
async function loadAccounts() {
  state.accounts = await api("/api/accounts/");
  renderAccountPills();

  if (state.accounts.length > 0 && !state.activeAlias) {
    await switchAccount(state.accounts[0].alias);
  } else {
    renderUsers();
  }
}

// ── Search & sort event handlers ──────────────────────────────────────────────
let searchTimer = null;
function onSearch(val) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.filters.search = val;
    state.pagination.offset = 0;
    fetchUsers();
  }, 280);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(message, type = "info") {
  const wrap = el("toast-wrap");
  const t = document.createElement("div");
  t.className = `toast ${type === "error" ? "error" : ""}`;
  t.textContent = message;
  wrap.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

// ── Filter Builder Logic ──────────────────────────────────────────────────────
function openFilterBuilder() {
  // Reset builderState for a new filter, or populate if editing
  if (!builderState.id) { // If no ID, it's a new filter
    builderState = { name: "", icon: "🔍", color: "#3b82f6", id: null, tree: { id: "root", op: "AND", conditions: [] } };
  }

  el("filter-name").value = builderState.name;
  el("filter-icon").value = builderState.icon;
  el("filter-color").value = builderState.color;
  
  // Show delete button only when editing an existing filter
  const deleteBtn = el("filter-delete-btn");
  if (builderState.id) {
    deleteBtn.style.display = "block";
  } else {
    deleteBtn.style.display = "none";
  }
  
  renderBuilder();
  el("filter-modal").classList.add("open");
}

function editFilterSet(e, id) {
  e.stopPropagation(); // Prevent triggering selectCustomFilter
  const f = state.customFilters.find(x => x.id === id);
  if (!f) return;
  builderState = { name: f.name, icon: f.icon, color: f.color, id: f.id, tree: typeof f.condition_tree === 'string' ? JSON.parse(f.condition_tree) : f.condition_tree };
  openFilterBuilder();
}

function closeFilterBuilder() { el("filter-modal").classList.remove("open"); }

function renderBuilder() {
  const root = el("builder-root");
  root.innerHTML = renderGroup(builderState.tree);
}

function renderGroup(group) {
  return `
    <div class="builder-group" data-id="${group.id}">
      <div class="group-header">
        <select onchange="updateGroupOp('${group.id}', this.value)">
          <option value="AND" ${group.op === 'AND' ? 'selected' : ''}>AND</option>
          <option value="OR" ${group.op === 'OR' ? 'selected' : ''}>OR</option>
        </select>
        <button class="btn btn-ghost btn-mini" onclick="addRule('${group.id}')">+ Rule</button>
        <button class="btn btn-ghost btn-mini" onclick="addMathExpressionRule('${group.id}')" title="Create math expression">+ Math</button>
        <button class="btn btn-ghost btn-mini" onclick="addGroup('${group.id}')">+ Group</button>
        ${group.id !== 'root' ? `<button class="btn btn-danger btn-mini" onclick="removeNode('${group.id}')">×</button>` : ''}
      </div>
      <div class="group-content">
        ${group.conditions.map(c => c.conditions ? renderGroup(c) : renderRule(c, group.id)).join("")}
      </div>
    </div>`;
}

function renderRule(rule, groupId) {
  const fieldDef = FILTER_FIELDS[rule.field] || { type: "string" };
  const ops = OPERATORS_BY_TYPE[fieldDef.type] || [];

  // ── Member of Filter Logic ──
  if (fieldDef.type === 'member') {
    const filterOpts = state.customFilters.map(f => `<option value="${f.id}" ${rule.value == f.id ? 'selected' : ''}>${f.icon} ${f.name}</option>`).join("");
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

  // ── Variable (Saved Expression) Logic ──
  // Shows as a collapsed chip. Dropdown includes all raw fields + user variables.
  // Pencil only appears for user-defined (editable) variables.
  if (fieldDef.type === 'variable') {
    const isEditable = !!fieldDef.editable;

    const pencilBtn = isEditable
      ? `<button class="var-chip-edit" onclick="inlineEditVariable('${rule.id}')" title="Edit expression">
           <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
         </button>`
      : ``;

    return `
      <div class="builder-rule builder-rule--variable" data-id="${rule.id}">
        <div class="var-chip">
          <span class="var-chip-icon">${isEditable ? 'ƒ' : '#'}</span>
          <select class="var-chip-select" onchange="updateRule('${rule.id}', 'field', this.value)">
            ${renderFieldOptions(rule.field, true)}
          </select>
          ${pencilBtn}
        </div>
        <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
          ${ops.map(o => `<option value="${o.val}" ${rule.op === o.val ? 'selected' : ''}>${o.label}</option>`).join("")}
        </select>
        <input class="rule-value" type="number" step="0.01" value="${rule.value || ''}"
               oninput="updateRule('${rule.id}', 'value', Number(this.value))">
        <button class="btn btn-ghost btn-mini" onclick="removeNode('${rule.id}')">×</button>
      </div>`;
  }

  // ── Math Expression Logic ──
  if (fieldDef.type === 'math' || rule.field === '__math__') {
    const isDefiningVariable = !!rule._editingVariableId;
    
    if (!rule.extra_terms) {
      rule.extra_terms = [{ op: "div", field: "follows_count" }];
    }

    /**
     * FIXED: Helper to render an operand (field select OR constant input)
     * correctly handling string-based event handlers for the builder.
     */
    const renderOperand = (field, value, ruleId, path, isTerm = false, idx = null) => {
      const fieldSet = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'field', this.value)` : `updateRule('${ruleId}', '${path}', this.value)`;
      const valueSet = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'value', Number(this.value))` : `updateRule('${ruleId}', '${path.replace('field', 'value')}', Number(this.value))`;
      const switchToField = isTerm ? `updateMathTerm('${ruleId}', ${idx}, 'field', 'followers_count')` : `updateRule('${ruleId}', '${path}', 'followers_count')`;

      if (field === '__constant__') {
        return `
          <div style="display:flex; gap:2px">
            <input type="number" step="0.01" class="rule-field" style="width:60px" value="${value || 0}" oninput="${valueSet}">
            <button class="btn btn-ghost btn-mini" onclick="${switchToField}" title="Switch to Field">#</button>
          </div>`;
      }
      return `
        <select class="rule-field" style="width:110px" onchange="${fieldSet}">
          ${renderFieldOptions(field, true)}
        </select>`;
    };

    const termsHtml = rule.extra_terms.map((term, idx) => {
      const mathOpts = MATH_OPS.map(o => `<option value="${o.val}" ${term.op === o.val ? 'selected' : ''}>${o.label}</option>`).join("");
      const operandHtml = renderOperand(term.field, term.value, rule.id, null, true, idx);

      return `
        <select class="rule-field" style="width:40px; font-weight:bold" onchange="updateMathTerm('${rule.id}', ${idx}, 'op', this.value)">
          ${mathOpts}
        </select>
        ${operandHtml}
        ${rule.extra_terms.length > 1 ? `<button class="btn btn-ghost btn-mini" onclick="removeMathTerm('${rule.id}', ${idx})">×</button>` : ''}
      `;
    }).join("");

    // If this rule is being edited from an existing variable, show a "save back" button
    const editingVarId = rule._editingVariableId || null;
    const saveBtn = editingVarId
      ? `<button class="btn btn-primary btn-mini" onclick="saveEditedVariable('${rule.id}', ${editingVarId})" title="Save changes to variable">✓ Save</button>
         <button class="btn btn-ghost btn-mini" onclick="cancelVariableEdit('${rule.id}', ${editingVarId})" title="Cancel edit">✕</button>`
      : `<button class="btn btn-ghost btn-mini" onclick="prepareVariableSave('${rule.id}')" title="Save as Variable">💾</button>`;
  
    const leftOperandHtml = renderOperand(rule.left_field, rule.left_value, rule.id, 'left_field');


    const comparisonHtml = isDefiningVariable ? '' : `
        <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
          ${(OPERATORS_BY_TYPE["math"] || []).map(o => `<option value="${o.val}" ${rule.op === o.val ? 'selected' : ''}>${o.label}</option>`).join("")}
        </select>
        <input class="rule-value" type="number" step="0.01" value="${rule.value || ''}"
               oninput="updateRule('${rule.id}', 'value', Number(this.value))">
    `;

    return `
      <div class="builder-rule builder-rule--math builder-rule--expanded" data-id="${rule.id}" style="flex-wrap: wrap;">
        ${saveBtn}
        ${leftOperandHtml}
        ${termsHtml}
        <button class="btn btn-ghost btn-mini" onclick="addMathTerm('${rule.id}')" title="Add term">+</button>
        ${comparisonHtml}
        <button class="btn btn-danger btn-mini" onclick="removeNode('${rule.id}')">×</button>
      </div>`;
  }

  return `
    <div class="builder-rule" data-id="${rule.id}">
      <select class="rule-field" onchange="updateRule('${rule.id}', 'field', this.value)">
        ${renderFieldOptions(rule.field)}
      </select>
      <select class="rule-op" onchange="updateRule('${rule.id}', 'op', this.value)">
        ${ops.map(o => `<option value="${o.val}" ${rule.op === o.val ? 'selected' : ''}>${o.label}</option>`).join("")}
      </select>
      ${fieldDef.type === 'boolean' ? `
        <select class="rule-value" onchange="updateRule('${rule.id}', 'value', this.value === 'true')">
          <option value="true" ${rule.value === true ? 'selected' : ''}>True</option>
          <option value="false" ${rule.value === false ? 'selected' : ''}>False</option>
        </select>` : `
        <input class="rule-value" type="${fieldDef.type === 'number' ? 'number' : 'text'}" 
               value="${rule.value || ''}"
               oninput="updateRule('${rule.id}', 'value', ${fieldDef.type === 'number' ? 'Number(this.value)' : 'this.value'})">`}
      <button class="btn btn-ghost btn-mini" onclick="removeNode('${rule.id}')">×</button>
    </div>`;
}

function findNode(tree, id) {
  if (tree.id === id) return tree;
  for (let c of tree.conditions) {
    if (c.id === id) return c;
    if (c.conditions) { let found = findNode(c, id); if (found) return found; }
  }
  return null;
}


function renderNumericFieldOptions(selectedValue) {
  return renderFieldOptions(selectedValue, true);
}

/**
 * Unified helper to render field selection options with sections and sorting.
 * @param {string} selectedValue The currently selected field key.
 * @param {boolean} numericOnly If true, only shows numeric-compatible fields.
 */
function renderFieldOptions(selectedValue, numericOnly = false) {
  const vars = [];
  const groupedRaws = {};

  Object.entries(FILTER_FIELDS).forEach(([k, v]) => {
    if (k === '__math__') return;
    if (numericOnly && v.type !== 'number' && v.type !== 'variable' && v.type !== 'math') return;

    if (v.type === 'variable') {
      vars.push({ key: k, ...v });
    } else {
      const g = v.group || "Other";
      if (!groupedRaws[g]) groupedRaws[g] = [];
      groupedRaws[g].push({ key: k, ...v });
    }
  });

  const varOpts = vars
    .sort((a, b) => a.label.localeCompare(b.label))
    .map(v => `<option value="${v.key}" ${selectedValue === v.key ? 'selected' : ''}>ƒ ${v.label}</option>`)
    .join("");

  const groupOrder = ["Relationship", "Profile", "Activity", "Network"];
  const sortedGroupNames = Object.keys(groupedRaws).sort((a, b) => {
    const idxA = groupOrder.indexOf(a);
    const idxB = groupOrder.indexOf(b);
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.localeCompare(b);
  });

  const rawGroupsHtml = sortedGroupNames.map(g => {
    const opts = groupedRaws[g]
      .sort((a, b) => a.label.localeCompare(b.label))
      .map(v => `<option value="${v.key}" ${selectedValue === v.key ? 'selected' : ''}>${v.label}</option>`)
      .join("");
    return `<optgroup label="${g}">${opts}</optgroup>`;
  }).join("");

  return `
    ${varOpts ? `<optgroup label="My Variables">${varOpts}</optgroup>` : ''}
    ${rawGroupsHtml}
    ${numericOnly ? `<optgroup label="Other"><option value="__constant__" ${selectedValue === '__constant__' ? 'selected' : ''}>Manual Value (#)</option></optgroup>` : ''}
  `;
}

function addRule(groupId) {
  const group = findNode(builderState.tree, groupId);
  group.conditions.push({ id: Math.random().toString(36).substr(2, 9), field: "handle", op: "contains", value: "" });
  renderBuilder();
}

function addMathExpressionRule(groupId) {
  const group = findNode(builderState.tree, groupId);
  group.conditions.push({
    id: Math.random().toString(36).substr(2, 9),
    field: "__math__",
    left_field: "followers_count",
    extra_terms: [{ op: "div", field: "follows_count" }],
    op: "lt",
    value: 0.5
  });
  renderBuilder();
  // Animate the new rule in
  requestAnimationFrame(() => {
    const builder = el("builder-root");
    const newRules = builder.querySelectorAll(".builder-rule--math");
    const last = newRules[newRules.length - 1];
    if (last) {
      last.classList.add("builder-rule--animate-in");
      setTimeout(() => last.classList.remove("builder-rule--animate-in"), 400);
    }
  });
}

function addGroup(groupId) {
  const group = findNode(builderState.tree, groupId);
  group.conditions.push({ id: Math.random().toString(36).substr(2, 9), op: "AND", conditions: [] });
  renderBuilder();
}

function removeNode(id) {
  const removeRecursive = (parent) => {
    parent.conditions = parent.conditions.filter(c => c.id !== id);
    parent.conditions.forEach(c => { if (c.conditions) removeRecursive(c); });
  };
  removeRecursive(builderState.tree);
  renderBuilder();
}

function updateRule(id, key, val) {
  const node = findNode(builderState.tree, id);
  node[key] = val;
  if (key === 'field') {
    const fieldDef = FILTER_FIELDS[val] || { type: "string" };
    node.op = 'eq';
    // Initialize value with type-appropriate defaults
    if (fieldDef.type === 'boolean') {
      node.value = true;
    } else if (fieldDef.type === 'number' || fieldDef.type === 'variable') {
      node.value = 0;
    } else if (fieldDef.type === 'math') {
      node.left_field = "followers_count";
      node.extra_terms = [{ op: "div", field: "follows_count" }];
      node.op = "lt";
      node.value = 0.5;
    }
    else node.value = '';

    renderBuilder();
  }
}

function updateGroupOp(id, op) { findNode(builderState.tree, id).op = op; }

function updateMathTerm(ruleId, termIdx, key, val) {
  const node = findNode(builderState.tree, ruleId);
  if (node.extra_terms && node.extra_terms[termIdx]) {
    node.extra_terms[termIdx][key] = val;
    renderBuilder();
  }
}

function addMathTerm(ruleId) {
  const node = findNode(builderState.tree, ruleId);
  if (node.extra_terms) {
    node.extra_terms.push({ op: "mul", field: "followers_count" });
    renderBuilder();
  }
}

function removeMathTerm(ruleId, termIdx) {
  const node = findNode(builderState.tree, ruleId);
  if (node.extra_terms && node.extra_terms.length > 1) {
    node.extra_terms.splice(termIdx, 1);
    renderBuilder();
  }
}

// ── Inline variable editing ────────────────────────────────────────────────────

/**
 * FIXED: Replaces a variable chip rule with an expanded math editor in-place.
 * The math editor pre-populates from the variable's stored expression.
 * Clicking the save/cancel buttons in the math editor updates the variable API
 * and collapses back to the chip.
 */
function inlineEditVariable(ruleId) {
  const node = findNode(builderState.tree, ruleId);
  if (!node) return;

  const variableName = node.field;
  const variable = state.variables.find(v => v.name === variableName);
  if (!variable) {
    toast("Variable not found", "error");
    return;
  }

  let expr;
  try {
    expr = JSON.parse(variable.expression_tree);
  } catch (e) {
    toast("Could not parse variable expression", "error");
    return;
  }

  // Preserve the current comparison op/value from the variable rule
  const currentOp = node.op || "gt";
  const currentValue = node.value || 0;

  // Replace the variable rule node in-place with an expanded math rule
  // We mutate the node object directly (findNode returns a reference)
  node.field = "__math__";
  node.left_field = expr.left_field || "followers_count";
  node.extra_terms = expr.extra_terms || [{ op: "div", field: "follows_count" }];
  node.op = currentOp;
  node.value = currentValue;
  node._editingVariableId = variable.id;
  node._editingVariableName = variableName;

  renderBuilder();

  // Animate the expanded rule in
  requestAnimationFrame(() => {
    const ruleEl = document.querySelector(`.builder-rule[data-id="${ruleId}"]`);
    if (ruleEl) {
      ruleEl.classList.add("builder-rule--animate-in");
      setTimeout(() => ruleEl.classList.remove("builder-rule--animate-in"), 400);
    }
  });
}

/**
 * Save changes made via inline editing back to the variable API,
 * then collapse the math editor back to a variable chip.
 */
async function saveEditedVariable(ruleId, variableId) {
  const node = findNode(builderState.tree, ruleId);
  if (!node) return;

  const newExpression = {
    left_field: node.left_field,
    extra_terms: node.extra_terms,
  };

  const variable = state.variables.find(v => v.id === variableId);
  if (!variable) return;

  try {
    await api(`/api/filters/${state.activeAlias}/variables/${variableId}`, {
      method: "PUT",
      body: JSON.stringify({ name: variable.name, expression_tree: JSON.stringify(newExpression) }),
    });

    // Reload variables so the update is reflected
    await loadVariables();

    // Collapse back to variable chip
    const savedOp = node.op;
    const savedValue = node.value;
    const varName = node._editingVariableName || variable.name;

    node.field = varName;
    node.op = savedOp;
    node.value = savedValue;
    delete node.left_field;
    delete node.extra_terms;
    delete node._editingVariableId;
    delete node._editingVariableName;

    renderBuilder();

    // Animate the chip in
    requestAnimationFrame(() => {
      const ruleEl = document.querySelector(`.builder-rule[data-id="${ruleId}"]`);
      if (ruleEl) {
        ruleEl.classList.add("builder-rule--animate-in");
        setTimeout(() => ruleEl.classList.remove("builder-rule--animate-in"), 400);
      }
    });

    toast(`Variable "${varName}" updated`);
  } catch (e) {
    toast("Failed to save variable: " + e.message, "error");
  }
}

/**
 * Cancel inline variable editing — collapse back to chip without saving.
 */
function cancelVariableEdit(ruleId, variableId) {
  const node = findNode(builderState.tree, ruleId);
  if (!node) return;

  const varName = node._editingVariableName;
  if (!varName) { removeNode(ruleId); return; }

  const savedOp = node.op;
  const savedValue = node.value;

  node.field = varName;
  node.op = savedOp;
  node.value = savedValue;
  delete node.left_field;
  delete node.extra_terms;
  delete node._editingVariableId;
  delete node._editingVariableName;

  renderBuilder();
}

// ── Variable save flow ────────────────────────────────────────────────────────

// Tracks the ruleId of the math rule being saved as a variable
let _pendingVariableSaveRuleId = null;

/**
 * FIXED: Captures the math rule's ruleId so it can be removed after saving.
 */
function prepareVariableSave(ruleId) {
  const node = findNode(builderState.tree, ruleId);
  currentMathExpressionForVar = {
    left_field: node.left_field,
    extra_terms: node.extra_terms,
  };
  _pendingVariableSaveRuleId = ruleId;
  el("var-save-btn").disabled = false;
  openVariableManager();
  toast("Expression captured. Give it a name to save.");
}

/**
 * FIXED: After saving, removes the originating math rule and adds a variable chip.
 */
async function saveCurrentExpressionAsVariable() {
  const name = el("var-name-input").value.trim().replace(/[^a-zA-Z0-9 ]/g, "").trim();
  if (!name) return toast("Name required (letters, numbers, and spaces)", "error");
  if (!currentMathExpressionForVar) return;

  const payload = {
    name: name,
    expression_tree: JSON.stringify(currentMathExpressionForVar),
  };

  await api(`/api/filters/${state.activeAlias}/variables`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  el("var-name-input").value = "";
  await loadVariables();

  // Remove the originating math rule from the tree
  const originatingRuleId = _pendingVariableSaveRuleId;
  if (originatingRuleId) {
    const node = findNode(builderState.tree, originatingRuleId);
    if (node) {
      // FIXED: Mutate the node in place to carry over the comparison op and target value
      node.field = name;
      // node.op and node.value are already correctly set on the existing math node
      delete node.left_field;
      delete node.left_value;
      delete node.extra_terms;
      delete node._editingVariableId;
      delete node._editingVariableName;
    }
    _pendingVariableSaveRuleId = null;
  }

  renderBuilder();

  // Animate the new variable chip in
  requestAnimationFrame(() => {
    const builder = el("builder-root");
    const varRules = builder.querySelectorAll(".builder-rule--variable");
    const last = varRules[varRules.length - 1];
    if (last) {
      last.classList.add("builder-rule--animate-in");
      setTimeout(() => last.classList.remove("builder-rule--animate-in"), 400);
    }
  });

  closeVariableManager();
  toast(`Variable "${name}" saved!`);
}

/**
 * Remove a node from the tree without re-rendering (used internally).
 */
function removeNodeSilent(id) {
  const removeRecursive = (parent) => {
    parent.conditions = parent.conditions.filter(c => c.id !== id);
    parent.conditions.forEach(c => { if (c.conditions) removeRecursive(c); });
  };
  removeRecursive(builderState.tree);
}

async function saveFilterSet() {
  const name = el("filter-name").value.trim();
  if (!name) return toast("Name required", "error");
  const payload = {
    name, icon: el("filter-icon").value, color: el("filter-color").value,
    condition_tree: JSON.stringify(builderState.tree)
  };

  if (builderState.id) {
    await api(`/api/filters/${state.activeAlias}/${builderState.id}`, { method: "PUT", body: JSON.stringify(payload) });
    toast("Filter updated!");
  } else {
    await api(`/api/filters/${state.activeAlias}`, { method: "POST", body: JSON.stringify(payload) });
    toast("Filter saved!");
  }
  closeFilterBuilder();
  await loadFilterSets();
}

async function handleDeleteInBuilder() {
  if (!builderState.id) return;
  if (!confirm("Delete this filter?")) return;
  await api(`/api/filters/${state.activeAlias}/${builderState.id}`, { method: "DELETE" });
  await loadFilterSets();
  closeFilterBuilder();
}

async function loadFilterSets() {
  if (!state.activeAlias) return;
  state.customFilters = await api(`/api/filters/${state.activeAlias}`);
  renderCustomFilters();
}

async function deleteFilterSet(e, id) {
  e.stopPropagation();
  if (!confirm("Delete this filter?")) return;
  await api(`/api/filters/${state.activeAlias}/${id}`, { method: "DELETE" });
  await loadFilterSets();
}

// ── Variable Management ──────────────────────────────────────────────────────
let currentMathExpressionForVar = null;

function updateFilterFieldsWithVariables() {
  FILTER_FIELDS = { ...BASE_FILTER_FIELDS };
  if (state.variables && Array.isArray(state.variables)) {
    state.variables.forEach(v => {
      // editable: true = user-defined derived variable, shows pencil icon
      FILTER_FIELDS[v.name] = { label: v.name, type: "variable", editable: true };
    });
  }
}

async function loadVariables() {
    if (!state.activeAlias) return;
    try {
        state.variables = await api(`/api/filters/${state.activeAlias}/variables`);
        updateFilterFieldsWithVariables();
        renderVariableList();
    } catch (e) {
        logError("loadVariables failed:", e);
    }
}

function renderVariableList() {
    const list = el("variable-list");
    const sidebarList = el("custom-variables-list");
    if (!list) return;

    list.innerHTML = state.variables.map(v => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding: 0.4rem; border-bottom: 1px solid var(--border);">
            <span style="font-family: var(--mono); font-size: 0.8rem;">${v.name}</span>
            <button class="btn btn-danger btn-mini" onclick="deleteVariable(${v.id})">Delete</button>
        </div>
    `).join("") || '<div class="state-box" style="padding:1rem">No variables yet.</div>';

    if (sidebarList) {
      sidebarList.innerHTML = state.variables.map(v => `<div>${v.name}</div>`).join("");
    }
}

function openVariableManager() { el("variable-modal").classList.add("open"); }
function closeVariableManager() {
  el("variable-modal").classList.remove("open");
  currentMathExpressionForVar = null;
  el("var-save-btn").disabled = true;
}

function addVariableToFilter(variableName) {
  const root = builderState.tree;
  const newRule = {
    id: Math.random().toString(36).substr(2, 9),
    field: variableName,
    op: "gt",
    value: 0
  };
  root.conditions.push(newRule);
  renderBuilder();
  toast(`"${variableName}" added to filter`);
}

async function deleteVariable(id) {
    if (!confirm("Delete variable? Filters using it will break.")) return;
    await api(`/api/filters/${state.activeAlias}/variables/${id}`, { method: "DELETE" });
    await loadVariables();
}

// ── Legacy variable editor (kept for compatibility, no longer primary UI) ─────
function openVariableEditor(variableId, ruleId) {
  // Redirect to inline edit if we have a ruleId
  if (ruleId) {
    inlineEditVariable(ruleId);
    return;
  }
  // Fallback: open manager
  openVariableManager();
}

function closeVariableEditor() {
  variableEditorState.isOpen = false;
  variableEditorState.editingVariableId = null;
  variableEditorState.editingExpression = null;
  const panel = el("variable-editor-panel");
  if (panel) panel.style.display = "none";
}

function saveVariableEdits() {
  closeVariableEditor();
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    el("search-input").focus();
  }
  if (e.key === "Escape") {
    closeAddAccount();
    el("search-input").blur();
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadAccounts();
  startStatusWatcher();
  initLazyLoading();
});