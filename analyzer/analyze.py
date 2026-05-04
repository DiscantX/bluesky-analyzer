"""
analyzer/analyze.py
Compute per-account statistics from raw atproto feed data.
Pure functions — no I/O, no DB access. Easy to unit test.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional


# ── Configuration defaults (overridden by settings in main.py) ─────────────────
INACTIVE_DAYS_DEFAULT = 90
REPOST_RATIO_THRESHOLD_DEFAULT = 0.70


def parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime from an atproto string or datetime object."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def analyze_feed(
    feed_items: list,
    owner_did: str,
) -> dict[str, Any]:
    """
    Analyse a list of atproto feed items for one account.

    Returns a dict with:
      last_post_at        — datetime of most recent activity (or None)
      repost_count        — reposts in the sample
      original_post_count — original posts in the sample
      repost_ratio        — float 0–1
      interacted_with_owner — bool: did any post reply to/mention owner_did?
    """
    last_post_at: Optional[datetime] = None
    repost_count = 0
    original_count = 0
    interacted = False

    for item in feed_items:
        post = getattr(item, "post", None)
        if post is None:
            continue

        # ── Determine if this is a repost ────────────────────────────────────
        reason = getattr(item, "reason", None)
        reason_type = getattr(reason, "py_type", "") if reason else ""
        is_repost = "reasonRepost" in reason_type

        # ── Track latest activity ────────────────────────────────────────────
        indexed = getattr(post, "indexed_at", None)
        dt = parse_dt(indexed)
        if dt and (last_post_at is None or dt > last_post_at):
            last_post_at = dt

        if is_repost:
            repost_count += 1
        else:
            original_count += 1
            # ── Check if this post interacted with the owner ─────────────────
            record = getattr(post, "record", None)
            if record and not interacted:
                # Reply to owner's post
                reply = getattr(record, "reply", None)
                if reply:
                    parent = getattr(reply, "parent", None)
                    if parent and owner_did in (getattr(parent, "uri", "") or ""):
                        interacted = True

                # Mention of owner in facets
                facets = getattr(record, "facets", None) or []
                for facet in facets:
                    features = getattr(facet, "features", None) or []
                    for feat in features:
                        if getattr(feat, "did", None) == owner_did:
                            interacted = True

    total = repost_count + original_count
    repost_ratio = repost_count / total if total > 0 else 0.0

    return {
        "last_post_at": last_post_at,
        "repost_count": repost_count,
        "original_post_count": original_count,
        "sampled_post_count": total,
        "repost_ratio": round(repost_ratio, 4),
        "interacted_with_owner": interacted,
    }


def compute_flags(
    feed_stats: dict[str, Any],
    i_follow_them: bool,
    they_follow_me: bool,
    inactive_days: int = INACTIVE_DAYS_DEFAULT,
    repost_threshold: float = REPOST_RATIO_THRESHOLD_DEFAULT,
) -> dict[str, Any]:
    """
    Derive boolean flag fields from feed stats and relationship info.
    These are stored denormalised for fast DB filtering.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=inactive_days)

    last_post_at = feed_stats.get("last_post_at")
    days_since_post: Optional[int] = None

    if last_post_at is None:
        is_inactive = True
    else:
        days_since_post = (now - last_post_at).days
        is_inactive = last_post_at < cutoff

    repost_ratio = feed_stats.get("repost_ratio", 0.0)
    sampled = feed_stats.get("sampled_post_count", 0)
    is_repost_heavy = sampled > 0 and repost_ratio >= repost_threshold

    return {
        "days_since_post": days_since_post,
        "is_inactive": is_inactive,
        "is_repost_heavy": is_repost_heavy,
        "is_one_sided_follow": i_follow_them and not they_follow_me,
        "is_follower_only": they_follow_me and not i_follow_them,
    }


def build_tracked_user_data(
    profile,
    feed_items: list,
    owner_did: str,
    i_follow_them: bool,
    they_follow_me: bool,
    inactive_days: int = INACTIVE_DAYS_DEFAULT,
    repost_threshold: float = REPOST_RATIO_THRESHOLD_DEFAULT,
) -> dict[str, Any]:
    """
    Combine a profile object and feed items into a flat dict ready for
    upserting into the TrackedUser table.
    """
    def _get(obj, *keys):
        """Helper to check multiple possible attribute/key names for atproto models."""
        for k in keys:
            val = getattr(obj, k, None)
            if val is not None:
                return val
        return 0

    feed_stats = analyze_feed(feed_items, owner_did)
    flags = compute_flags(
        feed_stats, i_follow_them, they_follow_me, inactive_days, repost_threshold
    )

    return {
        "did": profile.did,
        "handle": profile.handle,
        "display_name": getattr(profile, "display_name", None) or "",
        "avatar_url": getattr(profile, "avatar", None) or "",
        "profile_url": f"https://bsky.app/profile/{profile.handle}",
        "followers_count": _get(profile, "followers_count", "followersCount"),
        "follows_count": _get(profile, "follows_count", "followsCount"),
        "posts_count": _get(profile, "posts_count", "postsCount"),
        "i_follow_them": i_follow_them,
        "they_follow_me": they_follow_me,
        "crawl_tier": 1,
        # Feed stats
        "last_post_at": feed_stats["last_post_at"],
        "repost_count": feed_stats["repost_count"],
        "original_post_count": feed_stats["original_post_count"],
        "sampled_post_count": feed_stats["sampled_post_count"],
        "repost_ratio": feed_stats["repost_ratio"],
        "interacted_with_owner": feed_stats["interacted_with_owner"],
        # Flags
        **flags,
    }
