r"""
analyzer/crawl.py
Implements the priority-based graph crawler for network expansion.

OPTIMIZATIONS APPLIED:
  - Fix 2: Hydration semaphore increased from 2 → 5 (2-5x hydration speedup) [cite: `c:\Users\Admin\Documents\Dylan\APE\bluesky-analyzer\analyzer\.ignore\BOTTLENECK_ANALYSIS.md`]
  - Fix 4: Batch degree recalculation (was N queries per user, now 2 queries per batch) [cite: `c:\Users\Admin\Documents\Dylan\APE\bluesky-analyzer\analyzer\.ignore\BOTTLENECK_ANALYSIS.md`]
  - Fix 6: Parallel follows/followers fetch (concurrent instead of sequential) [cite: `c:\Users\Admin\Documents\Dylan\APE\bluesky-analyzer\analyzer\.ignore\BOTTLENECK_ANALYSIS.md`]
"""

import math
import logging
import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx
from typing import Optional, List
from tortoise.expressions import Q
from db.models import AccountRelationship, FollowEdge, Profile, SavedAccount, CrawlRun, CrawlQueueItem
from db.profile_store import upsert_profile_relationship
from analyzer.fetch import public_fetch_graph, public_fetch_profiles, BskyClient
from analyzer.analyze import parse_dt
from analyzer.metrics import run_graph_analysis
import config
from settings_cache import settings_cache

logger = logging.getLogger(__name__)

def _now() -> datetime:
    return datetime.now(timezone.utc)


class CrawlBudgetExceeded(Exception):
    """Custom exception for when the crawl budget is exceeded."""
    pass

def _get_db_size_mb() -> float:
    if config.DB_PATH.exists():
        return config.DB_PATH.stat().st_size / (1024 * 1024)
    return 0.0

def _is_user_expandable(user: AccountRelationship) -> bool:
    if user.crawl_tier > 0:
        return True
    if user.i_follow_them or user.they_follow_me:
        return True
    return user.in_subgraph_degree >= settings_cache.get("min_connection_threshold", 3)


async def reset_interrupted_crawl_work(owner: SavedAccount) -> None:
    """Return orphaned in-flight queue items to pending after a process restart."""
    await CrawlQueueItem.filter(account=owner, status="running").update(
        status="pending",
        locked_at=None,
    )


def _profile_value(profile: dict, snake_name: str, camel_name: str, default=0):
    value = profile.get(snake_name, profile.get(camel_name, default))
    return default if value is None else value

async def calculate_priority(user: AccountRelationship) -> float:
    """
    Computes crawl priority based on the roadmap formula:
    priority = (relationship_weight × 1000)
             + (mutual_follow_bonus × 500)
             + (log10(followers_count + 1) / 7 × 200)
             + (in_subgraph_degree × 100)
             - (days_since_last_crawled × 10)
    """
    # relationship_weight: 3 (owner follows), 2 (follows owner), 1 (graph discovery)
    rel_weight = 1
    if user.i_follow_them:
        rel_weight = 3
    elif user.they_follow_me:
        rel_weight = 2

    mutual_bonus = 1 if (user.i_follow_them and user.they_follow_me) else 0

    # Reach score (normalized log10 of followers, assuming max ~10M followers)
    profile = getattr(user, "_profile_cache", None) or await user.profile
    reach_score = (math.log10(profile.followers_count + 1) / 7.0) * 200

    # Recency penalty
    days_stale = 0
    if user.last_crawled_at:
        days_stale = (datetime.now(timezone.utc) - user.last_crawled_at).days

    priority = (rel_weight * 1000) + (mutual_bonus * 500) + reach_score + \
               (user.in_subgraph_degree * 100) - (days_stale * 10)
    return priority


