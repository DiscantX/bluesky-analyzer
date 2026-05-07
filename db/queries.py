"""
db/queries.py
Joined query helpers for shared profiles plus per-account relationship state.
"""

from __future__ import annotations
import json
from typing import Any
from tortoise import connections


SORTABLE_FIELDS = {
    "handle": "p.handle",
    "display_name": "p.display_name",
    "followers_count": "p.followers_count",
    "follows_count": "p.follows_count",
    "posts_count": "p.posts_count",
    "days_since_post": "p.days_since_post",
    "repost_ratio": "p.repost_ratio",
    "last_post_at": "p.last_post_at",
    "last_analyzed_at": "p.last_analyzed_at",
    "is_inactive": "p.is_inactive",
    "is_repost_heavy": "p.is_repost_heavy",
    "is_one_sided_follow": "r.is_one_sided_follow",
    "is_follower_only": "r.is_follower_only",
    "sampled_post_count": "p.sampled_post_count",
    "repost_count": "p.repost_count",
    "original_post_count": "p.original_post_count",
    "flowrank_score": "r.flowrank_score",
    "clustering_coefficient": "r.clustering_coefficient",
    "in_subgraph_degree": "r.in_subgraph_degree",
    "crawl_priority": "r.crawl_priority",
    "interacted_with_owner": "r.interacted_with_owner",
    "last_hydrated_at": "p.last_hydrated_at",
    "last_crawled_at": "r.last_crawled_at",
    "first_seen_at": "p.first_seen_at",
}

FILTERABLE_FLAGS = {
    "i_follow_them": "r.i_follow_them",
    "they_follow_me": "r.they_follow_me",
    "is_one_sided_follow": "r.is_one_sided_follow",
    "is_follower_only": "r.is_follower_only",
    "interacted_with_owner": "r.interacted_with_owner",
    "muted": "r.muted",
    "blocked": "r.blocked",
    "is_stub": "r.crawl_tier", # Special handling for is_stub
}

FILTERABLE_FIELDS_MAP = {
    # Boolean flags (from AccountRelationship)
    "i_follow_them": "r.i_follow_them",
    "they_follow_me": "r.they_follow_me",
    "interacted_with_owner": "r.interacted_with_owner",
    "muted": "r.muted",
    "blocked": "r.blocked",
    "is_one_sided_follow": "r.is_one_sided_follow",
    "is_follower_only": "r.is_follower_only",
    # Boolean flags (from Profile)

    "did": "p.did",
    # Numeric fields (from Profile)
    "followers_count": "p.followers_count",
    "follows_count": "p.follows_count",
    "posts_count": "p.posts_count",
    "days_since_post": "p.days_since_post",
    "sampled_post_count": "p.sampled_post_count",
    "repost_count": "p.repost_count",
    "original_post_count": "p.original_post_count",

    # Numeric fields (from AccountRelationship)
    "flowrank_score": "r.flowrank_score",
    "clustering_coefficient": "r.clustering_coefficient",
    "in_subgraph_degree": "r.in_subgraph_degree",
    "crawl_priority": "r.crawl_priority",
    "crawl_tier": "r.crawl_tier",
    "community_id": "r.community_id",

    # Date fields (from Profile)
    "last_post_at": "p.last_post_at",
    "last_analyzed_at": "p.last_analyzed_at",
    "last_hydrated_at": "p.last_hydrated_at",
    "first_seen_at": "p.first_seen_at",

    # Date fields (from AccountRelationship)
    "last_crawled_at": "r.last_crawled_at",

    # String fields (from Profile/AccountRelationship)
    "handle": "p.handle",
    "display_name": "p.display_name",
    "discovered_via": "r.discovered_via",
}


