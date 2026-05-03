"""
api/accounts.py
CRUD endpoints for saved accounts + account switching.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from db.models import SavedAccount

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
        )
        for a in accounts
    ]


@router.post("/", response_model=AccountResponse, status_code=201)
async def add_account(body: AddAccountRequest):
    # Persist to config (keychain + accounts.json)
    config.save_account(body.alias, body.handle, body.app_password)

    # Upsert into DB
    account, _ = await SavedAccount.update_or_create(
        defaults={"handle": body.handle},
        alias=body.alias,
    )
    return AccountResponse(
        id=account.id,
        alias=account.alias,
        handle=account.handle,
        did=account.did,
        last_synced_at=None,
    )


@router.delete("/{alias}", status_code=204)
async def remove_account(alias: str):
    removed = config.remove_account(alias)
    await SavedAccount.filter(alias=alias).delete()
    if not removed:
        raise HTTPException(status_code=404, detail="Account not found.")
