"""
api/chart_registry.py
Single source of truth for all chart types.
Adding a new chart type: add an entry here + a renderer in static/js/renderers/.
"""

CHART_REGISTRY = {
    "scatter": {
        "label": "Scatter Plot",
        "icon": "⚬",
        "description": "Plot two numeric values against each other. Each point is one account.",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["numeric"],                "label": "X Axis",     "dynamic": False },
            "y":     { "required": True,  "accepts": ["numeric"],                "label": "Y Axis",     "dynamic": False },
            "color": { "required": False, "accepts": ["numeric", "categorical"], "label": "Color By",   "dynamic": False },
            "size":  { "required": False, "accepts": ["numeric"],                "label": "Point Size", "dynamic": False },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "min_points": 1,
        "default_limit": 2000,
    },
    "bubble": {
        "label": "Bubble Chart",
        "icon": "⬤",
        "description": "Scatter plot where a third numeric dimension controls point size.",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["numeric"],                "label": "X Axis"     },
            "y":     { "required": True,  "accepts": ["numeric"],                "label": "Y Axis"     },
            "size":  { "required": True,  "accepts": ["numeric"],                "label": "Bubble Size"},
            "color": { "required": False, "accepts": ["numeric", "categorical"], "label": "Color By"   },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 1000,
    },
    "histogram": {
        "label": "Histogram",
        "icon": "▬",
        "description": "Distribution of a single numeric variable across your accounts.",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["numeric"],                "label": "Variable" },
            "color": { "required": False, "accepts": ["categorical"],            "label": "Color By" },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 5000,
    },
    "bar": {
        "label": "Bar Chart",
        "icon": "▌",
        "description": "Compare an aggregate value across groups (communities, handles, etc.).",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["categorical"],            "label": "Group By" },
            "y":     { "required": True,  "accepts": ["numeric"],                "label": "Value"    },
            "color": { "required": False, "accepts": ["categorical"],            "label": "Color By" },
        },
        "data_shape": "aggregated",
        "aggregation": "avg",
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 50,
    },
    "timeline": {
        "label": "Timeline / Dot Plot",
        "icon": "◌",
        "description": "Plot accounts along a time axis. Ideal for last_post_at vs a metric.",
        "dimensions": {
            "x":     { "required": True,  "accepts": ["datetime"],                        "label": "Time Axis" },
            "y":     { "required": True,  "accepts": ["numeric"],                         "label": "Y Axis"    },
            "color": { "required": False, "accepts": ["categorical", "numeric"],           "label": "Color By"  },
            "size":  { "required": False, "accepts": ["numeric"],                         "label": "Point Size"},
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 2000,
    },
    "hive": {
        "label": "Hive Plot",
        "icon": "🍯",
        "description": "Radial layout with N axes. Curved links connect accounts across axes.",
        "dimensions": {
            "axis_0":     { "required": True,  "accepts": ["numeric"],                "label": "Axis 1",     "dynamic": True },
            "axis_1":     { "required": True,  "accepts": ["numeric"],                "label": "Axis 2",     "dynamic": True },
            "axis_2":     { "required": True,  "accepts": ["numeric"],                "label": "Axis 3",     "dynamic": True },
            "link_color": { "required": False, "accepts": ["numeric", "categorical"], "label": "Link Color", "dynamic": False },
        },
        "data_shape": "rows",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 2000,
        "min_axes": 3,
        "max_axes": 8,
    },
    "circle_packing": {
        "label": "Circle Packing",
        "icon": "⭕",
        "description": "Hierarchical layout grouping accounts into nested circles by community.",
        "dimensions": {
            "group_by": { "required": True,  "accepts": ["categorical"], "label": "Group By"  },
            "size":     { "required": True,  "accepts": ["numeric"],     "label": "Node Size" },
            "color":    { "required": False, "accepts": ["categorical"], "label": "Color By"  },
        },
        "data_shape": "hierarchy",
        "aggregation": None,
        "render_mode": "svg",
        "webgl_available": False,
        "default_limit": 3000,
    },
    "force_directed": {
        "label": "Force-Directed Graph",
        "icon": "🕸",
        "description": "Network graph with physics simulation. Nodes are accounts, edges are follow relationships.",
        "dimensions": {
            "node_size":  { "required": False, "accepts": ["numeric"],      "label": "Node Size"  },
            "node_color": { "required": False, "accepts": ["categorical"],  "label": "Node Color" },
        },
        "data_shape": "graph",
        "aggregation": None,
        "render_mode": "webgl",
        "webgl_available": True,
        "default_limit": 1500,
    },
}

# Field categories (mirrors FILTERABLE_FIELDS_MAP in db/queries.py)
FIELD_CATEGORIES = {
    "numeric": [
        "followers_count", "follows_count", "posts_count", "days_since_post",
        "repost_ratio", "sampled_post_count", "repost_count", "original_post_count",
        "flowrank_score", "clustering_coefficient", "in_subgraph_degree", "crawl_priority",
    ],
    "categorical": [
        "community_id", "crawl_tier", "discovered_via",
        "i_follow_them", "they_follow_me", "interacted_with_owner",
        "is_inactive", "is_repost_heavy", "is_one_sided_follow", "is_follower_only",
        "muted", "blocked",
    ],
    "datetime": [
        "last_post_at", "last_analyzed_at", "last_hydrated_at",
        "last_crawled_at", "first_seen_at",
    ],
    "string": ["handle", "display_name", "did"],
}