SELECT_FIELDS = """
    r.id,
    p.did,
    p.handle,
    p.display_name,
    p.avatar_url,
    p.profile_url,
    p.followers_count,
    p.follows_count,
    p.posts_count,
    r.i_follow_them,
    r.they_follow_me,
    p.last_post_at,
    p.days_since_post,
    p.repost_ratio,
    p.repost_count,
    p.original_post_count,
    p.sampled_post_count,
    p.first_seen_at,
    r.interacted_with_owner,
    p.is_inactive,
    p.is_repost_heavy,
    r.is_one_sided_follow,
    r.is_follower_only,
    r.muted,
    r.blocked,
    r.flowrank_score,
    r.community_id,
    r.in_subgraph_degree,
    r.crawl_tier,
    r.crawl_priority,
    r.clustering_coefficient,
    r.discovered_via,
    cm.name as comm_name,
    r.last_crawled_at,
    p.last_analyzed_at,
    p.last_hydrated_at
"""


def _bool_param(value: bool) -> int:
    return 1 if value else 0


async def _resolve_field_sql(field_name: Any, owner_id: int) -> str | None:
    """Resolves a field name to SQL, checking hardcoded map then Custom Variables."""
    if isinstance(field_name, (int, float)):
        return str(field_name)
    
    if isinstance(field_name, dict):
        return await _build_math_sql(field_name, owner_id)

    if not isinstance(field_name, str):
        return None

    # 1. Check hardcoded columns
    col = FILTERABLE_FIELDS_MAP.get(field_name)
    if col:
        return col

    # 2. Check Custom Variables
    from db.models import CustomVariable
    var = await CustomVariable.get_or_none(owner_id=owner_id, name=field_name)
    if var:
        tree = json.loads(var.expression_tree)
        return await _build_math_sql(tree, owner_id)
    
    return None


async def _build_math_sql(cond: dict, owner_id: int) -> str | None:
    """Helper to build math expressions from a node."""
    # Recursively resolve the left side (could be a raw column, constant, or sub-expression)
    left_field = cond.get("left_field") or cond.get("field")
    if left_field == "__constant__":
        left_field = cond.get("left_value", 0)
    elif left_field is None and cond.get("numerator"): 
        left_field = cond.get("numerator")
    
    extra_terms = cond.get("extra_terms")
    if not extra_terms and cond.get("denominator"):
        extra_terms = [{"op": "div", "field": cond.get("denominator")}]

    # Legacy support
    if left_field and extra_terms is None:
        math_op = cond.get("math_op") or ("div" if cond.get("denominator") else None)
        right_field = cond.get("right_field") or cond.get("denominator")
        if math_op and right_field:
            extra_terms = [{"op": math_op, "field": right_field}]

    if not left_field or not extra_terms:
        return None

    col_left = await _resolve_field_sql(left_field, owner_id)
    if not col_left:
        return None

    expr_sql = col_left
    for term in extra_terms:
        t_op = term.get("op")
        t_field = term.get("field")
        if t_field == "__constant__":
            # For constants, we resolve the literal value
            col_right = str(term.get("value", 0))
        else:
            col_right = await _resolve_field_sql(t_field, owner_id)
            
        if not col_right:
            return None
        
        if t_op == "add":   expr_sql = f"({expr_sql} + {col_right})"
        elif t_op == "sub": expr_sql = f"({expr_sql} - {col_right})"
        elif t_op == "mul": expr_sql = f"({expr_sql} * {col_right})"
        elif t_op == "div": expr_sql = f"(1.0 * {expr_sql} / NULLIF({col_right}, 0))"
        elif t_op == "mod": expr_sql = f"({expr_sql} % NULLIF({col_right}, 0))"
        elif t_op == "pow": expr_sql = f"POWER({expr_sql}, {col_right})"
    
    return expr_sql


