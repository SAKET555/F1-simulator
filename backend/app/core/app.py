from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import races, simulate, ws
from app.routers import live as live_router

log = logging.getLogger(__name__)


def _build_calendar_sync() -> None:
    """Runs in a thread-pool executor so it never blocks the event loop."""
    try:
        from app.engine.calendar import build_catalogue
        races_list = build_catalogue()
        log.info("Calendar ready: %d races", len(races_list))
    except Exception as exc:
        log.error("Calendar build failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build / refresh the race calendar in a background thread at startup.
    # If calendar_cache.json already exists this returns in < 1 ms.
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(loop.run_in_executor(None, _build_calendar_sync))
    yield
    # (shutdown cleanup goes here if needed)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Real-time F1 Race & Strategy Simulator — SAK Racing Sim",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(races.router, prefix="/api")
    app.include_router(simulate.router, prefix="/api")
    app.include_router(ws.router)
    app.include_router(live_router.router)   # live F1 endpoints

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name, "version": "2.0.0"}

    return app
