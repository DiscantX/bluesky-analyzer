"""
api/charts.py
Chart Studio API — CRUD for ChartDefinition, registry, and data endpoints.

Routes:
  GET    /api/charts/registry                     — registry metadata
  GET    /api/charts/{alias}                      — list charts
  POST   /api/charts/{alias}                      — create chart
  GET    /api/charts/{alias}/{id}                 — get single chart
  PUT    /api/charts/{alias}/{id}                 — update chart
  DELETE /api/charts/{alias}/{id}                 — delete chart
  PATCH  /api/charts/{alias}/{id}/pin             — toggle pin
  GET    /api/charts/{alias}/{id}/data            — execute saved chart
  POST   /api/charts/{alias}/preview              — execute unsaved definition
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.chart_registry import CHART_REGISTRY, DEFAULT_CHARTS, FIELD_LABELS
from db.chart_queries import query_chart_data
from analyzer.manager import record_user_activity
from db.models import SavedAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/charts", tags=["charts"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChartDefinitionSchema(BaseModel):
    name:          str
    icon:          Optional[str]  = "📊"
    description:   Optional[str] = None
    chart_type:    str            = "scatter"
    dimensions:    str            # JSON string
    filter_set_id: Optional[int] = None
    filter_tree:   Optional[str] = None  # JSON string
    aggregation:   Optional[str] = None
    limit:         int            = 2000
    sort_by:       Optional[str] = None
    sort_dir:      str            = "desc"
    options:       Optional[str] = None  # JSON string
    pinned:        bool           = False
    pin_order:     Optional[int] = None


def _chart_to_dict(c) -> dict:
    return {
        "id":           c.id,
        "name":         c.name,
        "icon":         c.icon,
        "description":  c.description,
        "chart_type":   c.chart_type,
        "dimensions":   c.dimensions,
        "filter_set_id":getattr(c, "filter_set_id", None),
        "filter_tree":  c.filter_tree,
        "aggregation":  c.aggregation,
        "limit":        c.limit,
        "sort_by":      c.sort_by,
        "sort_dir":     c.sort_dir,
        "options":      c.options,
        "pinned":       c.pinned,
        "pin_order":    c.pin_order,
        "created_at":   c.created_at.isoformat() if c.created_at else None,
        "updated_at":   c.updated_at.isoformat() if c.updated_at else None,
    }


async def _seed_default_charts(owner: SavedAccount) -> None:
    """Seed default charts on first visit to the gallery."""
    from db.models import ChartDefinition
    for i, template in enumerate(DEFAULT_CHARTS):
        await ChartDefinition.create(
            owner=owner,
            name=template["name"],
            icon=template.get("icon", "📊"),
            chart_type=template["chart_type"],
            dimensions=json.dumps(template.get("dimensions", {})),
            filter_tree=json.dumps(template["filter_tree"]) if template.get("filter_tree") else None,
            aggregation=template.get("aggregation"),
            limit=template.get("limit", 2000),
            sort_dir=template.get("sort_dir", "desc"),
            pinned=template.get("pinned", False),
            pin_order=i if template.get("pinned") else None,
        )
    logger.info(f"Seeded {len(DEFAULT_CHARTS)} default charts for {owner.alias}")


# ── Registry ──────────────────────────────────────────────────────────────────

@router.get("/registry")
async def get_registry():
    """Return the full chart type registry for the builder UI."""
    record_user_activity()
    return {
        "types":        CHART_REGISTRY,
        "field_labels": FIELD_LABELS,
    }


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/{alias}")
async def list_charts(alias: str, pinned_only: bool = Query(False)):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    # Seed defaults on first visit
    count = await ChartDefinition.filter(owner=owner).count()
    if count == 0:
        await _seed_default_charts(owner)

    qs = ChartDefinition.filter(owner=owner)
    if pinned_only:
        qs = qs.filter(pinned=True)

    charts = await qs.order_by("pin_order", "created_at").all()
    return [_chart_to_dict(c) for c in charts]


@router.post("/{alias}", status_code=201)
async def create_chart(alias: str, data: ChartDefinitionSchema):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    if data.chart_type not in CHART_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown chart type: {data.chart_type}")

    chart = await ChartDefinition.create(
        owner=owner,
        **data.model_dump(),
    )
    return _chart_to_dict(chart)


@router.get("/{alias}/{chart_id}")
async def get_chart(alias: str, chart_id: int):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner)
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    return _chart_to_dict(chart)


@router.put("/{alias}/{chart_id}")
async def update_chart(alias: str, chart_id: int, data: ChartDefinitionSchema):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner)
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    for field, value in data.model_dump().items():
        setattr(chart, field, value)
    await chart.save()

    return _chart_to_dict(chart)


@router.delete("/{alias}/{chart_id}", status_code=204)
async def delete_chart(alias: str, chart_id: int):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    deleted = await ChartDefinition.filter(id=chart_id, owner=owner).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Chart not found")


@router.patch("/{alias}/{chart_id}/pin")
async def toggle_pin(alias: str, chart_id: int, pinned: bool = Query(...)):
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner)
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    chart.pinned = pinned
    if pinned and chart.pin_order is None:
        # Assign next pin_order
        max_order = await ChartDefinition.filter(owner=owner, pinned=True).count()
        chart.pin_order = max_order
    elif not pinned:
        chart.pin_order = None

    await chart.save()
    return _chart_to_dict(chart)


# ── Data endpoints ─────────────────────────────────────────────────────────────

@router.get("/{alias}/{chart_id}/data")
async def get_chart_data(alias: str, chart_id: int, thumbnail: bool = Query(False)):
    """Execute a saved chart definition and return structured data."""
    record_user_activity()
    from db.models import ChartDefinition
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner)
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    chart_def = _chart_to_dict(chart)
    # Deserialize dimensions JSON
    if isinstance(chart_def["dimensions"], str):
        chart_def["dimensions"] = json.loads(chart_def["dimensions"])
    if isinstance(chart_def.get("filter_tree"), str):
        chart_def["filter_tree"] = json.loads(chart_def["filter_tree"])

    try:
        result = await query_chart_data(owner.id, chart_def, thumbnail=thumbnail)
        return result
    except Exception as e:
        logger.exception(f"Chart data query failed for chart {chart_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{alias}/preview")
async def preview_chart(alias: str, chart_def: dict):
    """Execute an unsaved chart definition and return structured data."""
    record_user_activity()
    owner = await SavedAccount.get_or_none(alias=alias)
    if not owner:
        raise HTTPException(status_code=404, detail="Account not found")

    if isinstance(chart_def.get("dimensions"), str):
        chart_def["dimensions"] = json.loads(chart_def["dimensions"])
    if isinstance(chart_def.get("filter_tree"), str) and chart_def["filter_tree"]:
        chart_def["filter_tree"] = json.loads(chart_def["filter_tree"])

    try:
        result = await query_chart_data(owner.id, chart_def, thumbnail=False)
        return result
    except Exception as e:
        logger.exception(f"Chart preview query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
