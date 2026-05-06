/**
 * static/js/graph.js
 * Handles the force-directed network visualization.
 */

const CONFIG = {
  nodeRelSize: 4,
  linkColor: () => 'rgba(255,255,255,0.1)',
  particleColor: () => 'rgba(167,139,250,0.4)',
};

// Categorical palette for communities
const COLORS = [
  '#5b8cf8', '#a78bfa', '#10b981', '#f59e0b', 
  '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6'
];

let graph = null;
let lastClickTime = 0;
let lastClickedNode = null; // Used for double-click detection
let selectedNode = null;
let neighbors = new Set();
let framesSinceLoad = 0; // Track simulation progress for camera following

let currentGraphMode = 'macro'; // 'macro', 'community_overview', 'community_detail', 'ego'
let currentCommunityId = null; // Tracks which community is being viewed in detail
let showParticles = true; // Global toggle state for flow particles

const fmt = (n) => n == null ? "—" : Number(n).toLocaleString();

async function loadGraphData(mode = 'macro', seedDid = null, communityId = null, spawnAt = null) {
  const statusEl = document.getElementById('graph-status');
  const metaEl = document.getElementById('graph-meta');
  const resetBtn = document.getElementById('reset-btn');
  const communityOverviewBtn = document.getElementById('community-overview-btn');
  const backToCommunityBtn = document.getElementById('back-to-community-btn');
  
  // Reset selection state and close panel before loading new view
  deselectNode();
  framesSinceLoad = 0;

  resetBtn.style.display = mode === 'macro' ? 'none' : 'block';
  
  try {
    statusEl.textContent = mode === 'macro' ? 'Fetching global network...' : 'Fetching neighborhood...';
    
    const url = new URL(`/api/graph/${ACTIVE_ALIAS}`, window.location.origin);
    url.searchParams.set('mode', mode);
    
    // Adjust limit based on mode
    let limit = 1500;
    if (mode === 'ego' || mode === 'community') {
        limit = 500; // Smaller limit for detailed views
    }
    url.searchParams.set('limit', limit);

    if (communityId !== null) url.searchParams.set('community_id', communityId);
    if (seedDid) url.searchParams.set('seed_did', seedDid);

    const response = await fetch(url);
    const data = await response.json();

    if (!data.nodes || data.nodes.length === 0) {
      statusEl.textContent = 'No data found.';
      return;
    }

    currentGraphMode = mode;
    currentCommunityId = communityId;

    if (!graph) {
      const elem = document.getElementById('graph-container');
      graph = ForceGraph()(elem);
    }

    // --- Shattering Logic (Design Doc Tier B) ---
    // If we have a spawn point, initialize all new nodes at that location
    // to create the "shatter" expansion effect.
    const nodes = data.nodes.map(n => {
        const nodeObj = { ...n, id: n.did || `comm-${n.id}` };
        if (spawnAt) {
            nodeObj.x = spawnAt.x;
            nodeObj.y = spawnAt.y;
        }
        return nodeObj;
    });

    // Memory Safety: Clear existing data arrays before loading new scene
    graph.graphData({ nodes: [], links: [] });

    const graphData = {
      nodes: nodes,
      links: data.links
    };

    // Pre-calculate neighbors for highlighting logic
    data.links.forEach(link => {
        const a = nodes.find(n => n.id === (link.source.id || link.source));
        const b = nodes.find(n => n.id === (link.target.id || link.target));
        if (a && b) {
            if (!a.neighbors) a.neighbors = [];
            if (!b.neighbors) b.neighbors = [];
            a.neighbors.push(b);
            b.neighbors.push(a);
        }
    });

    // Update UI buttons visibility
    resetBtn.style.display = mode === 'macro' ? 'none' : 'block';
    communityOverviewBtn.style.display = (mode === 'macro' || mode === 'ego') ? 'block' : 'none';
    backToCommunityBtn.style.display = (mode === 'community' && communityId !== null || mode === 'ego') ? 'block' : 'none';

    let modeLabel = '';
    if (mode === 'macro') modeLabel = 'Macro-View';
    else if (mode === 'ego') modeLabel = 'Ego-Graph';
    else if (mode === 'community' && communityId === null) modeLabel = 'Community Overview';
    else if (mode === 'community' && communityId !== null) modeLabel = `Community ${communityId} Detail`;

    metaEl.innerHTML = `Mode: ${modeLabel}<br>Nodes: ${data.metadata.node_count} | Links: ${data.metadata.link_count}`;
    
    if (mode === 'ego' && data.metadata.truncated_counts && data.metadata.truncated_counts[seedDid]) {
        metaEl.innerHTML += `<br>Ghost Nodes: +${data.metadata.truncated_counts[seedDid]} hidden neighbors`;
    }

    graph.graphData(graphData)
      .nodeId('id')
      .nodeLabel(node => {
          if (node.type === 'community_meta') {
              const name = node.name || `Community ${node.id.toString().replace('comm-', '')}`;
              return `${name} (${node.member_count} members, Avg Rank: ${(node.avg_rank * 1000).toFixed(4)})`;
          }
          const truncated = data.metadata.truncated_counts?.[node.did]; // Tooltip for ghost nodes
          const commPart = node.comm_name ? ` [${node.comm_name}]` : '';
          return `@${node.handle}${commPart}${truncated ? ` (+${truncated} neighbors)` : ''} (Rank: ${(node.rank * 1000).toFixed(4)})`;
      })
      .nodeColor(node => {
          if (node.type === 'community_meta') {
              return COLORS[node.id % COLORS.length]; // Color meta-nodes by their community ID
          }
          return COLORS[node.comm % COLORS.length];
      })
      // Size based on square root of FlowRank score (Design Doc Tier A)
      .nodeVal(node => {
          if (node.type === 'community_meta') {
              return Math.sqrt(node.member_count) * 5 + 1; // Size meta-nodes by member count
          }
          return Math.sqrt(node.rank) * 200 + 1;
      })
      .nodeCanvasObject((node, ctx, globalScale) => {
          const isMeta = node.type === 'community_meta';
          const r = (isMeta ? Math.sqrt(node.member_count) * 2.5 + 1 : Math.sqrt(node.rank) * 100 + 0.5);
          
          const isHighlighted = !selectedNode || selectedNode === node || neighbors.has(node);
          ctx.save();
          ctx.globalAlpha = isHighlighted ? 1 : 0.1;

          // Draw main node circle
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
          ctx.fillStyle = node.color;
          ctx.fill();
          // Subtle stroke
          ctx.strokeStyle = node.type === 'community_meta' ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.2)';
          ctx.lineWidth = 1 / globalScale;
          ctx.stroke();

           // --- Semantic Zoom Logic (Design Doc Section 5) ---
          // Labels fade in based on zoom level and node importance
          const labelThreshold = isMeta ? 0.2 : 2.5;
          if (globalScale > labelThreshold) {
              const label = isMeta ? (node.name || `Community ${node.id.toString().replace('comm-', '')}`) : `@${node.handle}`;
              const fontSize = (isMeta ? 14 : 10) / globalScale;
              ctx.font = `${fontSize}px Sans-Serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillStyle = 'rgba(232, 234, 240, 0.85)';
              ctx.fillText(label, node.x, node.y + r + fontSize + 2);
          }
          ctx.restore();
      })
      .linkColor(link => {
          if (!selectedNode) return CONFIG.linkColor();
          const isHighlighted = link.source === selectedNode || link.target === selectedNode;
          return isHighlighted ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.02)';
      })
      .linkDirectionalParticles(link => {
          if (!showParticles) return 0;
          if (!selectedNode) return 4;
          return (link.source === selectedNode || link.target === selectedNode) ? 4 : 0;
      })
      .linkDirectionalParticleSpeed(d => 0.005)
      .linkDirectionalParticleWidth(1)
      .linkDirectionalParticleColor(CONFIG.particleColor)
      .backgroundColor('#0c0e14')
      .linkVisibility(link => currentGraphMode !== 'community_overview')
      .onNodeClick(node => {
        const now = Date.now();
        if (now - lastClickTime < 300 && lastClickedNode === node) {
          // Double Click Logic
          if (node.type === 'community_meta') {
            // Shatter Meta-node into community details
            const rawId = node.id.toString().replace('comm-', '');
            loadGraphData('community', null, rawId, { x: node.x, y: node.y });
          } else if (node.did) {
            // Walk into Ego-Graph
            loadGraphData('ego', node.did, null, { x: node.x, y: node.y });
          }
        } else {
          handleNodeSelection(node);
        }
        lastClickTime = now;
        lastClickedNode = node;
      })
      .onNodeRightClick(node => {
         window.open(`https://bsky.app/profile/${node.did}`, '_blank');
      })
      .onBackgroundClick(deselectNode);

    // Adjust forces
    graph.d3Force('charge').strength(-120);
    graph.d3Force('link').distance(50);

    // Pre-selection and Centering Logic for drill-downs (UX Improvement)
    if (spawnAt) {
        // Immediately center on the explosion point
        graph.centerAt(spawnAt.x, spawnAt.y);
    }

    if (mode === 'ego' && seedDid) {
        const target = nodes.find(n => n.did === seedDid);
        if (target) handleNodeSelection(target);
    } else if (mode === 'community' && communityId !== null && nodes.length > 0) {
        // For community shatter, pre-select the highest-ranked member
        handleNodeSelection(nodes[0]);
    }

    // Freeze simulation when stable to save CPU (Design Doc Section 7)
    graph.onEngineTick(() => {
        framesSinceLoad++;
        // Follow the selected node during the first 2 seconds of expansion (shatter effect tracking)
        if (selectedNode && framesSinceLoad < 120) {
            centerOnNode(selectedNode, false);
        }
    });

    graph.onEngineStop(() => {
        statusEl.textContent = 'Simulation stabilized.';
        console.log('Graph simulation stopped.');
    });

  } catch (err) {
    console.error('Graph init failed:', err);
    statusEl.textContent = 'Error loading graph.';
  }
}

