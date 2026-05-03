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

from db.models import SavedAccount, TrackedUser
from db.queries import build_query, get_stats, SORTABLE_FIELDS, FILTERABLE_FLAGS

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
    interacted_with_owner: bool
    is_inactive: bool
    is_repost_heavy: bool
    is_one_sided_follow: bool
    is_follower_only: bool
    muted: bool
    blocked: bool
    last_analyzed_at: str | None


def _serialize(u: TrackedUser) -> TrackedUserResponse:
    return TrackedUserResponse(
        id=u.id,
        did=u.did,
        handle=u.handle,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        profile_url=u.profile_url,
        followers_count=u.followers_count,
        follows_count=u.follows_count,
        posts_count=u.posts_count,
        i_follow_them=u.i_follow_them,
        they_follow_me=u.they_follow_me,
        last_post_at=u.last_post_at.isoformat() if u.last_post_at else None,
        days_since_post=u.days_since_post,
        repost_ratio=u.repost_ratio,
        repost_count=u.repost_count,
        original_post_count=u.original_post_count,
        sampled_post_count=u.sampled_post_count,
        interacted_with_owner=u.interacted_with_owner,
        is_inactive=u.is_inactive,
        is_repost_heavy=u.is_repost_heavy,
        is_one_sided_follow=u.is_one_sided_follow,
        is_follower_only=u.is_follower_only,
        muted=u.muted,
        blocked=u.blocked,
        last_analyzed_at=u.last_analyzed_at.isoformat() if u.last_analyzed_at else None,
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
    # Numeric range filters
    min_days_inactive: Optional[int] = Query(None, ge=0),
    min_repost_ratio: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_repost_ratio: Optional[float] = Query(None, ge=0.0, le=1.0),
    min_followers: Optional[int] = Query(None, ge=0),
    max_followers: Optional[int] = Query(None, ge=0),
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

    qs = build_query(
        owner_id=account.id,
        search=search,
        flags=flags or None,
        min_days_inactive=min_days_inactive,
        min_repost_ratio=min_repost_ratio,
        max_repost_ratio=max_repost_ratio,
        min_followers=min_followers,
        max_followers=max_followers,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )

    users = await qs
    total = await build_query(
        owner_id=account.id,
        search=search,
        flags=flags or None,
        min_days_inactive=min_days_inactive,
        min_repost_ratio=min_repost_ratio,
        max_repost_ratio=max_repost_ratio,
        min_followers=min_followers,
        max_followers=max_followers,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=99999,
        offset=0,
    ).count()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "users": [_serialize(u) for u in users],
    }
