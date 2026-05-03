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
import logging
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

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data.db"

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
    # RegisterTortoise manages init, schema creation, and teardown.
    # It properly sets up the TortoiseContext required by Tortoise ORM v1.x.
    async with RegisterTortoise(
        app,
        config=TORTOISE_CONFIG,
        generate_schemas=True,
        add_exception_handlers=True,
    ):
        logger.info(f"Database ready at {DB_PATH}")

        # Sync accounts.json -> DB on every startup so manually edited
        # accounts files are picked up automatically.
        try:
            import config as cfg
            from db.models import SavedAccount
            for acc in cfg.list_saved_accounts():
                await SavedAccount.update_or_create(
                    defaults={"handle": acc["handle"]},
                    alias=acc["alias"],
                )
        except Exception as e:
            logger.warning(f"Could not sync accounts.json to DB: {e}")

        yield  # server runs here

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

# Static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(accounts_router)
app.include_router(sync_router)
app.include_router(users_router)

# ── Page route ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

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
    parser = argparse.ArgumentParser(description="Bluesky Analyzer local server")
    parser.add_argument("--host",       default="127.0.0.1")
    parser.add_argument("--port",       type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't automatically open the browser")
    parser.add_argument("--reload",     action="store_true",
                        help="Enable hot-reload (development mode)")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    logger.info(f"Starting Bluesky Analyzer at {url}")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()