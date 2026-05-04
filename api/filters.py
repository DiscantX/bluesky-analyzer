from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from db.models import SavedAccount, FilterSet

router = APIRouter(prefix="/api/filters", tags=["filters"])

class FilterSetSchema(BaseModel):
    name: str
    icon: Optional[str] = "🔍"
    color: Optional[str] = "#3b82f6"
    condition_tree: str  # JSON string
    sort_by: str = "handle"
    sort_dir: str = "asc"

@router.get("/{alias}", response_model=List[dict])
async def list_filters(alias: str):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    filters = await FilterSet.filter(owner=account).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "icon": f.icon,
            "color": f.color,
            "condition_tree": f.condition_tree,
            "sort_by": f.sort_by,
            "sort_dir": f.sort_dir,
        } for f in filters
    ]

@router.post("/{alias}")
async def create_filter(alias: str, data: FilterSetSchema):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    new_filter = await FilterSet.create(
        owner=account,
        **data.dict()
    )
    return {"id": new_filter.id, "status": "created"}

@router.delete("/{alias}/{filter_id}")
async def delete_filter(alias: str, filter_id: int):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    deleted_count = await FilterSet.filter(id=filter_id, owner=account).delete()
    if not deleted_count:
        raise HTTPException(status_code=404, detail="Filter not found")
    
    return {"status": "deleted"}

@router.put("/{alias}/{filter_id}")
async def update_filter(alias: str, filter_id: int, data: FilterSetSchema):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    filter_set = await FilterSet.get_or_none(id=filter_id, owner=account)
    if not filter_set:
        raise HTTPException(status_code=404, detail="Filter not found")
    
    filter_set.name = data.name
    filter_set.icon = data.icon
    filter_set.color = data.color
    filter_set.condition_tree = data.condition_tree
    filter_set.sort_by = data.sort_by
    filter_set.sort_dir = data.sort_dir
    await filter_set.save()
    
    return {"id": filter_set.id, "status": "updated"}