"""
settings_cache.py

In-memory cache for GlobalSettings so hot-path code (crawl loops, feed fetching)
doesn't hit the DB on every iteration. Updated atomically whenever settings are saved.

Usage:
    from settings_cache import settings_cache

    val = settings_cache.get("crawl_concurrency", 3)
    # or access the full snapshot:
    snap = settings_cache.snapshot
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default values mirror db/models.py GlobalSettings — kept in sync manually.
# These serve as the authoritative fallback if the DB hasn't loaded yet.
DEFAULTS: dict[str, Any] = {
    # ── Analysis ──────────────────────────────────────────────────────────────
    "inactivity_threshold_days": 90,
    "repost_ratio_threshold": 0.70,
    "feed_sample_size": 100,

    # ── Sync ──────────────────────────────────────────────────────────────────
    "sync_staleness_hours": 12,
    "worker_sweep_interval_seconds": 300,
    "staleness_tier2_days": 3,
    "staleness_tier1_days": 7,
    "staleness_tier0_days": 30,
    "ignore_staleness_threshold_days": 0,
    "disable_startup_sync": False,

    # ── API / Rate limits ─────────────────────────────────────────────────────
    "feed_fetch_concurrency": 15,
    "disable_internal_rate_limits": False,
    "api_max_retries": 4,
    "api_base_backoff_seconds": 2.0,
    "api_polite_delay_ms": 10,

    # ── Crawl ─────────────────────────────────────────────────────────────────
    "crawl_concurrency": 6,
    "min_connection_threshold": 3,
    "crawl_budget_mb": 1024,
    "crawl_hydration_concurrency": 12,

    # ── Turbo Mode ────────────────────────────────────────────────────────────
    "turbo_mode_manual": False,
    "auto_turbo_enabled": True,
    "turbo_inactivity_threshold_mins": 5,
    "turbo_concurrency": 50,

    # ── Profile analysis loop ─────────────────────────────────────────────────
    "profile_analysis_batch_size": 30,
    "profile_analysis_staleness_days": 7,
    "turbo_profile_analysis_batch_size": 100,
    "turbo_feed_fetch_concurrency": 25,
    "profile_analysis_inter_batch_sleep_seconds": 2.0,
    "profile_analysis_idle_sleep_seconds": 60.0,

    # ── Graph metrics ─────────────────────────────────────────────────────────
    "clustering_top_n": 1000,
    "louvain_max_nodes": 10000,
    "louvain_resolution": 1.0,
    "bio_keyword_weight": 5,
    "community_keywords_node_sample": 100,
    "community_keywords_staleness_days": 30,
    "label_prop_max_nodes": 500000,
}


class SettingsCache:
    """Thread-safe in-memory snapshot of GlobalSettings."""

    def __init__(self):
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default if default is not None else DEFAULTS.get(key))

    async def refresh(self) -> None:
        """Pull latest values from DB and update cache atomically."""
        try:
            from db.models import GlobalSettings
            s = await GlobalSettings.get_or_none(id=1)
            if s is None:
                return
            async with self._lock:
                for key in DEFAULTS:
                    db_val = getattr(s, key, None)
                    if db_val is not None:
                        self._data[key] = db_val
            logger.debug("SettingsCache refreshed from DB.")
        except Exception as e:
            logger.warning(f"SettingsCache.refresh() failed: {e}")

    async def update(self, updates: dict[str, Any]) -> None:
        """Apply a dict of updates to cache (call after saving to DB)."""
        async with self._lock:
            self._data.update(updates)


# Module-level singleton
settings_cache = SettingsCache()
