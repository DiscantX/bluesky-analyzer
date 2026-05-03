# Bluesky Analyzer — Project Description

A local web application for analysing and managing your Bluesky social network. It fetches your follows and followers via the AT Protocol API, analyses each account's activity, and presents the results in a filterable, sortable dashboard served to `localhost`.

## Purpose

The app answers questions like:
- Who have I followed that hasn't posted in months?
- Which accounts I follow mostly just repost content?
- Who follows me that I don't follow back (and vice versa)?
- Who have I followed that has never once interacted with my posts?
- Which accounts in my extended network have the highest influence (FlowRank)?
- Which accounts bridge otherwise disconnected communities?
- Who has recently come back to life after a long period of inactivity?

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
| Graph analysis | NetworkX | Local graph metric computation (FlowRank, clustering, community detection) |
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
│  │   TrackedUser        FilterSet                │  │
│  │   FollowEdge                                  │  │
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
│              graph.py   metrics.py                   │
│              crawl      FlowRank/                    │
│              queue      community                    │
└─────────────────────────┬────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          │ Authenticated PDS             │ Public AppView
          │ (auth required)               │ public.api.bsky.app
          │ - Owner follows/followers     │ - Profile stubs
          │ - Feed samples                │ - Follow/follower lists
          │ - Write operations            │   for graph crawl
          │ 3,000 req / 5 min (per IP)    │ No published limit;
          │                               │ 30s CDN cache (BunnyCDN)
          └───────────────────────────────┘
                   Bluesky API (HTTPS)
