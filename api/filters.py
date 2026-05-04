import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Any
from db.models import SavedAccount, FilterSet, CustomVariable

router = APIRouter(prefix="/api/filters", tags=["filters"])

class FilterSetSchema(BaseModel):
    name: str
    icon: Optional[str] = "🔍"
    color: Optional[str] = "#3b82f6"
    condition_tree: str  # JSON string
    sort_by: str = "handle"
    sort_dir: str = "asc"

class CustomVariableSchema(BaseModel):
    name: str
    expression_tree: str  # JSON string


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
    
    # Check if this filter is used by other filters
    others = await FilterSet.filter(owner=account).exclude(id=filter_id).all()
    for f in others:
        if f'"field":"__member__","op":"eq","value":{filter_id}' in f.condition_tree.replace(" ", ""):
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot delete: Filter is used as a dependency in '{f.name}'"
            )

    # Check if used by variables
    vars = await CustomVariable.filter(owner=account).all()
    for v in vars:
        if f'"{filter_id}"' in v.expression_tree: # Simple heuristic
            raise HTTPException(status_code=400, detail=f"Used in variable '{v.name}'")

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

@router.get("/{alias}/variables", response_model=List[dict])
async def list_variables(alias: str):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    vars = await CustomVariable.filter(owner=account).all()
    return [
        {"id": v.id, "name": v.name, "expression_tree": v.expression_tree}
        for v in vars
    ]

@router.post("/{alias}/variables")
async def create_variable(alias: str, data: CustomVariableSchema):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Ensure unique name per account
    existing = await CustomVariable.get_or_none(owner=account, name=data.name)
    if existing:
        existing.expression_tree = data.expression_tree
        await existing.save()
        return {"id": existing.id, "status": "updated"}

    new_var = await CustomVariable.create(owner=account, **data.dict())
    return {"id": new_var.id, "status": "created"}

@router.put("/{alias}/variables/{var_id}")
async def update_variable(alias: str, var_id: int, data: CustomVariableSchema):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    var = await CustomVariable.get_or_none(id=var_id, owner=account)
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found")
    
    var.name = data.name
    var.expression_tree = data.expression_tree
    await var.save()
    return {"id": var.id, "status": "updated"}

@router.delete("/{alias}/variables/{var_id}")
async def delete_variable(alias: str, var_id: int):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    await CustomVariable.filter(id=var_id, owner=account).delete()
    return {"status": "deleted"}