from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db.models import GlobalSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])

class SettingsSchema(BaseModel):
    inactivity_threshold_days: int
    repost_ratio_threshold: float
    feed_sample_size: int
    sync_staleness_hours: int
    worker_sweep_interval_seconds: int
    crawl_concurrency: int
    min_connection_threshold: int
    crawl_budget_mb: int

@router.get("/", response_model=SettingsSchema)
async def get_settings():
    settings = await GlobalSettings.get_or_none(id=1)
    if not settings:
        settings = await GlobalSettings.create(id=1)
    return settings

@router.patch("/", response_model=SettingsSchema)
async def update_settings(data: SettingsSchema):
    settings = await GlobalSettings.get_or_none(id=1)
    if not settings:
        settings = await GlobalSettings.create(id=1)
    
    settings.inactivity_threshold_days = data.inactivity_threshold_days
    settings.repost_ratio_threshold = data.repost_ratio_threshold
    settings.feed_sample_size = data.feed_sample_size
    settings.sync_staleness_hours = data.sync_staleness_hours
    settings.worker_sweep_interval_seconds = data.worker_sweep_interval_seconds
    settings.crawl_concurrency = data.crawl_concurrency
    settings.min_connection_threshold = data.min_connection_threshold
    settings.crawl_budget_mb = data.crawl_budget_mb
    
    await settings.save()
    return settings