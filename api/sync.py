"""
api/sync.py
Sync trigger + Server-Sent Events progress stream.
POST /api/sync/{alias}         — kick off a background sync
GET  /api/sync/{alias}/stream  — SSE stream of progress events
GET  /api/sync/{alias}/status  — latest sync run status (polling fallback)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import config
import logging
from analyzer.client import BskyClient
from analyzer.sync import run_sync
from analyzer.crawl import crawl_step
from analyzer.crawl import _get_db_size_mb # Import for current DB size
from db.models import SavedAccount, SyncRun, CrawlRun, CrawlQueueItem
from analyzer.manager import running_tasks, bus, is_running, is_operation_running, task_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])

@router.post("/{alias}", status_code=202)
async def trigger_sync(alias: str):
    """Kick off a background sync for the given account alias."""
    if is_operation_running(alias, "sync"):
        raise HTTPException(status_code=409, detail="Sync already in progress.")

    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    password = config.get_password(alias)
    if not password:
        raise HTTPException(
            status_code=400,
            detail="No app password found. Re-add the account to save credentials.",
        )

    client = BskyClient(alias=alias)
    await client.login(account.handle, password)

    async def _background():
        try:
            await run_sync(account, client, alias)
        except asyncio.CancelledError:
            logger.info(f"Sync for {alias} cancelled.")
        finally:
            running_tasks.pop(task_key(alias, "sync"), None)

    bus.clear(alias, "sync")
    running_tasks[task_key(alias, "sync")] = asyncio.create_task(_background())
    return {"status": "started", "alias": alias}

@router.post("/{alias}/crawl", status_code=202)
async def trigger_crawl(alias: str, batch_size: int = 20):
    """Trigger a network expansion crawl step."""
    if is_operation_running(alias, "crawl"):
        raise HTTPException(status_code=409, detail="Crawl already in progress.")

    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    async def _background():
        try:
            # Brief delay to allow the frontend EventSource to connect
            await asyncio.sleep(1.5)
            
            async def emit_progress(msg, pct=None, **kwargs):
                event = {"kind": "progress", "operation": "crawl", "message": msg, **kwargs}
                if pct is not None:
                    event["pct"] = pct
                await bus.emit(alias, event)
            
            await crawl_step(account, batch_size=batch_size, on_progress=emit_progress)
            await bus.emit(alias, {"kind": "done", "operation": "crawl", "message": "Crawl complete!"})
        except asyncio.CancelledError:
            logger.info(f"Crawl for {alias} cancelled.")
            stopped_run = await CrawlRun.filter(
                account=account,
                status="paused",
                error_message="Stopped by user.",
            ).first()
            if stopped_run:
                return
            await CrawlRun.filter(account=account, status="running").update(
                status="paused",
                error_message="Crawl cancelled.",
            )
            await bus.emit(alias, {"kind": "error", "operation": "crawl", "message": "Crawl cancelled."})
        except Exception as e:
            logger.exception(f"Crawl failed for {alias}: {e}")
            await CrawlRun.filter(account=account, status="running").update(
                status="error",
                error_message=str(e),
            )
            await bus.emit(alias, {"kind": "error", "operation": "crawl", "message": str(e)})
        finally:
            running_tasks.pop(task_key(alias, "crawl"), None)

    bus.clear(alias, "crawl")
    running_tasks[task_key(alias, "crawl")] = asyncio.create_task(_background())
    return {"status": "started", "crawl": True}


@router.post("/{alias}/crawl/stop")
async def stop_crawl(alias: str):
    """Stop the active network crawl and leave queue state resumable."""
    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    key = task_key(alias, "crawl")
    task = running_tasks.get(key)
    if task and not task.done():
        task.cancel()

    await CrawlRun.filter(account=account, status="running").update(
        status="paused",
        error_message="Stopped by user.",
        last_message="Crawl stopped.",
    )
    await CrawlQueueItem.filter(account=account, status="running").update(
        status="pending",
        locked_at=None,
    )
    await bus.emit(alias, {"kind": "done", "operation": "crawl", "message": "Crawl stopped."})
    return {"status": "stopped", "crawl": True}

@router.get("/{alias}/stream")
async def sync_stream(alias: str, operation: str | None = None):
    """
    Server-Sent Events stream — browser connects here to receive live progress.
    Closes automatically when a 'done' or 'error' event is received.
    """
    queue = bus.subscribe(alias, operation)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    data = json.dumps(event)
                    yield f"data: {data}\n\n"
                    if event.get("kind") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    # Send a keepalive comment so the connection doesn't drop
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(alias, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{alias}/status")
async def sync_status(alias: str):
    """Return latest sync and crawl status for this account (polling fallback)."""
    from analyzer.manager import global_req_tracker, global_found_tracker
    run = await SyncRun.filter(account__alias=alias).order_by("-started_at").first()
    crawl_run = await CrawlRun.filter(account__alias=alias).order_by("-started_at").first()

    sync_payload = {"status": "never_synced"}
    if run:
        live_sync = bus.last_event.get((alias, "sync"), {})
        sync_payload = {
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "follows_fetched": run.follows_fetched,
            "followers_fetched": run.followers_fetched,
            "request_count": live_sync.get("req_count", run.request_count),
            "error_message": run.error_message,
        }

    crawl_payload = {"status": "never_crawled"}
    if crawl_run:
        pending = await CrawlQueueItem.filter(
            account_id=crawl_run.account_id,
            status="pending",
        ).count()
        running = await CrawlQueueItem.filter(
            account_id=crawl_run.account_id,
            status="running",
        ).count()
        
        # ── MERGE LIVE IN-MEMORY STATS ────────────────────────────────────────
        # If the crawl is running, the memory bus has more accurate numbers 
        # than the disk.
        live_event = bus.last_event.get((alias, "crawl"), {})
        
        discovered_count = live_event.get("discovered_count", crawl_run.discovered_count)
        request_count = live_event.get("request_count", crawl_run.request_count)
        last_message = live_event.get("message", crawl_run.last_message)

        crawl_payload = {
            "id": crawl_run.id,
            "status": crawl_run.status,
            "started_at": crawl_run.started_at.isoformat() if crawl_run.started_at else None,
            "finished_at": crawl_run.finished_at.isoformat() if crawl_run.finished_at else None,
            "error_message": crawl_run.error_message,
            "batch_size": crawl_run.batch_size,
            "candidates_queued": crawl_run.candidates_queued,
            "candidates_completed": crawl_run.candidates_completed,
            "candidates_failed": crawl_run.candidates_failed,
            "candidates_skipped": crawl_run.candidates_skipped,
            "discovered_count": discovered_count,
            "last_message": last_message,
            "pending_queue_items": pending,
            "running_queue_items": running,
            "is_running": is_operation_running(alias, "crawl"),
        }

    return {
        "req_rate": global_req_tracker.get_rate(),
        "found_rate": global_found_tracker.get_rate(),
        **sync_payload,
        "is_running": is_running(alias),
        "sync_running": is_operation_running(alias, "sync"),
        "crawl_running": is_operation_running(alias, "crawl"),
        "sync": sync_payload,
        "crawl": crawl_payload,
    }
    # Add global crawl budget info
    response["crawl_budget_mb"] = settings_cache.get("crawl_budget_mb", 1024)
    response["current_db_size_mb"] = _get_db_size_mb()
    return response
