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
import json as _json
import logging
import sqlite3
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import config
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tortoise.contrib.fastapi import RegisterTortoise

from api.accounts import router as accounts_router
from api.sync import router as sync_router
from api.users import router as users_router
from api.filters import router as filters_router
from api.api_settings import router as settings_router
from api.graph import router as graph_router
from api.charts import router as charts_router
import analyzer.worker as worker_module
from analyzer.manager import running_tasks

# ── Logging ───────────────────────────────────────────────────────────────────
class LogTruncator(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str) and len(record.msg) > 180:
            record.msg = record.msg[:177] + "..."
        return True

class BusLogHandler(logging.Handler):
    def emit(self, record):
        from analyzer.manager import current_alias_var, current_op_var, bus
        alias = current_alias_var.get()
        op = current_op_var.get()
        if alias and record.name.startswith(("httpx", "httpcore")):
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(bus.emit(alias, {
                        "kind": "progress",
                        "operation": op,
                        "message": record.getMessage(),
                        "is_heartbeat": True
                    }))
                )
            except RuntimeError:
                pass

class TerminalLibraryFilter(logging.Filter):
    def filter(self, record):
        if record.name.startswith(("httpx", "httpcore", "uvicorn.access")) and record.levelno < logging.WARNING:
            return False
        return True

root_logger = logging.getLogger()
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

logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH = config.DB_PATH
BASE_DIR = DB_PATH.parent


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
        NEW_GLOBAL_SETTINGS_COLUMNS = {
            "inactivity_threshold_days":        "INTEGER NOT NULL DEFAULT 90",
            "repost_ratio_threshold":           "REAL NOT NULL DEFAULT 0.70",
            "feed_sample_size":                 "INTEGER NOT NULL DEFAULT 100",
            "sync_staleness_hours":             "INTEGER NOT NULL DEFAULT 12",
            "worker_sweep_interval_seconds":    "INTEGER NOT NULL DEFAULT 300",
            "disable_internal_rate_limits":     "INTEGER NOT NULL DEFAULT 0",
            "ignore_staleness_threshold_days":  "INTEGER NOT NULL DEFAULT 0",
            "feed_fetch_concurrency":           "INTEGER NOT NULL DEFAULT 15",
            "staleness_tier2_days":             "INTEGER NOT NULL DEFAULT 3",
            "staleness_tier1_days":             "INTEGER NOT NULL DEFAULT 7",
            "staleness_tier0_days":             "INTEGER NOT NULL DEFAULT 30",
            "api_max_retries":                  "INTEGER NOT NULL DEFAULT 4",
            "api_base_backoff_seconds":         "REAL NOT NULL DEFAULT 2.0",
            "api_polite_delay_ms":              "INTEGER NOT NULL DEFAULT 10",
            "crawl_concurrency":                "INTEGER NOT NULL DEFAULT 3",
            "min_connection_threshold":         "INTEGER NOT NULL DEFAULT 3",
            "crawl_budget_mb":                  "INTEGER NOT NULL DEFAULT 1024",
            "crawl_hydration_concurrency":      "INTEGER NOT NULL DEFAULT 5",
            "profile_analysis_batch_size":                  "INTEGER NOT NULL DEFAULT 30",
            "profile_analysis_staleness_days":              "INTEGER NOT NULL DEFAULT 7",
            "profile_analysis_inter_batch_sleep_seconds":   "REAL NOT NULL DEFAULT 2.0",
            "profile_analysis_idle_sleep_seconds":          "REAL NOT NULL DEFAULT 60.0",
            "clustering_top_n":     "INTEGER NOT NULL DEFAULT 1000",
            "louvain_max_nodes":    "INTEGER NOT NULL DEFAULT 10000",
            "louvain_resolution":   "REAL NOT NULL DEFAULT 1.0",
            "bio_keyword_weight":               "INTEGER NOT NULL DEFAULT 5",
            "community_keywords_node_sample":   "INTEGER NOT NULL DEFAULT 100",
            "community_keywords_staleness_days":"INTEGER NOT NULL DEFAULT 30",
            "label_prop_max_nodes":             "INTEGER NOT NULL DEFAULT 500000",
            "disable_startup_sync":             "INTEGER NOT NULL DEFAULT 0",
            "turbo_mode_manual":                "INTEGER NOT NULL DEFAULT 0",
            "auto_turbo_enabled":               "INTEGER NOT NULL DEFAULT 1",
            "turbo_inactivity_threshold_mins":  "INTEGER NOT NULL DEFAULT 5",
            "turbo_concurrency":                "INTEGER NOT NULL DEFAULT 25",
            "turbo_profile_analysis_batch_size":"INTEGER NOT NULL DEFAULT 100",
            "turbo_feed_fetch_concurrency":     "INTEGER NOT NULL DEFAULT 25",
        }

        columns_gs = {row[1] for row in conn.execute("PRAGMA table_info(global_settings)").fetchall()}
        if columns_gs:
            for name, sql_type in NEW_GLOBAL_SETTINGS_COLUMNS.items():
                if name not in columns_gs:
                    conn.execute(f"ALTER TABLE global_settings ADD COLUMN {name} {sql_type}")

        exists = conn.execute("SELECT 1 FROM global_settings WHERE id = 1").fetchone()
        if not exists:
            conn.execute("INSERT INTO global_settings (id) VALUES (1)")

        cleanup_updates = [
            "worker_sweep_interval_seconds = 300 WHERE worker_sweep_interval_seconds < 30 OR worker_sweep_interval_seconds IS NULL",
            "inactivity_threshold_days = 90 WHERE inactivity_threshold_days = 0 OR inactivity_threshold_days IS NULL",
            "feed_sample_size = 100 WHERE feed_sample_size = 0 OR feed_sample_size IS NULL",
            "sync_staleness_hours = 12 WHERE sync_staleness_hours = 0 OR sync_staleness_hours IS NULL",
            "feed_fetch_concurrency = 15 WHERE feed_fetch_concurrency = 0 OR feed_fetch_concurrency IS NULL",
            "crawl_concurrency = 3 WHERE crawl_concurrency = 0 OR crawl_concurrency IS NULL",
            "profile_analysis_batch_size = 30 WHERE profile_analysis_batch_size = 0 OR profile_analysis_batch_size IS NULL",
            "louvain_resolution = 1.0 WHERE louvain_resolution < 0.1 OR louvain_resolution IS NULL",
            "louvain_max_nodes = 10000 WHERE louvain_max_nodes < 1000 OR louvain_max_nodes IS NULL",
            "clustering_top_n = 1000 WHERE clustering_top_n < 100 OR clustering_top_n IS NULL",
            "bio_keyword_weight = 5 WHERE bio_keyword_weight < 1 OR bio_keyword_weight IS NULL",
            "community_keywords_node_sample = 100 WHERE community_keywords_node_sample < 10 OR community_keywords_node_sample IS NULL",
            "community_keywords_staleness_days = 30 WHERE community_keywords_staleness_days < 1 OR community_keywords_staleness_days IS NULL",
            "label_prop_max_nodes = 500000 WHERE label_prop_max_nodes < 10000 OR label_prop_max_nodes IS NULL",
        ]
        for update in cleanup_updates:
            conn.execute(f"UPDATE global_settings SET {update}")

        # ── chart_definitions — safe incremental columns ───────────────────
        try:
            columns_cd = {row[1] for row in conn.execute("PRAGMA table_info(chart_definitions)").fetchall()}
            if columns_cd:
                for col, typ in {
                    "description": "TEXT",
                    "filter_tree": "TEXT",
                    "aggregation": "TEXT",
                    "options":     "TEXT",
                    "pin_order":   "INTEGER",
                }.items():
                    if col not in columns_cd:
                        conn.execute(f"ALTER TABLE chart_definitions ADD COLUMN {col} {typ}")
        except Exception:
            pass

        conn.commit()
    finally:
        conn.close()

