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
    // numeric ranges
    min_days_inactive: null,
    min_repost_ratio: null,
    max_repost_ratio: null,
    min_followers: null,
    max_followers: null,
  },
  sort: { by: "handle", dir: "asc" },
  pagination: { limit: 200, offset: 0 },
  activeTab: "all",
};

// Tab definitions — each sets a filter preset
const TABS = [
  { id: "all",        label: "All Follows",      icon: "👤", statKey: "total_follows",  filters: { i_follow_them: true } },
  { id: "inactive",   label: "Inactive",          icon: "⏸", statKey: "inactive",       filters: { i_follow_them: true, is_inactive: true } },
  { id: "repost",     label: "Repost Heavy",      icon: "🔁", statKey: "repost_heavy",   filters: { i_follow_them: true, is_repost_heavy: true } },
  { id: "onesided",   label: "One-Sided",         icon: "↗",  statKey: "one_sided",      filters: { is_one_sided_follow: true } },
  { id: "followers",  label: "Followers Only",    icon: "↙",  statKey: "follower_only",  filters: { is_follower_only: true } },
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
    throw new Error(err.detail || res.statusText);
  }
  return res.status === 204 ? null : res.json();
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
      ${avatar(u)}
      <div class="user-info">
        <div class="user-name">${u.display_name || u.handle}</div>
        <div class="user-handle">@${u.handle}</div>
      </div>
      <div class="badges">${badges(u)}</div>
      <div class="user-meta">
        <div class="meta-item">
          <div class="meta-val">${fmt(u.followers_count)}</div>
          <div class="meta-lbl">followers</div>
        </div>
        <div class="meta-item">
          <div class="meta-val">${u.days_since_post != null ? u.days_since_post + "d" : "—"}</div>
          <div class="meta-lbl">inactive</div>
        </div>
        <div class="meta-item">
          <div class="meta-val">${pct(u.repost_ratio)}</div>
          <div class="meta-lbl">reposts</div>
        </div>
      </div>
    </a>`;
}

// ── Stats strip ───────────────────────────────────────────────────────────────
function renderStats() {
  const s = state.stats;
  el("stat-follows").textContent    = fmt(s.total_follows ?? "—");
  el("stat-followers").textContent  = fmt(s.total_followers ?? "—");
  el("stat-inactive").textContent   = fmt(s.inactive ?? "—");
  el("stat-repost").textContent     = fmt(s.repost_heavy ?? "—");
  el("stat-onesided").textContent   = fmt(s.one_sided ?? "—");
  el("stat-nointeract").textContent = fmt(s.no_interaction ?? "—");

  const synced = s.last_synced_at
    ? new Date(s.last_synced_at).toLocaleString()
    : "Never";
  el("last-synced").textContent = `Last synced: ${synced}`;
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

// ── User list ─────────────────────────────────────────────────────────────────
function renderUsers() {
  const list = el("user-list");

  if (state.loading) {
    list.innerHTML = `<div class="state-box">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4"/>
      </svg>
      Loading…</div>`;
    return;
  }

  if (!state.activeAlias) {
    list.innerHTML = `<div class="state-box">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
        <circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
      </svg>
      Add an account to get started</div>`;
    return;
  }

  if (state.users.length === 0) {
    list.innerHTML = `<div class="state-box">No accounts match your filters.</div>`;
    el("result-count").textContent = "0 results";
    return;
  }

  list.innerHTML = state.users.map(userRow).join("");
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
            onclick="switchAccount('${a.alias}')">
      @${a.handle}
    </button>`).join("");
}

// ── Sort controls ─────────────────────────────────────────────────────────────
function renderSortControls() {
  const sel = el("sort-by");
  sel.innerHTML = SORT_OPTIONS.map(o =>
    `<option value="${o.value}" ${state.sort.by === o.value ? "selected" : ""}>${o.label}</option>`
  ).join("");
}

// ── Fetch data from API ───────────────────────────────────────────────────────
async function fetchStats() {
  if (!state.activeAlias) return;
  state.stats = await api(`/api/users/${state.activeAlias}/stats`);
  renderStats();
  renderNav();
}

async function fetchUsers() {
  if (!state.activeAlias) return;
  state.loading = true;
  renderUsers();

  const params = new URLSearchParams();

  if (state.filters.search) params.set("search", state.filters.search);
  params.set("sort_by", state.sort.by);
  params.set("sort_dir", state.sort.dir);
  params.set("limit", state.pagination.limit);
  params.set("offset", state.pagination.offset);

  // Boolean filters — only send when not null
  const boolFlags = [
    "i_follow_them","they_follow_me","is_inactive","is_repost_heavy",
    "is_one_sided_follow","is_follower_only","interacted_with_owner","muted","blocked",
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
    state.users = data.users;
    state.total = data.total;
  } catch (e) {
    toast(e.message, "error");
    state.users = [];
    state.total = 0;
  }

  state.loading = false;
  renderUsers();
}

async function refresh() {
  await fetchStats();
  await fetchUsers();
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

// ── Account switching ─────────────────────────────────────────────────────────
async function switchAccount(alias) {
  state.activeAlias = alias;
  state.users = [];
  state.stats = {};
  state.activeTab = "all";

  // Reset filters to "all follows" default
  for (const key of Object.keys(state.filters)) state.filters[key] = null;
  state.filters.i_follow_them = true;

  renderAccountPills();
  renderNav();
  renderUsers();
  await refresh();
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
    toast(e.message, "error");
    endSync();
    return;
  }

  // Connect to SSE stream
  const es = new EventSource(`/api/sync/${state.activeAlias}/stream`);

  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);

    if (data.kind === "progress") {
      showSyncBar(data.message, data.pct);
    } else if (data.kind === "phase") {
      showSyncBar(data.message, null);
    } else if (data.kind === "done") {
      es.close();
      showSyncBar("Sync complete!", 100);
      setTimeout(() => {
        hideSyncBar();
        endSync();
        refresh();
        toast("Sync complete!");
      }, 800);
    } else if (data.kind === "error") {
      es.close();
      hideSyncBar();
      endSync();
      toast("Sync error: " + data.message, "error");
    }
  };

  es.onerror = () => {
    es.close();
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

function onSortBy(val) {
  state.sort.by = val;
  state.pagination.offset = 0;
  fetchUsers();
}

function onSortDir() {
  state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
  el("sort-dir-btn").textContent = state.sort.dir === "asc" ? "↑" : "↓";
  fetchUsers();
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
  renderSortControls();
  loadAccounts();
});
