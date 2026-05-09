"""
db/chart_queries.py
Chart-specific query engine.

resolve_axis_sql() — converts an AxisConfig dict to a SQL expression string.
query_chart_data() — dispatches to the correct execution path per data_shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tortoise import connections

from api.chart_registry import CHART_REGISTRY
from db.queries import (
    _build_recursive_where_clause,
    _resolve_field_sql,
    _where,
    FILTERABLE_FIELDS_MAP,
    SELECT_FIELDS,
)

logger = logging.getLogger(__name__)


# ── Field metadata for axes ────────────────────────────────────────────────────

FIELD_LABELS = {
    "followers_count":        "Followers",
    "follows_count":          "Following",
    "posts_count":            "Total Posts",
    "days_since_post":        "Days Since Post",
    "repost_ratio":           "Repost Ratio",
    "sampled_post_count":     "Sampled Posts",
    "repost_count":           "Reposts",
    "original_post_count":    "Original Posts",
    "flowrank_score":         "FlowRank",
    "clustering_coefficient": "Clustering Coeff.",
    "in_subgraph_degree":     "In-Subgraph Degree",
    "crawl_priority":         "Crawl Priority",
    "community_id":           "Community",
    "crawl_tier":             "Crawl Tier",
    "i_follow_them":          "I Follow",
    "they_follow_me":         "Follows Me",
    "interacted_with_owner":  "Interacted",
    "is_inactive":            "Inactive",
    "is_repost_heavy":        "Repost Heavy",
    "is_one_sided_follow":    "One-Sided Follow",
    "is_follower_only":       "Follower Only",
    "muted":                  "Muted",
    "blocked":                "Blocked",
    "last_post_at":           "Last Post",
    "last_analyzed_at":       "Last Analyzed",
    "last_hydrated_at":       "Last Hydrated",
    "last_crawled_at":        "Last Crawled",
    "first_seen_at":          "First Seen",
    "handle":                 "Handle",
    "display_name":           "Display Name",
}


async def resolve_axis_sql(axis_config: dict, owner_id: int) -> str | None:
    """
    Converts an AxisConfig dict to a SQL expression string.
    Handles source=field, source=variable, source=expression.
    """
    source = axis_config.get("source", "field")
    field  = axis_config.get("field")

    if source == "field":
        return await _resolve_field_sql(field, owner_id)

    elif source == "variable":
        from db.models import CustomVariable
        var = await CustomVariable.get_or_none(owner_id=owner_id, name=field)
        if not var:
            return None
        tree = json.loads(var.expression_tree)
        from db.queries import _build_math_sql
        return await _build_math_sql(tree, owner_id)

    elif source == "expression":
        expr = axis_config.get("expression")
        if not expr:
            return None
        from db.queries import _build_math_sql
        return await _build_math_sql(expr, owner_id)

    return None


def _compute_domain(rows: list[dict], col_key: str) -> list:
    """Compute min/max domain for a given key from row data."""
    vals = [r[col_key] for r in rows if r.get(col_key) is not None]
    if not vals:
        return [None, None]
    try:
        numeric_vals = [float(v) for v in vals]
        return [min(numeric_vals), max(numeric_vals)]
    except (TypeError, ValueError):
        return [None, None]


async def _resolve_filter(chart_def: dict, owner_id: int) -> tuple[str, list]:
    """
    Resolve the chart's filter to a WHERE clause + params.
    Prefers filter_tree over filter_set_id.
    """
    filter_tree = chart_def.get("filter_tree")
    filter_set_id = chart_def.get("filter_set_id")

    if not filter_tree and filter_set_id:
        from db.models import FilterSet
        fs = await FilterSet.get_or_none(id=filter_set_id, owner_id=owner_id)
        if fs:
            filter_tree = json.loads(fs.condition_tree) if isinstance(fs.condition_tree, str) else fs.condition_tree

    base_where = f"r.owner_id = ?"
    params = [owner_id]

    if filter_tree:
        if isinstance(filter_tree, str):
            filter_tree = json.loads(filter_tree)
        sub_params: list[Any] = []
        sub_clause = await _build_recursive_where_clause(filter_tree, sub_params, owner_id)
        if sub_clause and sub_clause != "1=1":
            base_where += f" AND ({sub_clause})"
            params.extend(sub_params)

    return base_where, params


async def _query_rows(owner_id: int, chart_def: dict, limit: int) -> dict:
    """
    Execute a row-level chart query (scatter, bubble, histogram, timeline, etc.)
    Returns resolved rows with axis values.
    """
    conn = connections.get("default")
    dimensions: dict = chart_def.get("dimensions", {})

    # Resolve each axis to SQL
    axis_sqls: dict[str, str] = {}
    for dim_key, axis_cfg in dimensions.items():
        sql = await resolve_axis_sql(axis_cfg, owner_id)
        if sql:
            axis_sqls[dim_key] = sql

    if not axis_sqls:
        return {"data": [], "axes": {}, "total": 0, "truncated": False}

    # Build SELECT list
    select_parts = [
        "p.did", "p.handle", "p.display_name", "p.avatar_url",
        "r.community_id", "r.flowrank_score",
        "cm.name as comm_name",
    ]
    for dim_key, sql in axis_sqls.items():
        select_parts.append(f"{sql} AS {dim_key}_val")

    where_clause, params = await _resolve_filter(chart_def, owner_id)

    # Sort
    sort_by = chart_def.get("sort_by")
    sort_dir = "DESC" if chart_def.get("sort_dir", "desc") == "desc" else "ASC"
    if sort_by and sort_by in axis_sqls:
        order = f"{axis_sqls[sort_by]} {sort_dir}"
    elif sort_by:
        from db.queries import SORTABLE_FIELDS
        order = f"{SORTABLE_FIELDS.get(sort_by, 'p.handle')} {sort_dir}"
    else:
        # Default: sort by first axis descending
        first_sql = next(iter(axis_sqls.values()))
        order = f"{first_sql} DESC"

    select_sql = ", ".join(select_parts)
    query = f"""
        SELECT {select_sql}
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
        WHERE {where_clause}
          AND {next(iter(axis_sqls.values()))} IS NOT NULL
        ORDER BY {order}
        LIMIT ?
    """

    rows = await conn.execute_query_dict(query, params + [limit])

    # Count total (without limit)
    count_query = f"""
        SELECT COUNT(*) as total
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        WHERE {where_clause}
          AND {next(iter(axis_sqls.values()))} IS NOT NULL
    """
    count_rows = await conn.execute_query_dict(count_query, params)
    total = int(count_rows[0]["total"]) if count_rows else 0

    # Build normalized data rows
    data = []
    for row in rows:
        point = {
            "did":          row.get("did"),
            "handle":       row.get("handle"),
            "display_name": row.get("display_name"),
            "avatar_url":   row.get("avatar_url"),
            "community_id": row.get("community_id"),
            "flowrank":     row.get("flowrank_score"),
            "comm_name":    row.get("comm_name"),
        }
        for dim_key in axis_sqls:
            val = row.get(f"{dim_key}_val")
            # Convert to float if numeric
            try:
                point[dim_key] = float(val) if val is not None else None
            except (TypeError, ValueError):
                point[dim_key] = val
        data.append(point)

    # Build axes metadata
    axes = {}
    for dim_key, axis_cfg in dimensions.items():
        if dim_key not in axis_sqls:
            continue
        domain_override = axis_cfg.get("domain", [None, None])
        auto_domain = _compute_domain(data, dim_key)
        axes[dim_key] = {
            "label":  axis_cfg.get("label") or FIELD_LABELS.get(axis_cfg.get("field"), dim_key),
            "scale":  axis_cfg.get("scale", "linear"),
            "domain": [
                domain_override[0] if domain_override[0] is not None else auto_domain[0],
                domain_override[1] if domain_override[1] is not None else auto_domain[1],
            ],
        }

    return {
        "data":      data,
        "axes":      axes,
        "total":     total,
        "truncated": total > limit,
    }


async def _query_aggregated(owner_id: int, chart_def: dict, limit: int) -> dict:
    """
    Execute an aggregated chart query (bar, violin).
    Groups by x dimension, aggregates y dimension.
    """
    conn = connections.get("default")
    dimensions: dict = chart_def.get("dimensions", {})
    aggregation = chart_def.get("aggregation", "avg").upper()
    if aggregation not in ("AVG", "SUM", "COUNT", "MAX", "MIN"):
        aggregation = "AVG"

    x_cfg = dimensions.get("x")
    y_cfg = dimensions.get("y")
    if not x_cfg or not y_cfg:
        return {"data": [], "axes": {}, "total": 0, "truncated": False}

    x_sql = await resolve_axis_sql(x_cfg, owner_id)
    y_sql = await resolve_axis_sql(y_cfg, owner_id)
    if not x_sql or not y_sql:
        return {"data": [], "axes": {}, "total": 0, "truncated": False}

    where_clause, params = await _resolve_filter(chart_def, owner_id)
    sort_dir = "DESC" if chart_def.get("sort_dir", "desc") == "desc" else "ASC"

    query = f"""
        SELECT
            {x_sql} AS x_val,
            {aggregation}({y_sql}) AS y_val,
            COUNT(*) AS member_count
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
        WHERE {where_clause}
          AND {x_sql} IS NOT NULL
          AND {y_sql} IS NOT NULL
        GROUP BY {x_sql}
        ORDER BY y_val {sort_dir}
        LIMIT ?
    """

    rows = await conn.execute_query_dict(query, params + [limit])

    data = []
    for row in rows:
        try:
            x_val = float(row["x_val"]) if row["x_val"] is not None else None
        except (TypeError, ValueError):
            x_val = row["x_val"]
        try:
            y_val = float(row["y_val"]) if row["y_val"] is not None else None
        except (TypeError, ValueError):
            y_val = row["y_val"]

        data.append({
            "x":            x_val,
            "y":            y_val,
            "member_count": row.get("member_count", 0),
        })

    axes = {
        "x": {
            "label":  x_cfg.get("label") or FIELD_LABELS.get(x_cfg.get("field"), "X"),
            "scale":  x_cfg.get("scale", "linear"),
            "domain": _compute_domain(data, "x"),
        },
        "y": {
            "label":  y_cfg.get("label") or FIELD_LABELS.get(y_cfg.get("field"), f"{aggregation.title()} Value"),
            "scale":  y_cfg.get("scale", "linear"),
            "domain": _compute_domain(data, "y"),
        },
    }

    return {
        "data":      data,
        "axes":      axes,
        "total":     len(data),
        "truncated": False,
        "aggregation": aggregation.lower(),
    }


async def _query_hierarchy(owner_id: int, chart_def: dict, limit: int) -> dict:
    """
    Execute a hierarchy chart query (circle packing).
    Delegates to get_graph_data with mode=packing.
    """
    from db.queries import get_graph_data
    return await get_graph_data(owner_id=owner_id, mode="packing", limit=limit)


async def _query_graph(owner_id: int, chart_def: dict, limit: int) -> dict:
    """
    Execute a graph chart query (force-directed).
    Delegates to get_graph_data with filter support.
    """
    from db.queries import get_graph_data
    return await get_graph_data(owner_id=owner_id, mode="macro", limit=limit)


async def query_chart_data(owner_id: int, chart_def: dict, thumbnail: bool = False) -> dict:
    """
    Main dispatcher — routes to the correct execution path based on data_shape.
    chart_def is a dict matching ChartDefinition fields (not a model instance).
    """
    chart_type_key = chart_def.get("chart_type", "scatter")
    chart_type = CHART_REGISTRY.get(chart_type_key)
    if not chart_type:
        raise ValueError(f"Unknown chart type: {chart_type_key}")

    data_shape = chart_type["data_shape"]
    max_limit   = chart_def.get("limit", chart_type.get("default_limit", 2000))
    limit       = 200 if thumbnail else min(max_limit, 10000)

    if data_shape == "rows":
        result = await _query_rows(owner_id, chart_def, limit)
    elif data_shape == "aggregated":
        result = await _query_aggregated(owner_id, chart_def, limit)
    elif data_shape == "hierarchy":
        result = await _query_hierarchy(owner_id, chart_def, limit)
    elif data_shape == "graph":
        result = await _query_graph(owner_id, chart_def, limit)
    else:
        raise ValueError(f"Unknown data_shape: {data_shape}")

    result["chart_type"]  = chart_type_key
    result["render_mode"] = chart_type["render_mode"]
    return result
