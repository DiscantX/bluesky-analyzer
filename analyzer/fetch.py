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
from db.models import GlobalSettings
import httpx

logger = logging.getLogger(__name__)


async def fetch_all_follows(client: BskyClient, actor: str) -> list:
    """Fetch every account that `actor` follows, paginating automatically."""
    settings = await GlobalSettings.get(id=1)
    results = []
    cursor = None
    while True:
        resp = await client.get_follows(actor=actor, limit=100, cursor=cursor)
        batch = getattr(resp, "follows", [])
        results.extend(batch)
        cursor = getattr(resp, "cursor", None)
        if not cursor or not batch:
            break
        if not settings.disable_internal_rate_limits:
            await asyncio.sleep(0.1)   # small polite delay between pages
    logger.info(f"Fetched {len(results)} follows for {actor}.")
    return results


async def fetch_all_followers(client: BskyClient, actor: str) -> list:
    """Fetch every account that follows `actor`, paginating automatically."""
    settings = await GlobalSettings.get(id=1)
    results = []
    cursor = None
    while True:
        resp = await client.get_followers(actor=actor, limit=100, cursor=cursor)
        batch = getattr(resp, "followers", [])
        results.extend(batch)
        cursor = getattr(resp, "cursor", None)
        if not cursor or not batch:
            break
        if not settings.disable_internal_rate_limits:
            await asyncio.sleep(0.1)
    logger.info(f"Fetched {len(results)} followers for {actor}.")
    return results


async def fetch_profiles_detailed(client: BskyClient, dids: list[str]) -> list:
    """
    Fetch detailed profiles in batches of 25 (the API limit).
    This ensures we get followers_count, follows_count, and posts_count.
    """
    settings = await GlobalSettings.get(id=1)
    results = []
    for i in range(0, len(dids), 25):
        batch_dids = dids[i:i + 25]
        try:
            resp = await client.get_profiles(batch_dids)
            results.extend(resp.profiles)
        except Exception as e:
            logger.error(f"Failed to fetch profiles batch: {e}")
        if not settings.disable_internal_rate_limits:
            await asyncio.sleep(0.1)
    return results


async def fetch_author_feed(client: BskyClient, actor_did: str, limit: int = 100) -> list:
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
    limit_per_actor: int = 100,
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


async def public_fetch_graph(
    actor_did: str,
    collection: str = "follows",
    limit: int = 100,
    cursor: str | None = None
) -> dict:
    """
    Fetch follows or followers using the unauthenticated public AppView.
    Used for graph crawl to save authenticated API budget.
    """
    url = f"https://public.api.bsky.app/xrpc/app.bsky.graph.get{collection.capitalize()}"
    params = {"actor": actor_did, "limit": limit}
    if cursor:
        params["cursor"] = cursor

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def public_fetch_profiles(dids: list[str]) -> list[dict]:
    """Fetch public profile details from AppView in batches of 25."""
    settings = await GlobalSettings.get(id=1)
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(dids), 25):
            batch = dids[i:i + 25]
            params = [("actors", did) for did in batch]
            try:
                resp = await client.get(
                    "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles",
                    params=params,
                )
                resp.raise_for_status()
                results.extend(resp.json().get("profiles", []))
            except Exception as e:
                logger.error(f"Public profile hydration failed: {e}")
            if not settings.disable_internal_rate_limits:
                await asyncio.sleep(0.1)
    return results


async def fetch_all_graph_public(actor_did: str, collection: str = "follows", on_page=None) -> list[dict]:
    """Paginate through the public graph endpoint."""
    settings = await GlobalSettings.get(id=1)
    results = []
    cursor = None
    while True:
        try:
            data = await public_fetch_graph(actor_did, collection, cursor=cursor)
            batch = data.get(collection, [])
            results.extend(batch)
            if on_page:
                await on_page(batch)
            cursor = data.get("cursor")
            if not cursor or not batch:
                break
            # Polite delay for public API
            if not settings.disable_internal_rate_limits:
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Public fetch failed for {actor_did} {collection}: {e}")
            break
    return results
