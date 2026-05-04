import asyncio
import logging
from datetime import datetime, timezone, timedelta

import config
from analyzer.client import BskyClient
from analyzer.crawl import crawl_step, refresh_priorities
from analyzer.manager import bus, is_operation_running, running_tasks, task_key
from analyzer.sync import run_sync
from db.models import CrawlRun, SavedAccount

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
                if account.auto_sync_enabled:
                    if not account.last_synced_at or (now - account.last_synced_at) > SYNC_STALENESS:
                        schedule_sync(account)

                if account.auto_crawl_enabled and account.last_synced_at:
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

        async def on_prog(msg, pct=None):
            event = {"kind": "progress", "operation": "crawl", "message": f"[Auto] {msg}"}
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
