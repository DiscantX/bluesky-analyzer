# Chart Studio — Design & Implementation Reference
**Bluesky Analyzer · Living Design Document**
*Last updated: Session 1*

---

## 1. Overview

Chart Studio is a first-class feature of the Bluesky Analyzer that lets users create, save, and view custom interactive visualizations of their social network data. It is not a bolt-on — it absorbs and replaces the existing hardcoded visualization pages (Network Graph, Hive Plot, Circle Packing) and becomes the canonical home for all graph-type views.

The system is built on three principles:

1. **Reuse everything.** The filter pipeline, variable system, and query engine from the main dashboard are consumed directly. No parallel implementations.
2. **Open-ended chart types.** Chart types are registered, not hardcoded. Adding a new type touches only the registry and a renderer file — no schema changes, no API changes.
3. **Build for WebGL from day one.** SVG renderers ship first. WebGL renderers drop in later. The abstraction layer is in place before it is needed.

---

## 2. Navigation & Page Structure

### 2.1 Sidebar

The left sidebar's Visualization section is restructured as follows. All existing hardcoded visualization links are removed:

```
── VISUALIZATION ──────────────────
📊 Charts
📌 Network Graph          ← pinned chart (default)
[user-pinned charts appear here]
```

"Charts" links to the gallery page. Pinned charts appear below it as direct links to their full-screen view pages. The Network Graph is pre-pinned. Users can pin/unpin any saved chart. Pin state is stored on the `ChartDefinition` model (`pinned: bool`).

### 2.2 Routes

Four routes, all full-screen:

| Route | Purpose |
|---|---|
| `/charts/{alias}` | Gallery — grid of saved chart preview cards |
| `/charts/{alias}/new` | Studio — create a new chart |
| `/charts/{alias}/{id}/edit` | Studio — edit an existing chart |
| `/charts/{alias}/{id}/view` | Full-screen chart view |

The existing `/graph/{alias}`, `/hive/{alias}`, and `/pack/{alias}` routes are kept alive as redirects to the corresponding seeded chart view URLs until all users have migrated. They are not immediately removed.

### 2.3 Gallery Page (`/charts/{alias}`)

A CSS grid of large preview cards, roughly 3 columns at desktop width. Each card:

- Renders a live mini-chart (the actual D3/canvas renderer at reduced scale, `interactive: false`, point limit 200)
- Shows the chart name, icon, type badge, and last-updated date
- Clicking the card body navigates to the full-screen view
- An Edit button (hover-revealed) navigates to studio
- A Pin toggle (hover-revealed) updates pin state via PATCH
- A Delete button (hover-revealed, with confirm) deletes the chart

Default charts are seeded silently on first visit (see §7.5).

### 2.4 Studio Page (`/charts/{alias}/new`, `/{id}/edit`)

Split layout: builder panel on the left, live preview on the right. The preview re-renders with a 500 ms debounce on any builder change.

```
┌───────────────────────────────────────────────────────────────────┐
│ ← Charts    [Untitled Chart]    [Discard]  [Save]  [Pin toggle]   │
├─────────────────────┬─────────────────────────────────────────────┤
│  BUILDER            │                                             │
│  ─────────────────  │           LIVE PREVIEW                      │
│  Chart Type         │           (debounced re-render)             │
│  [Scatter ▼]        │                                             │
│                     │                                             │
│  Data Population    │                                             │
│  [My Follows  ▼]    │                                             │
│  [+ Custom Filter]  │                                             │
│                     │                                             │
│  Dimensions         │                                             │
│  x  [FlowRank  ▼]   │                                             │
│     Scale [Log ▼]   │                                             │
│  y  [Followers ▼]   │                                             │
│     Scale [Log ▼]   │                                             │
│  color [Comm. ▼]    │                                             │
│  [+ Add Dimension]  │                                             │  
│                     │                                             │
│  Options            │                                             │
│  Limit [2000    ]   │                                             │
│  Agg.  [Avg ▼]      │  ← only shown when chart type requires it   │
│                     │                                             │
└─────────────────────┴─────────────────────────────────────────────┘
```

### 2.5 Full-Screen View Page (`/{id}/view`)

The chart fills the entire viewport. A thin (40px) top bar contains:

- ← Back to Charts
- Chart name
- Edit button
- Export button (Phase 7)
- Pin toggle

The profile side panel slides in from the right when a data point, node, or bar is clicked (see §8, Profile Panel).

---

## 3. Data Model

