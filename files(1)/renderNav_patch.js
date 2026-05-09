// ── Sidebar nav ───────────────────────────────────────────────────────────────
// PATCH: replace the existing renderNav function in app.js with this version.
// The only change is adding the "📊 Chart Studio" nav item before Network Graph.

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
    <a class="nav-item" href="/charts/${encodeURIComponent(state.activeAlias || "")}" style="text-decoration:none;">
      <span>📊</span><span>Chart Studio</span>
    </a>
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
