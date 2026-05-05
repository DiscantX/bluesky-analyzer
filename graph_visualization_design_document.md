# Graph Visualization Design Document

## 1. Objective
To provide an interactive, spatial representation of the Bluesky social network. The graph should surface community structures, identify bridge influencers, and allow for hierarchical discovery without crashing the browser on million-node datasets.

## 2. Technical Stack
- **Engine:** `force-graph` (HTML5 Canvas-based).
- **Rationale:** 
    - **SVG (Raw D3)** chokes at ~1,000 nodes due to DOM overhead.
    - **WebGL** is performant but adds extreme complexity for text rendering and interaction.
    - **Canvas** provides a "Goldilocks" zone: handling 5,000–10,000 nodes smoothly while maintaining simple interaction logic and readable labels.
- **Physics:** D3-force (Barnes-Hut simulation) running on the CPU.

## 3. Scale Management Strategy (Tiered Exploration)
We do not render the "whole" graph. We use a three-tier visibility model:

### Tier A: Global Macro-View (The Constellations)
- **Content:** Top 1,000–2,000 nodes globally.
- **Sampling Logic:** Stratified sampling.
    - Top 50 nodes by FlowRank per `community_id`.
    - High-bridge-score nodes (low clustering, high FlowRank).
    - A 5% random "discovery" sample of active Tier 1/2 nodes.
- **Purpose:** Provides a "Map of the Galaxy" view of the network.

### Tier B: Community View (The Clusters)
- **Visual:** Communities are initially represented as "Meta-Nodes" (spheres sized by member count).
- **Shattering Logic:** Clicking a Meta-Node triggers a "shatter" transition:
    - The meta-node disappears.
    - Its constituent nodes (standard profiles) spawn at the centroid.
    - A temporary force pulls them toward the centroid to keep the cluster contained.

### Tier C: Ego-Graph (The Neighborhood)
- **Trigger:** Searching for a handle or double-clicking a node.
- **Content:** The "Seed" node + immediate neighbors (Depth 1 and 2).
- **Constraints:** 
    - **Hard Cap:** 1,000 nodes.
    - **Pruning:** If neighbors > 1,000, prioritize: Mutual Follows > Highest FlowRank > Recently Active.
    - **Ghost Nodes:** Truncated edges are represented as "Ghost Nodes" (e.g., "+4.2k followers").

## 4. Visual Language
- **Node Radius:** `sqrt(flowrank_score) * scale_factor`.
- **Node Color:** Discrete categorical palette based on `community_id`.
- **Edge Styling:** 
    - **Solid:** Mutual follow.
    - **Faded/Gradient:** One-way follow.
    - **Opacity:** Represents "Data Confidence." Stub nodes (Tier 0) are 30% opaque; analyzed nodes are 100% opaque.
- **Labels:** Hidden by default. Fade in on hover or high zoom level.

## 5. Interaction Model
| Action | Result |
|---|---|
| **Hover** | Tooltip with Handle, FlowRank, and Community Name. |
| **Single Click** | Select Node. Highlight local neighborhood, dim the rest. Update Side Panel. |
| **Double Click** | Recenter Graph. Clear current view and fetch Depth-2 Ego Graph for that node. |
| **Scroll Zoom** | Semantic Zoom. Transition from Meta-Nodes (Communities) to Profiles. |
| **Time Slider** | Filter nodes by `last_post_at` to see "live" network segments. |

## 6. API Specification
### `GET /api/graph/{alias}`
**Query Parameters:**
- `mode`: `macro` (stratified) | `ego` (neighborhood) | `community` (cluster focus)
- `seed_did`: Required for `ego` mode.
- `community_id`: Required for `community` mode.
- `limit`: Max nodes to return (default 1000).

**Response Schema:**
```json
{
  "nodes": [
    { "id": "did:...", "handle": "...", "rank": 0.004, "comm": 4, "tier": 1 }
  ],
  "links": [
    { "source": "did:A", "target": "did:B", "weight": 1 }
  ],
  "metadata": {
    "truncated_counts": { "did:A": 450 }
  }
}
```

## 7. Performance & Memory Safety
1. **Simulation Freeze:** The force simulation runs with high `alphaDecay`. Once `alpha < 0.01`, `simulation.stop()` is called. This prevents background CPU usage while the user is inspecting.
2. **Scene Disposal:** Before loading a new "Ego Graph," the previous Canvas context and data arrays must be explicitly cleared for Garbage Collection.
3. **Ghosting:** No full profile data is sent in the graph packet. Only IDs and metrics. Full profile data is fetched on-demand when a node is selected.

## 8. Implementation Steps
1. **Phase 1:** Backend SQL for Stratified Sampling (Top-N per Community).
2. **Phase 2:** Basic Canvas rendering of the Macro-view.
3. **Phase 3:** Ego-graph "Walk" logic (Click to re-center and fetch).
4. **Phase 4:** Semantic Zoom (Meta-nodes to Profiles).
```

This document sets the ground rules. We avoid the "millions of nodes" trap by using smart sampling and localized ego-graphs, while the Canvas-based engine gives us a high enough limit to make the visualization feel expansive.

How would you like to start? We could look at the **SQL logic for the Stratified Sampling** or set up the **D3/Canvas frontend boilerplate**.

<!--
[PROMPT_SUGGESTION]Draft the SQL query for Stratified Sampling (Top-N per Community) to feed the graph API.[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Set up the initial force-graph boilerplate in a new static/js/graph.js file.[/PROMPT_SUGGESTION]
