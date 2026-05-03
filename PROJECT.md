# Bluesky Analyzer — Project Description

A local web application for analysing and managing your Bluesky social network. It fetches your follows and followers via the AT Protocol API, analyses each account's activity, and presents the results in a filterable, sortable dashboard served to `localhost`.

## Purpose

The app answers questions like:
- Who have I followed that hasn't posted in months?
- Which accounts I follow mostly just repost content?
- Who follows me that I don't follow back (and vice versa)?
- Who have I followed that has never once interacted with my posts?

Results are stored in a local SQLite database so the dashboard is always instant — syncing is a background operation you trigger on demand, not something that blocks browsing.

## Current Status

**Working and functional.** Core sync, analysis, and UI are all operational. The app has been through a debugging pass resolving Python 3.14 / Tortoise ORM v1.x / Starlette compatibility issues. It is ready for feature development.

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend framework | FastAPI | Async-native, auto docs at `/docs`, clean routing |
| ASGI server | Uvicorn | Standard FastAPI server, auto-opens browser on launch |
| Database | SQLite via Tortoise ORM v1.x | Local file, no server, persistent between runs |
| Bluesky client | `atproto` Python SDK | Official AT Protocol client |
| Credential storage | `keyring` (system keychain) | App passwords never written to disk |
| Frontend | Vanilla JS + Jinja2 templates | No build step, no framework, fully functional |
| Timezone support | `tzdata` | Required on Windows (no OS-level IANA tz database) |

---

# Design Document

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     Browser                         │
│         http://127.0.0.1:8000                       │
└────────────────────┬────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│                  FastAPI (main.py)                  │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐  │
│  │ api/        │ │ api/         │ │ api/        │  │
│  │ accounts.py │ │ sync.py      │ │ users.py    │  │
│  └──────┬──────┘ └──────┬───────┘ └──────┬──────┘  │
│         │               │                │          │
│  ┌──────▼───────────────▼────────────────▼──────┐  │
│  │              db/ (Tortoise ORM)               │  │
│  │   models.py          queries.py               │  │
│  │   SavedAccount       build_query()            │  │
│  │   SyncRun            get_stats()              │  │
│  │   TrackedUser                                 │  │
│  └──────────────────────┬────────────────────────┘  │
│                         │ SQLite                     │
│                    data.db (local file)              │
└─────────────────────────┼────────────────────────────┘
                          │ async (semaphore-limited)
┌─────────────────────────▼────────────────────────────┐
│              analyzer/ (background tasks)            │
│  client.py   fetch.py   analyze.py   sync.py         │
│  BskyClient  paginate   feed stats   orchestrate     │
│  + session   follows/   pure funcs   + SSE events    │
│  + backoff   followers               + DB upsert     │
└─────────────────────────┬────────────────────────────┘
                          │ AT Protocol (HTTPS)
                   Bluesky API (bsky.social)
```

## File Structure

```
bluesky_analyzer/
├── main.py                   # FastAPI app, lifespan, routes, CLI entry point
├── config.py                 # Credential management (keychain + accounts.json)
├── requirements.txt
├── accounts.json             # Saved account aliases + handles (no passwords)
├── data.db                   # SQLite database (auto-created on first run)
├── favicon.ico               # Optional, place in root directory
│
├── analyzer/
│   ├── client.py             # BskyClient: atproto wrapper with session
│   │                         #   persistence, semaphore, 429 backoff,
│   │                         #   write operation stubs
│   ├── fetch.py              # Async paginated fetching:
│   │                         #   fetch_all_follows(), fetch_all_followers(),
│   │                         #   fetch_feeds_concurrent() (yields as completed)
│   ├── analyze.py            # Pure stat computation from feed items:
│   │                         #   analyze_feed(), compute_flags(),
│   │                         #   build_tracked_user_data()
│   └── sync.py               # Full sync orchestrator:
│                             #   run_sync() — fetches, analyses, upserts,
│                             #   emits SSE progress events to a queue
│
├── api/
│   ├── accounts.py           # GET/POST/DELETE /api/accounts/
│   ├── sync.py               # POST /api/sync/{alias} (trigger)
│   │                         # GET  /api/sync/{alias}/stream (SSE)
│   │                         # GET  /api/sync/{alias}/status (polling fallback)
│   └── users.py              # GET /api/users/{alias} (filtered/sorted/paginated)
│                             # GET /api/users/{alias}/stats (summary counts)
│
├── db/
│   ├── models.py             # Three Tortoise ORM models (see below)
│   └── queries.py            # build_query() + get_stats() — all DB filtering
│                             #   lives here; adding a filter = 1 line
│
├── templates/
│   └── index.html            # Single HTML shell; JS does all rendering
│
└── static/
    ├── css/app.css           # All styles (dark theme, sidebar, cards, modals)
    └── js/app.js             # All frontend logic (state, API calls, rendering)
