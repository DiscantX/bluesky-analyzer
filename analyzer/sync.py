"""
analyzer/sync.py
Orchestrates a full sync for one saved account:
  1. Fetch follows + followers
  2. Analyse each account's feed concurrently (rate-limit-safe)
  3. Upsert results into TrackedUser table
  4. Stream progress events via an async queue

OPTIMIZATIONS APPLIED:
  - Fix 1: Batch FollowEdge creation via bulk_create (was N*2 get_or_create calls)
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
from analyzer.manager import bus, current_alias_var, current_op_var
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
    settings = await GlobalSettings.get(id=1)

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

        # Override staleness if ignore_staleness_threshold_days is set and exceeded
        if settings.ignore_staleness_threshold_days > 0 and \
           time_since_analysis.days >= settings.ignore_staleness_threshold_days:
            to_analyze.append(did)
            continue

        if time_since_analysis > threshold:
            # Stale — needs refresh
            to_analyze.append(did)
        else:
            # Fresh — can skip
            skipped += 1

    logger.info(
        f"Staleness filter: {len(to_analyze)} to analyze, {skipped} skipped "
        f"(threshold: tier2={STALENESS_THRESHOLDS[2].days}d, "
        f"tier1={STALENESS_THRESHOLDS[1].days}d, tier0={STALENESS_THRESHOLDS[0].days}d"
        f"{f', force_reanalyze_after={settings.ignore_staleness_threshold_days}d' if settings.ignore_staleness_threshold_days > 0 else ''})"
    )

    return to_analyze, [d for d in all_dids if d not in to_analyze]


async def _bulk_upsert_follow_edges(owner_did: str, follows: list, followers: list) -> None:
    """
    FIX 1: Replace N*2 get_or_create calls with two bulk_create operations.

    Before: for f in follows: await FollowEdge.get_or_create(...)  →  O(2N) queries
    After:  bulk_create with ignore_conflicts=True               →  O(2) queries

    Estimated improvement: 50-70% reduction in sync database time.
    """
    # Collect existing edges in one query to avoid duplicates
    follow_dids = [f.did for f in follows]
    follower_dids = [f.did for f in followers]
    all_relevant_dids = list(set(follow_dids + follower_dids))

    # Fetch existing outgoing edges (owner → followee) in one shot
    existing_out = set(
        await FollowEdge.filter(
            follower_did=owner_did,
            followee_did__in=follow_dids,
        ).values_list("followee_did", flat=True)
    ) if follow_dids else set()

    # Fetch existing incoming edges (follower → owner) in one shot
    existing_in = set(
        await FollowEdge.filter(
            follower_did__in=follower_dids,
            followee_did=owner_did,
        ).values_list("follower_did", flat=True)
    ) if follower_dids else set()

    new_follow_edges = [
        FollowEdge(follower_did=owner_did, followee_did=f.did)
        for f in follows
        if f.did not in existing_out
    ]
    new_follower_edges = [
        FollowEdge(follower_did=f.did, followee_did=owner_did)
        for f in followers
        if f.did not in existing_in
    ]

    if new_follow_edges:
        await FollowEdge.bulk_create(new_follow_edges, ignore_conflicts=True)
    if new_follower_edges:
        await FollowEdge.bulk_create(new_follower_edges, ignore_conflicts=True)

    logger.info(
        f"FollowEdge bulk upsert: {len(new_follow_edges)} new outgoing, "
        f"{len(new_follower_edges)} new incoming edges created."
    )


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
    current_alias_var.set(alias)
    current_op_var.set("sync")

    sync_run = await SyncRun.create(account=saved_account, status="running")

    session_start = datetime.now(timezone.utc)
    start_reqs = client.request_count

    async def emit(kind: str, **kwargs):
        from analyzer.manager import global_req_tracker
        reqs_done = client.request_count - start_reqs
        sync_run.request_count = reqs_done

        req_rate = global_req_tracker.get_rate()
        await bus.emit(alias, _evt(kind, operation="sync", sync_run_id=sync_run.id, req_rate=req_rate, req_count=reqs_done, **kwargs))

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

        # FIX 1: Use bulk edge creation instead of N get_or_create calls
        await _bulk_upsert_follow_edges(owner_did, follows, followers)

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
        # Add owner to the analysis pool so the user's own stats are calculated
        if owner_did not in all_dids:
            all_dids.append(owner_did)
            profile_map[owner_did] = my_profile

        total = len(all_dids)

        # ── 2.5 Hydrate profiles with social counts ───────────────────────────
        BATCH_SIZE_HYDRATE = 25
        for i in range(0, total, BATCH_SIZE_HYDRATE):
            batch = all_dids[i : i + BATCH_SIZE_HYDRATE]
            detailed_batch = await fetch_profiles_detailed(client, batch)
            for dp in detailed_batch:
                profile_map[dp.did] = dp

            current = min(i + BATCH_SIZE_HYDRATE, total)
            pct = int(current / total * 100)

            handle = detailed_batch[0].handle if detailed_batch else "..."
            await emit("progress", message=f"Hydrating: @{handle} ({current}/{total})…", pct=pct)

        # ── 2.5.1 Fast pass: Update relationship status and promote stubs ─────
        # We do this before analysis so the UI reflects the new graph immediately.
        await emit("phase", message="Updating relationship status…")

        BATCH_SIZE = 50
        for i in range(0, len(all_dids), BATCH_SIZE):
            batch = all_dids[i : i + BATCH_SIZE]
            tasks = []
            for did in batch:
                p = profile_map[did]
                is_self = did == owner_did
                i_follow = did in follows_dids if not is_self else False
                they_follow = did in followers_dids if not is_self else False
                tasks.append(upsert_profile_relationship(saved_account, {
                    "did": did,
                    "handle": getattr(p, 'handle', saved_account.handle),
                    "i_follow_them": i_follow,
                    "they_follow_me": they_follow,
                    "crawl_tier": 2 if is_self else 1,  # Owner is Tier 2 (High Priority)
                    "is_one_sided_follow": i_follow and not they_follow,
                    "is_follower_only": they_follow and not i_follow,
                }))
            await asyncio.gather(*tasks)
            if i % 250 == 0:
                pct = int(min(i + BATCH_SIZE, total) / total * 100)
                await emit("progress", message=f"Updating relationships ({i}/{total})…", pct=pct)

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