"""
api/settings.py
Full CRUD for GlobalSettings — covers every tunable in the project.
On save: persists to DB and refreshes the in-memory SettingsCache.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from db.models import GlobalSettings
from analyzer.manager import record_user_activity
from settings_cache import settings_cache
from tortoise import connections

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsSchema(BaseModel):
    # ── Analysis ──────────────────────────────────────────────────────────────
    inactivity_threshold_days:  int   = Field(90,   ge=1,   le=365)
    repost_ratio_threshold:     float = Field(0.70, ge=0.0, le=1.0)
    feed_sample_size:           int   = Field(100,  ge=10,  le=200)

    # ── Sync ──────────────────────────────────────────────────────────────────
    sync_staleness_hours:               int = Field(12,  ge=1,  le=720)
    worker_sweep_interval_seconds:      int = Field(300, ge=30, le=86400)
    staleness_tier2_days:               int = Field(3,   ge=1,  le=90)
    staleness_tier1_days:               int = Field(7,   ge=1,  le=180)
    staleness_tier0_days:               int = Field(30,  ge=1,  le=365)
    ignore_staleness_threshold_days:    int = Field(0,   ge=0,  le=365)
    disable_startup_sync:               bool = False

    # ── API / Rate limits ─────────────────────────────────────────────────────
    feed_fetch_concurrency:         int   = Field(15,  ge=1,  le=50)
    disable_internal_rate_limits:   bool  = False
    api_max_retries:                int   = Field(4,   ge=0,  le=10)
    api_base_backoff_seconds:       float = Field(2.0, ge=0.5, le=60.0)
    api_polite_delay_ms:            int   = Field(10,  ge=0,  le=5000)

    # ── Crawl ─────────────────────────────────────────────────────────────────
    crawl_concurrency:              int = Field(3,    ge=1,  le=20)
    min_connection_threshold:       int = Field(3,    ge=1,  le=50)
    crawl_budget_mb:                int = Field(1024, ge=100, le=102400)
    crawl_hydration_concurrency:    int = Field(5,    ge=1,  le=20)

    # ── Turbo Mode ────────────────────────────────────────────────────────────
    turbo_mode_manual:               bool  = False
    auto_turbo_enabled:              bool  = True
    turbo_inactivity_threshold_mins: int   = Field(5,  ge=1,  le=60)
    turbo_concurrency:               int   = Field(25, ge=1,  le=100)

    # ── Profile analysis loop ─────────────────────────────────────────────────
    profile_analysis_batch_size:                int   = Field(30,   ge=1,   le=500)
    profile_analysis_staleness_days:            int   = Field(7,    ge=1,   le=365)
    turbo_profile_analysis_batch_size:          int   = Field(100,  ge=1,   le=500)
    turbo_feed_fetch_concurrency:               int   = Field(25,   ge=1,   le=100)
    profile_analysis_inter_batch_sleep_seconds: float = Field(2.0,  ge=0.0, le=60.0)
    profile_analysis_idle_sleep_seconds:        float = Field(60.0, ge=5.0, le=3600.0)

    # ── Graph metrics ─────────────────────────────────────────────────────────
    clustering_top_n:   int = Field(1000,  ge=100,  le=100000)
    louvain_max_nodes:  int = Field(10000, ge=1000, le=1000000)
    louvain_resolution: float = Field(1.0, ge=0.1, le=10.0)
    bio_keyword_weight:                 int = Field(5,      ge=1,   le=100)
    community_keywords_node_sample:     int = Field(100,    ge=10,  le=1000)
    community_keywords_staleness_days:  int = Field(30,     ge=1,   le=365)
    label_prop_max_nodes:               int = Field(500000, ge=10000, le=5000000)

    class Config:
        from_attributes = True


async def patch_global_settings():
    """Patch missing GlobalSettings columns for SQLite compatibility."""
    try:
        conn = connections.get("default")
        new_cols = [
            ("turbo_mode_manual",               "INT DEFAULT 0"),
            ("auto_turbo_enabled",              "INT DEFAULT 1"),
            ("turbo_inactivity_threshold_mins", "INT DEFAULT 5"),
            ("turbo_concurrency",               "INT DEFAULT 25"),
            ("crawl_hydration_concurrency",     "INT DEFAULT 5"),
            ("profile_analysis_batch_size",      "INT DEFAULT 30"),
            ("profile_analysis_staleness_days",  "INT DEFAULT 7"),
            ("turbo_profile_analysis_batch_size", "INT DEFAULT 100"),
            ("turbo_feed_fetch_concurrency",    "INT DEFAULT 25"),
            ("profile_analysis_inter_batch_sleep_seconds", "REAL DEFAULT 2.0"),
            ("profile_analysis_idle_sleep_seconds",       "REAL DEFAULT 60.0"),
            ("clustering_top_n",                "INT DEFAULT 1000"),
            ("louvain_max_nodes",               "INT DEFAULT 10000"),
            ("louvain_resolution",              "REAL DEFAULT 1.0"),
            ("bio_keyword_weight",              "INT DEFAULT 5"),
            ("community_keywords_node_sample",  "INT DEFAULT 100"),
            ("community_keywords_staleness_days", "INT DEFAULT 30"),
            ("label_prop_max_nodes",            "INT DEFAULT 500000"),
            ("disable_startup_sync",            "INT DEFAULT 0"),
        ]
        for col, spec in new_cols:
            try:
                await conn.execute_query(f"ALTER TABLE global_settings ADD COLUMN {col} {spec};")
            except:
                pass # Column already exists or table not ready
    except Exception as e:
        logger.warning(f"Settings patch skipped: {e}")

async def _get_or_create() -> GlobalSettings:
    await patch_global_settings()
    s, _ = await GlobalSettings.get_or_create(id=1)
    return s


@router.get("/", response_model=SettingsSchema)
async def get_settings():
    record_user_activity()
    return await _get_or_create()


@router.patch("/", response_model=SettingsSchema)
async def update_settings(data: SettingsSchema):
    record_user_activity()
    s = await _get_or_create()
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(s, field, value)
        
    if update_data:
        await s.save(update_fields=list(update_data.keys()))

    # Refresh in-memory cache immediately so running loops pick up new values
    await settings_cache.refresh()
    return s