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
  lastUserFetch: 0,
  settings: {},
  crawlBudgetMb: 0,
  currentDbSizeMb: 0,

  // Filter / sort state
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
    is_stub: null,
    filter_tree: null,
    // numeric ranges
    min_days_inactive: null,
    min_repost_ratio: null,
    max_repost_ratio: null,
    min_followers: null,
    max_followers: null,
    min_sampled_post_count: null,
    max_sampled_post_count: null,
    min_repost_count: null,
    max_repost_count: null,
    min_original_post_count: null,
    max_original_post_count: null,
    min_crawl_priority: null,
    max_crawl_priority: null,
    min_clustering_coefficient: null,
    max_clustering_coefficient: null,
    // date ranges
    before_last_post_at: null,
    after_last_post_at: null,
    before_last_analyzed_at: null,
    after_last_analyzed_at: null,
    before_last_hydrated_at: null,
    after_last_hydrated_at: null,
    before_last_crawled_at: null,
    after_last_crawled_at: null,
    before_first_seen_at: null,
    after_first_seen_at: null,
  },
  sort: { by: "handle", dir: "asc" },
  pagination: { limit: 50, offset: 0 },
  activeTab: "all",
};

// Tab definitions — each sets a filter preset
const TABS = [
  { id: "all",           label: "All Profiles",    icon: "🌐", statKey: "graph_size",     filters: {} },
  { id: "follows",       label: "Follows",          icon: "👤", statKey: "total_follows",  filters: { i_follow_them: true } },
  { id: "followers",     label: "Followers",        icon: "👥", statKey: "total_followers",filters: { they_follow_me: true } },
  { id: "stubs",         label: "Stubs",            icon: "🔍", statKey: "stubs_count",    filters: { is_stub: true } },
  { id: "inactive",      label: "Inactive",         icon: "⏸", statKey: "inactive",       filters: { i_follow_them: true, is_inactive: true } },
  { id: "repost",        label: "Repost Heavy",     icon: "🔁", statKey: "repost_heavy",   filters: { i_follow_them: true, is_repost_heavy: true } },
  { id: "onesided",      label: "One-Sided",        icon: "↗",  statKey: "one_sided",      filters: { is_one_sided_follow: true } },
  { id: "followersonly", label: "Followers Only",   icon: "↙",  statKey: "follower_only",  filters: { is_follower_only: true } },
  { id: "nointeract",    label: "No Interactions",  icon: "💤", statKey: "no_interaction", filters: { i_follow_them: true, interacted_with_owner: false } },
];

const SORT_OPTIONS = [
  { value: "handle",                 label: "Handle" },
  { value: "display_name",           label: "Name" },
  { value: "followers_count",        label: "Followers" },
  { value: "follows_count",          label: "Following" },
  { value: "posts_count",            label: "Post Count" },
  { value: "sampled_post_count",     label: "Sampled Posts" },
  { value: "repost_count",           label: "Reposts" },
  { value: "original_post_count",    label: "Original Posts" },
  { value: "days_since_post",        label: "Days Inactive" },
  { value: "repost_ratio",           label: "Repost %" },
  { value: "flowrank_score",         label: "FlowRank" },
  { value: "clustering_coefficient", label: "Clustering Coeff." },
  { value: "in_subgraph_degree",     label: "In-Subgraph Degree" },
  { value: "crawl_priority",         label: "Crawl Priority" },
  { value: "last_post_at",           label: "Last Post" },
  { value: "last_analyzed_at",       label: "Last Analyzed" },
  { value: "last_hydrated_at",       label: "Last Hydrated" },
  { value: "last_crawled_at",        label: "Last Crawled" },
  { value: "first_seen_at",          label: "First Seen" },
];

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
        context: { error: err?.message || err?.toString(), alias: state.activeAlias },
      }),
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
  if (u.is_inactive)
    b.push(`<span class="badge badge-inactive">⏸ ${u.days_since_post ?? "?"}d</span>`);
  if (u.is_repost_heavy)
    b.push(`<span class="badge badge-repost">🔁 ${pct(u.repost_ratio)}</span>`);
  if (u.is_one_sided_follow)
    b.push(`<span class="badge badge-onesided">↗ one-sided</span>`);
  if (u.is_follower_only)
    b.push(`<span class="badge badge-follower">↙ follows you</span>`);
  if (!u.interacted_with_owner && u.i_follow_them)
    b.push(`<span class="badge badge-nointeract">💤 no interact</span>`);
  return b.join("");
}