### 3.1 `ChartDefinition` (new table: `chart_definitions`)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `owner_id` | FK → `saved_accounts` | |
| `name` | varchar(128) | |
| `icon` | varchar(8) null | Emoji |
| `description` | text null | User-facing notes |
| `chart_type` | varchar(64) | Registry key, e.g. `scatter`, `hive`, `bar` |
| `dimensions` | text | JSON — see §3.2 |
| `filter_set_id` | int null | FK → `filter_sets` (optional) |
| `filter_tree` | text null | Inline JSON filter tree (alternative to FK) |
| `aggregation` | varchar(16) null | `avg` `sum` `count` `max` `min` — for aggregated chart types |
| `limit` | int | Default 2000, max 10000 |
| `sort_by` | varchar(64) null | Column to sort/rank before applying limit |
| `sort_dir` | varchar(8) | `asc` / `desc` |
| `options` | text null | JSON — chart-type-specific display options |
| `pinned` | bool | Default false; pinned charts appear in sidebar |
| `pin_order` | int null | Sort order within pinned list |
| `created_at` | datetime | |
| `updated_at` | datetime auto | |

Exactly one of `filter_set_id` or `filter_tree` is set, or neither (meaning "all accounts"). The query engine checks `filter_set_id` first, falls back to `filter_tree`, then falls back to no filter.

### 3.2 `AxisConfig` — the `dimensions` JSON structure

`dimensions` is a JSON object whose keys are defined by the chart type registry. Each value is an `AxisConfig`:

```json
{
  "source": "field",
  "field": "flowrank_score",
  "label": "FlowRank",
  "scale": "log",
  "domain": [null, null]
}
```

| Field | Values | Notes |
|---|---|---|
| `source` | `field` `variable` `expression` | How the value is resolved |
| `field` | string | Built-in column name if `source=field`; variable name if `source=variable`; ignored if `source=expression` |
| `expression` | object null | Inline math tree (same JSON format as filter builder math nodes) if `source=expression` |
| `label` | string | Display label for axes and tooltips |
| `scale` | `linear` `log` `sqrt` `time` | D3 scale type |
| `domain` | `[min, max]` | Override auto-domain; null values mean auto |

#### Examples

```json
// Scatter chart dimensions
{
  "x":     { "source": "field",    "field": "flowrank_score",       "label": "FlowRank",  "scale": "log"    },
  "y":     { "source": "field",    "field": "followers_count",      "label": "Followers", "scale": "log"    },
  "color": { "source": "field",    "field": "community_id",         "label": "Community", "scale": "linear" },
  "size":  { "source": "variable", "field": "FollowerRatio",        "label": "Ratio",     "scale": "sqrt"   }
}

// Hive chart — dynamic axes, N >= 3
{
  "axis_0":    { "source": "field", "field": "flowrank_score",         "label": "Influence",  "scale": "log"    },
  "axis_1":    { "source": "field", "field": "posts_count",            "label": "Activity",   "scale": "log"    },
  "axis_2":    { "source": "field", "field": "clustering_coefficient", "label": "Clustering", "scale": "linear" },
  "axis_3":    { "source": "variable", "field": "FollowerRatio",       "label": "Ratio",      "scale": "linear" },
  "link_color":{ "source": "field", "field": "community_id",           "label": "Community",  "scale": "linear" }
}

// Force-directed — no positional axes, node attributes only
{
  "node_size":  { "source": "field", "field": "flowrank_score",   "label": "FlowRank",   "scale": "sqrt"   },
  "node_color": { "source": "field", "field": "community_id",     "label": "Community",  "scale": "linear" }
}

// Circle packing — grouping + sizing
{
  "group_by": { "source": "field", "field": "community_id",    "label": "Community", "scale": "linear" },
  "size":     { "source": "field", "field": "flowrank_score",  "label": "FlowRank",  "scale": "sqrt"   },
  "color":    { "source": "field", "field": "community_id",    "label": "Community", "scale": "linear" }
}
```

### 3.3 `options` JSON

Chart-type-specific display settings that don't fit the dimension model. Each chart type's registry entry documents which keys are valid. Examples:

```json
// Scatter
{ "point_radius": 4, "point_opacity": 0.7, "show_labels_above": 50 }

// Hive
{ "inner_radius": 40, "link_curvature": "quadratic", "show_cross_axis_only": true }

// Force-directed
{ "charge_strength": -150, "link_distance": 50, "particle_speed": 0.005, "show_particles": true }

// Histogram
{ "bin_count": 30, "show_density_curve": true }

// Violin
{ "bandwidth": 0.4, "show_box": true, "show_points": false }
```

---

## 4. Chart Type Registry

The registry lives in `api/chart_registry.py` and is imported wherever chart type metadata is needed. Adding a new chart type requires only adding an entry here and a renderer in `static/js/renderers/`.

### 4.1 Registry Structure