```

## API Strategy — Two Endpoints

All API calls are split across two endpoints with distinct rate limit characteristics:

### Authenticated PDS (via `atproto` client)
- **Used for:** owner's follows/followers, feed samples, write operations
- **Rate limit:** 3,000 requests / 5 minutes per IP (hard, tracked via response headers)
- **Write budget:** 5,000 points / hour, 35,000 points / day (CREATE=3pts, UPDATE=2pts, DELETE=1pt)
- **Concurrency:** max 5 simultaneous requests (semaphore-controlled)
- **Backoff:** exponential on 429 (base 2s, doubles per retry, max 4 retries)

### Public AppView (`public.api.bsky.app`)
- **Used for:** profile stubs and follow/follower lists of discovered accounts during graph crawl
- **Rate limit:** no published limit; "generous" per Bluesky docs; no rate limit headers returned
- **Cache TTL:** 30 seconds (BunnyCDN `cache-control: public, max-age=30`)
- **Concurrency:** higher ceiling — self-imposed throttle of 50–100 req/min as good citizenship
- **Relationship detection:** follow/follower lists are available unauthenticated; `they_follow_me` is determined by scanning their follower list for the owner's DID (more robust than convenience endpoints, since DIDs are canonical and handles can change)

### Rate Limit UI Display
A persistent status bar shows:
- **Read budget gauge:** requests used in current 5-min window (authenticated PDS only; public AppView has no readable headers so request counts are tracked internally)
- **Hourly write points gauge:** dormant until write ops are implemented
- **Daily write points gauge:** dormant until write ops are implemented
- Reset countdown timer for the authenticated read window

---

## Quality Signals — Defining "Useful"

Rather than a single quality score, the app computes several orthogonal signals and lets the user compose them via the filter system.

### Signal Categories

**Reach signals**
- `followers_count` — raw reach
- `follower_growth_rate` — rising accounts (requires snapshot history)
- `flowrank_score` — network-weighted influence (see Graph Metrics below)

**Engagement quality signals**
- `repost_ratio` — moderate (20–40%) is positive (amplifier); very high (>80%) is noise
- `original_content_ratio` — complement of repost ratio
- `reply_ratio` — high reply rate signals genuine discourse engagement
- `interacted_with_owner` — replied to or mentioned the owner specifically

**Temporal signals**
- `posting_frequency` — posts per week (derived from feed samples over time)
- `posting_consistency` — variance in posting frequency
- `days_since_post` — simple recency
- `burst_score` — reposts-per-hour during active periods; high burst = content noise

**Network position signals** (graph-derived, computed by NetworkX)
- `flowrank_score` — influence flowing through the network (analogous to PageRank but named distinctly; computed locally via NetworkX on the crawled subgraph)
- `clustering_coefficient` — how interconnected are their neighbors
- `bridge_score` — connects otherwise-disconnected communities (low clustering + high FlowRank)
- `in_subgraph_degree` — how many already-tracked accounts follow them
- `community_id` — Louvain community detection label

### Prebuilt Composite Presets (Planned)
- **High Amplification Potential** — high followers, moderate repost ratio, active, has interacted with similar content
- **Hidden Gem** — high engagement rate relative to follower count, growing, original content
- **Network Bridge** — low clustering coefficient, follows across communities, moderate follower count
- **Noise Source** — very high repost ratio AND high burst score
- **Risen from the Dead** — posted recently, previous post was 365+ days ago

---

## Custom Filter System (Planned)

### FilterSet Model
A named, saved filter configuration stored in the DB as a JSON condition tree:

```json
{
  "name": "Risen from the Dead",
  "icon": "🧟",
  "color": "#f59e0b",
  "tree": {
    "op": "AND",
    "conditions": [
      { "field": "i_follow_them", "op": "eq", "value": true },
      { "field": "days_since_post", "op": "lte", "value": 30 },
      { "field": "posting_gap_days", "op": "gte", "value": 365 }
    ]
  },
  "sort": { "by": "days_since_post", "dir": "asc" }
}
```

The tree is recursive — conditions can themselves contain nested AND/OR groups.

### UI: Block-Based Condition Builder
Each condition row has three elements:
1. **Field selector** — grouped by category (Identity, Activity, Relationship, Network, Temporal)
2. **Operator selector** — context-sensitive by field type (`eq/neq` for booleans, `lt/gt/lte/gte/between` for numerics, `contains/starts_with` for strings, `before/after/within_last` for datetimes)
3. **Value input** — appropriate widget per type

AND/OR groups are nestable and drag-reorderable. Named FilterSets appear in the sidebar below built-in tabs with their chosen icon and color.

### Backend
`db/queries.py::build_query()` is extended to accept and recursively execute a condition tree. The `SORTABLE_FIELDS` and `FILTERABLE_FLAGS` whitelists are expanded to cover all new signal columns.

---

## Graph Crawl Architecture

### Data Tiers
| Tier | What we store | When assigned |
|---|---|---|
| **Stub** | handle, DID, follower/following counts | On discovery |
| **Standard** | + feed sample (20 posts), relationship flags, all signal columns | On queue pop |
| **Full** | + extended feed (100 posts), their follows list expanded | High-priority accounts or explicit request |

### Crawl Priority Score
```
priority = (relationship_weight × 1000)
         + (mutual_follow_bonus × 500)
         + (log10(followers_count + 1) / 7 × 200)
         + (in_subgraph_degree × 100)
         - (days_since_last_crawled × 10)
