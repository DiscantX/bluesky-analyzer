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
from analyzer.profile_analysis_loop import start_profile_analysis_loop
from analyzer.sync import run_sync
from db.models import CrawlRun, SavedAccount, AccountRelationship
from settings_cache import settings_cache
from db.profile_store import upsert_profile_relationship

logger = logging.getLogger(__name__)

PROFILE_ANALYSIS_STALENESS = timedelta(days=7)
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


async def promote_stubs(account: SavedAccount):
    """
    Promotes Tier 0 (Stubs) to Tier 1 (Standard) if they meet
    interest thresholds (high connections or influence).
    """
    threshold = settings_cache.get("min_connection_threshold", 3)
    promotable = await AccountRelationship.filter(
        owner=account,
        crawl_tier=0
    ).filter(
        Q(in_subgraph_degree__gte=threshold) |
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


async def worker_loop():
    """Periodically schedules sync and crawl work for all accounts."""
    logger.info("Background worker loop started.")
    await asyncio.sleep(2)

    # ── Startup: launch one persistent analysis loop per account ──────────────
    accounts = await SavedAccount.all()
    for account in accounts:
        logger.info(f"Refreshing crawl priorities for {account.alias}...")
        await refresh_priorities(account)

        # Start the persistent profile analysis loop — it runs forever alongside
        # sync and crawl, independently selecting and analyzing stale profiles.
        start_profile_analysis_loop(account)

        if account.auto_sync_enabled:
            schedule_sync(account)
        elif account.auto_crawl_enabled and account.last_synced_at:
            schedule_crawl(account)

    # ── Main sweep loop ───────────────────────────────────────────────────────
    while True:
        try:
            accounts = await SavedAccount.all()
            now = datetime.now(timezone.utc)

            for account in accounts:
                # Ensure the persistent analysis loop is alive (restarts if it
                # crashed or was never started for a newly added account).
                start_profile_analysis_loop(account)

                # Expand the Tier 1 candidate pool
                await promote_stubs(account)

                if account.auto_sync_enabled:
                    sync_stale_hours = settings_cache.get("sync_staleness_hours", 12)
                    stale = not account.last_synced_at or (now - account.last_synced_at) > timedelta(hours=sync_stale_hours)
                    if stale or await needs_urgent_sync(account):
                        schedule_sync(account)

                if account.auto_crawl_enabled and account.last_synced_at:
                    if not is_operation_running(account.alias, "sync"):
                        schedule_crawl(account)

        except Exception as e:
            logger.error(f"Worker loop encountered an error: {e}")

        interval = settings_cache.get("worker_sweep_interval_seconds", WORKER_SWEEP_INTERVAL)
        await asyncio.sleep(interval)


async def run_auto_sync(account: SavedAccount):
    try:
        password = config.get_password(account.alias)
        if not password:
            return

        client = BskyClient(alias=account.alias)
        await client.login(account.handle, password)
        await run_sync(account, client, account.alias)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, client._save_session)

        account = await SavedAccount.get(id=account.id)
        if account.auto_crawl_enabled:
            await asyncio.sleep(2)
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

        async def on_prog(msg, pct=None, crawl_stats=None, account_stats=None, **kwargs):
            event = {"kind": "progress", "operation": "crawl", "message": f"[Auto] {msg}", **kwargs}
            if pct is not None:
                event["pct"] = pct
            if crawl_stats is not None:
                event["crawl_stats"] = crawl_stats
            if account_stats is not None:
                event["account_stats"] = account_stats
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