```python
CHART_REGISTRY = {
    "scatter": {
        "label": "Scatter Plot",
        "icon": "⚬",
        "description": "Plot two numeric values against each other. Each point is one account.",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["numeric"],               "label": "X Axis",     "dynamic": False },
            "y":     { "required": True,  "accepts": ["numeric"],               "label": "Y Axis",     "dynamic": False },
            "color": { "required": False, "accepts": ["numeric", "categorical"],"label": "Color By",   "dynamic": False },
            "size":  { "required": False, "accepts": ["numeric"],               "label": "Point Size", "dynamic": False },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,   # flip to True when WebGL renderer ships
        "min_points": 1,
        "default_limit": 2000,
    },
    "hive": {
        "label": "Hive Plot",
        "icon": "🍯",
        "description": "Radial layout with N axes. Each axis represents a dimension; curved links connect accounts across axes.",
        "dimensions": {
            # dynamic=True means the builder shows add/remove buttons for this dimension slot
            "axis_*":    { "required": True,  "accepts": ["numeric"],               "label": "Axis",      "dynamic": True, "min": 3, "max": None },
            "link_color":{ "required": False, "accepts": ["numeric", "categorical"],"label": "Link Color","dynamic": False },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 2000,
    },
    "bubble": {
        "label": "Bubble Chart",
        "icon": "⬤",
        "description": "Scatter plot where a third numeric dimension controls point size.",
        "dimensions": {
            "x":    { "required": True,  "accepts": ["numeric"],               "label": "X Axis"    },
            "y":    { "required": True,  "accepts": ["numeric"],               "label": "Y Axis"    },
            "size": { "required": True,  "accepts": ["numeric"],               "label": "Bubble Size"},
            "color":{ "required": False, "accepts": ["numeric", "categorical"],"label": "Color By"  },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "default_limit": 1000,   # bubbles overlap more; lower default
    },
    "histogram": {
        "label": "Histogram",
        "icon": "▬",
        "description": "Distribution of a single numeric variable across your accounts.",
        "dimensions": {
            "x":    { "required": True,  "accepts": ["numeric"],               "label": "Variable"  },
            "color":{ "required": False, "accepts": ["categorical"],           "label": "Color By"  },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "default_limit": 5000,  # histograms aggregate client-side; more data = better bins
    },
    "bar": {
        "label": "Bar Chart (Top-N)",
        "icon": "▌",
        "description": "Compare an aggregate value across groups (communities, handles, etc.).",
        "dimensions": {
            "x":    { "required": True, "accepts": ["categorical"],            "label": "Group By"  },
            "y":    { "required": True, "accepts": ["numeric"],                "label": "Value"     },
            "color":{ "required": False, "accepts": ["categorical"],           "label": "Color By"  },
        },
        "data_shape": "aggregated",
        "aggregation": "avg",       # default; user can change to sum/count/max/min
        "render_mode": "svg",
        "default_limit": 50,        # limit is top-N groups, not top-N rows
    },
    "violin": {
        "label": "Violin / Box Plot",
        "icon": "𝄞",
        "description": "Distribution of a numeric variable, grouped by a categorical variable.",
        "dimensions": {
            "x":    { "required": True, "accepts": ["categorical"],            "label": "Group By"  },
            "y":    { "required": True, "accepts": ["numeric"],                "label": "Value"     },
        },
        "data_shape": "aggregated",
        "aggregation": "distribution",  # special: returns full distribution per group, not scalar
        "render_mode": "svg",
        "default_limit": 100,           # groups, not rows
    },
    "timeline": {
        "label": "Timeline / Dot Plot",
        "icon": "◌",
        "description": "Plot accounts along a time axis. Ideal for last_post_at vs a metric.",
        "dimensions": {
            "x":    { "required": True, "accepts": ["datetime"],               "label": "Time Axis" },
            "y":    { "required": True, "accepts": ["numeric"],                "label": "Y Axis"    },
            "color":{ "required": False, "accepts": ["categorical", "numeric"],"label": "Color By"  },
            "size": { "required": False, "accepts": ["numeric"],               "label": "Point Size"},
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "default_limit": 2000,
    },
    "circle_packing": {
        "label": "Circle Packing",
        "icon": "⭕",
        "description": "Hierarchical layout grouping accounts into nested circles by community.",
        "dimensions": {
            "group_by": { "required": True, "accepts": ["categorical"],        "label": "Group By"  },
            "size":     { "required": True, "accepts": ["numeric"],            "label": "Node Size" },
            "color":    { "required": False, "accepts": ["categorical"],       "label": "Color By"  },
        },
        "data_shape": "hierarchy",
        "aggregation": None,
        "render_mode": "svg",
        "default_limit": 3000,
    },
    "force_directed": {
        "label": "Force-Directed Graph",
        "icon": "🕸",
        "description": "Network graph with physics simulation. Nodes are accounts, edges are follow relationships.",
        "dimensions": {
            "node_size":  { "required": False, "accepts": ["numeric"],         "label": "Node Size"  },
            "node_color": { "required": False, "accepts": ["categorical"],     "label": "Node Color" },
        },
        "data_shape": "graph",
        "aggregation": None,
        "render_mode": "webgl",
        "webgl_available": True,    # force-graph library handles this
        "default_limit": 1500,
    },
}
```

