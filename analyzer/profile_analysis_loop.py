"""
analyzer/profile_analysis_loop.py

A dedicated, persistent background task that continuously analyzes profiles
in priority order while other operations (sync, crawl) run alongside it.

Design:
- Runs as a long-lived asyncio.Task, never exits unless cancelled
- Pulls batches of the highest-priority un-analyzed / stale profiles
- Sleeps briefly between batches to stay cooperative with crawl/sync
- Respects the same GlobalSettings concurrency limits as other workers
- Emits progress to the bus so the UI can display activity
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from tortoise.expressions import Q

import config
from analyzer.analyze import build_tracked_user_data
from analyzer.client import BskyClient
from analyzer.fetch import fetch_feeds_concurrent
from analyzer.manager import bus, global_found_tracker, global_req_tracker, running_tasks, task_key
from db.models import AccountRelationship, SavedAccount, Profile
from settings_cache import settings_cache
from db.profile_store import upsert_profile_relationship

logger = logging.getLogger(__name__)

# How stale a profile must be before it's re-queued for analysis
ANALYSIS_STALENESS = timedelta(days=7)

# How many profiles to pull per batch
BATCH_SIZE = 100

# Cooperative sleep between batches (seconds) — keeps the event loop free for
# crawl/sync tasks without starving the analysis loop
INTER_BATCH_SLEEP = 2.0

# Sleep when there is genuinely nothing to do (seconds)
IDLE_SLEEP = 60.0

# Priority order for selecting which profiles to analyze next.
# Higher crawl_tier and higher in_subgraph_degree = more interesting.
PRIORITY_ORDER = ["-crawl_tier", "-in_subgraph_degree", "profile__last_analyzed_at"]


async def _select_batch(owner: SavedAccount) -> list[AccountRelationship]:
    """
    Select the next batch of profiles that need analysis, ordered by priority.
    """
    staleness_days = settings_cache.get("profile_analysis_staleness_days", 7)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=staleness_days)
    batch_size = settings_cache.get("profile_analysis_batch_size", 30)

    return await (
        AccountRelationship.filter(owner=owner)
        .exclude(did=owner.did)
        .filter(
            # Only profiles that have been hydrated (we need handle/counts)
            profile__last_hydrated_at__isnull=False,
        )
        .filter(
            Q(profile__last_analyzed_at__isnull=True)
            | Q(profile__last_analyzed_at__lt=stale_cutoff)
        )
        .order_by(*PRIORITY_ORDER)
        .limit(batch_size)
        .prefetch_related("profile")
    )


async def _analyze_batch(
    owner: SavedAccount,
    batch: list[AccountRelationship],
    client: BskyClient,
) -> int:
    """Fetch feeds and upsert analysis results for a batch. Returns count analyzed."""
    dids = [rel.did for rel in batch]
    rel_by_did = {rel.did: rel for rel in batch}

    completed = 0
    now = datetime.now(timezone.utc)
    updated_profiles = []

    async for did, feed_items in fetch_feeds_concurrent(
        client,
        dids,
        limit_per_actor=settings_cache.get("feed_sample_size", 100),
    ):
        rel = rel_by_did.get(did)
        if not rel:
            continue

        profile_obj = await rel.profile
        data = build_tracked_user_data(
            profile=profile_obj,
            feed_items=feed_items,
            owner_did=owner.did,
            i_follow_them=rel.i_follow_them,
            they_follow_me=rel.they_follow_me,
            inactive_days=settings_cache.get("inactivity_threshold_days", 90),
            repost_threshold=settings_cache.get("repost_ratio_threshold", 0.7),
        )
        
        for key, value in data.items():
            if hasattr(profile_obj, key):
                setattr(profile_obj, key, value)
        profile_obj.last_analyzed_at = now
        updated_profiles.append(profile_obj)
        completed += 1

    if updated_profiles:
        await Profile.bulk_update(updated_profiles, fields=[
            "last_post_at", "repost_count", "original_post_count", "sampled_post_count",
            "repost_ratio", "is_inactive", "is_repost_heavy", "top_keywords", 
            "last_analyzed_at", "days_since_post"
        ])

    return completed


async def run_profile_analysis_loop(owner: SavedAccount) -> None:
    """
    Persistent loop: select → analyze → sleep → repeat.

    This task never returns unless cancelled. It is started once per account
    on app startup and kept alive by the background worker.
    """
    alias = owner.alias
    logger.info(f"[profile-analysis-loop] Starting for {alias}")

    client: BskyClient | None = None

    async def _ensure_client() -> BskyClient | None:
        """Lazily initialise (or re-login) the atproto client."""
        nonlocal client
        try:
            password = config.get_password(alias)
            if not password:
                logger.warning(f"[profile-analysis-loop] No password for {alias}, skipping.")
                return None
            if client is None:
                client = BskyClient(alias=alias)
                await client.login(owner.handle, password)
            return client
        except Exception as e:
            logger.error(f"[profile-analysis-loop] Login failed for {alias}: {e}")
            client = None
            return None

    while True:
        try:
            c = await _ensure_client()
            idle_sleep = settings_cache.get("profile_analysis_idle_sleep_seconds", IDLE_SLEEP)

            if c is None:
                await asyncio.sleep(idle_sleep)
                continue

            batch = await _select_batch(owner)

            if not batch:
                logger.debug(f"[profile-analysis-loop] Nothing to analyze for {alias}, sleeping {idle_sleep}s")
                await bus.emit(alias, {
                    "kind": "progress",
                    "operation": "profile_analysis_loop",
                    "message": "Profile analysis: queue empty, sleeping.",
                    "is_heartbeat": True,
                })
                await asyncio.sleep(idle_sleep)
                continue

            logger.info(f"[profile-analysis-loop] Analyzing batch of {len(batch)} for {alias}")

            count = await _analyze_batch(owner, batch, c)

            await bus.emit(alias, {
                "kind": "progress",
                "operation": "profile_analysis_loop",
                "message": f"Profile analysis: {count} profiles updated.",
                "is_heartbeat": True,
            })

            logger.info(f"[profile-analysis-loop] Batch done: {count}/{len(batch)} analyzed for {alias}")

        except asyncio.CancelledError:
            logger.info(f"[profile-analysis-loop] Cancelled for {alias}")
            raise
        except Exception as e:
            logger.exception(f"[profile-analysis-loop] Error for {alias}: {e}")
            # Don't die on transient errors — sleep and retry
            await asyncio.sleep(settings_cache.get("profile_analysis_idle_sleep_seconds", IDLE_SLEEP))
            continue

        # Cooperative yield between batches
        await asyncio.sleep(settings_cache.get("profile_analysis_inter_batch_sleep_seconds", INTER_BATCH_SLEEP))


def start_profile_analysis_loop(account: SavedAccount) -> bool:
    """
    Start the persistent analysis loop for an account unless already running.
    Returns True if a new task was started.
    """
    key = task_key(account.alias, "profile_analysis_loop")
    existing = running_tasks.get(key)
    if existing and not existing.done():
        return False  # Already running

    async def _wrapper():
        try:
            await run_profile_analysis_loop(account)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(key, None)

    running_tasks[key] = asyncio.create_task(_wrapper())
    logger.info(f"[profile-analysis-loop] Task started for {account.alias}")
    return True