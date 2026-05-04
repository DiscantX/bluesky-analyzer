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
    // numeric ranges
    min_days_inactive: null,
    min_repost_ratio: null,
    max_repost_ratio: null,
    min_followers: null,
    max_followers: null,
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
  { id: "stubs",      label: "Discovered",       icon: "🔍", statKey: "pending",        filters: { crawl_tier: 0 } },
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
  { value: "days_since_post", label: "Days Inactive" },
  { value: "repost_ratio",    label: "Repost %" },
  { value: "posts_count",     label: "Post Count" },
  { value: "last_post_at",    label: "Last Post" },
  { value: "last_analyzed_at",label: "Last Analyzed" },
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

function shortDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
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
        <div class="col-stat" title="FlowRank Influence">💎 ${u.flowrank_score > 0 ? (u.flowrank_score * 1000).toFixed(2) : "—"}</div>
        <div class="col-stat" title="Community ID">🌐 ${u.community_id != null ? u.community_id : "—"}</div>
        <div class="col-date">${shortDate(u.last_post_at)}</div>
        <div class="col-date">${shortDate(u.last_analyzed_at)}</div>
      </div>
      <div class="badges-row">${badges(u)}</div>
    </a>`;
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
  }).join("");
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
    const descDefaults = ["followers_count", "follows_count", "days_since_post", "repost_ratio", "posts_count", "last_post_at", "last_analyzed_at", "flowrank_score", "community_id"];
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

  if (state.filters.search) params.set("search", state.filters.search);
  params.set("sort_by", state.sort.by);
  params.set("sort_dir", state.sort.dir);
  params.set("limit", limit);
  params.set("offset", offset);

  // Boolean filters — only send when not null
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner","muted","blocked", 
    "exclude_stubs", "exclude_unanalyzed"
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
  ];
  for (const key of numericFilters) {
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

  // Reset all filter flags, then apply tab preset
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner","muted","blocked",
  ];
  for (const key of boolFlags) state.filters[key] = null;
  Object.assign(state.filters, tab.filters);

  renderNav();
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