async def _batch_update_degrees(
    owner: SavedAccount,
    page_dids: list[str],
    tracked_dids: set[str],
) -> None:
    """
    FIX 4: Replace per-user degree recalculation (N queries each) with a
    batched approach using 2 queries total for the entire page.

    Before: for each DID → query FollowEdge (N queries) → save (N queries)
    After:  1 query for all edges in batch → group in Python → bulk_update

    Estimated improvement: 60-80% per-batch speedup.
    """
    if not page_dids:
        return

    # 1. Fetch all users in this batch in one query
    batch_users = await AccountRelationship.filter(
        owner=owner,
        did__in=page_dids,
    ).prefetch_related("profile").all()

    if not batch_users:
        return

    # 2. Fetch ALL incoming edges for the entire batch in one query
    all_incoming_edges = await FollowEdge.filter(
        followee_did__in=page_dids
    ).values_list("follower_did", "followee_did")

    # 3. Group edges by followee in Python (O(E) — fast)
    edges_by_followee: dict[str, set[str]] = {}
    for follower_did, followee_did in all_incoming_edges:
        if followee_did not in edges_by_followee:
            edges_by_followee[followee_did] = set()
        edges_by_followee[followee_did].add(follower_did)

    # 4. Compute degree and priority for each user, collect updates
    for user in batch_users:
        incoming_for_user = edges_by_followee.get(user.did, set())
        user.in_subgraph_degree = len(incoming_for_user.intersection(tracked_dids))
        user.crawl_priority = await calculate_priority(user)

    # 5. Bulk update instead of individual saves
    if batch_users:
        await AccountRelationship.bulk_update(
            batch_users,
            fields=["in_subgraph_degree", "crawl_priority"],
        )

    logger.debug(
        f"Batch degree update: {len(batch_users)} users updated "
        f"across {len(page_dids)} DIDs in 2 queries."
    )


