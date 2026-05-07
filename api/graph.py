from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from db.models import SavedAccount
from db.queries import get_graph_data

router = APIRouter(prefix="/api/graph", tags=["graph"])

@router.get("/{alias}")
async def get_network_graph(
    alias: str,
    mode: str = Query("macro", pattern="^(macro|ego|community|packing)$"),
    seed_did: Optional[str] = Query(None),
    community_id: Optional[int] = Query(None),
    limit: int = Query(1000, ge=10, le=5000)
):
    """
    Returns a node-link JSON structure for force-directed graph visualization,
    or a hierarchy structure for circle packing (mode=packing).
    """
    account = await SavedAccount.filter(alias=alias).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    try:
        data = await get_graph_data(
            owner_id=account.id,
            mode=mode,
            seed_did=seed_did,
            community_id=community_id,
            limit=limit
        )

        # Packing mode returns a hierarchy, not a node-link graph
        if mode == "packing":
            return data

        # Enrich metadata for graph modes
        data["metadata"].update({
            "mode": mode,
            "seed_did": seed_did,
            "node_count": len(data["nodes"]),
            "link_count": len(data["links"])
        })
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))