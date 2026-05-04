"""
api/accounts.py
CRUD endpoints for saved accounts + account switching.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from db.models import SavedAccount
from analyzer.worker import schedule_sync

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AddAccountRequest(BaseModel):
    alias: str
    handle: str
    app_password: str


class AccountResponse(BaseModel):
    id: int
    alias: str
    handle: str
    did: str | None
    last_synced_at: str | None
    auto_sync_enabled: bool
    auto_crawl_enabled: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=list[AccountResponse])
async def list_accounts():
    accounts = await SavedAccount.all().order_by("alias")
    return [
        AccountResponse(
            id=a.id,
            alias=a.alias,
            handle=a.handle,
            did=a.did,
            last_synced_at=a.last_synced_at.isoformat() if a.last_synced_at else None,
            auto_sync_enabled=a.auto_sync_enabled,
            auto_crawl_enabled=a.auto_crawl_enabled,
        )
        for a in accounts
    ]

@router.patch("/{alias}/settings")
async def update_settings(alias: str, auto_sync: bool = None, auto_crawl: bool = None):
    account = await SavedAccount.get_or_none(alias=alias)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    
    if auto_sync is not None:
        account.auto_sync_enabled = auto_sync
    if auto_crawl is not None:
        account.auto_crawl_enabled = auto_crawl
        
    await account.save()
    return {"status": "ok"}

@router.post("/", response_model=AccountResponse, status_code=201)
async def add_account(body: AddAccountRequest):
    # Persist to config (keychain + accounts.json)
    config.save_account(body.alias, body.handle, body.app_password)

    # Upsert into DB
    account, _ = await SavedAccount.update_or_create(
        defaults={"handle": body.handle},
        alias=body.alias,
    )
    if account.auto_sync_enabled:
        schedule_sync(account)
    return AccountResponse(
        id=account.id,
        alias=account.alias,
        handle=account.handle,
        did=account.did,
        last_synced_at=None,
        auto_sync_enabled=account.auto_sync_enabled,
        auto_crawl_enabled=account.auto_crawl_enabled,
    )


@router.delete("/{alias}", status_code=204)
async def remove_account(alias: str):
    removed = config.remove_account(alias)
    await SavedAccount.filter(alias=alias).delete()
    if not removed:
        raise HTTPException(status_code=404, detail="Account not found.")