### 4.2 `data_shape` Execution Paths

| Shape | SQL Pattern | Return Shape |
|---|---|---|
| `rows` | Standard `SELECT ... WHERE ... LIMIT n` | `[{x, y, z?, color_val?, handle, did, avatar_url}]` |
| `aggregated` | `SELECT group_col, AGG(val) ... GROUP BY group_col ORDER BY ... LIMIT n` | `[{group, value, color_val?}]` |
| `aggregated/distribution` | One value column per group, all raw values | `[{group, values: [float]}]` |
| `hierarchy` | Adapted from existing `get_graph_data(mode="packing")` | `{name, children: [{name, value, children}]}` |
| `graph` | Adapted from existing `get_graph_data(mode="macro"|"ego")` | `{nodes: [...], links: [...], metadata}` |

The `hierarchy` and `graph` shapes reuse the existing query functions from `db/queries.py`. They gain the ability to accept a `filter_tree` and custom dimension mappings (e.g. which field drives node size).

---

## 5. API Design

### 5.1 New Endpoints

All endpoints live under `api/charts.py` and are mounted at `/api/charts`.

```
GET    /api/charts/{alias}                  — List saved chart definitions
POST   /api/charts/{alias}                  — Create chart definition
GET    /api/charts/{alias}/{id}             — Get single definition
PUT    /api/charts/{alias}/{id}             — Update definition
DELETE /api/charts/{alias}/{id}             — Delete
PATCH  /api/charts/{alias}/{id}/pin         — Toggle pin state

GET    /api/charts/{alias}/{id}/data        — Execute saved chart, return data
POST   /api/charts/{alias}/preview          — Execute unsaved chart definition (body = ChartDefinition JSON)
GET    /api/charts/registry                 — Return CHART_REGISTRY (for builder UI)
```

### 5.2 Data Endpoint Detail

`GET /api/charts/{alias}/{id}/data?thumbnail=false`

The `thumbnail=true` param caps the limit at 200 for gallery card rendering. The response shape is always:

```json
{
  "data": [ ... ],
  "axes": {
    "x": { "label": "FlowRank", "scale": "log", "domain": [0.0001, 0.05] },
    "y": { "label": "Followers", "scale": "log", "domain": [0, 1200000] }
  },
  "chart_type": "scatter",
  "render_mode": "svg",
  "total": 1847,
  "truncated": false
}
```

The `axes` object mirrors the `dimensions` keys plus resolved `domain` (min/max from actual data). The frontend uses this to configure D3 scales without any extra computation.

### 5.3 Query Engine Integration

The chart query engine in `db/queries.py` adds two new public functions:

**`resolve_axis_sql(axis_config, owner_id) → str`**

Wraps the existing `_resolve_field_sql()`. Accepts an `AxisConfig` dict and returns the SQL expression string. Handles all three sources:
- `source=field` → `FILTERABLE_FIELDS_MAP[field]`
- `source=variable` → looks up `CustomVariable` by name, calls `_build_math_sql()`
- `source=expression` → calls `_build_math_sql()` directly on the inline tree

This is the critical integration point. CustomVariables defined in the filter system are immediately available as chart axes with zero additional code.

**`query_chart_data(owner_id, chart_def, thumbnail=False) → dict`**

Dispatches to the correct execution path based on `chart_def["chart_type"]`'s `data_shape`:

```python
async def query_chart_data(owner_id: int, chart_def: dict, thumbnail: bool = False) -> dict:
    chart_type = CHART_REGISTRY[chart_def["chart_type"]]
    data_shape = chart_type["data_shape"]
    limit = 200 if thumbnail else min(chart_def.get("limit", 2000), 10000)

    if data_shape == "rows":
        return await _query_rows(owner_id, chart_def, limit)
    elif data_shape == "aggregated":
        return await _query_aggregated(owner_id, chart_def, limit)
    elif data_shape == "hierarchy":
        return await _query_hierarchy(owner_id, chart_def, limit)
    elif data_shape == "graph":
        return await _query_graph(owner_id, chart_def, limit)
```

`_query_rows` is structurally identical to `query_users()` but with a dynamic SELECT list built from the `dimensions` config. `_query_hierarchy` and `_query_graph` delegate to the existing `get_graph_data()` with added filter and dimension parameters.

---

## 6. Filter Integration — Dropdown vs Inline Builder

This section answers the question asked about filter picker design in the studio.

### 6.1 Dropdown of Saved FilterSets (chosen approach, Phase 3)

The studio shows a dropdown listing all saved FilterSets for the active account, plus a "Custom..." option. Choosing "Custom..." opens the existing filter builder modal (the same modal used from the main dashboard sidebar). When the user saves a filter in that modal, it's added to the FilterSet list and immediately selected in the dropdown.

