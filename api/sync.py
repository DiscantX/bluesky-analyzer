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
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import config
from analyzer.client import BskyClient
from analyzer.sync import run_sync
from db.models import SavedAccount, SyncRun

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])

# One progress queue per account alias — shared between trigger and stream endpoints
_queues: dict[str, asyncio.Queue] = {}
_running: set[str] = set()


def _get_queue(alias: str) -> asyncio.Queue:
    if alias not in _queues:
        _queues[alias] = asyncio.Queue(maxsize=256)
    return _queues[alias]


@router.post("/{alias}", status_code=202)
async def trigger_sync(alias: str):
    """Kick off a background sync for the given account alias."""
    if alias in _running:
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

    queue = _get_queue(alias)
    # Drain any stale events from a previous run
    while not queue.empty():
        queue.get_nowait()

    client = BskyClient(alias=alias)
    await client.login(account.handle, password)

    _running.add(alias)

    async def _background():
        try:
            await run_sync(account, client, queue)
        finally:
            _running.discard(alias)

    asyncio.create_task(_background())
    return {"status": "started", "alias": alias}


@router.get("/{alias}/stream")
async def sync_stream(alias: str):
    """
    Server-Sent Events stream — browser connects here to receive live progress.
    Closes automatically when a 'done' or 'error' event is received.
    """
    queue = _get_queue(alias)

    async def event_generator() -> AsyncGenerator[str, None]:
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
    """Return the latest sync run for this account (polling fallback)."""
    run = await SyncRun.filter(account__alias=alias).order_by("-started_at").first()
    if not run:
        return {"status": "never_synced"}
    return {
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "follows_fetched": run.follows_fetched,
        "followers_fetched": run.followers_fetched,
        "error_message": run.error_message,
        "is_running": alias in _running,
    }