async def _build_recursive_where_clause(condition_tree: dict, params: list[Any], owner_id: int) -> str:
    """
    Recursively translates a FilterSet JSON tree into SQL.
    """
    op = condition_tree.get("op", "AND").upper()
    conditions = condition_tree.get("conditions", [])

    if not conditions:
        return "1=1"

    parts = []
    for cond in conditions:
        # Nested logic group
        if "op" in cond and "conditions" in cond:
            parts.append(f"({await _build_recursive_where_clause(cond, params, owner_id)})")
            continue

        # Member of Filter logic
        if cond.get("field") == "__member__":
            filter_id = cond.get("value")
            from db.models import FilterSet
            target_fs = await FilterSet.get_or_none(id=filter_id, owner_id=owner_id)
            if target_fs:
                sub_params = []
                sub_where = await _build_recursive_where_clause(json.loads(target_fs.condition_tree), sub_params, owner_id)
                sub_sql = f"r.did IN (SELECT p2.did FROM account_relationships r2 JOIN profiles p2 ON p2.id = r2.profile_id WHERE r2.owner_id = {owner_id} AND {sub_where.replace('?', '%PARAM%')})"
                # Tortoise doesn't easily nested parameters this way, so we manually interpolate sub_params
                for p in sub_params:
                    val = f"'{p}'" if isinstance(p, str) else str(p)
                    sub_sql = sub_sql.replace("%PARAM%", val, 1)
                parts.append(sub_sql)
            continue

        # Leaf condition
        field = cond.get("field")
        cond_op = cond.get("op")
        value = cond.get("value")
        
        # Resolve column (could be raw column or math expr)
        is_math_expr = (cond.get("left_field") or cond.get("numerator")) is not None
        if is_math_expr:
            column = await _build_math_sql(cond, owner_id)
        else:
            column = await _resolve_field_sql(field, owner_id)

        if not column:
            continue

        # Coerce values for known boolean fields (FILTERABLE_FLAGS contains the bool keys)
        if not is_math_expr and field in FILTERABLE_FLAGS:
            if isinstance(value, str):
                value = value.lower() == "true"
            value = bool(value)

        if cond_op == "eq":
            if value is None:
                parts.append(f"{column} IS NULL")
            else:
                parts.append(f"{column} = ?")
                params.append(_bool_param(value) if isinstance(value, bool) else value)
        elif cond_op == "neq":
            if value is None:
                parts.append(f"{column} IS NOT NULL")
            else:
                parts.append(f"{column} != ?")
                params.append(_bool_param(value) if isinstance(value, bool) else value)
        elif cond_op == "gt":
            parts.append(f"{column} > ?")
            params.append(value)
        elif cond_op == "gte":
            parts.append(f"{column} >= ?")
            params.append(value)
        elif cond_op == "lt":
            parts.append(f"{column} < ?")
            params.append(value)
        elif cond_op == "lte":
            parts.append(f"{column} <= ?")
            params.append(value)
        elif cond_op == "between":
            if isinstance(value, list) and len(value) == 2:
                parts.append(f"{column} BETWEEN ? AND ?")
                params.extend(value)
        elif cond_op == "contains":
            parts.append(f"{column} LIKE ?")
            params.append(f"%{value}%")
        elif cond_op == "starts_with":
            parts.append(f"{column} LIKE ?")
            params.append(f"{value}%")
        elif cond_op == "ends_with":
            parts.append(f"{column} LIKE ?")
            params.append(f"%{value}")
        elif cond_op == "is_null":
            parts.append(f"{column} IS NULL")
        elif cond_op == "is_not_null":
            parts.append(f"{column} IS NOT NULL")

    if not parts:
        return "1=1"

    return f" {op} ".join(parts)