async def crawl_step(owner: SavedAccount, batch_size: int = 10, on_progress=None):
    """
    Performs one crawl iteration:
    1. Select top N priority accounts.
    2. Fetch their follows using the public AppView.
    3. Save new edges and create stubs.
    4. Update priorities for affected accounts.
    """
    await CrawlRun.filter(account=owner, status="running", finished_at__isnull=True).update(
        status="paused",
        last_message="Interrupted while server was offline.",
    )

    crawl_run = await CrawlRun.create(
        account=owner,
        status="running",
        batch_size=batch_size,
        last_message="Seeding crawl queue...",
    )
    from analyzer.manager import current_alias_var, current_op_var
    current_alias_var.set(owner.alias)
    current_op_var.set("crawl")

    await reset_interrupted_crawl_work(owner)

    session_start = datetime.now(timezone.utc)
    session_reqs = 0
    session_found = 0

    async def emit(message: str, pct: int | None = None, req_inc: int = 0):
        nonlocal session_reqs, session_found
        crawl_run.last_message = message

        session_reqs += req_inc
        crawl_run.request_count = session_reqs
        crawl_run.discovered_count = session_found

        from analyzer.manager import global_req_tracker, global_found_tracker
        req_rate = global_req_tracker.get_rate()
        found_rate = global_found_tracker.get_rate()

        # Fetch overall account stats for the UI
        from db.queries import get_stats
        account_stats = await get_stats(owner.id)

        # Pass all relevant crawl_run stats to the emit function
        crawl_stats = {
            "candidates_queued": crawl_run.candidates_queued,
            "candidates_completed": crawl_run.candidates_completed,
            "candidates_failed": crawl_run.candidates_failed,
            "candidates_skipped": crawl_run.candidates_skipped,
            "discovered_count": crawl_run.discovered_count,
            "request_count": crawl_run.request_count,
            "last_message": crawl_run.last_message,
            "batch_size": crawl_run.batch_size,
            "status": crawl_run.status,
        }

        if on_progress:
            try:
                await on_progress(message, pct, req_rate=req_rate, found_rate=found_rate, crawl_stats=crawl_stats, account_stats=account_stats)
            except TypeError:
                await on_progress(message, pct)

    await emit("Seeding crawl queue...")
    seeded = await seed_crawl_queue(owner, on_progress=emit)
    crawl_run.candidates_queued = await CrawlQueueItem.filter(
        account=owner,
        status="pending",
    ).count()
    await crawl_run.save(update_fields=["candidates_queued"])

    if seeded:
        logger.info(f"Seeded {seeded} crawl queue items for {owner.alias}")

    # Check budget at the start of processing candidates
    current_db_size_mb = _get_db_size_mb()
    crawl_budget_mb = settings_cache.get("crawl_budget_mb", 1024)
    if current_db_size_mb >= crawl_budget_mb:
        crawl_run.status = "paused"
        crawl_run.last_message = f"Crawl paused: Database size ({current_db_size_mb:.1f} MB) exceeds budget ({crawl_budget_mb} MB)."
        crawl_run.error_message = crawl_run.last_message
        crawl_run.finished_at = _now()
        await crawl_run.save(update_fields=["status", "last_message", "error_message", "finished_at"])
        await emit(crawl_run.last_message, 100)
        logger.warning(crawl_run.last_message)
        return

    # --- Turbo Mode Orchestration ---
    from analyzer.manager import is_turbo_active
    turbo_active = is_turbo_active()

    # Load concurrency limits based on power state
    crawl_limit = settings_cache.get("turbo_concurrency" if turbo_active else "crawl_concurrency", 3)
    hydrate_limit = settings_cache.get("turbo_concurrency" if turbo_active else "crawl_hydration_concurrency", 5)

    if settings_cache.get("disable_internal_rate_limits", False):
        crawl_limit = 100
        hydrate_limit = 100
    
    crawl_semaphore = asyncio.Semaphore(crawl_limit)
    hydration_semaphore = asyncio.Semaphore(hydrate_limit)

    candidates = await claim_crawl_items(owner, batch_size)

    if not candidates:
        logger.info(f"No candidates found for crawl for account {owner.alias}")
        crawl_run.status = "done"
        crawl_run.finished_at = _now()
        await crawl_run.save(update_fields=["status", "finished_at"])
        await emit("No crawl candidates are ready.", 100)
        return

    # Cache tracked DIDs for local subgraph degree calculations
    tracked_dids = set(await AccountRelationship.filter(owner=owner).values_list("did", flat=True))

    # Pre-fetch tiers to avoid redundant Tier 1 -> Tier 0 demotion attempts
    owner_relationships = await AccountRelationship.filter(owner=owner).all()
    rel_tier_by_did = {rel.did: rel.crawl_tier for rel in owner_relationships}

    # Initialize Authenticated Turbo client if needed
    auth_client: Optional[BskyClient] = None
    if turbo_active:
        try:
            password = config.get_password(owner.alias)
            if password:
                # Boost the client semaphore to match the turbo concurrency setting
                auth_client = BskyClient(alias=owner.alias, concurrency=crawl_limit)
                await auth_client.login(owner.handle, password)
            logger.info(f"Turbo Mode Active for {owner.alias}: Using authenticated API budget.")
        except Exception as e:
            logger.warning(f"Failed to initialize Turbo client for {owner.alias}: {e}. Falling back to public.")

    async def process_candidate(item: CrawlQueueItem, public_client: httpx.AsyncClient, auth_client_shared: Optional[BskyClient] = None):
        async with crawl_semaphore:
            user = await AccountRelationship.filter(owner=owner, did=item.did).prefetch_related("profile").first()
            if not user:
                item.status = "skipped"
                item.completed_at = datetime.now(timezone.utc)
                item.last_error = "Tracked user no longer exists."
                await item.save(update_fields=["status", "completed_at", "last_error"])
                crawl_run.candidates_skipped += 1
                await asyncio.sleep(0.001) # Yield to event loop
                await crawl_run.save(update_fields=["candidates_skipped"])
                return

            # Enforcement of connection threshold for stubs
            if user.crawl_tier == 0 and user.in_subgraph_degree < settings_cache.get("min_connection_threshold", 3):
                if not (user.i_follow_them or user.they_follow_me):
                    skipped_profile = await user.profile
                    logger.debug(f"Skipping @{skipped_profile.handle} expansion (degree {user.in_subgraph_degree} < threshold)")
                    item.status = "skipped"
                    item.completed_at = datetime.now(timezone.utc)
                    item.last_error = f"Degree {user.in_subgraph_degree} is below threshold."
                    await item.save(update_fields=["status", "completed_at", "last_error"])
                    await asyncio.sleep(0.001) # Yield to event loop
                    crawl_run.candidates_skipped += 1
                    await crawl_run.save(update_fields=["candidates_skipped"])
                    return

            user_profile = await user.profile
            msg = f"Expanding network from @{user_profile.handle}..."
            logger.info(f"{msg} (priority: {user.crawl_priority:.2f})")
            await emit(msg)

            # Collected page_dids across both directions for batched degree update
            all_discovered_dids: list[str] = []

            async def fetch_direction_pages(direction: str, start_cursor: str | None = None, c: httpx.AsyncClient | BskyClient | None = None):
                """Paginate one direction fully and process each page."""
                nonlocal session_reqs, session_found, all_discovered_dids
                cursor = start_cursor
                while True:
                    data = await public_fetch_graph(user.did, direction, cursor=cursor, client=c)
                    batch = data.get(direction, [])
                    if not batch:
                        break

                    page_dids = [f["did"] for f in batch]
                    
                    # Determine edges based on direction
                    if direction == "follows":
                        edge_data = [(user.did, f["did"], f.get("createdAt")) for f in batch]
                        target_filter = {"followee_did__in": page_dids, "follower_did": user.did}
                    else:
                        edge_data = [(f["did"], user.did, f.get("createdAt")) for f in batch]
                        target_filter = {"follower_did__in": page_dids, "followee_did": user.did}

                    all_edges = await FollowEdge.filter(**target_filter).all()
                    existing_edges = {(e.follower_did, e.followee_did) for e in all_edges}

                    new_edges = [
                        FollowEdge(follower_did=s, followee_did=t, discovered_at=parse_dt(ts) or datetime.now(timezone.utc))
                        for s, t, ts in edge_data
                        if (s, t) not in existing_edges
                    ]

                    if new_edges:
                        await FollowEdge.bulk_create(new_edges, ignore_conflicts=True)

                    for f in batch:
                        target_did = f["did"]
                        target_handle = f["handle"]

                        if target_did not in rel_tier_by_did or rel_tier_by_did[target_did] == 0:
                            _, target_user = await upsert_profile_relationship(
                                owner,
                                {
                                    "did": target_did,
                                    "handle": target_handle,
                                    "display_name": f.get("displayName", ""),
                                    "avatar_url": f.get("avatar", ""),
                                    "profile_url": f"https://bsky.app/profile/{target_handle}",
                                    "discovered_via": "graph_crawl",
                                    "crawl_tier": 0,
                                    "crawl_pending_fields": json.dumps(["feed_sample", "relationship_flags"]),
                                },
                            )
                        else:
                            target_user = await AccountRelationship.filter(owner=owner, did=target_did).first()

                        if target_user and target_user.first_seen_at and target_user.first_seen_at >= datetime.now(timezone.utc) - timedelta(seconds=5):
                            from analyzer.manager import global_found_tracker
                            global_found_tracker.record()
                            session_found += 1

                        await enqueue_crawl_user(owner, target_user)

                    all_discovered_dids.extend(page_dids)
                    await hydrate_stubs(owner, page_dids, hydration_semaphore, on_progress=emit, client=c)

                    next_cursor = data.get("cursor")
                    if direction == "follows":
                        item.cursor = next_cursor

                    item.pages_fetched += 1
                    item.edges_found += len(batch)
                    await item.save(update_fields=["cursor", "pages_fetched", "edges_found"])

                    await emit(f"Discovered {len(batch)} {direction} for @{user_profile.handle}", req_inc=1)

                    if not next_cursor:
                        break

                    cursor = next_cursor
                    if not settings_cache.get("disable_internal_rate_limits", False):
                        await asyncio.sleep(0.01)

            try:
                # FIX 6: Fetch follows and followers CONCURRENTLY instead of sequentially.
                # Each direction is independently paginated using the best available client.
                # Run both directions concurrently
                client_to_use = auth_client_shared or public_client
                start_cursor = item.cursor  # Resume follows from where we left off
                await asyncio.gather(
                    fetch_direction_pages("follows", start_cursor, client_to_use),
                    fetch_direction_pages("followers", None, client_to_use),
                )

                # FIX 4: Now that all pages across both directions are done,
                # run a single batched degree update for every discovered DID.
                if all_discovered_dids:
                    unique_discovered = list(dict.fromkeys(all_discovered_dids))
                    CHUNK = 500
                    for i in range(0, len(unique_discovered), CHUNK):
                        chunk = unique_discovered[i:i + CHUNK]
                        await _batch_update_degrees(owner, chunk, tracked_dids)

                # Check budget after batch degree updates
                current_db_size_mb = _get_db_size_mb()
                crawl_budget_mb = settings_cache.get("crawl_budget_mb", 1024)
                if current_db_size_mb >= crawl_budget_mb:
                    raise CrawlBudgetExceeded(f"Database size ({current_db_size_mb:.1f} MB) exceeds budget ({crawl_budget_mb} MB).")

            except Exception as e:
                logger.exception(f"Failed to expand @{user_profile.handle}: {e}")
                item.status = "error"
                item.completed_at = datetime.now(timezone.utc)
                item.last_error = str(e)
                await item.save(update_fields=["status", "completed_at", "last_error"])
                await asyncio.sleep(0.001) # Yield to event loop
                crawl_run.candidates_failed += 1
                await crawl_run.save(update_fields=["candidates_failed"])
                await emit(f"Failed to expand @{user_profile.handle}: {e}")
                return

            user.last_crawled_at = datetime.now(timezone.utc)
            await user.save()
            await asyncio.sleep(0.001) # Yield to event loop
            item.status = "done"
            item.cursor = None
            item.completed_at = datetime.now(timezone.utc)
            await item.save(update_fields=["status", "cursor", "completed_at"])
            await asyncio.sleep(0.001) # Yield to event loop
            crawl_run.candidates_completed += 1
            await crawl_run.save(update_fields=["candidates_completed", "request_count", "discovered_count", "last_message"])
   # Process all candidates concurrently using a shared HTTP client
    async with httpx.AsyncClient(timeout=30.0) as public_client:
        tasks = [process_candidate(item, public_client, auth_client) for item in candidates] # type: ignore
        
        # Execute candidates concurrently. Errors are returned in the list.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check if any task triggered a budget stop
        for r in results:
            if isinstance(r, CrawlBudgetExceeded):
                crawl_run.status = "paused"
                crawl_run.last_message = str(r)
                crawl_run.finished_at = datetime.now(timezone.utc)
                await crawl_run.save(update_fields=["status", "last_message", "error_message", "finished_at"])
                await emit(crawl_run.last_message, 100)
                logger.warning(crawl_run.last_message)
                return

        failures = [r for r in results if isinstance(r, Exception)]
        
    if failures:
        logger.warning(f"{len(failures)} crawl candidates failed for {owner.alias}")
        crawl_run.candidates_failed += len(failures)
        await asyncio.sleep(0.001) # Yield to event loop
        await crawl_run.save(update_fields=["candidates_failed"])
        await emit(f"{len(failures)} crawl candidates failed; continuing.")

    # Trigger graph analysis to refresh FlowRank/Communities after expansion
    logger.info(f"Batch crawl finished for {owner.alias}. Refreshing graph metrics.")
    await emit("Computing network metrics...")
    try:
        async def on_graph_prog(msg, pct=None):
            # In crawl, emit helper is (message, pct, req_inc)
            await emit(f"Graph: {msg}", pct=pct)
        await run_graph_analysis(owner, on_progress=on_graph_prog)
    except Exception as e:
        logger.exception(f"Graph analysis failed after crawl for {owner.alias}: {e}")
        await emit("Crawl complete; graph metrics will retry later.")
    crawl_run.status = "done"
    crawl_run.finished_at = _now()
    crawl_run.last_message = "Crawl complete!"
    await asyncio.sleep(0.001) # Yield to event loop
    await crawl_run.save(update_fields=["status", "finished_at", "last_message"])