# ── CLI Arguments ─────────────────────────────────────────────────────────────
def parse_cli_args():
    parser = argparse.ArgumentParser(description="Bluesky Analyzer local server")
    parser.add_argument("--host",       default="127.0.0.1")
    parser.add_argument("--port",       type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-sync-on-startup", action="store_true")
    parser.add_argument("--ignore-staleness-threshold", type=int, default=0)
    parser.add_argument("--reload",     action="store_true")
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
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.commit()
        conn.close()

        logger.info(f"Database ready at {DB_PATH}")

        from db.models import GlobalSettings, SavedAccount
        settings, _ = await GlobalSettings.get_or_create(id=1)
        from settings_cache import settings_cache
        await settings_cache.refresh()
        if app.state.args.ignore_staleness_threshold > 0:
            settings.ignore_staleness_threshold_days = app.state.args.ignore_staleness_threshold
            await settings.save()

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
app.include_router(charts_router)

# ── Client logging ────────────────────────────────────────────────────────────
@app.post("/api/client-log")
async def client_log(request: Request):
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
    """Legacy redirect → Chart Studio force_directed chart."""
    from fastapi.responses import RedirectResponse as _RR
    from db.models import ChartDefinition, SavedAccount as _SA
    owner = await _SA.get_or_none(alias=alias)
    if owner:
        chart = await ChartDefinition.filter(
            owner=owner, chart_type="force_directed"
        ).order_by("pin_order", "created_at").first()
        if chart:
            return _RR(f"/charts/{alias}/{chart.id}/view")
    return _RR(f"/charts/{alias}")

@app.get("/hive/{alias}", response_class=HTMLResponse)
async def hive_view(request: Request, alias: str):
    """Legacy redirect → Chart Studio hive chart."""
    from fastapi.responses import RedirectResponse as _RR
    from db.models import ChartDefinition, SavedAccount as _SA
    owner = await _SA.get_or_none(alias=alias)
    if owner:
        chart = await ChartDefinition.filter(
            owner=owner, chart_type="hive"
        ).order_by("created_at").first()
        if chart:
            return _RR(f"/charts/{alias}/{chart.id}/view")
    return _RR(f"/charts/{alias}")

@app.get("/pack/{alias}", response_class=HTMLResponse)
async def pack_view(request: Request, alias: str):
    """Legacy redirect → Chart Studio circle_packing chart."""
    from fastapi.responses import RedirectResponse as _RR
    from db.models import ChartDefinition, SavedAccount as _SA
    owner = await _SA.get_or_none(alias=alias)
    if owner:
        chart = await ChartDefinition.filter(
            owner=owner, chart_type="circle_packing"
        ).order_by("created_at").first()
        if chart:
            return _RR(f"/charts/{alias}/{chart.id}/view")
    return _RR(f"/charts/{alias}")

# ── Chart Studio page routes ──────────────────────────────────────────────────
@app.get("/charts/{alias}", response_class=HTMLResponse)
async def charts_gallery(request: Request, alias: str):
    return templates.TemplateResponse(request, "charts.html", {"alias": alias})

@app.get("/charts/{alias}/new", response_class=HTMLResponse)
async def chart_new(request: Request, alias: str):
    return templates.TemplateResponse(request, "chart_studio.html", {
        "alias":        alias,
        "title":        "New Chart",
        "chart_id":     None,
        "chart_name":   "Untitled Chart",
        "chart_icon":   "📊",
        "initial_data": {},
    })

@app.get("/charts/{alias}/{chart_id}/edit", response_class=HTMLResponse)
async def chart_edit(request: Request, alias: str, chart_id: int):
    from db.models import ChartDefinition, SavedAccount
    owner = await SavedAccount.get_or_none(alias=alias)
    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner) if owner else None
    if not chart:
        return templates.TemplateResponse(request, "charts.html", {"alias": alias})

    dims = _json.loads(chart.dimensions) if isinstance(chart.dimensions, str) else (chart.dimensions or {})
    ft   = _json.loads(chart.filter_tree) if isinstance(chart.filter_tree, str) and chart.filter_tree else None

    return templates.TemplateResponse(request, "chart_studio.html", {
        "alias":        alias,
        "title":        f"Edit — {chart.name}",
        "chart_id":     chart_id,
        "chart_name":   chart.name,
        "chart_icon":   chart.icon or "📊",
        "initial_data": {
            "name":           chart.name,
            "icon":           chart.icon,
            "chart_type":     chart.chart_type,
            "dimensions":     dims,
            "filter_tree":    ft,
            "filter_set_id":  getattr(chart, "filter_set_id", None),
            "aggregation":    chart.aggregation,
            "limit":          chart.limit,
            "sort_by":        chart.sort_by,
            "sort_dir":       chart.sort_dir,
        },
    })

@app.get("/charts/{alias}/{chart_id}/view", response_class=HTMLResponse)
async def chart_view_page(request: Request, alias: str, chart_id: int):
    from db.models import ChartDefinition, SavedAccount
    owner = await SavedAccount.get_or_none(alias=alias)
    chart = await ChartDefinition.get_or_none(id=chart_id, owner=owner) if owner else None
    if not chart:
        return templates.TemplateResponse(request, "charts.html", {"alias": alias})
    return templates.TemplateResponse(request, "chart_view.html", {
        "alias":      alias,
        "chart_id":   chart_id,
        "chart_name": chart.name,
        "chart_icon": chart.icon or "📊",
        "pinned":     chart.pinned,
    })

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
    args = app.state.args
    url = f"http://{args.host}:{args.port}"
    logger.info(f"Starting Bluesky Analyzer at {url}")

    if not args.no_browser:
        opener = threading.Timer(2.5, lambda: webbrowser.open(url))
        opener.start()

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
