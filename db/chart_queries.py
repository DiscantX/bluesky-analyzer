"""
db/chart_queries.py
Chart-specific query engine.

resolve_axis_sql() — converts an AxisConfig dict to a SQL expression string.
query_chart_data() — dispatches to the correct execution path per data_shape.

Fixes vs initial version:
  - Hive charts use axis_* keys; _query_rows now handles them correctly by
    including ALL dimension keys in the SELECT (not just named ones).
  - force_directed_3d shares the same graph data path as force_directed.
  - Robust NULL filtering: only the first required axis gates the WHERE clause.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tortoise import connections

from api.chart_registry import CHART_REGISTRY, FIELD_LABELS
from db.queries import (
    _build_recursive_where_clause,
    _resolve_field_sql,
    FILTERABLE_FIELDS_MAP,
)

logger = logging.getLogger(__name__)


async def resolve_axis_sql(axis_config: dict, owner_id: int) -> str | None:
    """
    Converts an AxisConfig dict to a SQL expression string.
    Handles source=field, source=variable, source=expression.
    """
    source = axis_config.get("source", "field")
    field  = axis_config.get("field")

    if not field:
        return None

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

    base_where = "r.owner_id = ?"
    params: list[Any] = [owner_id]

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
    Execute a row-level chart query (scatter, bubble, histogram, timeline, hive, etc.)

    Key fix: hive charts have dynamic axis_* keys. We resolve ALL dimension keys,
    not just the ones named in a fixed list.
    """
    conn = connections.get("default")
    dimensions: dict = chart_def.get("dimensions", {})

    # Resolve ALL dimension keys to SQL. Skip link_color (not a data column).
    axis_sqls: dict[str, str] = {}
    for dim_key, axis_cfg in dimensions.items():
        if dim_key == "link_color":
            # Resolve but tag separately — used for coloring, not axis placement
            sql = await resolve_axis_sql(axis_cfg, owner_id)
            if sql:
                axis_sqls[dim_key] = sql
            continue
        if not isinstance(axis_cfg, dict):
            continue
        sql = await resolve_axis_sql(axis_cfg, owner_id)
        if sql:
            axis_sqls[dim_key] = sql

    if not axis_sqls:
        return {"data": [], "axes": {}, "total": 0, "truncated": False, "chart_type": chart_def.get("chart_type")}

    # Build SELECT — always include identity columns
    select_parts = [
        "p.did",
        "p.handle",
        "p.display_name",
        "p.avatar_url",
        "r.community_id",
        "r.flowrank_score",
        "cm.name as comm_name",
    ]
    for dim_key, sql in axis_sqls.items():
        # Use a safe alias (replace non-alphanum chars)
        alias = dim_key.replace("-", "_")
        select_parts.append(f"{sql} AS {alias}_val")

    where_clause, params = await _resolve_filter(chart_def, owner_id)

    # For NULL filtering, use the first required axis (first non-link_color key)
    first_required_sql = None
    for dim_key, sql in axis_sqls.items():
        if dim_key != "link_color":
            first_required_sql = sql
            break

    null_filter = f"AND {first_required_sql} IS NOT NULL" if first_required_sql else ""

    # Sort
    sort_by = chart_def.get("sort_by")
    sort_dir = "DESC" if chart_def.get("sort_dir", "desc") == "desc" else "ASC"
    if sort_by and sort_by in axis_sqls:
        order = f"{axis_sqls[sort_by]} {sort_dir}"
    elif sort_by:
        from db.queries import SORTABLE_FIELDS
        col = SORTABLE_FIELDS.get(sort_by)
        order = f"{col} {sort_dir}" if col else f"{first_required_sql or 'p.handle'} {sort_dir}"
    elif first_required_sql:
        order = f"{first_required_sql} {sort_dir}"
    else:
        order = "p.handle ASC"

    select_sql = ", ".join(select_parts)
    query = f"""
        SELECT {select_sql}
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN community_metadata cm
               ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
        WHERE {where_clause}
          {null_filter}
        ORDER BY {order}
        LIMIT ?
    """

    rows = await conn.execute_query_dict(query, params + [limit])

    # Count total
    count_query = f"""
        SELECT COUNT(*) as total
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        WHERE {where_clause}
          {null_filter}
    """
    count_rows = await conn.execute_query_dict(count_query, params)
    total = int(count_rows[0]["total"]) if count_rows else 0

    # Normalise rows — map {dim_key}_val → point[dim_key]
    data = []
    for row in rows:
        point: dict[str, Any] = {
            "did":          row.get("did"),
            "handle":       row.get("handle"),
            "display_name": row.get("display_name"),
            "avatar_url":   row.get("avatar_url"),
            "community_id": row.get("community_id"),
            "flowrank":     row.get("flowrank_score"),
            "comm_name":    row.get("comm_name"),
            "color":        row.get("community_id"),   # default colour fallback
        }
        for dim_key in axis_sqls:
            alias = dim_key.replace("-", "_")
            val = row.get(f"{alias}_val")
            try:
                point[dim_key] = float(val) if val is not None else None
            except (TypeError, ValueError):
                point[dim_key] = val

        # hive link_color convenience alias
        if "link_color" in axis_sqls:
            point["color"] = point.get("link_color")

        data.append(point)

    # Build axes metadata
    axes: dict[str, dict] = {}
    for dim_key, axis_cfg in dimensions.items():
        if dim_key not in axis_sqls:
            continue
        domain_override = axis_cfg.get("domain", [None, None]) or [None, None]
        auto_domain = _compute_domain(data, dim_key)
        axes[dim_key] = {
            "label":  axis_cfg.get("label") or FIELD_LABELS.get(axis_cfg.get("field", ""), dim_key),
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
    aggregation = (chart_def.get("aggregation") or "avg").upper()
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
        LEFT JOIN community_metadata cm
               ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
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
            "label":  x_cfg.get("label") or FIELD_LABELS.get(x_cfg.get("field", ""), "X"),
            "scale":  x_cfg.get("scale", "linear"),
            "domain": _compute_domain(data, "x"),
        },
        "y": {
            "label":  y_cfg.get("label") or FIELD_LABELS.get(y_cfg.get("field", ""), f"{aggregation.title()} Value"),
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
    """Circle packing — delegates to get_graph_data(mode=packing)."""
    from db.queries import get_graph_data
    hierarchy = await get_graph_data(owner_id=owner_id, mode="packing", limit=limit)
    
    return {
        "data": hierarchy,
        "axes": {},
        "total": len(hierarchy.get("children", [])),
        "truncated": False,
    }


async def _query_graph(owner_id: int, chart_def: dict, limit: int) -> dict:
    """Force-directed (2D or 3D) — delegates to get_graph_data(mode=macro)."""
    from db.queries import get_graph_data

    # Apply filter if provided, passing it to a filtered macro view
    filter_tree = chart_def.get("filter_tree")
    filter_set_id = chart_def.get("filter_set_id")

    graph = await get_graph_data(owner_id=owner_id, mode="macro", limit=limit)

    # If filter is set, post-filter nodes by running the WHERE clause
    if filter_tree or filter_set_id:
        try:
            where_clause, params = await _resolve_filter(chart_def, owner_id)
            conn = connections.get("default")
            filtered_dids_rows = await conn.execute_query_dict(
                f"""
                SELECT p.did FROM account_relationships r
                JOIN profiles p ON p.id = r.profile_id
                WHERE {where_clause}
                """,
                params,
            )
            allowed = {r["did"] for r in filtered_dids_rows}
            graph["nodes"] = [n for n in graph.get("nodes", []) if n.get("did") in allowed]
            filtered_dids_set = {n.get("did") for n in graph["nodes"]}
            graph["links"] = [
                lnk for lnk in graph.get("links", [])
                if lnk.get("source") in filtered_dids_set and lnk.get("target") in filtered_dids_set
            ]
        except Exception as e:
            logger.warning(f"Graph filter failed, returning unfiltered: {e}")

    return {
        "data": graph,
        "axes": {},
        "total": len(graph.get("nodes", [])),
        "truncated": len(graph.get("nodes", [])) >= limit,
    }


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
    max_limit   = chart_def.get("limit") or chart_type.get("default_limit", 2000)
    limit       = 200 if thumbnail else min(int(max_limit), 10000)

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

    # Pass options_schema to front-end for 3D chart option rendering
    if chart_type.get("options_schema"):
        result["options_schema"] = chart_type["options_schema"]

    # Parse saved options blob
    raw_options = chart_def.get("options")
    if raw_options:
        try:
            result["chart_options"] = json.loads(raw_options) if isinstance(raw_options, str) else raw_options
        except (json.JSONDecodeError, TypeError):
            result["chart_options"] = {}
    else:
        result["chart_options"] = {}

    return result