```
Where `relationship_weight` = 3 (owner follows them), 2 (they follow owner), 1 (graph discovery).

### Crawl Depth and Budget

Depth is configured by the user, with hard stops enforced:

| Depth | Scope | Typical account count | Typical DB size |
|---|---|---|---|
| 0 — seed | Owner's direct follows + followers | ~500–2,000 | < 5 MB |
| 1 — follows-of-follows | Stubs for all depth-0 accounts' networks | ~10,000–50,000 | ~20–150 MB |
| 2 — selective | Full analysis for high-priority depth-1; stubs for rest | ~50,000–500,000 | ~100 MB–2 GB |
| 3+ | Budget-bounded; crawl until size cap hit | Potentially millions | Up to user cap |

**Depth 3+ requires explicit user confirmation.** The confirmation dialog shows estimated account count and disk usage calculated from their actual seed size, alongside their current budget setting:

> *"Based on your current network (~500 follows), a depth 3 crawl could discover 500,000–2,000,000 accounts and consume 2–8 GB. The crawl will stop when your 1 GB budget is reached. This may take days to complete."*

### Size Budget
- **Default:** 1 GB
- **Soft warning:** displayed in UI at 80% of budget
- **Hard stop:** crawl pauses at 100%; user can raise budget to resume
- **Depth 3 requirement:** the confirmation dialog requires the user to review (and optionally raise) the budget before proceeding

### Crawl Queue Persistence
The queue state (pending DIDs, priority scores, tier assignments) is persisted to the DB. When the app closes mid-crawl, it resumes exactly where it left off on next launch with no data loss and no repeated API calls.

### Minimum Connection Threshold
Depth-2+ accounts are only expanded (their follows list fetched) if they have ≥ 3 connections to already-tracked accounts. This prevents the graph from exploding into irrelevant parts of the network and keeps the working set analytically meaningful. Default threshold: 3 (user-configurable).

---

## Graph Metric Computation (NetworkX)

After each sync completes, a background job loads the `follow_edges` table into NetworkX as a directed graph and computes:

1. **FlowRank** (`flowrank_score`) — NetworkX's `pagerank()` on the directed subgraph
2. **In-subgraph degree** (`in_subgraph_degree`) — in-degree within the crawled graph
3. **Clustering coefficient** (`clustering_coefficient`) — computed for top-N accounts by FlowRank (expensive for all)
4. **Community detection** (`community_id`) — Louvain or label propagation; written as an integer label

Results are written back to `tracked_users` columns. This runs in a thread pool executor to avoid blocking the event loop. NetworkX handles graphs up to ~100K nodes comfortably in memory; larger graphs may require sampling.

---

## Sync Strategy — Pull-Based, Not Firehose

The app uses on-demand pull syncing rather than a persistent firehose connection. This is intentional:

- **The firehose is designed for always-on infrastructure.** A residential laptop that sleeps, closes its lid, and has intermittent connectivity is not a suitable firehose consumer.
- **Cursor gap risk.** Relay servers don't guarantee indefinite cursor retention; a multi-day offline gap could mean missed events with no clean recovery path.
- **Bandwidth.** The full firehose is the entire Bluesky network; even with JetStream filtering it is a continuous background bandwidth consumer inappropriate for a shared residential connection.

Instead, syncs are smart and differential:

- **Re-sync only fetches accounts whose `last_analyzed_at` exceeds a configurable staleness threshold** (default: 7 days). New follows always get a full fetch.
- **Tiered staleness:** high-priority accounts refresh more often than low-priority discovered stubs.
- **Background crawl throttle:** graph expansion runs at a configurable req/min cap, pausable by the user. Queue state persists across app restarts.

The firehose is not precluded architecturally and could be added later if the tool evolves toward always-on server deployment.

---

## Database Schema

### `saved_accounts`
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| alias | varchar unique | e.g. "main", "alt" |
| handle | varchar unique | e.g. "you.bsky.social" |
| did | varchar null | Populated on first sync |
| created_at | datetime | |
| last_synced_at | datetime null | |

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
One row per `(owner_account, tracked_did)` pair.

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| owner_id | FK → saved_accounts | |
| did | varchar | Permanent identifier |
| handle | varchar | |
| display_name | varchar null | |
| avatar_url | text null | |
| profile_url | text null | |
| followers_count | int | |
| follows_count | int | |
| posts_count | int | |
| i_follow_them | bool | |
| they_follow_me | bool | Determined by DID scan of their follower list |
| last_post_at | datetime null | |
| days_since_post | int null | |
| sampled_post_count | int | |
| repost_count | int | |
| original_post_count | int | |
| repost_ratio | float | 0.0–1.0 |
| interacted_with_owner | bool | |
| muted | bool | Reserved for write features |
| blocked | bool | Reserved for write features |
| is_inactive | bool | Denormalised flag |
| is_repost_heavy | bool | Denormalised flag |
| is_one_sided_follow | bool | |
| is_follower_only | bool | |
| crawl_tier | int | 0=stub, 1=standard, 2=full |
| crawl_priority | real | Computed score for queue ordering |
| last_crawled_at | datetime null | |
| crawl_pending_fields | text null | JSON list of what's not yet fetched |
| discovered_via | varchar null | `owner_follows`, `owner_followers`, `graph_crawl` |
| flowrank_score | real null | Computed by NetworkX post-sync |
| clustering_coefficient | real null | Computed by NetworkX (top-N only) |
| in_subgraph_degree | int | Count of crawled accounts that follow this one |
| community_id | int null | Louvain community label |
| first_seen_at | datetime | |
| last_analyzed_at | datetime null | |

**Unique constraint:** `(owner_id, did)`

### `follow_edges` (new)
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| follower_did | varchar | |
| followee_did | varchar | |
| discovered_at | datetime | |

**Unique constraint:** `(follower_did, followee_did)`

### `filter_sets` (new)
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| owner_id | FK → saved_accounts | |
| name | varchar | Display name e.g. "Risen from the Dead" |
| icon | varchar null | Emoji |
| color | varchar null | Hex color for sidebar |
| condition_tree | text | JSON condition tree |
| sort_by | varchar | |
| sort_dir | varchar | `asc` / `desc` |
| created_at | datetime | |

---

## Planned DB Size Estimates

| Scenario | Accounts | Edges | Est. DB Size |
|---|---|---|---|
| Seed only (depth 0) | ~500 | ~500 | < 5 MB |
| Depth 1 stubs | ~50,000 | ~150,000 | ~100–150 MB |
| Depth 2 selective | ~500,000 | ~5,000,000 | ~2–4 GB |
| Depth 3+ (budget-bounded) | millions | hundreds of millions | up to user cap |

Default budget of 1 GB comfortably covers depth 1 fully and meaningful selective depth 2 for most users.

---

## Planned Force-Directed Graph View (`/graph`)

A future route rendering an interactive D3 force-directed graph of the crawled social network.

- **Nodes:** accounts, sized by FlowRank or followers_count, colored by community_id
- **Edges:** follow relationships (mutual follows rendered as undirected to reduce noise)
- **Interaction:** click node → profile card + stats; double-click → expand neighborhood; filter controls to show/hide by tier/community/flag
- **Performance:** cap default render at top-N accounts by FlowRank; use WebGL (`three-forcegraph` or similar) for larger graphs

---

## File Structure

```
bluesky_analyzer/
├── main.py                   # FastAPI app, lifespan, routes, CLI entry point
├── config.py                 # Credential management (keychain + accounts.json)
├── requirements.txt
├── accounts.json             # Saved account aliases + handles (no passwords)
├── data.db                   # SQLite database (auto-created on first run)
│
├── analyzer/
│   ├── client.py             # BskyClient: atproto wrapper with session
│   │                         #   persistence, semaphore, 429 backoff,
│   │                         #   write operation stubs
│   ├── fetch.py              # Async paginated fetching:
│   │                         #   fetch_all_follows(), fetch_all_followers(),
│   │                         #   fetch_feeds_concurrent()
│   │                         #   public_fetch() — unauthenticated graph crawl
│   ├── analyze.py            # Pure stat computation from feed items
│   ├── sync.py               # Full sync orchestrator + SSE progress events
│   ├── crawl.py              # (planned) Graph crawl queue + priority scheduler
│   └── metrics.py            # (planned) NetworkX graph metric computation:
│                             #   FlowRank, clustering, community detection
│
├── api/
│   ├── accounts.py           # GET/POST/DELETE /api/accounts/
│   ├── sync.py               # POST /api/sync/{alias}
│   │                         # GET  /api/sync/{alias}/stream (SSE)
│   │                         # GET  /api/sync/{alias}/status
│   ├── users.py              # GET /api/users/{alias}
│   │                         # GET /api/users/{alias}/stats
│   └── filters.py            # (planned) CRUD for saved FilterSets
│                             # POST /api/filters/{alias}/execute
│
├── db/
│   ├── models.py             # Tortoise ORM models (TrackedUser, FollowEdge,
│   │                         #   FilterSet, SavedAccount, SyncRun)
│   └── queries.py            # build_query() extended to execute condition trees
│
├── templates/
│   └── index.html            # Single HTML shell
│
└── static/
    ├── css/app.css           # All styles
    └── js/app.js             # All frontend logic
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves the HTML dashboard |
| GET | `/graph` | (planned) D3 force-directed graph view |
| GET | `/api/accounts/` | List saved accounts |
| POST | `/api/accounts/` | Add account |
| DELETE | `/api/accounts/{alias}` | Remove account |
| POST | `/api/sync/{alias}` | Trigger background sync |
| GET | `/api/sync/{alias}/stream` | SSE progress stream |
| GET | `/api/sync/{alias}/status` | Latest sync run status |
| GET | `/api/users/{alias}` | Filtered/sorted/paginated user list |
| GET | `/api/users/{alias}/stats` | Summary counts |
| GET | `/api/filters/{alias}` | (planned) List saved FilterSets |
| POST | `/api/filters/{alias}` | (planned) Create FilterSet |
| PUT | `/api/filters/{alias}/{id}` | (planned) Update FilterSet |
| DELETE | `/api/filters/{alias}/{id}` | (planned) Delete FilterSet |
| POST | `/api/filters/{alias}/{id}/execute` | (planned) Run a FilterSet query |
| GET | `/api/graph/{alias}` | (planned) Graph data for D3 rendering |
| GET | `/health` | Health check |
| GET | `/docs` | Swagger UI |

