"""
analyzer/crawl.py
Implements the priority-based graph crawler for network expansion.
"""

import math
import logging
import asyncio
import json
from datetime import datetime, timezone, timedelta
from tortoise.expressions import Q
from db.models import AccountRelationship, FollowEdge, Profile, SavedAccount, CrawlRun, CrawlQueueItem, GlobalSettings
from db.profile_store import upsert_profile_relationship
from analyzer.fetch import public_fetch_graph, public_fetch_profiles
from analyzer.analyze import parse_dt
from analyzer.metrics import run_graph_analysis

logger = logging.getLogger(__name__)

# Minimum connections to existing tracked users before a stub is expanded
MIN_CONNECTION_THRESHOLD = 3

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_user_expandable(user: AccountRelationship) -> bool:
    if user.crawl_tier > 0:
        return True
    if user.i_follow_them or user.they_follow_me:
        return True
    return user.in_subgraph_degree >= MIN_CONNECTION_THRESHOLD


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


async def crawl_step(owner: SavedAccount, batch_size: int = 10, on_progress=None):
    """
    Performs one crawl iteration:
    1. Select top N priority accounts.
    2. Fetch their follows using the public AppView.
    3. Save new edges and create stubs.
    4. Update priorities for affected accounts.
    """
    settings = await GlobalSettings.get(id=1)
    await CrawlRun.filter(account=owner, status="running", finished_at__isnull=True).update(
        status="paused",
        last_message="Interrupted while server was offline.",
    )

    crawl_run = await CrawlRun.create(
        account=owner,
        status="running",
        batch_size=batch_size,
        last_message="Preparing crawl queue...",
    )
    await reset_interrupted_crawl_work(owner)

    async def emit(message: str, pct: int | None = None):
        crawl_run.last_message = message
        await crawl_run.save(update_fields=["last_message"])
        if on_progress:
            await on_progress(message, pct)

    await emit("Preparing crawl queue...")
    seeded = await seed_crawl_queue(owner)
    crawl_run.candidates_queued = await CrawlQueueItem.filter(
        account=owner,
        status="pending",
    ).count()
    await crawl_run.save(update_fields=["candidates_queued"])

    if seeded:
        logger.info(f"Seeded {seeded} crawl queue items for {owner.alias}")

    # Dynamically initialize semaphores based on current GlobalSettings
    crawl_semaphore = asyncio.Semaphore(settings.crawl_concurrency)
    hydration_semaphore = asyncio.Semaphore(2) # Keep hydration internal limit

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

    async def process_candidate(item: CrawlQueueItem):
        async with crawl_semaphore:
            user = await AccountRelationship.filter(owner=owner, did=item.did).prefetch_related("profile").first()
            if not user:
                item.status = "skipped"
                item.completed_at = _now()
                item.last_error = "Tracked user no longer exists."
                await item.save(update_fields=["status", "completed_at", "last_error"])
                crawl_run.candidates_skipped += 1
                await crawl_run.save(update_fields=["candidates_skipped"])
                return

            # Enforcement of connection threshold for stubs
            if user.crawl_tier == 0 and user.in_subgraph_degree < settings.min_connection_threshold:
                if not (user.i_follow_them or user.they_follow_me):
                    skipped_profile = await user.profile
                    logger.debug(f"Skipping @{skipped_profile.handle} expansion (degree {user.in_subgraph_degree} < threshold)")
                    item.status = "skipped"
                    item.completed_at = _now()
                    item.last_error = f"Degree {user.in_subgraph_degree} is below threshold."
                    await item.save(update_fields=["status", "completed_at", "last_error"])
                    crawl_run.candidates_skipped += 1
                    await crawl_run.save(update_fields=["candidates_skipped"])
                    return

            user_profile = await user.profile
            msg = f"Expanding network from @{user_profile.handle}..."
            logger.info(f"{msg} (priority: {user.crawl_priority:.2f})")
            await emit(msg)
            discovered_new = 0

            async def process_page(batch, direction: str):
                nonlocal discovered_new
                page_dids = [f["did"] for f in batch]
                
                # Determine edges based on direction
                if direction == "follows":
                    # We are looking at who 'user' follows
                    edge_data = [(user.did, f["did"], f.get("createdAt")) for f in batch]
                    target_filter = {"followee_did__in": page_dids}
                else:
                    # We are looking at who follows 'user'
                    edge_data = [(f["did"], user.did, f.get("createdAt")) for f in batch]
                    target_filter = {"follower_did__in": page_dids}
                
                all_edges = await FollowEdge.filter(**target_filter).all()
                existing_edges = {(e.follower_did, e.followee_did) for e in all_edges}
                
                new_edges = [
                    FollowEdge(follower_did=s, followee_did=t, discovered_at=parse_dt(ts) or _now())
                    for s, t, ts in edge_data
                    if (s, t) not in existing_edges
                ]

                if new_edges:
                    await FollowEdge.bulk_create(new_edges, ignore_conflicts=True)
                
                for f in batch:
                    target_did = f["did"]
                    target_handle = f["handle"]

                    # Optimization: Only upsert if this is a new discovery or currently a stub.
                    # If Tier 1+, we don't need to touch the relationship record.
                    if target_did not in rel_tier_by_did or rel_tier_by_did[target_did] == 0:
                        profile, target_user = await upsert_profile_relationship(
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

                    if target_user.first_seen_at and target_user.first_seen_at >= _now() - timedelta(seconds=5):
                        discovered_new += 1

                    # We will update in_subgraph_degree in a batch after hydration
                    await enqueue_crawl_user(owner, target_user)

                await hydrate_stubs(owner, page_dids, hydration_semaphore)
                
                # Recalculate degree for the batch
                for did in page_dids:
                    t_user = await AccountRelationship.filter(owner=owner, did=did).first()
                    if t_user:
                        incoming = await FollowEdge.filter(followee_did=did).values_list("follower_did", flat=True)
                        t_user.in_subgraph_degree = len(set(incoming).intersection(tracked_dids))
                        t_user.crawl_priority = await calculate_priority(t_user)
                        await t_user.save()

                # Signal a batch of new discoveries to trigger UI refresh
                await emit(f"Discovered {len(batch)} from @{user_profile.handle}")

            try:
                # Sequential fetch of both directions
                for direction in ["follows", "followers"]:
                    cursor = item.cursor if direction == "follows" else None
                    while True:
                        data = await public_fetch_graph(user.did, direction, cursor=cursor)
                        batch = data.get(direction, [])
                        if batch:
                            await process_page(batch, direction)

                        next_cursor = data.get("cursor")
                        if direction == "follows":
                            item.cursor = next_cursor
                        
                        item.pages_fetched += 1
                        item.edges_found += len(batch)
                        await item.save(update_fields=["cursor", "pages_fetched", "edges_found"])

                        if not next_cursor or not batch:
                            break
                        cursor = next_cursor
                        await asyncio.sleep(0.1)
                        
            except Exception as e:
                logger.exception(f"Failed to expand @{user_profile.handle}: {e}")
                item.status = "error"
                item.completed_at = _now()
                item.last_error = str(e)
                await item.save(update_fields=["status", "completed_at", "last_error"])
                crawl_run.candidates_failed += 1
                await crawl_run.save(update_fields=["candidates_failed"])
                await emit(f"Failed to expand @{user_profile.handle}: {e}")
                return

            user.last_crawled_at = _now()
            await user.save()
            item.status = "done"
            item.cursor = None
            item.completed_at = _now()
            await item.save(update_fields=["status", "cursor", "completed_at"])
            crawl_run.candidates_completed += 1
            crawl_run.discovered_count += discovered_new
            await crawl_run.save(update_fields=["candidates_completed", "discovered_count"])

    # Process all candidates concurrently
    tasks = [process_candidate(item) for item in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        logger.warning(f"{len(failures)} crawl candidates failed for {owner.alias}")
        crawl_run.candidates_failed += len(failures)
        await crawl_run.save(update_fields=["candidates_failed"])
        await emit(f"{len(failures)} crawl candidates failed; continuing.")

    # Trigger graph analysis to refresh FlowRank/Communities after expansion
    logger.info(f"Batch crawl finished for {owner.alias}. Refreshing graph metrics.")
    await emit("Computing network metrics...")
    try:
        await run_graph_analysis(owner)
    except Exception as e:
        logger.exception(f"Graph analysis failed after crawl for {owner.alias}: {e}")
        await emit("Crawl complete; graph metrics will retry later.")
    crawl_run.status = "done"
    crawl_run.finished_at = _now()
    crawl_run.last_message = "Crawl complete!"
    await crawl_run.save(update_fields=["status", "finished_at", "last_message"])


async def enqueue_crawl_user(owner: SavedAccount, user: AccountRelationship) -> bool:
    """Create or refresh a pending queue item for an expandable user."""
    if not _is_user_expandable(user) or user.crawl_tier >= 2:
        return False

    stale_cutoff = _now() - timedelta(days=1)
    if user.last_crawled_at and user.last_crawled_at >= stale_cutoff:
        return False

    priority = await calculate_priority(user)
    existing = await CrawlQueueItem.filter(account=owner, did=user.did).first()
    profile = await user.profile
    if existing:
        existing.relationship = user
        existing.handle = profile.handle
        existing.priority = priority
        existing.tier = user.crawl_tier
        if existing.status in ("error", "skipped"):
            existing.status = "pending"
            existing.last_error = None
            existing.completed_at = None
            existing.cursor = None
        await existing.save()
        return False

    await CrawlQueueItem.create(
        account=owner,
        relationship=user,
        did=user.did,
        handle=profile.handle,
        priority=priority,
        tier=user.crawl_tier,
        status="pending",
    )
    return True


async def seed_crawl_queue(owner: SavedAccount, limit: int = 5000) -> int:
    """Populate the persisted queue from tracked users that are ready to expand."""
    now = _now()
    expandable = (
        Q(i_follow_them=True) |
        Q(they_follow_me=True) |
        Q(crawl_tier__gt=0) |
        Q(in_subgraph_degree__gte=MIN_CONNECTION_THRESHOLD)
    )
    users = await AccountRelationship.filter(
        owner=owner,
        crawl_tier__lt=2,
    ).filter(
        expandable
    ).filter(
        Q(last_crawled_at__isnull=True) |
        Q(last_crawled_at__lt=now - timedelta(days=1))
    ).order_by("last_crawled_at", "-crawl_priority").limit(limit)

    created = 0
    for user in users:
        if await enqueue_crawl_user(owner, user):
            created += 1
    return created


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


async def hydrate_stubs(owner: SavedAccount, dids: list[str], semaphore: asyncio.Semaphore) -> int:
    """Hydrate graph-discovered stubs with public profile counts/avatar data."""
    unique_dids = list(dict.fromkeys(dids))
    if not unique_dids:
        return 0

    async with semaphore:
        profiles = await public_fetch_profiles(unique_dids)

    hydrated = 0
    hydrated_at = _now()
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
        await shared_profile.save()
        user.crawl_pending_fields = json.dumps(["feed_sample", "relationship_flags"])
        user.crawl_priority = await calculate_priority(user)
        await user.save()

        item = await CrawlQueueItem.filter(account=owner, did=did).first()
        if item:
            item.handle = handle
            item.priority = user.crawl_priority
            item.hydrated_at = hydrated_at
            await item.save(update_fields=["handle", "priority", "hydrated_at"])
        hydrated += 1

    return hydrated

async def refresh_priorities(owner: SavedAccount, limit: int = 1000):
    """Recalculate priorities for the top N potential candidates."""
    users = await AccountRelationship.filter(owner=owner).order_by("-crawl_priority").limit(limit)
    if not users:
        return
    
    for u in users:
        u.crawl_priority = await calculate_priority(u)
        await u.save(update_fields=["crawl_priority"])
