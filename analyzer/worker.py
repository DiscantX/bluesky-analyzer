import asyncio
import logging
from datetime import datetime, timezone, timedelta

from tortoise.expressions import Q

import config
from analyzer.client import BskyClient
from analyzer.crawl import crawl_step, refresh_priorities
from analyzer.fetch import fetch_feeds_concurrent
from analyzer.analyze import build_tracked_user_data
from analyzer.manager import bus, is_operation_running, running_tasks, task_key
from analyzer.sync import run_sync
from db.models import CrawlRun, SavedAccount, AccountRelationship, GlobalSettings
from db.profile_store import upsert_profile_relationship

logger = logging.getLogger(__name__)

SYNC_STALENESS = timedelta(hours=12)
WORKER_SWEEP_INTERVAL = 300

worker_task: asyncio.Task | None = None


async def start_background_worker():
    """Start the background scheduler."""
    global worker_task
    worker_task = asyncio.create_task(worker_loop())


def schedule_sync(account: SavedAccount) -> bool:
    """Schedule a sync unless one is already running for this account."""
    key = task_key(account.alias, "sync")
    if is_operation_running(account.alias, "sync"):
        return False
    bus.clear(account.alias, "sync")
    running_tasks[key] = asyncio.create_task(run_auto_sync(account))
    return True


def schedule_crawl(account: SavedAccount) -> bool:
    """Schedule a crawl unless one is already running for this account."""
    key = task_key(account.alias, "crawl")
    if is_operation_running(account.alias, "crawl"):
        return False
    bus.clear(account.alias, "crawl")
    running_tasks[key] = asyncio.create_task(run_auto_crawl(account))
    return True

def schedule_discovery_analysis(account: SavedAccount) -> bool:
    """Schedule a discovery analysis for promoted stubs."""
    key = task_key(account.alias, "discovery")
    if is_operation_running(account.alias, "discovery"):
        return False
    bus.clear(account.alias, "discovery")
    running_tasks[key] = asyncio.create_task(run_auto_discovery_analysis(account))
    return True

async def promote_stubs(account: SavedAccount):
    """
    Promotes Tier 0 (Stubs) to Tier 1 (Standard) if they meet
    interest thresholds (high connections or influence).
    """
    settings = await GlobalSettings.get(id=1)
    # Promote based on subgraph density or FlowRank prestige
    promotable = await AccountRelationship.filter(
        owner=account,
        crawl_tier=0
    ).filter(
        Q(in_subgraph_degree__gte=settings.min_connection_threshold) |
        Q(flowrank_score__gt=0.0001)
    ).all()
    
    if promotable:
        logger.info(f"Promoting {len(promotable)} stubs to Tier 1 for {account.alias}")
        for rel in promotable:
            rel.crawl_tier = 1
            await rel.save(update_fields=["crawl_tier"])

async def needs_urgent_sync(account: SavedAccount) -> bool:
    """
    Returns True if there are direct follows (Standard/Full)
    that have never been analyzed.
    """
    count = await AccountRelationship.filter(
        owner=account,
        i_follow_them=True,
        profile__last_analyzed_at__isnull=True
    ).count()
    if count > 0:
        logger.info(f"Account {account.alias} has {count} un-analyzed follows. Prioritizing sync.")
    return count > 0

async def needs_discovery_analysis(account: SavedAccount) -> bool:
    """
    Returns True if there are promoted stubs (Tier 1)
    that have never been analyzed.
    """
    # Check for accounts never analyzed OR stale discovery accounts (older than 7 days)
    stale_threshold = datetime.now(timezone.utc) - timedelta(days=7)
    count = await AccountRelationship.filter(
        owner=account,
        crawl_tier__gt=0,
        i_follow_them=False,
    ).filter(
        Q(profile__last_analyzed_at__isnull=True) | 
        Q(profile__last_analyzed_at__lt=stale_threshold)
    ).limit(1).count()
    if count > 0:
        logger.info(f"Account {account.alias} has {count} un-analyzed discovery stubs. Prioritizing discovery analysis.")
    return count > 0


