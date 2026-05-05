"""
api/users.py
Query endpoints for tracked users — filtering, sorting, pagination.
GET /api/users/{alias}         — paginated + filtered list (JSON)
GET /api/users/{alias}/stats   — summary counts for the dashboard
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.models import SavedAccount
from db.queries import query_users, get_stats

router = APIRouter(prefix="/api/users", tags=["users"])


class TrackedUserResponse(BaseModel):
    id: int
    did: str
    handle: str
    display_name: str | None
    avatar_url: str | None
    profile_url: str | None
    followers_count: int
    follows_count: int
    posts_count: int
    i_follow_them: bool
    they_follow_me: bool
    last_post_at: str | None
    days_since_post: int | None
    repost_ratio: float
    repost_count: int
    original_post_count: int
    sampled_post_count: int
    first_seen_at: str | None
    interacted_with_owner: bool
    is_inactive: bool
    is_repost_heavy: bool
    is_one_sided_follow: bool
    is_follower_only: bool
    muted: bool
    blocked: bool
    # Graph metrics
    flowrank_score: float | None
    community_id: int | None
    in_subgraph_degree: int
    crawl_priority: float | None
    clustering_coefficient: float | None
    crawl_tier: int
    discovered_via: str | None
    last_analyzed_at: str | None
    last_hydrated_at: str | None
    last_crawled_at: str | None


def _dt(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize(u: dict) -> TrackedUserResponse:
    return TrackedUserResponse(
        id=u["id"],
        did=u["did"],
        handle=u["handle"],
        display_name=u["display_name"],
        avatar_url=u["avatar_url"],
        profile_url=u["profile_url"],
        followers_count=u["followers_count"] or 0,
        follows_count=u["follows_count"] or 0,
        posts_count=u["posts_count"] or 0,
        i_follow_them=bool(u["i_follow_them"]),
        they_follow_me=bool(u["they_follow_me"]),
        last_post_at=_dt(u["last_post_at"]) if u["last_post_at"] else None,
        days_since_post=u["days_since_post"],
        repost_ratio=u["repost_ratio"] or 0.0,
        repost_count=u["repost_count"] or 0,
        original_post_count=u["original_post_count"] or 0,
        sampled_post_count=u["sampled_post_count"] or 0,
        first_seen_at=_dt(u["first_seen_at"]) if u["first_seen_at"] else None,
        interacted_with_owner=bool(u["interacted_with_owner"]),
        is_inactive=bool(u["is_inactive"]),
        is_repost_heavy=bool(u["is_repost_heavy"]),
        is_one_sided_follow=bool(u["is_one_sided_follow"]),
        is_follower_only=bool(u["is_follower_only"]),
        muted=bool(u["muted"]),
        blocked=bool(u["blocked"]),
        flowrank_score=u["flowrank_score"],
        community_id=u["community_id"],
        in_subgraph_degree=u["in_subgraph_degree"] or 0,
        crawl_priority=u["crawl_priority"],
        clustering_coefficient=u["clustering_coefficient"],
        crawl_tier=u["crawl_tier"] or 0,
        discovered_via=u["discovered_via"],
        last_analyzed_at=_dt(u["last_analyzed_at"]) if u["last_analyzed_at"] else None,
        last_hydrated_at=_dt(u["last_hydrated_at"]) if u["last_hydrated_at"] else None,
        last_crawled_at=_dt(u["last_crawled_at"]) if u["last_crawled_at"] else None,
    )


@router.get("/{alias}/stats")
async def get_account_stats(alias: str):
    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    stats = await get_stats(account.id)
    stats["last_synced_at"] = (
        account.last_synced_at.isoformat() if account.last_synced_at else None
    )
    return stats


@router.get("/{alias}", response_model=dict)
async def list_users(
    alias: str,
    # Text search
    search: Optional[str] = Query(None),
    # Boolean flag filters — any combination
    i_follow_them: Optional[bool] = Query(None),
    they_follow_me: Optional[bool] = Query(None),
    is_inactive: Optional[bool] = Query(None),
    is_repost_heavy: Optional[bool] = Query(None),
    is_one_sided_follow: Optional[bool] = Query(None),
    is_follower_only: Optional[bool] = Query(None),
    interacted_with_owner: Optional[bool] = Query(None),
    muted: Optional[bool] = Query(None),
    blocked: Optional[bool] = Query(None),
    exclude_stubs: bool = Query(False),
    exclude_unanalyzed: bool = Query(False),
    is_stub: Optional[bool] = Query(None),
    # Advanced / Graph filters
    filter_tree: Optional[str] = Query(None),
    min_flowrank: Optional[float] = Query(None),
    min_in_degree: Optional[int] = Query(None),
    # Numeric range filters
    min_days_inactive: Optional[int] = Query(None, ge=0),
    min_repost_ratio: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_repost_ratio: Optional[float] = Query(None, ge=0.0, le=1.0),
    min_followers: Optional[int] = Query(None, ge=0),
    max_followers: Optional[int] = Query(None, ge=0),
    min_sampled_post_count: Optional[int] = Query(None, ge=0),
    max_sampled_post_count: Optional[int] = Query(None, ge=0),
    min_repost_count: Optional[int] = Query(None, ge=0),
    max_repost_count: Optional[int] = Query(None, ge=0),
    min_original_post_count: Optional[int] = Query(None, ge=0),
    max_original_post_count: Optional[int] = Query(None, ge=0),
    min_crawl_priority: Optional[float] = Query(None, ge=0.0),
    max_crawl_priority: Optional[float] = Query(None, ge=0.0),
    min_clustering_coefficient: Optional[float] = Query(None, ge=0.0),
    max_clustering_coefficient: Optional[float] = Query(None, ge=0.0),
    # Date range filters
    before_last_post_at: Optional[str] = Query(None),
    after_last_post_at: Optional[str] = Query(None),
    before_last_analyzed_at: Optional[str] = Query(None),
    after_last_analyzed_at: Optional[str] = Query(None),
    before_last_hydrated_at: Optional[str] = Query(None),
    after_last_hydrated_at: Optional[str] = Query(None),
    before_last_crawled_at: Optional[str] = Query(None),
    after_last_crawled_at: Optional[str] = Query(None),
    before_first_seen_at: Optional[str] = Query(None),
    after_first_seen_at: Optional[str] = Query(None),
    # Sorting
    sort_by: str = Query("handle"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    # Pagination
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    # Collect active boolean flags
    flags: dict[str, bool] = {}
    for name, val in [
        ("i_follow_them", i_follow_them),
        ("they_follow_me", they_follow_me),
        ("is_inactive", is_inactive),
        ("is_repost_heavy", is_repost_heavy),
        ("is_one_sided_follow", is_one_sided_follow),
        ("is_follower_only", is_follower_only),
        ("interacted_with_owner", interacted_with_owner),
        ("muted", muted),
        ("blocked", blocked),
    ]:
        if val is not None:
            flags[name] = val

    users, total = await query_users(
        owner_id=account.id,
        search=search,
        flags=flags or None,
        filter_tree=filter_tree,
        # The following individual parameters will be ignored if filter_tree is provided
        exclude_stubs=exclude_stubs,
        exclude_unanalyzed=exclude_unanalyzed,
        is_stub=is_stub,
        min_flowrank=min_flowrank,
        min_in_degree=min_in_degree,
        min_days_inactive=min_days_inactive,
        min_repost_ratio=min_repost_ratio,
        max_repost_ratio=max_repost_ratio,
        min_followers=min_followers,
        max_followers=max_followers,
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
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "users": [_serialize(u) for u in users],
    }
