"""
analyzer/client.py
Wraps atproto Client with:
  - JWT session persistence (avoid hammering createSession endpoint)
  - Rate-limit-aware request handling (reads ratelimit-* headers, backs off on 429)
  - Write-ready structure (rate limit points budget tracked for future write ops)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from atproto import Client
from atproto_client.exceptions import RequestException

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).parent.parent / ".sessions"
SESSION_DIR.mkdir(exist_ok=True)

# Concurrency: max simultaneous in-flight requests to Bluesky API.
# At 5 concurrent we stay well under the 3000/5min IP limit.
DEFAULT_CONCURRENCY = 5

# Retry config for 429 responses
MAX_RETRIES = 4
BASE_BACKOFF = 2.0   # seconds — doubles each retry


class RateLimitTracker:
    """
    Tracks remaining API budget from response headers.
    Future write operations can check this before attempting.
    """

    def __init__(self):
        self.remaining: Optional[int] = None
        self.reset_at: Optional[float] = None   # unix timestamp
        self.limit: Optional[int] = None

    def update(self, headers: dict):
        try:
            if "ratelimit-remaining" in headers:
                self.remaining = int(headers["ratelimit-remaining"])
            if "ratelimit-limit" in headers:
                self.limit = int(headers["ratelimit-limit"])
            if "ratelimit-reset" in headers:
                self.reset_at = float(headers["ratelimit-reset"])
        except (ValueError, TypeError):
            pass

    @property
    def seconds_until_reset(self) -> float:
        if self.reset_at is None:
            return 0.0
        return max(0.0, self.reset_at - time.time())

    def is_exhausted(self) -> bool:
        return self.remaining is not None and self.remaining == 0


class BskyClient:
    """
    Thin async-friendly wrapper around the synchronous atproto Client.
    The atproto library is synchronous, so all calls run in a thread pool
    executor, while the semaphore limits overall concurrency from our side.
    """

    def __init__(self, alias: str, concurrency: int = DEFAULT_CONCURRENCY):
        self.alias = alias
        self._client = Client()
        self._semaphore = asyncio.Semaphore(concurrency)
        self.request_count = 0
        self.rate_limit = RateLimitTracker()
        self._session_file = SESSION_DIR / f"{alias}.session"

    # ── Session management ─────────────────────────────────────────────────────

    def _save_session(self):
        try:
            session = self._client.export_session_string()
            self._session_file.write_text(session)
        except Exception as e:
            logger.warning(f"[{self.alias}] Could not save session: {e}")

    def _load_session(self) -> bool:
        if not self._session_file.exists():
            return False
        try:
            session_str = self._session_file.read_text().strip()
            if not session_str:
                return False
            self._client.import_session_string(session_str)
            logger.info(f"[{self.alias}] Resumed session from disk.")
            return True
        except Exception as e:
            logger.warning(f"[{self.alias}] Could not load session: {e}")
            return False

    async def login(self, handle: str, app_password: str) -> None:
        """
        Login, reusing a saved session if one exists.
        Falls back to full login (which costs a createSession call) only when needed.
        """
        loop = asyncio.get_event_loop()

        if await loop.run_in_executor(None, self._load_session):
            # Verify the session is still valid with a lightweight call
            try:
                await self._run(lambda: self._client.get_current_user())
                logger.info(f"[{self.alias}] Session is valid, skipping login.")
                return
            except Exception:
                logger.info(f"[{self.alias}] Saved session expired, logging in fresh.")

        await self._run(lambda: self._client.login(handle, app_password))
        await loop.run_in_executor(None, self._save_session)
        logger.info(f"[{self.alias}] Logged in as @{handle}.")

    # ── Core request runner ────────────────────────────────────────────────────

    async def _run(self, fn, *args, **kwargs):
        """
        Run a synchronous atproto call in a thread pool, respecting the
        semaphore and retrying on 429 with exponential backoff.
        """
        loop = asyncio.get_event_loop()
        retries = 0

        from db.models import GlobalSettings
        settings = await GlobalSettings.get(id=1)
        
        async def execute_with_retry():
            nonlocal retries
            while True:
                try:
                    from analyzer.manager import global_req_tracker
                    self.request_count += 1
                    global_req_tracker.record()
                    
                    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
                except RequestException as e:
                    status = getattr(e, "response", None)
                    status_code = getattr(status, "status_code", None) if status else None

                    if status_code == 429:
                        if retries >= MAX_RETRIES:
                            raise
                        wait = BASE_BACKOFF * (2 ** retries)
                        reset_wait = self.rate_limit.seconds_until_reset
                        wait = max(wait, reset_wait)
                        logger.warning(
                            f"[{self.alias}] Rate limited (429). "
                            f"Retrying in {wait:.1f}s (attempt {retries+1}/{MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait)
                        retries += 1
                    else:
                        raise

        if settings.disable_internal_rate_limits:
            return await execute_with_retry()
        
        async with self._semaphore:
            return await execute_with_retry()

    # ── Public API wrappers ────────────────────────────────────────────────────
    # These are thin passthroughs — fetch.py composes them into higher-level ops.

    async def get_profile(self, actor: str):
        return await self._run(lambda: self._client.get_profile(actor=actor))

    async def get_profiles(self, actors: list[str]):
        return await self._run(lambda: self._client.get_profiles(actors=actors))

    async def get_follows(self, actor: str, limit: int = 100, cursor: str | None = None):
        return await self._run(
            lambda: self._client.get_follows(actor=actor, limit=limit, cursor=cursor)
        )

    async def get_followers(self, actor: str, limit: int = 100, cursor: str | None = None):
        return await self._run(
            lambda: self._client.get_followers(actor=actor, limit=limit, cursor=cursor)
        )

    async def get_author_feed(self, actor: str, limit: int = 100):
        return await self._run(
            lambda: self._client.get_author_feed(actor=actor, limit=limit)
        )

    # ── Future write operations ────────────────────────────────────────────────
    # Stubs — flesh these out when write support is added.

    async def follow(self, did: str):
        raise NotImplementedError("Write operations not yet implemented.")

    async def unfollow(self, did: str):
        raise NotImplementedError("Write operations not yet implemented.")

    async def mute(self, did: str):
        raise NotImplementedError("Write operations not yet implemented.")

    async def block(self, did: str):
        raise NotImplementedError("Write operations not yet implemented.")
