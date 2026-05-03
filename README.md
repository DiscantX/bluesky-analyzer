# Bluesky Analyzer

A local web app for analysing and sorting your Bluesky follows/followers.

## Stack

- **FastAPI** — async Python web framework
- **Uvicorn** — ASGI server
- **Tortoise ORM + SQLite** — persistent local database (no server required)
- **atproto** — official Bluesky/AT Protocol Python client
- **keyring** — system keychain for credential storage (never writes passwords to disk)

---

## Setup

```bash
# 1. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python main.py
```

The app opens in your browser automatically at `http://127.0.0.1:8000`.

---

## First Run

1. Click **+ Account** in the top bar
2. Enter an alias (e.g. `main`), your handle, and an **App Password**
   - Generate one at: **Settings → Privacy & Security → App Passwords**
   - Your password is stored in the system keychain only — never written to disk
3. Click **↺ Sync** to fetch and analyse your network
   - A progress bar streams live updates while the sync runs in the background
   - A full sync of 200 follows takes roughly 2–3 minutes (rate-limit safe)

---

## Multiple Accounts

Click **+ Account** again and add a second alias (e.g. `alt`).  
Switch between accounts using the pills in the top bar.

---

## Usage

```
python main.py                        # default: 127.0.0.1:8000, opens browser
python main.py --port 9000            # custom port
python main.py --no-browser           # don't auto-open browser
python main.py --reload               # hot-reload for development
```

---

## Views

| View | Shows |
|---|---|
| All Follows | Everyone you follow |
| ⏸ Inactive | Follows with no posts in 90+ days |
| 🔁 Repost Heavy | Follows where 70%+ of recent posts are reposts |
| ↗ One-Sided | You follow them, they don't follow back |
| ↙ Followers Only | They follow you, you don't follow them |
| 💤 No Interactions | Follows that have never interacted with your posts |

All views support **search**, **sort** (by any column), and are backed by the local SQLite DB — no re-fetching needed after the initial sync.

---

## Project Structure

```
bluesky_analyzer/
├── main.py                   # FastAPI app, routes, startup
├── config.py                 # Credential management (keychain + accounts.json)
├── requirements.txt
│
├── analyzer/
│   ├── client.py             # atproto wrapper (session persistence, rate limits)
│   ├── fetch.py              # Async paginated fetching
│   ├── analyze.py            # Feed stat computation (pure functions)
│   └── sync.py               # Sync orchestration + SSE progress events
│
├── db/
│   ├── models.py             # Tortoise ORM models
│   └── queries.py            # Reusable filter/sort query builders
│
├── api/
│   ├── accounts.py           # CRUD for saved accounts
│   ├── sync.py               # Sync trigger + SSE stream
│   └── users.py              # Tracked user queries (filter/sort/paginate)
│
├── templates/
│   └── index.html            # Single-page HTML shell
│
└── static/
    ├── css/app.css           # All styles
    └── js/app.js             # All frontend logic
```

---

## API

FastAPI generates interactive docs automatically:

- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

---

## Rate Limits

The app is designed to stay well within Bluesky's API limits:

- Max **5 concurrent** requests (semaphore-controlled)
- Automatic **exponential backoff** on 429 responses
- **Session persistence** — avoids repeated `createSession` calls
- Sync runs in the **background** — the UI stays responsive throughout

---

## Planned Features

- Write operations (unfollow, mute, block) with bulk actions
- Scheduled auto-sync
- Historical trend tracking (follower growth, activity changes over time)
- Export to CSV
