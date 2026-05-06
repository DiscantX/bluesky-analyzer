"""
main.py
FastAPI application entry point.

Usage:
    python main.py
    python main.py --host 127.0.0.1 --port 8000 --no-browser
    python main.py --reload   (hot-reload for development)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tortoise.contrib.fastapi import RegisterTortoise

from api.accounts import router as accounts_router
from api.sync import router as sync_router
from api.users import router as users_router
from api.filters import router as filters_router
from api.settings import router as settings_router
from api.graph import router as graph_router
import analyzer.worker as worker_module
from analyzer.manager import running_tasks

# ── Logging ───────────────────────────────────────────────────────────────────
class LogTruncator(logging.Filter):
    """Truncates massive log messages to avoid terminal I/O bottlenecks."""
    def filter(self, record):
        if isinstance(record.msg, str) and len(record.msg) > 180:
            record.msg = record.msg[:177] + "..."
        return True

class BusLogHandler(logging.Handler):
    """Routes library logs to the web progress bus if an active task context exists."""
    def emit(self, record):
        from analyzer.manager import current_alias_var, current_op_var, bus
        alias = current_alias_var.get()
        op = current_op_var.get()
        # We only route HTTP library logs to the web view to provide a "heartbeat"
        if alias and record.name.startswith(("httpx", "httpcore")):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(bus.emit(alias, {
                    "kind": "progress",
                    "operation": op,
                    "message": record.getMessage(),
                    "is_heartbeat": True
                }))
            except RuntimeError:
                pass

class TerminalLibraryFilter(logging.Filter):
    """Hides verbose library logs from the terminal while letting them flow to the bus."""
    def filter(self, record):
        if record.name.startswith(("httpx", "httpcore", "uvicorn.access")) and record.levelno < logging.WARNING:
            return False
        return True

root_logger = logging.getLogger()
# Clear any existing handlers to prevent duplicate logs,
# especially if basicConfig was called implicitly or by another library.
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
root_logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s", datefmt="%H:%M:%S")

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.addFilter(LogTruncator())
console_handler.addFilter(TerminalLibraryFilter())
root_logger.addHandler(console_handler)

bus_handler = BusLogHandler()
bus_handler.setFormatter(formatter)
root_logger.addHandler(bus_handler)

# Re-enable library loggers to ensure they generate records for the BusLogHandler
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data.db"


def ensure_sqlite_compat_columns() -> None:
    """Small no-migration safety net until Aerich migrations are introduced."""
    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # Update crawl_queue_items
        columns_q = {row[1] for row in conn.execute("PRAGMA table_info(crawl_queue_items)").fetchall()}
        additions_q = {
            "cursor": "TEXT",
            "pages_fetched": "INTEGER NOT NULL DEFAULT 0",
            "edges_found": "INTEGER NOT NULL DEFAULT 0",
            "hydrated_at": "TIMESTAMP NULL",
        }
        for name, sql_type in additions_q.items():
            if columns_q and name not in columns_q:
                conn.execute(f"ALTER TABLE crawl_queue_items ADD COLUMN {name} {sql_type}")

        # Update crawl_runs
        columns_r = {row[1] for row in conn.execute("PRAGMA table_info(crawl_runs)").fetchall()}
        if columns_r and "request_count" not in columns_r:
            conn.execute("ALTER TABLE crawl_runs ADD COLUMN request_count INTEGER NOT NULL DEFAULT 0")

        # Update sync_runs
        columns_sr = {row[1] for row in conn.execute("PRAGMA table_info(sync_runs)").fetchall()}
        if columns_sr and "request_count" not in columns_sr:
            conn.execute("ALTER TABLE sync_runs ADD COLUMN request_count INTEGER NOT NULL DEFAULT 0")

        # Update profiles
        columns_p = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        additions_p = {
            "description": "TEXT",
            "banner_url": "TEXT",
            "account_created_at": "TIMESTAMP NULL",
            "labels": "TEXT",
            "top_keywords": "TEXT",
        }
        for name, sql_type in additions_p.items():
            if columns_p and name not in columns_p:
                conn.execute(f"ALTER TABLE profiles ADD COLUMN {name} {sql_type}")

        # Update global_settings
        columns_gs = {row[1] for row in conn.execute("PRAGMA table_info(global_settings)").fetchall()}
        if columns_gs:
            if "disable_internal_rate_limits" not in columns_gs:
                conn.execute("ALTER TABLE global_settings ADD COLUMN disable_internal_rate_limits INT NOT NULL DEFAULT 0")
            # FIX 5: Add feed_fetch_concurrency to existing databases.
            if "ignore_staleness_threshold_days" not in columns_gs:
                conn.execute("ALTER TABLE global_settings ADD COLUMN ignore_staleness_threshold_days INTEGER NOT NULL DEFAULT 0")
            # Default 15 (3x the old hardcoded 5).
            if "feed_fetch_concurrency" not in columns_gs:
                conn.execute("ALTER TABLE global_settings ADD COLUMN feed_fetch_concurrency INTEGER NOT NULL DEFAULT 15")

        conn.commit()
    finally:
        conn.close()

# ── CLI Arguments ─────────────────────────────────────────────────────────────
def parse_cli_args():
    """
    Parse CLI arguments at the module level. We use parse_known_args 
    to ensure that uvicorn workers can import this module without 
    crashing on uvicorn's own internal CLI flags.
    """
    parser = argparse.ArgumentParser(description="Bluesky Analyzer local server")
    parser.add_argument("--host",       default="127.0.0.1")
    parser.add_argument("--port",       type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="Don't automatically open the browser")
    parser.add_argument("--skip-sync-on-startup", action="store_true", help="Skip syncing accounts.json to DB on startup")
    parser.add_argument("--ignore-staleness-threshold", type=int, default=0, help="Override staleness threshold for all accounts (in days)")
    parser.add_argument("--reload",     action="store_true", help="Enable hot-reload (development mode)")
    
    args, _ = parser.parse_known_args()
    return args

# ── Tortoise ORM config ───────────────────────────────────────────────────────
TORTOISE_CONFIG = {
    "connections": {
        "default": f"sqlite://{DB_PATH}",
    },
    "apps": {
        "models": {
            "models": ["db.models"],
            "default_connection": "default",
        }
    },
}

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app,
        config=TORTOISE_CONFIG,
        generate_schemas=True,
        add_exception_handlers=True,
    ):
        ensure_sqlite_compat_columns()
        logger.info(f"Database ready at {DB_PATH}")

        # Initialize default settings and apply CLI overrides
        from db.models import GlobalSettings, SavedAccount
        settings, _ = await GlobalSettings.get_or_create(id=1)
        if app.state.args.ignore_staleness_threshold > 0:
            settings.ignore_staleness_threshold_days = app.state.args.ignore_staleness_threshold
            await settings.save()

        # Sync accounts.json -> DB on every startup
        if not app.state.args.skip_sync_on_startup:
            try:
                import config as cfg
                for acc in cfg.list_saved_accounts():
                    await SavedAccount.update_or_create(
                        defaults={"handle": acc["handle"]},
                        alias=acc["alias"],
                    )
            except Exception as e:
                logger.warning(f"Could not sync accounts.json to DB: {e}")

        # Start background automation worker
        await worker_module.start_background_worker()

        try:
            yield
        finally:
            logger.info("Shutting down background tasks...")
            tasks = []
            if worker_module.worker_task:
                worker_module.worker_task.cancel()
                tasks.append(worker_module.worker_task)

            for alias, task in list(running_tasks.items()):
                logger.info(f"Cancelling task for {alias}")
                task.cancel()
                tasks.append(task)

            if tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Timed out waiting for background tasks to cancel.")

    logger.info("Database connections closed.")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Bluesky Analyzer",
    description="Analyse and sort your Bluesky follows/followers.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Initialize args on app.state during module import so lifespan can access them
# even when running in uvicorn worker processes or reload mode.
app.state.args = parse_cli_args()

# Static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(accounts_router)
app.include_router(sync_router)
app.include_router(users_router)
app.include_router(filters_router)
app.include_router(settings_router)
app.include_router(graph_router)

# ── Client logging ────────────────────────────────────────────────────────────
@app.post("/api/client-log")
async def client_log(request: Request):
    """Endpoint for the frontend to report errors back to the terminal."""
    try:
        data = await request.json()
        level = data.get("level", "info")
        message = data.get("message", "No message")
        context = data.get("context", {})
        log_msg = f"[Frontend] {message} | Context: {context}"
        if level == "error":
            logger.error(log_msg)
        else:
            logger.info(log_msg)
    except Exception:
        pass
    return {"status": "ok"}

# ── Page routes ───────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/graph/{alias}", response_class=HTMLResponse)
async def graph_view(request: Request, alias: str):
    return templates.TemplateResponse(request, "graph.html", {"alias": alias})

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

# ── Favicon ───────────────────────────────────────────────────────────────────
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    path = BASE_DIR / "favicon.ico"
    if path.exists():
        return FileResponse(path)
    return HTMLResponse(status_code=204)


# ── CLI entry point ───────────────────────────────────────────────────────────
def main():
    # Access the arguments already parsed during module import
    args = app.state.args

    url = f"http://{args.host}:{args.port}"
    logger.info(f"Starting Bluesky Analyzer at {url}")

    if not args.no_browser:
        opener = threading.Timer(1.5, lambda: webbrowser.open(url))
        opener.daemon = True
        opener.start()

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        log_config=None, # Prevent uvicorn from overriding our custom log routing
        access_log=False,
    )


if __name__ == "__main__":
    main()