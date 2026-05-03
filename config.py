"""
config.py
Credential loading with graceful fallback chain:
  1. keyring (system keychain)       — most secure, silent
  2. accounts.json                   — saved accounts list
  3. environment variables           — BSKY_HANDLE / BSKY_APP_PASSWORD
  4. interactive prompt              — last resort

Accounts are stored by alias so you can switch between handles easily.
App passwords are never written to disk in plaintext — keyring only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# keyring is optional — if it fails to import or the backend is unavailable
# we fall back gracefully without crashing.
try:
    import keyring
    from keyring.errors import KeyringError
    _KEYRING_OK = True
except ImportError:
    _KEYRING_OK = False
    KeyringError = Exception  # type: ignore

ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"
KEYRING_SERVICE = "bluesky_analyzer"


# ── accounts.json helpers ──────────────────────────────────────────────────────

def _load_accounts_file() -> dict:
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text())
        except Exception:
            pass
    return {"accounts": []}


def _save_accounts_file(data: dict) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(data, indent=2))


def list_saved_accounts() -> list[dict]:
    """Return list of saved account dicts (alias + handle, no passwords)."""
    return _load_accounts_file().get("accounts", [])


def save_account(alias: str, handle: str, app_password: str) -> None:
    """
    Persist an account alias+handle to accounts.json.
    Store the app password in the system keychain only — never on disk.
    Falls back to printing a warning if keyring is unavailable.
    """
    data = _load_accounts_file()
    accounts = data.setdefault("accounts", [])

    # Update existing or append new
    for acc in accounts:
        if acc["alias"] == alias:
            acc["handle"] = handle
            break
    else:
        accounts.append({"alias": alias, "handle": handle})

    _save_accounts_file(data)

    # Store password in keychain
    if _KEYRING_OK:
        try:
            keyring.set_password(KEYRING_SERVICE, alias, app_password)
            return
        except KeyringError:
            pass

    # Keyring unavailable — warn but don't crash
    print(
        f"[config] Warning: system keychain unavailable. "
        f"App password for '{alias}' was NOT saved. "
        f"You will be prompted on next launch."
    )


def remove_account(alias: str) -> bool:
    """Remove a saved account. Returns True if it existed."""
    data = _load_accounts_file()
    before = len(data.get("accounts", []))
    data["accounts"] = [a for a in data.get("accounts", []) if a["alias"] != alias]
    if len(data["accounts"]) < before:
        _save_accounts_file(data)
        if _KEYRING_OK:
            try:
                keyring.delete_password(KEYRING_SERVICE, alias)
            except KeyringError:
                pass
        return True
    return False


# ── Password retrieval ─────────────────────────────────────────────────────────

def get_password(alias: str) -> Optional[str]:
    """Retrieve the stored app password for an alias from keyring."""
    if not _KEYRING_OK:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, alias)
    except KeyringError:
        return None


# ── Credential resolution ──────────────────────────────────────────────────────

def resolve_credentials(alias: Optional[str] = None) -> tuple[str, str, str]:
    """
    Return (alias, handle, app_password) for the given alias, or the first
    saved account, or fall back to env vars / interactive prompt.
    """
    accounts = list_saved_accounts()

    # Try to find the requested alias (or default to first saved account)
    target: Optional[dict] = None
    if alias:
        target = next((a for a in accounts if a["alias"] == alias), None)
    elif accounts:
        target = accounts[0]

    if target:
        password = get_password(target["alias"])
        if password:
            return target["alias"], target["handle"], password
        # Keyring miss — fall through to prompt for just the password
        print(f"[config] App password for '{target['alias']}' not found in keychain.")
        password = _prompt_password(target["handle"])
        return target["alias"], target["handle"], password

    # Env vars
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_APP_PASSWORD")
    if handle and password:
        return "env", handle, password

    # Interactive prompt
    print("[config] No saved accounts found.")
    handle = input("Bluesky handle (e.g. you.bsky.social): ").strip()
    password = _prompt_password(handle)
    alias_input = input(f"Save this account as (alias, e.g. 'main'): ").strip() or "main"
    save_account(alias_input, handle, password)
    return alias_input, handle, password


def _prompt_password(handle: str) -> str:
    import getpass
    return getpass.getpass(f"App password for @{handle}: ")