function userRow(u) {
  const groupLabel = u.comm_name || (u.community_id != null ? u.community_id : "—");
  const groupTitle = u.comm_name ? `Group: ${u.comm_name} (#${u.community_id})` : "Community ID";
  return `
    <div class="user-row js-profile-trigger" data-did="${u.did}" style="cursor:pointer">
      <div class="user-grid">
        ${avatar(u)}
        <div class="user-name" title="${u.display_name}" style="min-width:0">${u.display_name || "—"}</div>
        <div class="user-handle" title="${u.handle}" style="min-width:0">@${u.handle}</div>
        <div class="col-stat" title="FlowRank Influence">💎 ${u.flowrank_score > 0 ? (u.flowrank_score * 1000).toFixed(4) : "—"}</div>
        <div class="col-stat js-community-trigger" data-id="${u.community_id}" title="${groupTitle}" style="cursor:pointer">🌐 ${groupLabel}</div>
        <div class="col-stat">${fmt(u.followers_count)}</div>
        <div class="col-stat">${fmt(u.follows_count)}</div>
        <div class="col-stat">${u.days_since_post != null ? u.days_since_post + "d" : "—"}</div>
        <div class="col-stat">${pct(u.repost_ratio)}</div>
        <div class="col-stat">${fmt(u.posts_count)}</div>
        <div class="col-stat">${fmt(u.sampled_post_count)}</div>
        <div class="col-stat">${fmt(u.repost_count)}</div>
        <div class="col-stat">${fmt(u.original_post_count)}</div>
        <div class="col-date">${shortDate(u.last_post_at)}</div>
        <div class="col-date">${shortDate(u.last_analyzed_at)}</div>
      </div>
      <div class="badges-row">${badges(u)}</div>
    </div>`;
}

function shortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}

