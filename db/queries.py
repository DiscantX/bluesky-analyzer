"""
db/queries.py
Joined query helpers for shared profiles plus per-account relationship state.
"""

from __future__ import annotations

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
    "interacted_with_owner": "r.interacted_with_owner",
    "flowrank_score": "r.flowrank_score",
    "clustering_coefficient": "r.clustering_coefficient",
    "in_subgraph_degree": "r.in_subgraph_degree",
    "crawl_priority": "r.crawl_priority",
}

FILTERABLE_FLAGS = {
    "i_follow_them": "r.i_follow_them",
    "they_follow_me": "r.they_follow_me",
    "is_inactive": "p.is_inactive",
    "is_repost_heavy": "p.is_repost_heavy",
    "is_one_sided_follow": "r.is_one_sided_follow",
    "is_follower_only": "r.is_follower_only",
    "interacted_with_owner": "r.interacted_with_owner",
    "muted": "r.muted",
    "blocked": "r.blocked",
    "crawl_tier": "r.crawl_tier",
    "community_id": "r.community_id",
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
    r.discovered_via,
    p.last_analyzed_at
"""


def _bool_param(value: bool) -> int:
    return 1 if value else 0


def _where(
    owner_id: int,
    *,
    search: str | None = None,
    flags: dict[str, bool] | None = None,
    min_days_inactive: int | None = None,
    min_repost_ratio: float | None = None,
    max_repost_ratio: float | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    min_flowrank: float | None = None,
    min_in_degree: int | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["r.owner_id = ?"]
    params: list[Any] = [owner_id]

    if search:
        clauses.append("(p.handle LIKE ? OR p.display_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if flags:
        for field, value in flags.items():
            column = FILTERABLE_FLAGS.get(field)
            if column:
                clauses.append(f"{column} = ?")
                params.append(_bool_param(value) if isinstance(value, bool) else value)

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
    sort_by: str = "handle",
    sort_dir: str = "asc",
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    # TODO: port recursive FilterSet trees to SQL once the new schema settles.
    where_sql, params = _where(
        owner_id,
        search=search,
        flags=flags,
        min_days_inactive=min_days_inactive,
        min_repost_ratio=min_repost_ratio,
        max_repost_ratio=max_repost_ratio,
        min_followers=min_followers,
        max_followers=max_followers,
        min_flowrank=min_flowrank,
        min_in_degree=min_in_degree,
    )
    order_col = SORTABLE_FIELDS.get(sort_by, "p.handle")
    direction = "DESC" if sort_dir == "desc" else "ASC"

    conn = connections.get("default")
    rows = await conn.execute_query_dict(
        f"""
        SELECT {SELECT_FIELDS}
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
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
            SUM(CASE WHEN p.last_analyzed_at IS NOT NULL THEN 1 ELSE 0 END) AS analysed,
            SUM(CASE WHEN p.last_analyzed_at IS NULL THEN 1 ELSE 0 END) AS pending
        FROM account_relationships r
        JOIN profiles p ON p.id = r.profile_id
        WHERE r.owner_id = ?
        """,
        [owner_id],
    )
    row = rows[0] if rows else {}
    return {key: int(value or 0) for key, value in row.items()}