**What this does well:**
- Zero new UI code — the modal is already built and battle-tested
- Promotes reuse: chart filters and dashboard filters are the same objects
- Any FilterSet saved from the chart studio is immediately usable as a dashboard tab
- Conceptually clean: population and chart definition are separate concerns

**What this cannot do:**
- The filter is always a saved named entity. You cannot have a truly throwaway one-off filter scoped only to this chart without saving it.
- If you want to test a chart with a slight variation of an existing filter, you must either edit the FilterSet (affecting all charts/tabs that use it) or save a new one.

### 6.2 Inline Filter Builder (alternative, not chosen for Phase 3)

The builder panel embeds the full condition tree UI directly — no modal, no separate saved entity. The chart stores its filter as an anonymous `filter_tree` JSON blob, never requiring a named FilterSet.

**What this adds:**
- Truly ad-hoc filters — tweak a condition, preview updates immediately, never forced to name or save it
- The filter is scoped to the chart and travels with it when the chart is exported or duplicated
- Faster iteration: changing one condition doesn't require reopening a modal

**What makes it harder:**
- The condition builder is currently implemented as DOM-manipulation functions in `app.js` with global state (`builderState`). Embedding it inside the studio page requires either extracting it into a proper component (a good refactor regardless) or maintaining a second parallel instance with separate state.
- The studio already has significant UI density. An inline tree builder adds vertical height that competes with the live preview.
- If the user later wants to reuse a chart's filter as a dashboard tab, they'd need a "Save as FilterSet" button — an extra affordance.

**When inline becomes worth it:**
If the filter builder is ever refactored into a standalone web component (custom element or React component), inline embedding becomes trivial and the modal approach should be revisited. The `filter_tree` column already exists on `ChartDefinition` for this exact reason — anonymous inline trees are fully supported by the data model and query engine from day one. Only the UI defaults to the saved-FilterSet path.

**Practical resolution:**
Phase 3 ships with the dropdown + modal approach. The `filter_tree` column is ready. When the filter builder is componentized (a separate refactor that benefits the main dashboard too), inline embedding is a one-session addition to the studio.

---

## 7. Frontend Architecture

### 7.1 File Structure (new files only)

```
templates/
  charts.html          — Gallery page
  chart_studio.html    — Studio (new + edit)
  chart_view.html      — Full-screen view

static/js/
  chart-studio.js      — Builder state management, axis picker, live preview
  chart-gallery.js     — Gallery grid, thumbnail rendering
  chart-registry.js    — Client-side copy of registry (fetched from /api/charts/registry)

static/js/renderers/
  base.js              — Shared utilities: scales, tooltips, color palette, export hook
  scatter.js
  bubble.js
  histogram.js
  bar.js
  timeline.js
  violin.js
  hive.js              — Adapted from existing static/js/hive.js
  circle-packing.js    — Adapted from existing static/js/pack.js
  force-directed.js    — Adapted from existing static/js/graph.js

static/js/
  profile-panel.js     — Shared profile side panel (Phase 0, prerequisite)
```

### 7.2 Renderer Abstraction

All renderers implement the same interface. The dispatcher in `base.js` selects the renderer and render mode:

```javascript
// base.js
export const RENDERERS = {};

export function registerRenderer(chartType, renderers) {
    RENDERERS[chartType] = renderers;
}

export function renderChart(container, apiResponse, options = {}) {
    const { chart_type, render_mode } = apiResponse;
    const available = RENDERERS[chart_type];
    if (!available) throw new Error(`No renderer registered for chart type: ${chart_type}`);

    const useWebGL = options.forceWebGL
        || (render_mode === "webgl" && available.webgl)
        || (apiResponse.total > 3000 && available.webgl);

    const renderer = useWebGL ? available.webgl : available.svg;
    if (!renderer) throw new Error(`No ${useWebGL ? "WebGL" : "SVG"} renderer for: ${chart_type}`);

    return renderer(container, apiResponse, options);
}
```

Each renderer file self-registers:

```javascript
// scatter.js
import { registerRenderer } from './base.js';

function renderScatterSVG(container, data, options) { /* ... */ }
// function renderScatterWebGL(container, data, options) { /* Phase 7 */ }

registerRenderer("scatter", {
    svg: renderScatterSVG,
    // webgl: renderScatterWebGL,
});
```

The `options` object passed to every renderer includes:

```javascript
{
  interactive: true,     // false for thumbnails
  animated: true,        // false for thumbnails
  labels: true,          // false for thumbnails
  onPointClick: fn,      // calls openProfilePanel(did, alias)
  colorPalette: [...],   // from base.js, shared across all renderers
  cssVars: {...},        // --accent, --surface, etc., read at render time
}
```

### 7.3 Studio State