---

## Key Design Decisions

### FlowRank (not "PageRank")
The network influence metric is computed locally via NetworkX and named **FlowRank** to avoid trademark issues. It captures influence flowing through the follow graph, analogous in concept to PageRank but computed on our local subgraph only.

### DID-Based Relationship Detection
`they_follow_me` is determined by scanning an account's follower list for the owner's DID rather than using a convenience API endpoint. DIDs are canonical and permanent; handles can change. This is more robust and works entirely via the public API.

### No Firehose
The app deliberately does not implement a firehose subscription. See Sync Strategy above.

### Pull-Based Differential Sync
Re-syncs skip accounts whose `last_analyzed_at` is within the staleness threshold. This makes repeated syncs fast and API-budget-efficient.

### Public API for Graph Crawl
Follow/follower list fetching for graph expansion uses `public.api.bsky.app` (unauthenticated, 30s CDN cache, no published rate limit). This preserves the authenticated API budget for owner-relative operations and write ops.

### SQLite + NetworkX (not a graph database)
SQLite remains the source of truth. NetworkX is used periodically for graph metric computation, with results stored back as columns. This avoids new infrastructure while enabling real graph algorithms. A graph DB (e.g. Kuzu) can be introduced later if the graph exceeds NetworkX's practical limits.

### Crawl Budget Over Fixed Depth
Rather than crawling to a fixed depth, the crawler is priority-queue-driven and budget-bounded. Depth 3+ triggers a confirmation dialog with concrete estimates. Default size budget is 1 GB.

---

## Known Compatibility Notes

- **Tortoise ORM v1.x:** requires `RegisterTortoise` context manager; global `Tortoise.init()` no longer works
- **Starlette 0.36+:** `TemplateResponse(request, "template.html")` — request is first positional arg
- **Windows:** requires `tzdata` PyPI package
- **Python 3.14:** fully compatible with all dependencies as of current versions

---

## Planned / Not Yet Implemented

- **Graph crawl queue** (`analyzer/crawl.py`) — priority-based, persisted, budget-bounded
- **NetworkX metrics** (`analyzer/metrics.py`) — FlowRank, clustering, community detection
- **`follow_edges` table** — foundation for all graph analysis
- **Custom FilterSets** — block-based UI condition builder + JSON tree backend
- **Write operations** — unfollow, mute, block (stubs exist in `BskyClient`)
- **Bulk actions** — multi-select + batch write from filtered views
- **D3 force-directed graph view** — `/graph` route
- **Rate limit UI gauges** — authenticated read budget + write point budgets
- **Historical trend tracking** — snapshots for follower growth, activity changes
- **Scheduled auto-sync** — background timer (APScheduler or similar)
- **Export to CSV**
- **Aerich migrations** — currently using `generate_schemas(safe=True)`

---

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