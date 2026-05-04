from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.models import AccountRelationship, Profile, SavedAccount


PROFILE_FIELDS = {
    "did",
    "handle",
    "display_name",
    "avatar_url",
    "profile_url",
    "followers_count",
    "follows_count",
    "posts_count",
    "last_post_at",
    "days_since_post",
    "sampled_post_count",
    "repost_count",
    "original_post_count",
    "repost_ratio",
    "is_inactive",
    "is_repost_heavy",
    "last_analyzed_at",
}

RELATIONSHIP_FIELDS = {
    "i_follow_them",
    "they_follow_me",
    "interacted_with_owner",
    "is_one_sided_follow",
    "is_follower_only",
    "muted",
    "blocked",
    "crawl_tier",
    "crawl_priority",
    "last_crawled_at",
    "crawl_pending_fields",
    "discovered_via",
    "flowrank_score",
    "clustering_coefficient",
    "in_subgraph_degree",
    "community_id",
}


async def upsert_profile(data: dict[str, Any]) -> Profile:
    profile_data = {k: v for k, v in data.items() if k in PROFILE_FIELDS and k != "did"}
    if profile_data:
        profile_data.setdefault("last_hydrated_at", datetime.now(timezone.utc))
    profile, _ = await Profile.update_or_create(
        defaults=profile_data,
        did=data["did"],
    )
    return profile


async def upsert_relationship(
    owner: SavedAccount,
    profile: Profile,
    data: dict[str, Any],
) -> AccountRelationship:
    rel_data = {k: v for k, v in data.items() if k in RELATIONSHIP_FIELDS}
    rel_data["did"] = profile.did

    existing = await AccountRelationship.get_or_none(owner=owner, profile=profile)
    if existing:
        # Promotion logic: Never demote a crawl tier (e.g. from Standard back to Stub)
        new_tier = rel_data.get("crawl_tier")
        if new_tier is not None:
            rel_data["crawl_tier"] = max(existing.crawl_tier, new_tier)
        
        # Update existing record
        existing.update_from_dict(rel_data)
        await existing.save()
        return existing

    rel = await AccountRelationship.create(owner=owner, profile=profile, **rel_data)
    return rel


async def upsert_profile_relationship(
    owner: SavedAccount,
    data: dict[str, Any],
) -> tuple[Profile, AccountRelationship]:
    profile = await upsert_profile(data)
    relationship = await upsert_relationship(owner, profile, data)
    return profile, relationship
