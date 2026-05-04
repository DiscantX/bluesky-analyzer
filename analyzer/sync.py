"""
analyzer/sync.py
Orchestrates a full sync for one saved account:
  1. Fetch follows + followers
  2. Analyse each account's feed concurrently (rate-limit-safe)
  3. Upsert results into TrackedUser table
  4. Stream progress events via an async queue
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

from analyzer.client import BskyClient
from analyzer.fetch import fetch_all_follows, fetch_all_followers, fetch_feeds_concurrent, fetch_profiles_detailed
from analyzer.analyze import build_tracked_user_data
from db.models import AccountRelationship, SavedAccount, SyncRun, FollowEdge, Profile, GlobalSettings
from db.profile_store import upsert_profile_relationship
from analyzer.manager import bus
from analyzer.metrics import run_graph_analysis

logger = logging.getLogger(__name__)

FEED_SAMPLE_SIZE = 100         # app.bsky.feed.getAuthorFeed max page size
INACTIVE_DAYS = 90
REPOST_THRESHOLD = 0.70

# Staleness thresholds for differential syncing
# High-priority accounts refresh more frequently than low-priority stubs
STALENESS_THRESHOLDS = {
    2: timedelta(days=3),    # Tier 2 (full): refresh every 3 days
    1: timedelta(days=7),    # Tier 1 (standard): refresh every 7 days (default)
    0: timedelta(days=30),   # Tier 0 (stub): refresh every 30 days
}
# Accounts without a crawl_tier default to tier 1 staleness (7 days)
DEFAULT_STALENESS = STALENESS_THRESHOLDS[1]


# ── Progress event helpers ─────────────────────────────────────────────────────

def _evt(kind: str, **kwargs) -> dict:
    return {"kind": kind, "ts": datetime.now(timezone.utc).isoformat(), **kwargs}


async def _get_staleness_threshold(rel: AccountRelationship) -> timedelta:
    """
    Determine staleness threshold based on crawl_tier.
    High-priority accounts (tier 2) refresh more frequently.
    """
    return STALENESS_THRESHOLDS.get(rel.crawl_tier, DEFAULT_STALENESS)


async def _filter_stale_accounts(
    saved_account: SavedAccount,
    all_dids: list[str],
) -> tuple[list[str], list[str]]:
    """
    Partition DIDs into (needs_analysis, can_skip) based on staleness.
    
    An account can be skipped if:
    - last_analyzed_at is set AND
    - (now - last_analyzed_at) < staleness_threshold for its tier
    
    Returns: (dids_to_analyze, dids_to_skip)
    """
    now = datetime.now(timezone.utc)
    
    # Fetch existing relationships for all DIDs
    relationships = await AccountRelationship.filter(
        owner=saved_account,
        did__in=all_dids,
    ).prefetch_related("profile").all()
    
    rel_by_did = {rel.did: rel for rel in relationships}
    
    to_analyze = []
    skipped = 0
    
    for did in all_dids:
        rel = rel_by_did.get(did)
        
        # New accounts (not yet tracked) always need analysis
        if not rel:
            to_analyze.append(did)
            continue
        
        # Accounts with no analysis history always need analysis
        if not rel.profile or not rel.profile.last_analyzed_at:
            to_analyze.append(did)
            continue
        
        # Check staleness threshold
        threshold = await _get_staleness_threshold(rel)
        time_since_analysis = now - rel.profile.last_analyzed_at
        
        if time_since_analysis > threshold:
            # Stale — needs refresh
            to_analyze.append(did)
        else:
            # Fresh — can skip
            skipped += 1
    
    logger.info(
        f"Staleness filter: {len(to_analyze)} to analyze, {skipped} skipped "
        f"(threshold: tier2={STALENESS_THRESHOLDS[2].days}d, "
        f"tier1={STALENESS_THRESHOLDS[1].days}d, tier0={STALENESS_THRESHOLDS[0].days}d)"
    )
    
    return to_analyze, [d for d in all_dids if d not in to_analyze]



# ── Main sync entry point ──────────────────────────────────────────────────────

async def run_sync(
    saved_account: SavedAccount,
    client: BskyClient,
    alias: str,
) -> None:
    settings = await GlobalSettings.get(id=1)
    """
    Perform a full sync. Progress events are pushed to the broadcast bus
    so the SSE endpoint can stream them to the browser.
    """
    sync_run = await SyncRun.create(account=saved_account, status="running")

    async def emit(kind: str, **kwargs):
        await bus.emit(alias, _evt(kind, operation="sync", sync_run_id=sync_run.id, **kwargs))

    try:
        await emit("start", message="Starting sync…")

        # ── 1. Fetch my profile ────────────────────────────────────────────────
        my_profile = await client.get_profile(actor=saved_account.handle)
        owner_did = my_profile.did

        # Update DID in case it changed (it won't, but good hygiene)
        saved_account.did = owner_did
        await saved_account.save()

        # ── 2. Fetch follows + followers ───────────────────────────────────────
        await emit("phase", message="Fetching connections…")
        
        follows_task = fetch_all_follows(client, saved_account.handle)
        followers_task = fetch_all_followers(client, saved_account.handle)
        follows, followers = await asyncio.gather(follows_task, followers_task)

        for f in follows:
            await FollowEdge.get_or_create(follower_did=owner_did, followee_did=f.did)
        for f in followers:
            await FollowEdge.get_or_create(follower_did=f.did, followee_did=owner_did)

        sync_run.follows_fetched = len(follows)
        sync_run.followers_fetched = len(followers)
        await sync_run.save()

        follows_dids = {f.did for f in follows}
        followers_dids = {f.did for f in followers}

        # Build combined profile map — all unique accounts we care about
        profile_map: dict[str, object] = {}
        for p in follows:
            profile_map[p.did] = p
        for p in followers:
            if p.did not in profile_map:
                profile_map[p.did] = p

        all_dids = list(profile_map.keys())
        total = len(all_dids)

        # ── 2.5 Hydrate profiles with social counts ───────────────────────────
        await emit("phase", message=f"Hydrating {total} profiles…")
        detailed_profiles = await fetch_profiles_detailed(client, all_dids)
        logger.info(f"Hydrated {len(detailed_profiles)} out of {len(all_dids)} profiles.")
        
        for dp in detailed_profiles:
            profile_map[dp.did] = dp

        # ── 2.6 Filter stale accounts to avoid wasteful re-analysis ───────────
        # Skip accounts that were analyzed recently (within their tier's threshold)
        dids_to_analyze, dids_to_skip = await _filter_stale_accounts(saved_account, all_dids)
        
        if dids_to_skip:
            await emit(
                "phase",
                message=f"Skipping {len(dids_to_skip)} recently-analysed accounts…",
            )

        await emit(
            "phase",
            message=f"Analysing {len(dids_to_analyze)} accounts…",
            follows=len(follows),
            followers=len(followers),
            total=total,
            skipped=len(dids_to_skip),
        )

        # ── 3. Fetch feeds concurrently and upsert (only for stale accounts) ───
        completed = 0

        async for did, feed_items in fetch_feeds_concurrent(
            client,
            dids_to_analyze,
            limit_per_actor=settings.feed_sample_size,
        ):
            completed += 1
            profile = profile_map[did]

            data = build_tracked_user_data(
                profile=profile,
                feed_items=feed_items,
                owner_did=owner_did,
                i_follow_them=did in follows_dids,
                they_follow_me=did in followers_dids,
                inactive_days=settings.inactivity_threshold_days,
                repost_threshold=settings.repost_ratio_threshold,
            )
            data["last_analyzed_at"] = datetime.now(timezone.utc)

            await upsert_profile_relationship(saved_account, data)

            if completed % 10 == 0 or completed == len(dids_to_analyze):
                pct = int(completed / len(dids_to_analyze) * 100) if dids_to_analyze else 100
                await emit(
                    "progress",
                    completed=completed,
                    total=len(dids_to_analyze),
                    pct=pct,
                    message=f"Analysed {completed}/{len(dids_to_analyze)} accounts ({pct}%)",
                )

        # ── 4. Mark accounts no longer in follows/followers as stale ──────────
        # (don't delete — historical data is useful)
        await AccountRelationship.filter(
            owner=saved_account,
        ).exclude(did__in=list(all_dids)).update(
            i_follow_them=False,
            they_follow_me=False,
        )

        # ── 5. Run Graph Analysis ──────────────────────────────────────────────
        await emit("phase", message="Computing network metrics (FlowRank/Communities)…")
        try:
            await run_graph_analysis(saved_account)
        except Exception as e:
            logger.exception(f"Graph analysis failed after sync for {saved_account.handle}: {e}")
            await emit("phase", message="Sync complete; graph metrics will retry later.")

        # ── 5. Finalise ────────────────────────────────────────────────────────
        saved_account.last_synced_at = datetime.now(timezone.utc)
        await saved_account.save()

        sync_run.status = "done"
        sync_run.finished_at = datetime.now(timezone.utc)
        await sync_run.save()

        await emit("done", message="Sync complete!", total=total)

    except Exception as e:
        logger.exception(f"Sync failed for {saved_account.handle}: {e}")
        sync_run.status = "error"
        sync_run.error_message = str(e)
        sync_run.finished_at = datetime.now(timezone.utc)
        await sync_run.save()
        await emit("error", message=str(e))