async def enqueue_crawl_user(owner: SavedAccount, user: AccountRelationship) -> bool:
    """
    Create or refresh a pending queue item for an expandable user.
    Note: For large-scale seeding, use seed_crawl_queue which is bulk-optimized.
    """
    if not _is_user_expandable(user) or user.crawl_tier >= 2:
        return False

    stale_cutoff = _now() - timedelta(days=1)
    if user.last_crawled_at and user.last_crawled_at >= stale_cutoff:
        return False

    priority = await calculate_priority(user)
    profile = await user.profile

    # Use update_or_create-like logic manually to support status reset
    item = await CrawlQueueItem.filter(account=owner, did=user.did).first()
    if not item:
        await CrawlQueueItem.create(
            account=owner,
            did=user.did,
            relationship=user,
            handle=profile.handle,
            priority=priority,
            tier=user.crawl_tier,
            status="pending",
        )
        return True
    else:
        item.relationship = user
        item.handle = profile.handle
        item.priority = priority
        item.tier = user.crawl_tier
        if item.status in ("error", "skipped"):
            item.status = "pending"
            item.last_error = None
            item.completed_at = None
            item.cursor = None
        await item.save()
        return False


async def seed_crawl_queue(owner: SavedAccount, limit: int = 5000, on_progress=None) -> int:
    """Populate the persisted queue from tracked users that are ready to expand."""
    now = _now()
    expandable = (
        Q(i_follow_them=True) |
        Q(they_follow_me=True) |
        Q(crawl_tier__gt=0) |
        Q(in_subgraph_degree__gte=settings_cache.get("min_connection_threshold", 3))
    )
    users = await AccountRelationship.filter(
        owner=owner,
        crawl_tier__lt=2,
    ).filter(
        expandable
    ).filter(
        Q(last_crawled_at__isnull=True) |
        Q(last_crawled_at__lt=now - timedelta(days=1))
    ).prefetch_related("profile").order_by("last_crawled_at", "-crawl_priority").limit(limit)

    total = len(users)
    if on_progress and total > 0:
        await on_progress(f"Seeding queue: 0/{total}...", pct=0)

    total = len(users)
    if total == 0:
        return 0

    if on_progress:
        await on_progress(f"Seeding: calculating priorities for {total} candidates...", pct=10)

    # 1. Fetch existing queue items in chunks to respect SQLite variable limits
    user_dids = [u.did for u in users]
    existing_items = []
    FETCH_CHUNK = 900
    for i in range(0, len(user_dids), FETCH_CHUNK):
        batch_dids = user_dids[i : i + FETCH_CHUNK]
        existing_items.extend(await CrawlQueueItem.filter(account=owner, did__in=batch_dids).all())

    existing_by_did = {item.did: item for item in existing_items}

    to_create = []
    to_update = []

    # 2. Partition into New vs Existing
    for user in users:
        priority = await calculate_priority(user)
        profile = await user.profile

        if user.did in existing_by_did:
            item = existing_by_did[user.did]
            item.relationship = user
            item.handle = profile.handle
            item.priority = priority
            item.tier = user.crawl_tier
            if item.status in ("error", "skipped"):
                item.status = "pending"
                item.last_error = None
                item.completed_at = None
                item.cursor = None
            to_update.append(item)
        else:
            to_create.append(CrawlQueueItem(
                account=owner,
                did=user.did,
                relationship=user,
                handle=profile.handle,
                priority=priority,
                tier=user.crawl_tier,
                status="pending",
            ))

    # 3. Execute batched writes
    if on_progress:
        await on_progress(f"Writing {total} items to queue...", pct=60)

    # Chunked writes to avoid SQLite's "too many SQL variables" error
    WRITE_BATCH = 50 
    if to_create:
        for i in range(0, len(to_create), WRITE_BATCH):
            await CrawlQueueItem.bulk_create(to_create[i : i + WRITE_BATCH], ignore_conflicts=True)

    if to_update:
        for i in range(0, len(to_update), WRITE_BATCH):
            await CrawlQueueItem.bulk_update(to_update[i : i + WRITE_BATCH], fields=[
                "relationship_id", "handle", "priority", "tier", "status",
                "last_error", "completed_at", "cursor"
            ])

    return len(to_create)