```

## Database Schema

### `saved_accounts`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| alias | varchar unique | User-chosen nickname, e.g. "main", "alt" |
| handle | varchar unique | e.g. "you.bsky.social" |
| did | varchar null | Populated on first sync |
| created_at | datetime | |
| last_synced_at | datetime null | Updated after each successful sync |

### `sync_runs`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| account_id | FK → saved_accounts | |
| started_at | datetime | |
| finished_at | datetime null | |
| status | varchar | `running` / `done` / `error` |
| error_message | text null | |
| follows_fetched | int | |
| followers_fetched | int | |

### `tracked_users`
One row per `(owner_account, tracked_did)` pair. The central table — everything the UI displays comes from here.

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| owner_id | FK → saved_accounts | Which of our accounts owns this row |
| did | varchar | Bluesky DID (permanent identifier) |
| handle | varchar | e.g. "someone.bsky.social" |
| display_name | varchar null | |
| avatar_url | text null | |
| profile_url | text null | |
| followers_count | int | From profile at sync time |
| follows_count | int | |
| posts_count | int | |
| i_follow_them | bool | |
| they_follow_me | bool | |
| last_post_at | datetime null | Most recent activity in sampled feed |
| days_since_post | int null | Computed, stored for fast filtering |
| sampled_post_count | int | How many feed items were sampled |
| repost_count | int | Reposts in sample |
| original_post_count | int | Original posts in sample |
| repost_ratio | float | 0.0–1.0 |
| interacted_with_owner | bool | Replied to or mentioned owner in sample |
| muted | bool | Reserved for write features |
| blocked | bool | Reserved for write features |
| is_inactive | bool | Denormalised flag — last_post_at > INACTIVE_DAYS |
| is_repost_heavy | bool | Denormalised — repost_ratio ≥ threshold |
| is_one_sided_follow | bool | i_follow_them AND NOT they_follow_me |
| is_follower_only | bool | they_follow_me AND NOT i_follow_them |
| first_seen_at | datetime | |
| last_analyzed_at | datetime null | |

**Unique constraint:** `(owner_id, did)` — one row per relationship pair.

## Key Design Decisions

### Rate Limit Safety
- `BskyClient` wraps all atproto calls with an `asyncio.Semaphore(5)` — max 5 concurrent requests, well under Bluesky's 3,000/5min IP limit
- 429 responses trigger exponential backoff (base 2s, doubles per retry, up to 4 retries)
- `RateLimitTracker` reads `ratelimit-remaining` / `ratelimit-reset` headers — ready for write operation budget tracking
- atproto JWT session is persisted to `.sessions/{alias}.session` so `createSession` is only called when the token expires, not on every app launch

### Sync Architecture
- Sync runs as a FastAPI `BackgroundTask` — never blocks the HTTP server
- Progress is streamed to the browser via **Server-Sent Events** (SSE) — no polling, no websockets, no extra dependencies
- One `asyncio.Queue` per account alias bridges the background task and the SSE endpoint
- Feed sampling is concurrent via `asyncio.as_completed()`, bounded by the semaphore

### Filtering and Sorting
All query logic lives in `db/queries.py::build_query()`. Adding a new filter requires:
1. One line in `build_query()` (the ORM filter)
2. One query param in `api/users.py::list_users()`
3. One entry in the JS `state.filters` object and `fetchUsers()` param builder

The `SORTABLE_FIELDS` and `FILTERABLE_FLAGS` sets act as a whitelist, preventing arbitrary column injection.

### Credential Management
Priority chain on startup: `keyring` (system keychain) → `accounts.json` → env vars (`BSKY_HANDLE` / `BSKY_APP_PASSWORD`) → interactive prompt. App passwords are stored in the system keychain only; `accounts.json` stores alias + handle only (safe to commit if needed).

### Frontend
Single HTML page (`templates/index.html`) with all state managed in `static/js/app.js`. No build step, no framework. The JS `state` object holds all filter/sort/pagination state; every user action calls `fetchUsers()` which rebuilds the API query from state. Adding a new UI filter requires only adding to `state.filters` and the `fetchUsers()` param builder — the backend already supports arbitrary filter combinations.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves the HTML dashboard |
| GET | `/api/accounts/` | List saved accounts |
| POST | `/api/accounts/` | Add account `{alias, handle, app_password}` |
| DELETE | `/api/accounts/{alias}` | Remove account |
| POST | `/api/sync/{alias}` | Trigger background sync |
| GET | `/api/sync/{alias}/stream` | SSE progress stream |
| GET | `/api/sync/{alias}/status` | Latest sync run status |
| GET | `/api/users/{alias}` | Filtered/sorted/paginated user list |
| GET | `/api/users/{alias}/stats` | Summary counts for dashboard header |
| GET | `/health` | Health check |
| GET | `/docs` | Auto-generated Swagger UI |

Full query params for `GET /api/users/{alias}`: `search`, `sort_by`, `sort_dir`, `limit`, `offset`, boolean flags (`i_follow_them`, `they_follow_me`, `is_inactive`, `is_repost_heavy`, `is_one_sided_follow`, `is_follower_only`, `interacted_with_owner`, `muted`, `blocked`), numeric ranges (`min_days_inactive`, `min_repost_ratio`, `max_repost_ratio`, `min_followers`, `max_followers`).

## Known Compatibility Notes

- **Tortoise ORM v1.x** (breaking change from 0.x): requires `RegisterTortoise` context manager from `tortoise.contrib.fastapi`; global `Tortoise.init()` no longer works
- **Starlette 0.36+**: `TemplateResponse` signature changed to `TemplateResponse(request, "template.html")` — request is the first positional arg
- **Windows**: requires `tzdata` PyPI package; Linux/macOS have IANA tz data at the OS level
- **Python 3.14**: fully compatible with all dependencies as of current versions

## Planned / Not Yet Implemented

- **Write operations**: `BskyClient` has stubs for `follow()`, `unfollow()`, `mute()`, `block()`; `TrackedUser` has `muted` and `blocked` columns; `RateLimitTracker` tracks the write points budget. The scaffolding is in place.
- **Bulk actions**: UI selections + batch unfollow/mute from filtered views
- **Historical tracking**: `SyncRun` table is the foundation; need a `TrackedUserSnapshot` table to record per-sync deltas
- **Scheduled sync**: background scheduler (APScheduler or similar) to auto-sync on a timer
- **Export to CSV**: straightforward given the existing query layer
- **Advanced UI filters**: date range pickers, follower count sliders — backend already supports all of these via `build_query()`
- **Aerich migrations**: currently using `generate_schemas(safe=True)`; proper migration history needed before schema changes

## Development Notes

```bash
# Setup
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run (opens browser automatically)
python main.py

# Dev mode (hot reload)
python main.py --reload

# Options
python main.py --host 0.0.0.0 --port 9000 --no-browser

# API explorer
open http://127.0.0.1:8000/docs
```

The database (`data.db`) and session files (`.sessions/`) are created automatically on first run. The `.gitignore` excludes both, along with `accounts.json`.
