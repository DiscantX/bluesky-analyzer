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
let lastClickedNode = null;

async function loadGraphData(mode = 'macro', seedDid = null) {
  const statusEl = document.getElementById('graph-status');
  const metaEl = document.getElementById('graph-meta');
  const resetBtn = document.getElementById('reset-btn');
  
  resetBtn.style.display = mode === 'macro' ? 'none' : 'block';
  
  try {
    statusEl.textContent = mode === 'macro' ? 'Fetching global network...' : 'Fetching neighborhood...';
    
    const url = new URL(`/api/graph/${ACTIVE_ALIAS}`, window.location.origin);
    url.searchParams.set('mode', mode);
    url.searchParams.set('limit', mode === 'macro' ? 1500 : 500);
    if (seedDid) url.searchParams.set('seed_did', seedDid);

    const response = await fetch(url);
    const data = await response.json();

    if (!data.nodes || data.nodes.length === 0) {
      statusEl.textContent = 'No data found.';
      return;
    }

    metaEl.innerHTML = `Mode: ${mode === 'macro' ? 'Macro-View' : 'Ego-Graph'}<br>Nodes: ${data.metadata.node_count} | Links: ${data.metadata.link_count}`;
    if (mode === 'ego' && data.metadata.truncated_counts[seedDid]) {
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
      .nodeLabel(n => {
          const truncated = data.metadata.truncated_counts?.[n.did];
          return `@${n.handle}${truncated ? ` (+${truncated} neighbors)` : ''} (Rank: ${n.rank.toFixed(5)})`;
      })
      .nodeColor(n => COLORS[n.comm % COLORS.length])
      // Size based on square root of FlowRank score (Design Doc Tier A)
      .nodeVal(n => Math.sqrt(n.rank) * 200 + 1)
      .linkColor(CONFIG.linkColor)
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(d => 0.005)
      .linkDirectionalParticleWidth(1)
      .linkDirectionalParticleColor(CONFIG.particleColor)
      .backgroundColor('#0c0e14')
      .onNodeClick(node => {
        const now = Date.now();
        if (now - lastClickTime < 300 && lastClickedNode === node) {
          // Double Click: Walk into Ego-Graph
          loadGraphData('ego', node.did);
        } else {
          // Single Click: Center view
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

function resetToMacro() {
    loadGraphData('macro');
}

document.addEventListener('DOMContentLoaded', () => loadGraphData('macro'));

window.addEventListener('resize', () => graph && graph.width(window.innerWidth).height(window.innerHeight));