async function handleNodeSelection(node) {
    if (selectedNode === node) {
        deselectNode();
        return;
    }
    selectedNode = node;
    neighbors = new Set(node.neighbors || []);
    
    // Open panel first so we can calculate the correct unoccluded offset
    showNodeDetails(node);
    
    centerOnNode(node, true);
    
    // Force re-render for highlighting
    graph.nodeRelSize(CONFIG.nodeRelSize);
}

/**
 * Centers the camera on a node, accounting for UI occlusion (side panel).
 */
function centerOnNode(node, animate = true) {
    if (!graph || !node) return;

    const duration = animate ? 1000 : 0;
    const currentZoom = graph.zoom() || 1;

    // During initial selection, force zoom to 4. 
    // During simulation tracking, respect the user's current zoom level to allow manual scrolling.
    const targetZoom = animate ? 4 : currentZoom;
    
    // Calculate visual offset: If panel is on the right, shift camera focus to the right
    // to keep the node centered in the left-hand workspace.
    const panel = document.getElementById('side-panel');
    
    // Fallback to 350px (standard sidebar width) if panel is open but width isn't yet rendered
    const isPanelOpen = panel && panel.classList.contains('open');
    const panelWidth = isPanelOpen ? (panel.offsetWidth || 350) : 0;
    
    const offset = (panelWidth / 2) / targetZoom;

    if (animate) graph.zoom(targetZoom, duration);
    graph.centerAt(node.x + offset, node.y, duration);
}

