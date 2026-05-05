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

let currentGraphMode = 'macro'; // 'macro', 'community_overview', 'community_detail', 'ego'
let currentCommunityId = null; // Tracks which community is being viewed in detail

async function loadGraphData(mode = 'macro', seedDid = null, communityId = null) {
  const statusEl = document.getElementById('graph-status');
  const metaEl = document.getElementById('graph-meta');
  const resetBtn = document.getElementById('reset-btn');
  const communityOverviewBtn = document.getElementById('community-overview-btn');
  const backToCommunityBtn = document.getElementById('back-to-community-btn');
  
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

    // Update UI buttons visibility
    resetBtn.style.display = (mode === 'macro' || mode === 'community_overview') ? 'none' : 'block';
    communityOverviewBtn.style.display = (mode === 'macro' || mode === 'ego') ? 'block' : 'none';
    backToCommunityBtn.style.display = (mode === 'community_detail' || mode === 'ego') ? 'block' : 'none';

    let modeLabel = '';
    if (mode === 'macro') modeLabel = 'Macro-View';
    else if (mode === 'ego') modeLabel = 'Ego-Graph';
    else if (mode === 'community' && communityId === null) modeLabel = 'Community Overview';
    else if (mode === 'community' && communityId !== null) modeLabel = `Community ${communityId} Detail`;

    metaEl.innerHTML = `Mode: ${modeLabel}<br>Nodes: ${data.metadata.node_count} | Links: ${data.metadata.link_count}`;
    
    // Display ghost nodes only for ego-graph
    if (mode === 'ego' && data.metadata.truncated_counts && data.metadata.truncated_counts[seedDid]) {
        metaEl.innerHTML += `<br>Ghost Nodes: +${data.metadata.truncated_counts[seedDid]} hidden neighbors`;
    }

    const graphData = {
      nodes: data.nodes.map(n => ({ ...n, id: n.did })),
      links: data.links
    };

    if (!graph) {
      const elem = document.getElementById('graph-container');
      graph = ForceGraph()(elem);
    }

    graph.graphData(graphData)
      .nodeId('id')
      .nodeLabel(node => {
          if (node.type === 'community_meta') {
              return `Community ${node.id} (${node.member_count} members, Avg Rank: ${node.avg_rank.toFixed(5)})`;
          }
          const truncated = data.metadata.truncated_counts?.[node.did];
          return `@${node.handle}${truncated ? ` (+${truncated} neighbors)` : ''} (Rank: ${node.rank.toFixed(5)})`;
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
          const r = node.val / 2;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
          ctx.fillStyle = node.color;
          ctx.fill();
          ctx.strokeStyle = 'rgba(255,255,255,0.3)';
          ctx.lineWidth = 1;
          ctx.stroke();

          if (node.type === 'community_meta') {
              // Draw text label for meta-nodes
              const label = `Comm ${node.id}`;
              const fontSize = 12 / globalScale;
              ctx.font = `${fontSize}px Sans-Serif`;
              ctx.textAlign = 'center';
              ctx.textBaseline = 'middle';
              ctx.fillStyle = 'white';
              // Position below the node
              ctx.fillText(label, node.x, node.y + r + fontSize / 2 + 2);
          }
      })
      .linkColor(CONFIG.linkColor)
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(d => 0.005)
      .linkDirectionalParticleWidth(1)
      .linkDirectionalParticleColor(CONFIG.particleColor)
      .backgroundColor('#0c0e14')
      .linkVisibility(link => {
          return currentGraphMode !== 'community_overview'; // Hide links between meta-nodes
      })
      .onNodeClick(node => {
        const now = Date.now();
        if (now - lastClickTime < 300 && lastClickedNode === node) {
          // Double Click: Walk into Ego-Graph
          loadGraphData('ego', node.did);
        } else {
          // Single Click: Center view and zoom in slightly
          graph.centerAt(node.x, node.y, 1000);
          graph.zoom(4, 1000);
        }
        lastClickTime = now;
        lastClickedNode = node;
      })
      .onNodeRightClick(node => {
         window.open(`https://bsky.app/profile/${node.did}`, '_blank');
      });

    // Adjust forces
    graph.d3Force('charge').strength(-120);
    graph.d3Force('link').distance(50);

    // Freeze simulation when stable to save CPU (Design Doc Section 7)
    graph.onEngineStop(() => {
        statusEl.textContent = 'Simulation stabilized.';
        console.log('Graph simulation stopped.');
    });

  } catch (err) {
    console.error('Graph init failed:', err);
    statusEl.textContent = 'Error loading graph.';
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

document.addEventListener('DOMContentLoaded', () => {
    // Initial load: start with macro view
    loadGraphData('macro');
});

window.addEventListener('resize', () => graph && graph.width(window.innerWidth).height(window.innerHeight));