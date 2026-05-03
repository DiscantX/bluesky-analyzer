"""
db/queries.py
Reusable query helpers. All filtering/sorting for the UI goes through here
so adding a new filter later is a one-line change.
"""

from __future__ import annotations

from typing import Any
from tortoise.queryset import QuerySet

from db.models import TrackedUser


# ── Field whitelist ────────────────────────────────────────────────────────────
# Any column in TrackedUser that the UI is allowed to sort by.
SORTABLE_FIELDS = {
    "handle",
    "display_name",
    "followers_count",
    "follows_count",
    "posts_count",
    "days_since_post",
    "repost_ratio",
    "last_post_at",
    "last_analyzed_at",
    "is_inactive",
    "is_repost_heavy",
    "is_one_sided_follow",
    "is_follower_only",
    "interacted_with_owner",
}

# Any column the UI is allowed to filter on (boolean flags + numeric ranges).
FILTERABLE_FLAGS = {
    "i_follow_them",
    "they_follow_me",
    "is_inactive",
    "is_repost_heavy",
    "is_one_sided_follow",
    "is_follower_only",
    "interacted_with_owner",
    "muted",
    "blocked",
}


def build_query(
    owner_id: int,
    *,
    search: str | None = None,
    flags: dict[str, bool] | None = None,
    min_days_inactive: int | None = None,
    min_repost_ratio: float | None = None,
    max_repost_ratio: float | None = None,
    min_followers: int | None = None,
    max_followers: int | None = None,
    sort_by: str = "handle",
    sort_dir: str = "asc",
    limit: int = 200,
    offset: int = 0,
) -> QuerySet[TrackedUser]:
    """
    Build a filtered + sorted queryset for tracked users belonging to owner_id.
    All parameters are optional — omitting them returns the full list.
    """
    qs = TrackedUser.filter(owner_id=owner_id)

    # ── Text search ───────────────────────────────────────────────────────────
    if search:
        qs = qs.filter(handle__icontains=search) | TrackedUser.filter(
            owner_id=owner_id, display_name__icontains=search
        )

    # ── Boolean flag filters ──────────────────────────────────────────────────
    if flags:
        for field, value in flags.items():
            if field in FILTERABLE_FLAGS:
                qs = qs.filter(**{field: value})

    # ── Numeric range filters ─────────────────────────────────────────────────
    if min_days_inactive is not None:
        qs = qs.filter(days_since_post__gte=min_days_inactive)
    if min_repost_ratio is not None:
        qs = qs.filter(repost_ratio__gte=min_repost_ratio)
    if max_repost_ratio is not None:
        qs = qs.filter(repost_ratio__lte=max_repost_ratio)
    if min_followers is not None:
        qs = qs.filter(followers_count__gte=min_followers)
    if max_followers is not None:
        qs = qs.filter(followers_count__lte=max_followers)

    # ── Sorting ───────────────────────────────────────────────────────────────
    if sort_by not in SORTABLE_FIELDS:
        sort_by = "handle"
    order = f"-{sort_by}" if sort_dir == "desc" else sort_by
    qs = qs.order_by(order)

    # ── Pagination ────────────────────────────────────────────────────────────
    qs = qs.offset(offset).limit(limit)

    return qs


async def get_stats(owner_id: int) -> dict[str, Any]:
    """Return summary counts for the dashboard header."""
    base = TrackedUser.filter(owner_id=owner_id)
    return {
        "total_follows": await base.filter(i_follow_them=True).count(),
        "total_followers": await base.filter(they_follow_me=True).count(),
        "inactive": await base.filter(is_inactive=True, i_follow_them=True).count(),
        "repost_heavy": await base.filter(is_repost_heavy=True, i_follow_them=True).count(),
        "one_sided": await base.filter(is_one_sided_follow=True).count(),
        "follower_only": await base.filter(is_follower_only=True).count(),
        "no_interaction": await base.filter(
            interacted_with_owner=False, i_follow_them=True
        ).count(),
    }
