from __future__ import annotations

from fastapi import FastAPI
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
