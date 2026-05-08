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

  // Programmatically add Hive Plot button if it's not already in the HTML
  if (!document.getElementById('hive-view-link')) {
      const hiveBtn = document.createElement('button');
      hiveBtn.id = 'hive-view-link';
      hiveBtn.className = 'btn btn-ghost';
      hiveBtn.innerHTML = '<span>🍯</span> Hive Plot';
      hiveBtn.onclick = () => location.href = `/hive/${encodeURIComponent(ACTIVE_ALIAS)}`;
      hiveBtn.style.marginLeft = '0.5rem';
      if (resetBtn && resetBtn.parentNode) resetBtn.parentNode.appendChild(hiveBtn);
  }
  
  // Reset selection state and close panel before loading new view
  deselectNode();
  framesSinceLoad = 0;

  resetBtn.style.display = mode === 'macro' ? 'none' : 'block';
  
  try {
    statusEl.textContent = mode === 'macro' ? 'Fetching global network...' : 'Fetching neighborhood...';
    
    const url = new URL(`/api/graph/${encodeURIComponent(ACTIVE_ALIAS)}`, window.location.origin);
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
      .linkVisibility(link => {
          if (currentGraphMode === 'community_overview') return true;
          return !selectedNode || link.source === selectedNode || link.target === selectedNode;
      })
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
         // Migrate direct links to InfoPanel system
         if (typeof InfoPanel !== 'undefined' && node.did) {
             InfoPanel.open('profile', node.did);
         }
      })
      .onBackgroundClick(deselectNode);

    // Adjust forces
    graph.d3Force('charge').strength(node => {
        // Stronger repulsion for community meta-nodes to prevent blobs
        return node.type === 'community_meta' ? -1000 : -150;
    });
    
    graph.d3Force('link').distance(50);
    
    // Community Gravity: push different communities apart
    if (currentGraphMode === 'macro') {
        graph.d3Force('collide', d3.forceCollide(node => Math.sqrt(node.rank) * 100 + 5));
    }

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
    
    // Use modular InfoPanel
    if (typeof InfoPanel !== 'undefined') {
        if (node.type === 'community_meta') {
            const rawId = node.id.toString().replace('comm-', '');
            InfoPanel.open('community', rawId);
        } else if (node.did) {
            InfoPanel.open('profile', node.did);
        }
    }
    
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
    
    // Calculate visual offset: account for InfoPanel width if open
    const panel = document.getElementById('info-panel');
    const isPanelOpen = panel && panel.classList.contains('open');
    // info-panel.css uses 380px width
    const panelWidth = isPanelOpen ? (panel.offsetWidth || 380) : 0;

    const offset = (panelWidth / 2) / targetZoom;

    if (animate) graph.zoom(targetZoom, duration);
    graph.centerAt(node.x + offset, node.y, duration);
}

function deselectNode() {
    selectedNode = null;
    neighbors.clear();
    if (typeof InfoPanel !== 'undefined') InfoPanel.close();
    if (graph) graph.nodeRelSize(CONFIG.nodeRelSize);
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

    // Sync graph state with InfoPanel events
    if (!window._graphPanelListener) {
        window.addEventListener('infopanel:toggle', (e) => {
            if (!e.detail.open) {
                // If panel was closed via close button or backdrop, clear selection
                if (selectedNode) {
                    selectedNode = null;
                    neighbors.clear();
                    if (graph) graph.nodeRelSize(CONFIG.nodeRelSize);
                }
            } else if (selectedNode) {
                // Panel opened, re-center focus area
                centerOnNode(selectedNode, true);
            }
        });
        window._graphPanelListener = true;
    }
});

window.addEventListener('resize', () => graph && graph.width(window.innerWidth).height(window.innerHeight));