# Human-readable labels for the Axis/Dimension selectors
FIELD_LABELS = {
    # Numeric
    "followers_count":        "Followers",
    "follows_count":          "Following",
    "posts_count":            "Total Posts",
    "days_since_post":        "Days Inactive",
    "repost_ratio":           "Repost Ratio",
    "sampled_post_count":     "Sampled Posts",
    "repost_count":           "Reposts",
    "original_post_count":    "Original Posts",
    "flowrank_score":         "FlowRank Influence",
    "clustering_coefficient": "Clustering Coefficient",
    "in_subgraph_degree":     "Network In-Degree",
    "crawl_priority":         "Crawl Priority",

    # Categorical
    "community_id":           "Community ID",
    "crawl_tier":             "Crawl Tier",
    "discovered_via":         "Discovered Via",
    "i_follow_them":          "I Follow Them",
    "they_follow_me":         "They Follow Me",
    "interacted_with_owner":  "Has Interacted",
    "is_inactive":            "Is Inactive",
    "is_repost_heavy":        "Is Repost Heavy",
    "is_one_sided_follow":    "One-Sided Follow",
    "is_follower_only":       "Follower Only",
    "muted":                  "Muted",
    "blocked":                "Blocked",

    # Datetime
    "last_post_at":           "Last Post Date",
    "last_analyzed_at":       "Last Analyzed",
    "last_hydrated_at":       "Last Hydrated",
    "last_crawled_at":        "Last Crawled",
    "first_seen_at":          "First Seen",
}

DEFAULT_CHARTS = [
    {
        "name": "Network Graph",
        "icon": "🕸",
        "chart_type": "force_directed",
        "dimensions": {
            "node_size":  { "source": "field", "field": "flowrank_score",  "label": "FlowRank",   "scale": "sqrt"   },
            "node_color": { "source": "field", "field": "community_id",    "label": "Community",  "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": True,
        "pin_order": 0,
        "limit": 1500,
    },
    {
        "name": "FlowRank vs Followers",
        "icon": "⚬",
        "chart_type": "scatter",
        "dimensions": {
            "x":     { "source": "field", "field": "flowrank_score",   "label": "FlowRank",  "scale": "log"    },
            "y":     { "source": "field", "field": "followers_count",  "label": "Followers", "scale": "log"    },
            "color": { "source": "field", "field": "community_id",     "label": "Community", "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": False,
        "limit": 2000,
    },
    {
        "name": "Repost Distribution",
        "icon": "▬",
        "chart_type": "histogram",
        "dimensions": {
            "x": { "source": "field", "field": "repost_ratio", "label": "Repost Ratio", "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": False,
        "limit": 5000,
    },
    {
        "name": "Community Influence",
        "icon": "▌",
        "chart_type": "bar",
        "dimensions": {
            "x": { "source": "field", "field": "community_id",   "label": "Community", "scale": "linear" },
            "y": { "source": "field", "field": "flowrank_score",  "label": "Avg FlowRank", "scale": "linear" },
        },
        "aggregation": "avg",
        "pinned": False,
        "limit": 50,
    },
    {
        "name": "Inactive Network",
        "icon": "⬤",
        "chart_type": "bubble",
        "dimensions": {
            "x":     { "source": "field", "field": "days_since_post",   "label": "Days Inactive", "scale": "linear" },
            "y":     { "source": "field", "field": "followers_count",   "label": "Followers",     "scale": "log"    },
            "size":  { "source": "field", "field": "flowrank_score",    "label": "FlowRank",      "scale": "sqrt"   },
            "color": { "source": "field", "field": "is_inactive",       "label": "Is Inactive",   "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": False,
        "limit": 2000,
    },
    {
        "name": "Activity Timeline",
        "icon": "◌",
        "chart_type": "timeline",
        "dimensions": {
            "x":     { "source": "field", "field": "last_post_at",     "label": "Last Post",  "scale": "time"   },
            "y":     { "source": "field", "field": "flowrank_score",   "label": "FlowRank",   "scale": "log"    },
            "color": { "source": "field", "field": "community_id",     "label": "Community",  "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": False,
        "limit": 2000,
    },
    {
        "name": "Hive Plot",
        "icon": "🍯",
        "chart_type": "hive",
        "dimensions": {
            "axis_0":     { "source": "field", "field": "flowrank_score",          "label": "Influence",  "scale": "log"    },
            "axis_1":     { "source": "field", "field": "posts_count",             "label": "Activity",   "scale": "log"    },
            "axis_2":     { "source": "field", "field": "clustering_coefficient",  "label": "Clustering", "scale": "linear" },
            "link_color": { "source": "field", "field": "community_id",            "label": "Community",  "scale": "linear" },
        },
        "filter_tree": { "op": "AND", "conditions": [{ "field": "i_follow_them", "op": "eq", "value": True }] },
        "pinned": False,
        "limit": 2000,
    },
    {
        "name": "Circle Packing",
        "icon": "⭕",
        "chart_type": "circle_packing",
        "dimensions": {
            "group_by": { "source": "field", "field": "community_id",   "label": "Community", "scale": "linear" },
            "size":     { "source": "field", "field": "flowrank_score", "label": "FlowRank",  "scale": "sqrt"   },
            "color":    { "source": "field", "field": "community_id",   "label": "Community", "scale": "linear" },
        },
        "pinned": False,
        "limit": 3000,
    },
]
