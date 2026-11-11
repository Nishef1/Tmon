"""Process settings (secrets, endpoints) from the environment.

Market rules live in the ``market_rules`` table and engine parameters in
``config/engine.yaml``; nothing of that kind belongs here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TMON_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://tmon:tmon@localhost:5432/tmon"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "tmon"
    minio_secret_key: str = "tmon-dev-secret"
    minio_secure: bool = False
    minio_raw_bucket: str = "raw-payloads"
    minio_artifact_bucket: str = "artifacts"

    # "minio" (default, Docker Compose) or "file" (no-Docker local runs: payloads and model
    # artifacts are written under object_store_dir).
    object_store: str = "minio"
    object_store_dir: Path = Path("data/objects")

    engine_config_path: Path = Field(default=BACKEND_ROOT / "config" / "engine.yaml")

    # Ingestion etiquette (per domain; see docs/02-data-sources.md).
    http_min_interval_seconds: float = 1.0
    http_max_retries: int = 5
    http_timeout_seconds: float = 30.0
    http_user_agent: str = "tmon-research-bot/0.1"
    # Optional proxy supplied by the operator (e.g. a network route that can reach Iranian hosts).
    http_proxy: str | None = None
    # Intraday polling is limited to the exchange's trading hours (market_rules.trading_hours).
    intraday_interval_seconds: float = 30.0
    book_top_n: int = 15
    # Days the scheduler wakes the ingest jobs (scheduling only; whether a day was a trading day is
    # derived from data into trading_calendar). Celery day names.
    schedule_days: str = "sat,sun,mon,tue,wed"
    # TSETMC hosts. Overridable so a mirror, a tunnel or the local stand-in server
    # (tmon.devtools.fake_tsetmc) can be used without touching code.
    tsetmc_old_url: str = "http://old.tsetmc.com"
    tsetmc_cdn_url: str = "http://cdn.tsetmc.com"

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
