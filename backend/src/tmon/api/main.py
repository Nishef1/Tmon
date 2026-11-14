from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from tmon.api.routers import (
    dashboard,
    instruments,
    macro,
    market,
    metrics,
    picks,
    ranking,
    recommendations,
    research,
    screener,
    search,
    signals,
)
from tmon.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Tmon API", version="0.1.0", docs_url="/docs", redoc_url=None)
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
        recommendations.router,
        instruments.router,
        dashboard.router,
        signals.router,
        metrics.router,
        picks.router,
        macro.router,
        screener.router,
        search.router,
        market.router,
        ranking.router,
        research.router,
    ):
        app.include_router(r)
    return app


app = create_app()