async def worker_loop():
    """Periodically schedules sync and crawl work for all accounts."""
    logger.info("Background worker loop started.")
    await asyncio.sleep(2)

    accounts = await SavedAccount.all()
    for account in accounts:
        logger.info(f"Refreshing crawl priorities for {account.alias}...")
        await refresh_priorities(account)
        if account.auto_sync_enabled:
            schedule_sync(account)
        if account.auto_crawl_enabled and account.last_synced_at:
            schedule_crawl(account)

    while True:
        try:
            accounts = await SavedAccount.all()
            now = datetime.now(timezone.utc)

            for account in accounts:
                # 1. Expand the Tier 1 candidate pool
                await promote_stubs(account)

                if account.auto_sync_enabled:
                    # Urgency check: stale sync OR un-analyzed direct follows
                    stale = not account.last_synced_at or (now - account.last_synced_at) > SYNC_STALENESS
                    if stale or await needs_urgent_sync(account):
                        schedule_sync(account)

                if not is_operation_running(account.alias, "sync") and await needs_discovery_analysis(account):
                    schedule_discovery_analysis(account)

                if account.auto_crawl_enabled and account.last_synced_at:
                    # Only crawl if a sync isn't urgently needed or currently running
                    if not is_operation_running(account.alias, "sync"):
                        schedule_crawl(account)

        except Exception as e:
            logger.error(f"Worker loop encountered an error: {e}")

        await asyncio.sleep(WORKER_SWEEP_INTERVAL)


async def run_auto_sync(account: SavedAccount):
    try:
        password = config.get_password(account.alias)
        if not password:
            return

        client = BskyClient(alias=account.alias)
        await client.login(account.handle, password)
        await run_sync(account, client, account.alias)

        account = await SavedAccount.get(id=account.id)
        if account.auto_crawl_enabled:
            schedule_crawl(account)
    except asyncio.CancelledError:
        logger.info(f"Auto-sync cancelled for {account.alias}.")
        raise
    except Exception as e:
        logger.error(f"Auto-sync failed for {account.alias}: {e}")
    finally:
        running_tasks.pop(task_key(account.alias, "sync"), None)


async def run_auto_crawl(account: SavedAccount):
    try:
        latest_run = await CrawlRun.filter(account=account).order_by("-started_at").first()
        if latest_run and latest_run.status == "paused" and latest_run.error_message == "Stopped by user.":
            return

        async def on_prog(msg, pct=None, **kwargs):
            event = {"kind": "progress", "operation": "crawl", "message": f"[Auto] {msg}", **kwargs}
            if pct is not None:
                event["pct"] = pct
            await bus.emit(account.alias, event)

        await crawl_step(account, batch_size=20, on_progress=on_prog)
        await bus.emit(account.alias, {"kind": "done", "operation": "crawl", "message": "Auto-crawl complete!"})
    except asyncio.CancelledError:
        logger.info(f"Auto-crawl cancelled for {account.alias}.")
        raise
    except Exception as e:
        logger.error(f"Auto-crawl failed for {account.alias}: {e}")
        await bus.emit(account.alias, {"kind": "error", "operation": "crawl", "message": str(e)})
    finally:
        running_tasks.pop(task_key(account.alias, "crawl"), None)

async def run_auto_discovery_analysis(account: SavedAccount):
    """
    Fetches feeds and activity metrics for promoted stubs.
    Targets accounts that are Tier 1 but NOT follows/followers.
    """
    try:
        password = config.get_password(account.alias)
        if not password:
            return

        client = BskyClient(alias=account.alias)
        await client.login(account.handle, password)

        # Find targets (Tier 1 stubs missing analysis or stale)
        stale_threshold = datetime.now(timezone.utc) - timedelta(days=7)
        targets = await AccountRelationship.filter(
            owner=account,
            crawl_tier__gt=0,
            i_follow_them=False
        ).filter(
            Q(profile__last_analyzed_at__isnull=True) | 
            Q(profile__last_analyzed_at__lt=stale_threshold)
        ).limit(50).prefetch_related("profile")

        if not targets:
            return

        dids = [t.did for t in targets]
        target_map = {t.did: t for t in targets}
        settings = await GlobalSettings.get(id=1)

        async for did, feed_items in fetch_feeds_concurrent(
            client, dids, limit_per_actor=settings.feed_sample_size
        ):
            rel = target_map[did]
            profile = await rel.profile
            data = build_tracked_user_data(
                profile=profile,
                feed_items=feed_items,
                owner_did=account.did,
                i_follow_them=rel.i_follow_them,
                they_follow_me=rel.they_follow_me,
                inactive_days=settings.inactivity_threshold_days,
                repost_threshold=settings.repost_ratio_threshold
            )
            data["last_analyzed_at"] = datetime.now(timezone.utc)
            await upsert_profile_relationship(account, data)
            
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Discovery analysis failed for {account.alias}: {e}")
    finally:
        running_tasks.pop(task_key(account.alias, "discovery"), None)