async def _where(
    owner_id: int,
    *,
    search: str | None = None,
    flags: dict[str, bool] | None = None,
    filter_tree: dict | str | None = None,
    min_days_inactive: int | None = None,
    min_repost_ratio: float | None = None,
    max_repost_ratio: float | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    min_flowrank: float | None = None,
    min_in_degree: int | None = None,
    exclude_stubs: bool = False,
    exclude_unanalyzed: bool = False,
    is_stub: bool | None = None,
    min_sampled_post_count: int | None = None,
    max_sampled_post_count: int | None = None,
    min_repost_count: int | None = None,
    max_repost_count: int | None = None,
    min_original_post_count: int | None = None,
    max_original_post_count: int | None = None,
    min_crawl_priority: float | None = None,
    max_crawl_priority: float | None = None,
    min_clustering_coefficient: float | None = None,
    max_clustering_coefficient: float | None = None,
    before_last_post_at: str | None = None,
    after_last_post_at: str | None = None,
    before_last_analyzed_at: str | None = None,
    after_last_analyzed_at: str | None = None,
    before_last_hydrated_at: str | None = None,
    after_last_hydrated_at: str | None = None,
    before_last_crawled_at: str | None = None,
    after_last_crawled_at: str | None = None,
    before_first_seen_at: str | None = None,
    after_first_seen_at: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["r.owner_id = ?"]
    params: list[Any] = [owner_id]

    if search:
        clauses.append("(p.handle LIKE ? OR p.display_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if filter_tree:
        if isinstance(filter_tree, str):
            filter_tree = json.loads(filter_tree)
        clauses.append(f"({await _build_recursive_where_clause(filter_tree, params, owner_id)})")

    if flags:
        for field, value in flags.items():
            if field == "is_stub": continue
            column = FILTERABLE_FLAGS.get(field)
            if column:
                clauses.append(f"{column} = ?")
                params.append(_bool_param(value) if isinstance(value, bool) else value)
    
    if is_stub is not None:
        if is_stub:
            clauses.append("r.crawl_tier = 0")
        else:
            clauses.append("r.crawl_tier > 0")

    if exclude_stubs:
        clauses.append("r.crawl_tier > 0")
    if exclude_unanalyzed:
        clauses.append("p.last_analyzed_at IS NOT NULL")

    if min_days_inactive is not None:
        clauses.append("p.days_since_post >= ?")
        params.append(min_days_inactive)
    if min_repost_ratio is not None:
        clauses.append("p.repost_ratio >= ?")
        params.append(min_repost_ratio)
    if max_repost_ratio is not None:
        clauses.append("p.repost_ratio <= ?")
        params.append(max_repost_ratio)
    if min_followers is not None:
        clauses.append("p.followers_count >= ?")
        params.append(min_followers)
    if max_followers is not None:
        clauses.append("p.followers_count <= ?")
        params.append(max_followers)
    if min_flowrank is not None:
        clauses.append("r.flowrank_score >= ?")
        params.append(min_flowrank)
    if min_in_degree is not None:
        clauses.append("r.in_subgraph_degree >= ?")
        params.append(min_in_degree)
    
    if min_sampled_post_count is not None:
        clauses.append("p.sampled_post_count >= ?")
        params.append(min_sampled_post_count)
    if max_sampled_post_count is not None:
        clauses.append("p.sampled_post_count <= ?")
        params.append(max_sampled_post_count)
    if min_repost_count is not None:
        clauses.append("p.repost_count >= ?")
        params.append(min_repost_count)
    if max_repost_count is not None:
        clauses.append("p.repost_count <= ?")
        params.append(max_repost_count)
    if min_original_post_count is not None:
        clauses.append("p.original_post_count >= ?")
        params.append(min_original_post_count)
    if max_original_post_count is not None:
        clauses.append("p.original_post_count <= ?")
        params.append(max_original_post_count)
    if min_crawl_priority is not None:
        clauses.append("r.crawl_priority >= ?")
        params.append(min_crawl_priority)
    if max_crawl_priority is not None:
        clauses.append("r.crawl_priority <= ?")
        params.append(max_crawl_priority)
    if min_clustering_coefficient is not None:
        clauses.append("r.clustering_coefficient >= ?")
        params.append(min_clustering_coefficient)
    if max_clustering_coefficient is not None:
        clauses.append("r.clustering_coefficient <= ?")
        params.append(max_clustering_coefficient)

    if before_last_post_at is not None:
        clauses.append("p.last_post_at < ?")
        params.append(before_last_post_at)
    if after_last_post_at is not None:
        clauses.append("p.last_post_at > ?")
        params.append(after_last_post_at)
    if before_last_analyzed_at is not None:
        clauses.append("p.last_analyzed_at < ?")
        params.append(before_last_analyzed_at)
    if after_last_analyzed_at is not None:
        clauses.append("p.last_analyzed_at > ?")
        params.append(after_last_analyzed_at)
    if before_last_hydrated_at is not None:
        clauses.append("p.last_hydrated_at < ?")
        params.append(before_last_hydrated_at)
    if after_last_hydrated_at is not None:
        clauses.append("p.last_hydrated_at > ?")
        params.append(after_last_hydrated_at)

    if before_first_seen_at is not None:
        clauses.append("p.first_seen_at < ?")
        params.append(before_first_seen_at)
    if after_first_seen_at is not None:
        clauses.append("p.first_seen_at > ?")
        params.append(after_first_seen_at)
    if before_last_crawled_at is not None:
        clauses.append("r.last_crawled_at < ?")
        params.append(before_last_crawled_at)
    if after_last_crawled_at is not None:
        clauses.append("r.last_crawled_at > ?")
        params.append(after_last_crawled_at)

    return " AND ".join(clauses), params


async def query_users(
    owner_id: int,
    *,
    search: str | None = None,
    flags: dict[str, bool] | None = None,
    filter_tree: dict | str | None = None,
    min_days_inactive: int | None = None,
    min_repost_ratio: float | None = None,
    max_repost_ratio: float | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    min_flowrank: float | None = None,
    min_in_degree: int | None = None,
    exclude_stubs: bool = False,
    exclude_unanalyzed: bool = False,
    is_stub: bool | None = None,
    min_sampled_post_count: int | None = None,
    max_sampled_post_count: int | None = None,
    min_repost_count: int | None = None,
    max_repost_count: int | None = None,
    min_original_post_count: int | None = None,
    max_original_post_count: int | None = None,
    min_crawl_priority: float | None = None,
    max_crawl_priority: float | None = None,
    min_clustering_coefficient: float | None = None,
    max_clustering_coefficient: float | None = None,
    before_last_post_at: str | None = None,
    after_last_post_at: str | None = None,
    before_last_analyzed_at: str | None = None,
    after_last_analyzed_at: str | None = None,
    before_last_hydrated_at: str | None = None,
    after_last_hydrated_at: str | None = None,
    before_last_crawled_at: str | None = None,
    after_last_crawled_at: str | None = None,
    before_first_seen_at: str | None = None,
    after_first_seen_at: str | None = None,
    sort_by: str = "handle",
    sort_dir: str = "asc",
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where_sql, params = await _where(
        owner_id,
        search=search,
        flags=flags,
        filter_tree=filter_tree,
        min_days_inactive=min_days_inactive,
        min_repost_ratio=min_repost_ratio,
        max_repost_ratio=max_repost_ratio,
        min_followers=min_followers,
        max_followers=max_followers,
        min_flowrank=min_flowrank,
        min_in_degree=min_in_degree,
        exclude_stubs=exclude_stubs,
        exclude_unanalyzed=exclude_unanalyzed,
        is_stub=is_stub,
        min_sampled_post_count=min_sampled_post_count,
        max_sampled_post_count=max_sampled_post_count,
        min_repost_count=min_repost_count,
        max_repost_count=max_repost_count,
        min_original_post_count=min_original_post_count,
        max_original_post_count=max_original_post_count,
        min_crawl_priority=min_crawl_priority,
        max_crawl_priority=max_crawl_priority,
        min_clustering_coefficient=min_clustering_coefficient,
        max_clustering_coefficient=max_clustering_coefficient,
        before_last_post_at=before_last_post_at,
        after_last_post_at=after_last_post_at,
        before_last_analyzed_at=before_last_analyzed_at,
        after_last_analyzed_at=after_last_analyzed_at,
        before_last_hydrated_at=before_last_hydrated_at,
        after_last_hydrated_at=after_last_hydrated_at,
        before_last_crawled_at=before_last_crawled_at,
        after_last_crawled_at=after_last_crawled_at,
        before_first_seen_at=before_first_seen_at,
        after_first_seen_at=after_first_seen_at,
    )
    order_col = SORTABLE_FIELDS.get(sort_by, "p.handle")
    direction = "DESC" if sort_dir == "desc" else "ASC"

    conn = connections.get("default")
    rows = await conn.execute_query_dict(
        f"""
        SELECT {SELECT_FIELDS}
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
        WHERE {where_sql}
        ORDER BY {order_col} {direction}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    total_rows = await conn.execute_query_dict(
        f"""
        SELECT COUNT(*) AS total
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
        WHERE {where_sql}
        """,
        params,
    )
    return rows, int(total_rows[0]["total"])


async def get_stats(owner_id: int) -> dict[str, Any]:
    conn = connections.get("default")
    rows = await conn.execute_query_dict(
        """
        SELECT
            SUM(CASE WHEN r.i_follow_them = 1 THEN 1 ELSE 0 END) AS total_follows,
            SUM(CASE WHEN r.they_follow_me = 1 THEN 1 ELSE 0 END) AS total_followers,
            SUM(CASE WHEN p.is_inactive = 1 AND r.i_follow_them = 1 THEN 1 ELSE 0 END) AS inactive,
            SUM(CASE WHEN p.is_repost_heavy = 1 AND r.i_follow_them = 1 THEN 1 ELSE 0 END) AS repost_heavy,
            SUM(CASE WHEN r.is_one_sided_follow = 1 THEN 1 ELSE 0 END) AS one_sided,
            SUM(CASE WHEN r.is_follower_only = 1 THEN 1 ELSE 0 END) AS follower_only,
            SUM(CASE WHEN r.interacted_with_owner = 0 AND r.i_follow_them = 1 THEN 1 ELSE 0 END) AS no_interaction,
            COUNT(*) AS graph_size,
            SUM(CASE WHEN p.last_hydrated_at IS NOT NULL THEN 1 ELSE 0 END) AS hydrated,
            SUM(CASE WHEN p.last_analyzed_at IS NOT NULL THEN 1 ELSE 0 END) AS analysed,
            SUM(CASE WHEN p.last_analyzed_at IS NULL THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN r.crawl_tier = 0 THEN 1 ELSE 0 END) AS stubs_count
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        WHERE r.owner_id = ?
        """,
        [owner_id],
    )
    from analyzer.manager import global_req_tracker, global_found_tracker
    
    row = rows[0] if rows else {}
    stats = {key: int(value or 0) for key, value in row.items()}
    stats["req_rate"] = global_req_tracker.get_rate()
    stats["found_rate"] = global_found_tracker.get_rate()
    return stats


async def get_graph_data(
    owner_id: int,
    mode: str = "macro",
    seed_did: str | None = None,
    community_id: int | None = None,
    limit: int = 1000
) -> dict[str, Any]:
    """
    Retrieves nodes and links for graph visualization.
    Supports stratified sampling for the macro-view and neighborhood fetching for ego-views.
    """
    conn = connections.get("default")
    
    # 1. Select Nodes based on mode
    if mode == "macro":
        # Stratified sampling: Top N per community + Bridges
        nodes_query = """
            WITH RankedNodes AS (
                SELECT 
                    r.did,
                    p.handle,
                    r.flowrank_score as rank,
                    r.community_id as comm,
                    r.crawl_tier as tier,
                    r.clustering_coefficient as cc,
                    p.followers_count,
                    p.posts_count,
                    p.repost_ratio,
                    r.i_follow_them,
                    r.they_follow_me,
                    ROW_NUMBER() OVER (PARTITION BY r.community_id ORDER BY r.flowrank_score DESC) as rank_in_comm
                FROM account_relationships r
                JOIN profiles p ON p.id = r.profile_id
                WHERE r.owner_id = ? AND r.community_id IS NOT NULL
            )
            SELECT rn.*, cm.name as comm_name
            FROM RankedNodes rn
            LEFT JOIN community_metadata cm ON cm.community_id = rn.comm AND cm.owner_id = ?
            WHERE rank_in_comm <= 500
               OR (cc < 0.1 AND rank > 0.001) -- Bridge nodes
            ORDER BY rank DESC
            LIMIT ?
        """
        params = [owner_id, owner_id, limit]
    elif mode == "ego" and seed_did:
        # Neighborhood prioritized by FlowRank (Depth 1 and 2)
        nodes_query = """
            WITH Neighbors AS (
                SELECT followee_did as did FROM follow_edges WHERE follower_did = ?
                UNION
                SELECT follower_did as did FROM follow_edges WHERE followee_did = ?
            )
            SELECT DISTINCT p.did, p.handle, r.flowrank_score as rank, r.community_id as comm, r.crawl_tier as tier, cm.name as comm_name,
                   r.clustering_coefficient as cc, p.followers_count, p.posts_count, p.repost_ratio,
                   r.i_follow_them, r.they_follow_me
            FROM account_relationships r
            JOIN profiles p ON p.id = r.profile_id
            LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
            WHERE r.owner_id = ? 
              AND (
                r.did = ? 
                OR r.did IN (SELECT did FROM Neighbors)
                -- Optional: add Depth 2 logic here if performance allows, 
                -- but usually Depth 1 + prioritized by Rank is a safer start
              )
            ORDER BY r.flowrank_score DESC
            LIMIT ?
        """
        params = [seed_did, seed_did, owner_id, seed_did, limit]
    elif mode == "community":
        if community_id is None:
            # Meta-nodes (communities overview)
            nodes_query = """
                SELECT
                    r.community_id as id,
                    cm.name as name,
                    cm.description as description,
                    cm.top_keywords as top_keywords,
                    cm.representative_members as representative_members,
                    COUNT(r.did) as member_count,
                    AVG(r.flowrank_score) as avg_rank,
                    MIN(p.handle) as representative_handle,
                    'community_meta' as type -- Custom type for frontend
                FROM account_relationships r
                JOIN profiles p ON p.id = r.profile_id
                LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
                WHERE r.owner_id = ? AND r.community_id IS NOT NULL
                GROUP BY r.community_id
                ORDER BY member_count DESC
                LIMIT ?
            """
            params = [owner_id, limit]
        else:
            # Individual nodes within a specific community
            nodes_query = """
                SELECT
                    r.did,
                    p.handle,
                    r.flowrank_score as rank,
                    r.community_id as comm,
                    r.crawl_tier as tier,
                    cm.name as comm_name,
                    r.clustering_coefficient as cc, p.followers_count, p.posts_count, p.repost_ratio,
                    r.i_follow_them, r.they_follow_me
                FROM account_relationships r
                JOIN profiles p ON p.id = r.profile_id
                LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
                WHERE r.owner_id = ? AND r.community_id = ?
                ORDER BY r.flowrank_score DESC
                LIMIT ?
            """
            params = [owner_id, community_id, limit]

    elif mode == "packing":
            # Hierarchical data for Zoomable Circle Packing
            # Top 100 members per community by FlowRank — these define each community's identity

            # BUG FIX: was `r.repost_ratio` (wrong table alias) — ratio lives on Profile (p), not AccountRelationship (r)
            members_query = """
                WITH RankedMembers AS (
                    SELECT
                        r.did,
                        p.handle,
                        p.display_name,
                        r.community_id,
                        r.flowrank_score  AS rank,
                        p.top_keywords,
                        ROW_NUMBER() OVER (
                            PARTITION BY r.community_id
                            ORDER BY r.flowrank_score DESC
                        ) AS rn
                    FROM account_relationships r
                    JOIN profiles p ON p.id = r.profile_id
                    WHERE r.owner_id = ? AND r.community_id IS NOT NULL
                )
                SELECT did, handle, display_name, community_id, rank, top_keywords
                FROM RankedMembers
                WHERE rn <= 100
            """
            members_data = await conn.execute_query_dict(members_query, [owner_id])

            # Unique community IDs from the result set
            cids = list({m["community_id"] for m in members_data})
            meta_lookup = {}
            if cids:
                placeholders = ",".join(["?"] * len(cids))
                comm_meta = await conn.execute_query_dict(
                    f"SELECT community_id, name, description FROM community_metadata "
                    f"WHERE owner_id = ? AND community_id IN ({placeholders})",
                    [owner_id] + cids,
                )
                meta_lookup = {c["community_id"]: c for c in comm_meta}

            # Assemble D3 hierarchy
            communities_map = {}
            for m in members_data:
                cid = m["community_id"]
                if cid not in communities_map:
                    meta = meta_lookup.get(cid, {})
                    communities_map[cid] = {
                        "name": meta.get("name") or f"Community {cid}",
                        "id": cid,
                        "children": [],
                    }

                # NULL-SAFE top_keywords parsing — value may be None, dict, or JSON string
                kws: dict = {}
                raw = m.get("top_keywords")
                if raw:
                    if isinstance(raw, dict):
                        kws = raw
                    else:
                        try:
                            import json as _json
                            kws = _json.loads(raw)
                        except (ValueError, TypeError):
                            kws = {}

                top5 = [k for k, _ in sorted(kws.items(), key=lambda x: x[1], reverse=True)[:5]]

                communities_map[cid]["children"].append({
                    "name": m["handle"],
                    "handle": m["handle"],
                    "display_name": m["display_name"],
                    "value": max(float(m["rank"] or 0.0), 1e-9),  # D3 pack requires value > 0
                    "keywords": top5,
                    "did": m["did"],
                })

            # Filter out communities that ended up with no members
            children = [c for c in communities_map.values() if c["children"]]
            return {
                "name": "Network",
                "children": children,
                "metadata": {"mode": "packing", "community_count": len(children)},
            }
 
 
    else:
        # Default fallback
        nodes_query = """
            SELECT p.did, p.handle, r.flowrank_score as rank, r.community_id as comm, r.crawl_tier as tier, cm.name as comm_name,
                   r.clustering_coefficient as cc, p.followers_count, p.posts_count, r.repost_ratio, 
                   r.i_follow_them, r.they_follow_me
            FROM account_relationships r
            JOIN profiles p ON p.id = r.profile_id
            LEFT JOIN community_metadata cm ON cm.community_id = r.community_id AND cm.owner_id = r.owner_id
            WHERE r.owner_id = ?
            ORDER BY r.flowrank_score DESC
            LIMIT ?
        """
        params = [owner_id, limit]

    nodes = await conn.execute_query_dict(nodes_query, params)

    # For community meta-nodes, links are not directly between them in this view.
    # For individual nodes, we need their DIDs.
    node_dids = []
    if mode == "community" and community_id is None:
        # Meta-nodes don't have DIDs in the same way, and we don't link them directly here.
        # The frontend will handle conceptual links or layout.
        links = []
    else:
        # For macro, ego, or community-detail, we need DIDs for links.
        node_dids = [n["did"] for n in nodes if "did" in n]

    if not node_dids:
        # Return meta-nodes even if no links, or empty nodes if no DIDs
        return {"nodes": nodes, "links": [], "metadata": {"mode": mode}}

    # Only fetch links if there are actual DIDs to link
    links = []
    # 2. Select Links between the chosen nodes
    placeholders = ",".join(["?"] * len(node_dids))
    links_query = f"""
        SELECT follower_did as source, followee_did as target
        FROM follow_edges
        WHERE follower_did IN ({placeholders})
          AND followee_did IN ({placeholders})
    """
    links = await conn.execute_query_dict(links_query, node_dids + node_dids)

    
    # Calculate truncated counts for "Ghost Nodes" (Design Doc Section 3 - Tier C)
    truncated_counts = {}
    if mode == "ego" and seed_did:
        total_neighbors_query = """
            SELECT COUNT(DISTINCT neighbor) as count
            FROM (
                SELECT followee_did as neighbor FROM follow_edges WHERE follower_did = ?
                UNION
                SELECT follower_did as neighbor FROM follow_edges WHERE followee_did = ?
            )
        """
        total_res = await conn.execute_query_dict(total_neighbors_query, [seed_did, seed_did])
        total_neighbors = total_res[0]["count"] if total_res else 0
        truncated_counts[seed_did] = max(0, total_neighbors - (len(nodes) - 1))

    return {"nodes": nodes, "links": links, "metadata": {"truncated_counts": truncated_counts, "mode": mode}}