```javascript
const studioState = {
  // Identity
  id: null,              // null = new chart
  name: "",
  icon: "📊",
  description: "",
  pinned: false,

  // Chart type
  chart_type: "scatter",

  // Data population
  filter_set_id: null,   // ID of a saved FilterSet, or null
  filter_tree: null,     // Inline filter tree blob, or null (see §6)

  // Dimensions — keys depend on chart_type
  dimensions: {
    x:     { source: "field", field: "flowrank_score", label: "FlowRank",  scale: "log"    },
    y:     { source: "field", field: "followers_count", label: "Followers", scale: "log"    },
    color: { source: "field", field: "community_id",    label: "Community", scale: "linear" },
  },

  // Options
  limit: 2000,
  sort_by: null,
  sort_dir: "desc",
  aggregation: "avg",
  options: {},           // Chart-type-specific display options

  // UI-only state
  _previewPending: false,
  _lastSaved: null,
  _dirty: false,
};
```

When `chart_type` changes, `dimensions` is reset to the defaults for the new type (populated from the registry). Existing dimension values are carried over by key name where they match (e.g. if both old and new types have an `x` dimension with `accepts: ["numeric"]`, the current `x` value is preserved).

### 7.4 Axis Selector Component

The axis picker is a dropdown with three sections. It reuses `renderFieldOptions()` from `app.js`, which already handles grouping by category and listing CustomVariables. The component additionally shows:

- A **Scale** dropdown (`linear`, `log`, `sqrt`, `time`) that appears after selection
- A **Label** text input (auto-populated from field name, editable)
- A **Domain** min/max pair (optional override; defaults to auto)

For `dynamic: true` dimension slots (hive `axis_*`), the studio renders an **Add Axis** / **Remove Axis** button pair, enforcing the registry's `min` and `max` constraints.

### 7.5 Default Chart Seeding

On first `GET /charts/{alias}`, the backend checks `ChartDefinition.filter(owner=account).count()`. If zero, `_seed_default_charts(account)` inserts the following:

| Name | Type | Dimensions | Filter | Pinned |
|---|---|---|---|---|
| Network Graph | `force_directed` | node_size=flowrank_score, node_color=community_id | i_follow_them=true | **true** |
| FlowRank vs Followers | `scatter` | x=flowrank_score(log), y=followers_count(log), color=community_id | i_follow_them=true | false |
| Repost Distribution | `histogram` | x=repost_ratio | i_follow_them=true | false |
| Community Activity | `bar` | x=community_id, y=flowrank_score, agg=avg | none | false |
| Inactive Network | `bubble` | x=days_since_post, y=followers_count, size=flowrank_score, color=is_inactive | i_follow_them=true | false |
| Engagement Timeline | `timeline` | x=last_post_at, y=flowrank_score, color=community_id | i_follow_them=true | false |
| Hive Plot | `hive` | axis_0=flowrank_score, axis_1=posts_count, axis_2=clustering_coefficient, link_color=community_id | i_follow_them=true | false |
| Circle Packing | `circle_packing` | group_by=community_id, size=flowrank_score, color=community_id | none | false |

---

## 8. Profile Side Panel (Phase 0 — Prerequisite)

Phase 0 is implemented independently by the developer before any chart work begins. This section documents the target contract so the chart system builds against it correctly from day one.

### 8.1 The Module

`static/js/profile-panel.js` exports a single function:

```javascript
export async function openProfilePanel(did, alias) {
    // 1. Fetch from /api/users/{alias}?filter_tree={"op":"AND","conditions":[{"field":"did","op":"eq","value":did}]}
    // 2. Render into the shared #side-panel element
    // 3. Slide panel in from right
    // Profile card content:
    //   - Avatar, display name, @handle
    //   - Network Position: FlowRank, Community, In-Degree
    //   - Activity Signals: Repost Ratio, Last Post, Interacted
    //   - Relationship: I Follow / They Follow badges
    //   - "Open in Bluesky" button (links to bsky.app/profile/{did})
    //   - NOT a direct navigation — the panel IS the interaction surface
}

export function closeProfilePanel() { /* ... */ }
```

### 8.2 Pages That Use It

After Phase 0:

| Page | Previous behavior | Phase 0 behavior |
|---|---|---|
| Main dashboard (user rows) | `<a href={profile_url}>` opens Bluesky | Click opens side panel |
| Network Graph | Side panel (inline impl in graph.js) | Migrated to shared module |
| Circle Packing | Side panel (inline impl in pack.js) | Migrated to shared module |
| All chart view pages | — | Uses shared module from day one |

### 8.3 Panel HTML

A single `#side-panel` div lives in each page's HTML (or in a shared layout include). It is positioned fixed, slides from the right, and sits above the chart canvas in z-order. The panel's close button and clicking the canvas background both call `closeProfilePanel()`.

---

## 9. WebGL Strategy

### 9.1 Current State

The force-directed graph (`graph.js`) already uses the `force-graph` library which renders to canvas/WebGL. This is the only WebGL-capable renderer in the current codebase.

