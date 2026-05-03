"""
analyzer/fetch.py
Async paginated fetching of follows, followers, and author feeds.
Each function yields results so callers can stream progress.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Any

from analyzer.client import BskyClient

logger = logging.getLogger(__name__)


async def fetch_all_follows(client: BskyClient, actor: str) -> list:
    """Fetch every account that `actor` follows, paginating automatically."""
    results = []
    cursor = None
    while True:
        resp = await client.get_follows(actor=actor, limit=100, cursor=cursor)
        batch = getattr(resp, "follows", [])
        results.extend(batch)
        cursor = getattr(resp, "cursor", None)
        if not cursor or not batch:
            break
        await asyncio.sleep(0.1)   # small polite delay between pages
    logger.info(f"Fetched {len(results)} follows for {actor}.")
    return results


async def fetch_all_followers(client: BskyClient, actor: str) -> list:
    """Fetch every account that follows `actor`, paginating automatically."""
    results = []
    cursor = None
    while True:
        resp = await client.get_followers(actor=actor, limit=100, cursor=cursor)
        batch = getattr(resp, "followers", [])
        results.extend(batch)
        cursor = getattr(resp, "cursor", None)
        if not cursor or not batch:
            break
        await asyncio.sleep(0.1)
    logger.info(f"Fetched {len(results)} followers for {actor}.")
    return results


async def fetch_author_feed(client: BskyClient, actor_did: str, limit: int = 20) -> list:
    """
    Fetch recent feed items for a single actor.
    Returns an empty list on any error (private/suspended accounts, etc.)
    """
    try:
        resp = await client.get_author_feed(actor=actor_did, limit=limit)
        return getattr(resp, "feed", []) or []
    except Exception as e:
        logger.debug(f"Could not fetch feed for {actor_did}: {e}")
        return []


async def fetch_feeds_concurrent(
    client: BskyClient,
    dids: list[str],
    limit_per_actor: int = 20,
    progress_callback=None,
) -> AsyncGenerator[tuple[str, list], None]:
    """
    Fetch feeds for many DIDs concurrently (respecting the client's semaphore).
    Yields (did, feed_items) tuples as they complete.
    `progress_callback(completed, total)` is called after each one finishes.
    """
    total = len(dids)
    completed = 0

    async def _fetch_one(did: str) -> tuple[str, list]:
        items = await fetch_author_feed(client, did, limit=limit_per_actor)
        return did, items

    tasks = [asyncio.create_task(_fetch_one(did)) for did in dids]

    for coro in asyncio.as_completed(tasks):
        did, items = await coro
        completed += 1
        if progress_callback:
            await progress_callback(completed, total)
        yield did, items