async def claim_crawl_items(owner: SavedAccount, batch_size: int) -> list[CrawlQueueItem]:
    """Claim pending queue items for this process."""
    items = await CrawlQueueItem.filter(
        account=owner,
        status="pending",
    ).order_by("-priority", "created_at").limit(batch_size)

    for item in items:
        item.status = "running"
        item.locked_at = _now()
        item.attempts += 1
        await item.save(update_fields=["status", "locked_at", "attempts"])
    return items


async def hydrate_stubs(
    owner: SavedAccount, 
    dids: list[str], 
    semaphore: asyncio.Semaphore, 
    on_progress=None,
    client: httpx.AsyncClient | None = None,
    write_queue: asyncio.Queue | None = None
) -> int:
    """Hydrate graph-discovered stubs with public profile counts/avatar data."""
    unique_dids = list(dict.fromkeys(dids))
    if not unique_dids:
        return 0

    total = len(unique_dids)
    hydrated = 0
    hydrated_at = _now()
    BATCH_SIZE = 25

    async def _process_chunk(chunk_dids: list[str]):
        nonlocal hydrated
        async with semaphore:
            profiles = await public_fetch_profiles(chunk_dids, client=client)
            if not profiles:
                return

            profiles_to_update = []
            relationships_to_update = []
            queue_items_to_update = []

            for profile in profiles:
                did = profile.get("did")
                if not did:
                    continue

                user = await AccountRelationship.filter(owner=owner, did=did).prefetch_related("profile").first()
                if not user:
                    continue

                shared_profile = await user.profile
                handle = profile.get("handle") or shared_profile.handle
                shared_profile.handle = handle
                shared_profile.display_name = profile.get("displayName", shared_profile.display_name) or ""
                shared_profile.avatar_url = profile.get("avatar", shared_profile.avatar_url) or ""
                shared_profile.profile_url = f"https://bsky.app/profile/{handle}"
                shared_profile.followers_count = _profile_value(profile, "followers_count", "followersCount")
                shared_profile.follows_count = _profile_value(profile, "follows_count", "followsCount")
                shared_profile.posts_count = _profile_value(profile, "posts_count", "postsCount")
                shared_profile.description = profile.get("description")
                shared_profile.banner_url = profile.get("banner")
                shared_profile.account_created_at = parse_dt(profile.get("createdAt"))
                shared_profile.labels = json.dumps([l.get("val") for l in profile.get("labels", [])]) if profile.get("labels") else None
                shared_profile.last_hydrated_at = hydrated_at
                profiles_to_update.append(shared_profile)

                user.crawl_pending_fields = json.dumps(["feed_sample", "relationship_flags"])
                user.crawl_priority = await calculate_priority(user)
                relationships_to_update.append(user)

                item = await CrawlQueueItem.filter(account=owner, did=did).first()
                if item:
                    item.handle = handle
                    item.priority = user.crawl_priority
                    item.hydrated_at = hydrated_at
                    queue_items_to_update.append(item)

                hydrated += 1

            # Internal chunk logging
            if on_progress:
                first_handle = profiles[0].get("handle", "...") if profiles else "..."
                await on_progress(f"Hydrated chunk starting @{first_handle}", req_inc=1)

            return profiles_to_update, relationships_to_update, queue_items_to_update

    chunks = [unique_dids[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    results = await asyncio.gather(*[_process_chunk(c) for c in chunks])

    for res in results:
        if not res: continue
        profiles_to_update, relationships_to_update, queue_items_to_update = res

        if profiles_to_update:
            task = Profile.bulk_update(profiles_to_update, fields=[
                "handle", "display_name", "avatar_url", "profile_url", 
                "followers_count", "follows_count", "posts_count", 
                "description", "banner_url", "account_created_at", 
                "labels", "last_hydrated_at"
            ])
            if write_queue: await write_queue.put(task)
            else: await task

        if relationships_to_update:
            task = AccountRelationship.bulk_update(relationships_to_update, fields=["crawl_pending_fields", "crawl_priority"])
            if write_queue: await write_queue.put(task)
            else: await task

        if queue_items_to_update:
            task = CrawlQueueItem.bulk_update(queue_items_to_update, fields=["handle", "priority", "hydrated_at"])
            if write_queue: await write_queue.put(task)
            else: await task

    return hydrated

async def refresh_priorities(owner: SavedAccount, limit: int = 1000):
    """
    Recalculate priorities for the top N potential candidates.

    FIX 5 (partial): Using prefetch_related to eliminate N+1 profile fetches.
    Previously each calculate_priority() call did a lazy profile fetch.
    """
    users = await AccountRelationship.filter(owner=owner).prefetch_related("profile").order_by("-crawl_priority").limit(limit)
    if not users:
        return

    for u in users:
        u.crawl_priority = await calculate_priority(u)

    # Bulk update instead of individual saves
    await AccountRelationship.bulk_update(users, fields=["crawl_priority"])
    logger.debug(f"Refreshed priorities for {len(users)} accounts in bulk.")