from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from tmon.api.routers import (
    columns,
    dashboard,
    data_health,
    freshness,
    industries,
    instruments,
    macro,
    market,
    picks,
    portfolios,
    ranking,
    research,
    screener,
    search,
)
from tmon.core.config import get_settings
from tmon.core.db import session_scope

log = logging.getLogger(__name__)


def _warm_columns() -> None:
    """Builds the derived-columns table once at start, off the request path. Without it the first
    stock page after every restart waits for the whole build (a minute or more on the server)."""
    try:
        with session_scope() as session:
            columns.table_for(session)
    except Exception:
        log.warning("warm-up of the derived columns failed", exc_info=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    threading.Thread(target=_warm_columns, name="warm-columns", daemon=True).start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tmon API", version="0.1.0", docs_url="/docs", redoc_url=None, lifespan=_lifespan
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def never_cache(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Answers describe the market right now: no browser, proxy or framework may keep one."""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for r in (
        instruments.router,
        dashboard.router,
        freshness.router,
        data_health.router,
        picks.router,
        macro.router,
        screener.router,
        search.router,
        market.router,
        industries.router,
        columns.router,
        ranking.router,
        research.router,
        portfolios.router,
    ):
        app.include_router(r)
    return app


app = create_app()