### 9.2 Future WebGL Renderers

The renderer abstraction (§7.2) is designed so that adding a WebGL renderer for any chart type is additive:

1. Write `renderScatterWebGL()` in `scatter.js` (likely using `regl`, `deck.gl`, or raw WebGL2 with GLSL)
2. Add it to the `registerRenderer("scatter", { svg: ..., webgl: renderScatterWebGL })` call
3. The dispatcher automatically uses it when `shouldUseWebGL()` returns true

No schema changes. No API changes. No changes to any other renderer.

### 9.3 Threshold Logic

The dispatcher uses WebGL when:
- The chart type's registry entry has `webgl_available: true` AND
- Either `render_mode === "webgl"` is declared for the type OR the data point count exceeds 3000

The 3000-point threshold is a constant in `base.js`. Below it, SVG is always used (simpler, better text rendering, native browser accessibility). Above it, WebGL is used if available for the type.

### 9.4 For Phase 7: Scatter WebGL

The recommended library is `regl` (lightweight, low-level, excellent for point clouds). Each point is rendered as a textured quad in a single draw call. Tooltip interaction is handled via a spatial index (`rbush` or a simple grid) rather than DOM events. Point click calls `openProfilePanel(did, alias)` identically to the SVG renderer.

---

## 10. Migration of Existing Visualization Pages

The existing `/graph/{alias}`, `/hive/{alias}`, and `/pack/{alias}` pages are not deleted — they redirect to the corresponding seeded chart view URLs. This ensures any bookmarks or external links continue to work.

```python
# main.py additions
@app.get("/graph/{alias}")
async def legacy_graph_redirect(alias: str):
    chart = await ChartDefinition.filter(
        owner__alias=alias,
        chart_type="force_directed"
    ).order_by("created_at").first()
    if chart:
        return RedirectResponse(f"/charts/{alias}/{chart.id}/view")
    return RedirectResponse(f"/charts/{alias}")

# Same pattern for /hive/{alias} and /pack/{alias}
```

The legacy templates (`graph.html`, `hive.html`, `pack.html`) and their JS files (`graph.js`, `hive.js`, `pack.js`) are kept until Phase 6 is complete. At that point, the logic is fully absorbed into the renderer files under `static/js/renderers/`, and the legacy files are deleted.

---

## 11. Implementation Phases

### Phase 0 — Shared InfoPanel System (COMPLETE)
*Implemented as a decoupled orchestrator and renderer system.*

- **Architecture:** Created a shared orchestrator (`info-panel.js`) that manages panel state, backdrop interactions, and a capped `Map` cache (50 entries) for performance.
- **Modularity:** Content is rendered via a "Registry" pattern using `profile-view.js` and `community-view.js`.
- **Integration:** Migrated the Dashboard, Force-Directed Graph, Hive Plot, and Circle Packing to use the shared system.
- **Layout Sync:** Implemented a custom event system (`infopanel:toggle`) that allows D3 and Canvas-based charts to dynamically re-center their camera focus when the sidebar occupies viewport space.
- **Universal Triggers:** Established global CSS classes (`js-profile-trigger`, `js-community-trigger`) to intercept clicks across all list views and injected content.

**Completion criteria:** Clicking any account or community anywhere opens the shared InfoPanel. No page navigates directly to Bluesky — all external navigation is contextualized through the panel.

---

### Phase 1 — Registry + DB + API
*Backend only. No frontend changes.*

- `CHART_REGISTRY` dict in `api/chart_registry.py`
- `ChartDefinition` Tortoise model in `db/models.py`
- `ensure_sqlite_compat_columns()` additions in `main.py`
- `api/charts.py` with all CRUD endpoints + registry endpoint
- `resolve_axis_sql()` in `db/queries.py`
- `query_chart_data()` dispatcher in `db/queries.py` with `rows` and `aggregated` paths
- `hierarchy` and `graph` paths delegating to existing `get_graph_data()`

**Completion criteria:** Can POST a chart definition and GET data back via curl. Registry endpoint returns full type metadata. All four data shape paths execute without error.

---

### Phase 2 — Gallery + View Pages (no builder yet)
*Frontend shell. Uses seeded charts to prove the pipeline.*

- `templates/charts.html` gallery page
- `templates/chart_view.html` full-screen view page
- `chart-gallery.js` — card grid, thumbnail rendering
- `base.js` renderer base with shared utilities
- Sidebar navigation updated (Charts link + pinned chart slots)
- `main.py` new routes for gallery and view
- Default chart seeding on first gallery visit
- Legacy route redirects

**Completion criteria:** Gallery loads and shows 8 seeded chart cards as live thumbnails. Clicking a card opens full-screen view. Profile panel opens on point click. Network Graph is in sidebar as pinned link.

---