function deselectNode() {
    selectedNode = null;
    neighbors.clear();
    const panel = document.getElementById('side-panel');
    if (panel) panel.classList.remove('open');
    if (graph) graph.nodeRelSize(CONFIG.nodeRelSize);
}

async function showNodeDetails(node) {
    const panel = document.getElementById('side-panel');
    const content = document.getElementById('panel-content');
    panel.classList.add('open');
    
    if (node.type === 'community_meta') {
        const rawId = node.id.toString().replace('comm-', '');
        
        let keywordHtml = '—';
        if (node.top_keywords) {
            try {
                const kws = typeof node.top_keywords === 'string' ? JSON.parse(node.top_keywords) : node.top_keywords;
                keywordHtml = Object.entries(kws)
                    .sort((a, b) => b[1] - a[1])
                    .map(([word]) => `<span class="badge" style="margin: 2px; background: var(--surface2); border: 1px solid var(--border); font-size: 0.7rem;">${word}</span>`)
                    .join('');
            } catch (e) { console.error("Error parsing keywords", e); }
        }

        let membersHtml = '—';
        if (node.representative_members) {
            try {
                const members = typeof node.representative_members === 'string' ? JSON.parse(node.representative_members) : node.representative_members;
                membersHtml = members.map(m => `<div style="font-size: 0.75rem; color: var(--accent); margin-bottom: 2px;">${m}</div>`).join('');
            } catch (e) { console.error("Error parsing members", e); }
        }

        content.innerHTML = `
            <div style="padding: 1rem;">
                <div style="margin-bottom: 1.5rem;">
                    <div style="font-size: 1.2rem; font-weight: 800; color: var(--accent2); margin-bottom: 0.25rem;">${node.name || `Community ${rawId}`}</div>
                    <div style="font-style: italic; font-size: 0.85rem; color: var(--muted); line-height: 1.4;">${node.description || 'No description available for this cluster.'}</div>
                </div>

                <div class="sidebar-label">Cluster Metrics</div>
                <div style="background:var(--surface2); padding:0.75rem; border-radius:4px; font-family:var(--mono); font-size:0.7rem; margin-bottom:1.5rem;">
                    <div style="display:flex; justify-content:space-between;"><span>Total Members</span><span style="color:var(--accent); font-weight: bold;">${fmt(node.member_count)}</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>Avg Influence</span><span style="color:var(--accent); font-weight: bold;">${(node.avg_rank * 1000).toFixed(4)}</span></div>
                </div>

                <div class="sidebar-label">Top Keywords</div>
                <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 1.5rem;">
                    ${keywordHtml}
                </div>

                <div class="sidebar-label">Representative Figures</div>
                <div style="background:var(--surface2); padding:0.75rem; border-radius:4px; margin-bottom:1.5rem;">
                    ${membersHtml}
                </div>

                <div class="state-box" style="font-size: 0.7rem; border-style: dashed; opacity: 0.8;">
                    Double-click the sphere in the network to shatter this meta-node into individual profiles.
                </div>
            </div>
        `;
        return;
    }

    content.innerHTML = `<div class="state-box">Loading profile...</div>`;
    
    try {
        const params = new URLSearchParams();
        params.set('limit', '1');
        params.set('filter_tree', JSON.stringify({ op: "AND", conditions: [{ field: "did", op: "eq", value: node.did }] }));

        const response = await fetch(`/api/users/${ACTIVE_ALIAS}?${params.toString()}`);
        const result = await response.json();
        const u = result.users[0];
        
        if (!u) { content.innerHTML = `<div class="state-box">Profile not in DB.</div>`; return; }

        content.innerHTML = `
            <div style="padding: 1rem;">
                <div style="display:flex; gap:1rem; align-items:center; margin-bottom:1.5rem;">
                    ${u.avatar_url ? `<img src="${u.avatar_url}" style="width:56px; height:56px; border-radius:50%; border:1px solid var(--border);">` : `<div class="avatar-placeholder" style="width:56px; height:56px;">${u.handle[0].toUpperCase()}</div>`}
                    <div style="overflow:hidden;">
                        <div style="font-weight:800; white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">${u.display_name || '—'}</div>
                        <div style="font-family:var(--mono); font-size:0.75rem; color:var(--accent);">@${u.handle}</div>
                    </div>
                </div>

                <div class="sidebar-label">Network Position</div>
                <div style="background:var(--surface2); padding:0.75rem; border-radius:4px; font-family:var(--mono); font-size:0.7rem; margin-bottom:1rem;">
                    <div style="display:flex; justify-content:space-between;"><span>FlowRank</span><span style="color:var(--accent);">${(u.flowrank_score * 1000).toFixed(4)}</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>Community</span><span style="color:var(--accent2);" title="${u.comm_name || ''}">${u.comm_name || '#' + (u.community_id ?? '—')}</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>In-Degree</span><span>${u.in_subgraph_degree}</span></div>
                </div>

                <div class="sidebar-label">Activity Signals</div>
                <div style="background:var(--surface2); padding:0.75rem; border-radius:4px; font-family:var(--mono); font-size:0.7rem; margin-bottom:1rem;">
                    <div style="display:flex; justify-content:space-between;"><span>Repost Ratio</span><span>${(u.repost_ratio * 100).toFixed(1)}%</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>Last Post</span><span>${u.days_since_post != null ? u.days_since_post + 'd ago' : '—'}</span></div>
                    <div style="display:flex; justify-content:space-between;"><span>Interacted</span><span style="color:${u.interacted_with_owner ? 'var(--repost)' : 'var(--muted)'};">${u.interacted_with_owner ? 'YES' : 'NO'}</span></div>
                </div>

                <div style="display:flex; gap:0.5rem; margin-top:2rem;">
                    <a href="https://bsky.app/profile/${u.did}" target="_blank" class="btn btn-primary" style="flex:1; justify-content:center;">Open in Bluesky</a>
                </div>
            </div>
        `;
    } catch (err) {
        content.innerHTML = `<div class="state-box" style="color:var(--danger)">Failed to fetch profile.</div>`;
    }
}

// UI functions for navigation
function resetToMacro() {
    loadGraphData('macro');
}

function showCommunityOverview() {
    loadGraphData('community', null, null);
}

function backToCommunityOverview() {
    loadGraphData('community', null, null);
}

function toggleParticles(enabled) {
    showParticles = enabled;
    if (graph) {
        graph.linkDirectionalParticles(showParticles ? 4 : 0);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Initial load: start with macro view
    loadGraphData('macro');
});

window.addEventListener('resize', () => graph && graph.width(window.innerWidth).height(window.innerHeight));