// ── Stats strip ───────────────────────────────────────────────────────────────
function renderStats() {
  const s = state.stats;
  el("stat-follows").textContent    = fmt(s.total_follows);
  el("stat-followers").textContent  = fmt(s.total_followers);
  el("stat-discovered").textContent = fmt(s.graph_size);
  el("stat-stubs").textContent      = fmt(s.stubs_count);
  el("stat-hydrated").textContent   = fmt(s.hydrated);
  el("stat-analysed").textContent   = fmt(s.analysed);
  el("stat-pending").textContent    = fmt(s.pending);
  el("stat-req-rate").textContent   = (s.req_rate  || 0) + "/m";
  el("stat-found-rate").textContent = (s.found_rate || 0) + "/m";

  if (state.crawlBudgetMb > 0) {
    const pctUsed  = (state.currentDbSizeMb / state.crawlBudgetMb) * 100;
    const budgetEl = el("stat-crawl-budget");
    budgetEl.textContent = `${state.currentDbSizeMb.toFixed(1)}/${state.crawlBudgetMb} MB`;
    budgetEl.style.color = pctUsed > 90
      ? "var(--danger)"
      : pctUsed > 75 ? "var(--inactive)" : "var(--accent)";
    budgetEl.title = `Database size: ${state.currentDbSizeMb.toFixed(1)} MB (${pctUsed.toFixed(1)}% of ${state.crawlBudgetMb} MB budget)`;
  }

  const synced = s.last_synced_at
    ? new Date(s.last_synced_at).toLocaleString()
    : "Never";
  el("last-synced").textContent = `Last synced: ${synced}`;

  const canCrawl = !!s.last_synced_at;
  el("crawl-btn").disabled    = !canCrawl;
  el("crawl-btn").textContent = state.crawling ? "■ Stop Crawl" : "✨ Crawl";
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────
function renderNav() {
  const s   = state.stats;
  const nav = el("nav-items");
  
  let extraNav = "";
  if (state.activeTab === "custom-community") {
    extraNav = `<div class="nav-item active"><span>🔍</span><span>Filtered View</span></div>`;
  }

  nav.innerHTML = TABS.map(tab => {
    const count  = s[tab.statKey] ?? "";
    const active = state.activeTab === tab.id ? "active" : "";
    return `
      <div class="nav-item ${active}" data-tab="${tab.id}" onclick="selectTab('${tab.id}')">
        <span>${tab.icon}</span>
        <span>${tab.label}</span>
        ${count !== "" ? `<span class="nav-count">${fmt(count)}</span>` : ""}
      </div>`;
  }).join("") + extraNav + `
    <div class="sidebar-label" style="margin-top: 1rem;">Visualization</div>
    <a class="nav-item" href="/graph/${encodeURIComponent(state.activeAlias || "")}" style="text-decoration:none;">
      <span>🕸️</span><span>Network Graph</span>
    </a>
    <a class="nav-item" href="/hive/${encodeURIComponent(state.activeAlias || "")}" style="text-decoration:none;">
      <span>🍯</span><span>Hive Plot</span>
    </a>
    <a class="nav-item" href="/pack/${encodeURIComponent(state.activeAlias || "")}" style="text-decoration:none;">
      <span>⭕</span><span>Circle Packing</span>
    </a>
  `;
}

function renderCustomFilters() {
  const wrap = el("custom-filters");
  if (!wrap) return;
  // Data is now owned by FilterBuilder
  const customFilters = FilterBuilder.getCustomFilters();
  wrap.innerHTML = customFilters.map(f => `
    <div class="nav-item ${state.activeTab === "custom-" + f.id ? "active" : ""}"
         onclick="selectCustomFilter(${f.id})">
      <span style="color:${f.color}">${f.icon || "🔍"}</span>
      <span style="flex:1;">${f.name}</span>
      <button class="btn-mini btn-ghost" onclick="editFilterSet(event, ${f.id})"
              style="margin-left:auto; border:none; opacity:0.4">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
        </svg>
      </button>
      <button class="btn-mini btn-ghost" onclick="deleteFilterSet(event, ${f.id})"
              style="margin-left:auto; border:none; opacity:0.4">×</button>
    </div>
  `).join("");
}

function renderHeader(label, field, isStat = false) {
  const active = state.sort.by === field;
  const dir    = state.sort.dir === "asc" ? "↑" : "↓";
  return `
    <div class="header-col ${active ? "active" : ""} ${isStat ? "col-stat" : ""}"
         onclick="sortByHeader('${field}')">
      ${label} ${active ? dir : ""}
    </div>`;
}

function sortByHeader(field) {
  if (state.sort.by === field) {
    state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
  } else {
    state.sort.by = field;
    const descDefaults = [
      "followers_count","follows_count","posts_count","sampled_post_count",
      "repost_count","original_post_count","days_since_post","repost_ratio",
      "flowrank_score","clustering_coefficient","in_subgraph_degree",
      "crawl_priority","last_post_at","last_analyzed_at","last_hydrated_at",
      "last_crawled_at","first_seen_at","community_id",
    ];
    state.sort.dir = descDefaults.includes(field) ? "desc" : "asc";
  }
  state.pagination.offset = 0;
  fetchUsers();
}

// ── Infinite scroll ───────────────────────────────────────────────────────────
function initLazyLoading() {
  const list = el("user-list");
  if (!list) return;
  list.addEventListener("scroll", () => {
    if (state.loading || state.users.length >= state.total) return;
    const { scrollTop, scrollHeight, clientHeight } = list;
    if (scrollTop + clientHeight >= scrollHeight - 200) loadMoreUsers();
  });
}

async function loadMoreUsers() {
  if (state.loading || state.users.length >= state.total) return;
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
      ${renderHeader("Name",      "display_name")}
      ${renderHeader("Handle",    "handle")}
      ${renderHeader("FlowRank",  "flowrank_score",         true)}
      ${renderHeader("Group",     "community_id",           true)}
      ${renderHeader("Followers", "followers_count",        true)}
      ${renderHeader("Following", "follows_count",          true)}
      ${renderHeader("Inactive",  "days_since_post",        true)}
      ${renderHeader("Repost %",  "repost_ratio",           true)}
      ${renderHeader("Posts",     "posts_count",            true)}
      ${renderHeader("Sampled",   "sampled_post_count",     true)}
      ${renderHeader("Reposts",   "repost_count",           true)}
      ${renderHeader("Originals", "original_post_count",    true)}
      ${renderHeader("Last Post", "last_post_at",           true)}
      ${renderHeader("Analyzed",  "last_analyzed_at",       true)}
    </div>
  `;

  list.innerHTML = headers + state.users.map(userRow).join("");
  el("result-count").textContent = `${fmt(state.total)} results`;
}

// ── Account switcher pills ────────────────────────────────────────────────────
function renderAccountPills() {
  const wrap = el("account-pills");
  if (state.accounts.length === 0) { wrap.innerHTML = ""; return; }
  wrap.innerHTML = state.accounts.map(a => `
    <button class="account-pill ${a.alias === state.activeAlias ? "active" : ""}"
            onclick="switchAccount('${a.alias}')"
            title="Alias: ${a.alias}">
      @${a.handle}
    </button>`).join("");

  const activeAcc = state.accounts.find(a => a.alias === state.activeAlias);
  if (activeAcc) el("auto-crawl-toggle").checked = activeAcc.auto_crawl_enabled;
}

// ── Fetch data from API ───────────────────────────────────────────────────────
async function fetchStats() {
  if (!state.activeAlias) return;
  try {
    state.stats = await api(`/api/users/${encodeURIComponent(state.activeAlias)}/stats`);
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

  if (!append && !silent) {
    state.pagination.offset = 0;
    state.users = [];
    renderUsers();
  }

  const params = new URLSearchParams();
  const limit  = append
    ? state.pagination.limit
    : Math.max(state.pagination.limit, state.users.length);
  const offset = append ? state.pagination.offset : 0;

  if (state.filters.filter_tree) {
    params.set("filter_tree", JSON.stringify(state.filters.filter_tree));
  }
  if (state.filters.search) params.set("search", state.filters.search);

  params.set("sort_by",  state.sort.by);
  params.set("sort_dir", state.sort.dir);
  params.set("limit",    limit);
  params.set("offset",   offset);

  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner",
    "muted","blocked","exclude_stubs","exclude_unanalyzed","is_stub",
  ];
  for (const key of boolFlags) {
    if (state.filters[key] !== null && state.filters[key] !== undefined) {
      params.set(key, state.filters[key]);
    }
  }

  const numericFilters = [
    "min_days_inactive","min_repost_ratio","max_repost_ratio",
    "min_followers","max_followers",
    "min_sampled_post_count","max_sampled_post_count",
    "min_repost_count","max_repost_count",
    "min_original_post_count","max_original_post_count",
    "min_crawl_priority","max_crawl_priority",
    "min_clustering_coefficient","max_clustering_coefficient",
  ];
  const dateFilters = [
    "before_last_post_at","after_last_post_at",
    "before_last_analyzed_at","after_last_analyzed_at",
    "before_last_hydrated_at","after_last_hydrated_at",
    "before_last_crawled_at","after_last_crawled_at",
    "before_first_seen_at","after_first_seen_at",
  ];
  for (const key of [...numericFilters, ...dateFilters]) {
    if (state.filters[key] != null) params.set(key, state.filters[key]);
  }

  try {
    const data = await api(`/api/users/${encodeURIComponent(state.activeAlias)}?${params}`);
    state.users = append ? [...state.users, ...data.users] : data.users;
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
  // FilterBuilder owns filter/variable loading
  await FilterBuilder.loadFilterSets();
  await FilterBuilder.loadVariables();
  await fetchUsers(false, true);
}

async function reconcileOperationStatus() {
  if (!state.activeAlias) return;

  try {
    const freshStats = await api(`/api/users/${encodeURIComponent(state.activeAlias)}/stats`);
    state.stats = { ...state.stats, ...freshStats };
    renderStats();
    renderNav();
  } catch (e) { /* ignore polling errors */ }

  if (state.syncing || state.crawling) return;

  try {
    const status = await api(`/api/sync/${encodeURIComponent(state.activeAlias)}/status`);
    const sync   = status.sync;
    const crawl  = status.crawl;

    if (status.req_rate   !== undefined) state.stats.req_rate   = status.req_rate;
    if (status.found_rate !== undefined) state.stats.found_rate = status.found_rate;
    renderStats();

    state.crawlBudgetMb    = status.crawl_budget_mb    ?? 0;
    state.currentDbSizeMb  = status.current_db_size_mb ?? 0;

    if (sync?.status === "running" && status.sync_running && !state.syncing) {
      state.syncing = true;
      el("sync-btn").disabled = true;
      showSyncBar("Sync running…", null);
      attachSyncStream();
    } else if (!status.sync_running && state.syncing) {
      state.syncing = false;
      if (state.syncStream) { state.syncStream.close(); state.syncStream = null; }
      el("sync-btn").disabled = false;
    }

    if (crawl?.status === "running" && crawl?.is_running) {
      state.crawling = true;
      showSyncBar(crawl.last_message || "Expanding network (Discovery)…", null);
      if (status.req_rate   !== undefined) state.stats.req_rate   = status.req_rate;
      if (status.found_rate !== undefined) state.stats.found_rate = status.found_rate;
      renderStats();
      if (!state.crawlStream) attachCrawlStream();
    } else if (!crawl?.is_running && state.crawling) {
      state.crawling = false;
      if (state.crawlStream) { state.crawlStream.close(); state.crawlStream = null; }
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

  state.filters.filter_tree = null;
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner",
    "muted","blocked","is_stub",
  ];
  for (const key of boolFlags) state.filters[key] = null;
  Object.assign(state.filters, tab.filters);

  renderCustomFilters();
  renderNav();
  fetchUsers();
}

function selectCustomFilter(id) {
  // Data is now owned by FilterBuilder
  const f = FilterBuilder.getCustomFilters().find(x => x.id === id);
  if (!f) return;
  state.activeTab = "custom-" + id;
  for (const k in state.filters) state.filters[k] = null;
  state.filters.filter_tree = typeof f.condition_tree === "string"
    ? JSON.parse(f.condition_tree)
    : f.condition_tree;
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
  state.users       = [];
  state.stats       = {};
  state.activeTab   = "follows";

  for (const key of Object.keys(state.filters)) state.filters[key] = null;
  state.filters.i_follow_them    = true;
  state.filters.exclude_stubs    = false;
  state.filters.exclude_unanalyzed = false;
  state.filters.is_stub          = null;

  if (el("exclude-stubs-toggle"))     el("exclude-stubs-toggle").checked     = false;
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
    await api(
      `/api/accounts/${encodeURIComponent(state.activeAlias)}/settings?auto_crawl=${enabled}`,
      { method: "PATCH" }
    );
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
    await api(`/api/sync/${encodeURIComponent(state.activeAlias)}`, { method: "POST" });
  } catch (e) {
    if (e.status !== 409) {
      logError("startSync failed:", e);
      toast(e.message, "error");
      endSync();
      return;
    }
    toast("Sync already in progress, attaching to stream...");
  }
  attachSyncStream();
}

function attachSyncStream() {
  if (state.syncStream) state.syncStream.close();
  const es = new EventSource(
    `/api/sync/${encodeURIComponent(state.activeAlias)}/stream?operation=sync`
  );
  state.syncStream = es;

  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.kind === "progress") {
      if (data.is_heartbeat) return;
      showSyncBar(data.message, data.pct);
      if (data.account_stats) {
        state.stats = { ...state.stats, ...data.account_stats };
        renderStats();
        renderNav();
      }
      if (Date.now() - state.lastUserFetch > 2000) fetchUsers(false, true);
    } else if (data.kind === "phase") {
      showSyncBar(data.message, null);
    } else if (data.kind === "done") {
      es.close(); state.syncStream = null;
      showSyncBar("Sync complete!", 100);
      setTimeout(() => { hideSyncBar(); endSync(); refresh(); reconcileOperationStatus(); toast("Sync complete!"); }, 800);
    } else if (data.kind === "error") {
      es.close(); state.syncStream = null;
      hideSyncBar(); endSync();
      toast("Sync error: " + data.message, "error");
    }
  };

  es.onerror = () => {
    es.close(); state.syncStream = null;
    hideSyncBar(); endSync();
    toast("Lost connection to sync stream.", "error");
  };
}

function endSync() {
  state.syncing = false;
  el("sync-btn").disabled = false;
}

function showSyncBar(message, pct) {
  el("sync-bar").classList.add("visible");
  el("sync-bar-text").textContent = message;
  if (pct != null) el("progress-fill").style.width = pct + "%";
}

function hideSyncBar() {
  el("sync-bar").classList.remove("visible");
  el("progress-fill").style.width = "0%";
}

// ── Crawl ─────────────────────────────────────────────────────────────────────
async function startCrawl() {
  if (!state.activeAlias) return;
  if (state.crawling) { await stopCrawl(); return; }
  state.crawling = true;
  renderStats();
  showSyncBar("Expanding network (Discovery)…", 0);

  try {
    await api(`/api/sync/${encodeURIComponent(state.activeAlias)}/crawl`, { method: "POST" });
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
  if (state.crawlStream) state.crawlStream.close();
  const es = new EventSource(
    `/api/sync/${encodeURIComponent(state.activeAlias)}/stream?operation=crawl`
  );
  state.crawlStream = es;

  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.kind === "progress" || data.kind === "phase") {
      if (data.is_heartbeat) return;
      let msg = data.message;
      if (data.crawl_stats) {
        const cs       = data.crawl_stats;
        const progress = cs.candidates_queued > 0 ? `[${cs.candidates_completed}/${cs.candidates_queued}] ` : "";
        msg = progress + data.message;
      }
      showSyncBar(msg, data.pct ?? null);
      if (data.req_rate   !== undefined) state.stats.req_rate   = data.req_rate;
      if (data.found_rate !== undefined) state.stats.found_rate = data.found_rate;
      if (data.account_stats) {
        state.stats = { ...state.stats, ...data.account_stats };
        renderStats();
        renderNav();
      }
      if (Date.now() - state.lastUserFetch > 2000) fetchUsers(false, true);
    } else if (data.kind === "done") {
      es.close(); state.crawlStream = null;
      showSyncBar("Crawl complete!", 100);
      setTimeout(() => { hideSyncBar(); state.crawling = false; renderStats(); refresh(); toast("Network expansion complete!"); }, 800);
    } else if (data.kind === "error") {
      es.close(); state.crawlStream = null;
      hideSyncBar(); state.crawling = false;
      renderStats();
      toast("Crawl error: " + data.message, "error");
    }
  };

  es.onerror = () => {
    es.close(); state.crawlStream = null;
    hideSyncBar(); state.crawling = false;
    renderStats();
    toast("Lost connection to crawl stream.", "error");
  };
}

async function stopCrawl() {
  if (!state.activeAlias) return;
  try {
    await api(`/api/sync/${encodeURIComponent(state.activeAlias)}/crawl/stop`, { method: "POST" });
    toast("Crawl stopped.");
  } catch (e) {
    logError("stopCrawl failed:", e);
    toast(e.message, "error");
  } finally {
    if (state.crawlStream) { state.crawlStream.close(); state.crawlStream = null; }
    state.crawling = false;
    hideSyncBar();
    renderStats();
  }
}

// ── Add Account modal ─────────────────────────────────────────────────────────
function openAddAccount()  { el("modal").classList.add("open"); el("modal-alias").focus(); }
function closeAddAccount() {
  el("modal").classList.remove("open");
  el("modal-alias").value = el("modal-handle").value = el("modal-password").value = "";
}

async function submitAddAccount() {
  const alias    = el("modal-alias").value.trim();
  const handle   = el("modal-handle").value.trim().replace(/^@/, "");
  const password = el("modal-password").value.trim();
  if (!alias || !handle || !password) return toast("All fields are required.", "error");
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
const SETTINGS_KEYS = [
  "inactivity_threshold_days","repost_ratio_threshold","feed_sample_size","bio_keyword_weight",
  "sync_staleness_hours","worker_sweep_interval_seconds","staleness_tier2_days",
  "staleness_tier1_days","staleness_tier0_days","ignore_staleness_threshold_days",
  "feed_fetch_concurrency","disable_internal_rate_limits","api_max_retries",
  "api_base_backoff_seconds","api_polite_delay_ms",
  "crawl_concurrency","crawl_hydration_concurrency","min_connection_threshold","crawl_budget_mb",
  "profile_analysis_batch_size","profile_analysis_staleness_days",
  "profile_analysis_inter_batch_sleep_seconds","profile_analysis_idle_sleep_seconds",
  "clustering_top_n","louvain_max_nodes","louvain_resolution",
  "community_keywords_node_sample","community_keywords_staleness_days","label_prop_max_nodes",
];

let _settingsBaseline = {};

function switchSettingsTab(tab) {
  document.querySelectorAll(".stab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".stab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === tab));
}

async function openSettings() {
  try {
    const data = await api("/api/settings/");
    _settingsBaseline = { ...data };
    for (const key of SETTINGS_KEYS) {
      const input = document.getElementById(`set-${key}`);
      if (!input) continue;
      input.type === "checkbox" ? (input.checked = !!data[key]) : (input.value = data[key] ?? "");
      input.classList.remove("dirty");
      input.oninput  = () => _markDirty(key);
      input.onchange = () => _markDirty(key);
    }
    const hint = el("settings-dirty-hint");
    if (hint) hint.textContent = "";
    const saveBtn = el("settings-save-btn");
    if (saveBtn) saveBtn.disabled = false;
    switchSettingsTab("analysis");
    el("settings-modal").classList.add("open");
  } catch (e) {
    logError("openSettings failed", e);
    toast("Failed to load settings: " + e.message, "error");
  }
}

function _markDirty(key) {
  const input = document.getElementById(`set-${key}`);
  if (!input) return;
  const current  = input.type === "checkbox" ? input.checked : (input.type === "number" ? Number(input.value) : input.value);
  const original = _settingsBaseline[key];
  input.classList.toggle("dirty", String(current) !== String(original));
  const anyDirty = SETTINGS_KEYS.some(k => document.getElementById(`set-${k}`)?.classList.contains("dirty"));
  const hint = el("settings-dirty-hint");
  if (hint) hint.textContent = anyDirty ? "Unsaved changes" : "";
}

function closeSettings() { el("settings-modal").classList.remove("open"); }

async function submitSettings() {
  const payload = {};
  for (const key of SETTINGS_KEYS) {
    const input = document.getElementById(`set-${key}`);
    if (!input) continue;
    payload[key] = input.type === "checkbox" ? input.checked
      : input.type === "number" ? Number(input.value)
      : input.value;
  }
  try {
    el("settings-save-btn").disabled = true;
    await api("/api/settings/", { method: "PATCH", body: JSON.stringify(payload) });
    _settingsBaseline = { ...payload };
    SETTINGS_KEYS.forEach(k => document.getElementById(`set-${k}`)?.classList.remove("dirty"));
    el("settings-dirty-hint").textContent = "";
    toast("Settings saved.");
    closeSettings();
  } catch (e) {
    toast(e.message || "Failed to save settings", "error");
  } finally {
    el("settings-save-btn").disabled = false;
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

// ── Search event handler ──────────────────────────────────────────────────────
let _searchTimer = null;
function onSearch(val) {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    state.filters.search = val;
    state.pagination.offset = 0;
    fetchUsers();
  }, 280);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(message, type = "info") {
  const wrap = el("toast-wrap");
  const t    = document.createElement("div");
  t.className = `toast ${type === "error" ? "error" : ""}`;
  t.textContent = message;
  wrap.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); el("search-input").focus(); }
  if (e.key === "Escape") { closeAddAccount(); el("search-input").blur(); }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Wire up the filter builder component with its dependencies.
  // getAlias returns a live value — FilterBuilder calls it at the moment
  // it needs the alias, so it always reflects the current active account.
  FilterBuilder.init({
    api,
    toast,
    logError,
    getAlias: () => state.activeAlias,
    onFiltersChanged:  () => renderCustomFilters(),
    onVariablesChanged: () => { /* FilterBuilder renders variable list internally */ },
  });

  // Initialize shared sidebar
  if (typeof InfoPanel !== 'undefined') InfoPanel.init();

  loadAccounts();
  startStatusWatcher();
  initLazyLoading();

  // Check for redirected community filters from graph pages
  const params = new URLSearchParams(window.location.search);
  const communityId = params.get('filter_community');
  if (communityId) {
      // Use a brief timeout to ensure loadAccounts/switchAccount initial setup is underway
      setTimeout(() => {
          window.filterByCommunity(communityId);
          // Clean up the URL to prevent re-filtering on manual page refreshes
          window.history.replaceState({}, document.title, window.location.pathname);
      }, 600);
  }
});