### Phase 3 — Scatter Renderer + Studio (scatter only)
*First interactive chart type. Proves the builder end-to-end.*

- `scatter.js` SVG renderer
- `templates/chart_studio.html` studio page
- `chart-studio.js` builder state + axis picker + live preview
- `main.py` routes for `/charts/{alias}/new` and `/{id}/edit`
- Filter picker: dropdown of saved FilterSets + "Custom..." → existing modal
- Save/load cycle working

**Completion criteria:** User can create a scatter chart from scratch, configure axes from any field or CustomVariable, apply a filter, preview live, save, and view full-screen. Editing a saved scatter chart works.

---

### Phase 4 — Histogram, Bubble, Bar, Timeline Renderers
*Expands chart type coverage. Bar requires the aggregated query path.*

- `histogram.js`, `bubble.js`, `bar.js`, `timeline.js` renderers
- Studio updated to show type-specific options (aggregation picker for bar, bin count for histogram)
- `_query_aggregated()` fully implemented including `distribution` shape for violin

**Completion criteria:** All four types are selectable in studio, render correctly, and round-trip through save/load.

---

### Phase 5 — Hive Renderer + Dynamic Dimensions in Studio
*Requires dynamic axis UI in the builder.*

- `hive.js` renderer (adapted from existing `static/js/hive.js`, now accepts arbitrary N axes)
- Studio builder: "+ Add Axis" / "- Remove Axis" for `dynamic: true` dimension slots
- Registry min/max enforcement (hive requires ≥ 3 axes)

**Completion criteria:** User can create a hive chart with 3–6 axes, each bound to any field or variable. Dynamic add/remove works. Existing Hive Plot seeded chart renders correctly.

---

### Phase 6 — Circle Packing + Force-Directed in Chart System
*Absorbs legacy visualization pages.*

- `circle-packing.js` renderer (adapted from `pack.js`)
- `force-directed.js` renderer (adapted from `graph.js`)
- Force-directed renderer gains filter support (can show only follows, only specific community, etc.)
- Legacy routes redirect confirmed working
- Legacy JS files (`graph.js`, `hive.js`, `pack.js`) and templates deleted

**Completion criteria:** All seeded charts render correctly including circle packing and force-directed. Legacy `/graph/`, `/hive/`, `/pack/` routes redirect cleanly. Old JS files removed.

---

### Phase 7 — Violin/Box, WebGL Scatter, Export, Polish
*Stretch goals and polish.*

- `violin.js` renderer
- WebGL scatter renderer using `regl`
- SVG/PNG export via `SVGElement.outerHTML` or `canvas.toBlob()`
- Gallery card pin/unpin animation
- Studio keyboard shortcuts (Cmd+S to save, Cmd+P to preview)
- Chart duplication ("Save as copy")

---

## 12. Open Decisions (to resolve in future sessions)

| # | Question | Status |
|---|---|---|
| A | When the filter builder is extracted into a standalone component, migrate studio filter picker from dropdown to inline. | Deferred to post-Phase 3 |
| B | Should the violin chart show individual points as an overlay option? (Affects query shape — needs raw rows + distribution simultaneously) | Resolve before Phase 4 |
| C | Maximum number of pinned charts in sidebar before it overflows. Hard limit or scroll? | Resolve before Phase 2 |
| D | Export format: SVG only, or also PNG (requires canvas)? PNG needs `html2canvas` or server-side render for WebGL charts. | Resolve before Phase 7 |
| E | Chart duplication — same owner only, or shareable across accounts (export/import JSON)? | Resolve before Phase 7 |
| F | When force-directed chart supports a `filter_tree`, does it still show edges between nodes outside the filter? (i.e. edges to non-filtered nodes are "ghost" links) | Resolve before Phase 6 |

---

## 13. Key Invariants

Rules that must not be broken across all phases:

1. **`CHART_REGISTRY` is the single source of truth** for what dimensions a chart type accepts, what its data shape is, and what render mode it uses. No chart-type-specific logic lives outside the registry entry and its paired renderer file.

2. **`resolve_axis_sql()` is the only axis resolution path.** No renderer or endpoint hand-rolls its own field resolution. This ensures CustomVariables work identically everywhere.

3. **`_where()` from `db/queries.py` is the only filter resolution path.** Chart data queries call it identically to the users list endpoint. Filters defined for a chart work the same as filters on a dashboard tab.

4. **The profile side panel is always opened via `openProfilePanel(did, alias)`.** No page navigates directly to a Bluesky URL from a data point or node click. The panel is the interaction surface; the panel links to Bluesky.

5. **SVG renderers ship before WebGL renderers** for every chart type. The `webgl_available: false` default in the registry enforces this.

6. **`ChartDefinition.filter_tree` accepts any valid filter tree**, including anonymous trees that are never saved as a `FilterSet`. The studio defaults to using saved FilterSets but the data model does not require it.
