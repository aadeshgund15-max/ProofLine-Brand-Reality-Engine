"""Environment-driven configuration. Secrets only ever come from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load the project root .env for local development without overriding process env vars.
load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str
    auth_mode: str                 # 'supabase' | 'local'
    supabase_url: str
    supabase_jwt_secret: str
    supabase_service_key: str
    local_jwt_secret: str
    storage_bucket: str
    storage_dir: str               # used when Supabase storage is not configured
    max_upload_bytes: int
    max_url_bytes: int
    url_timeout_s: float
    cors_origins: list[str]
    review_rate_per_min: int


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", ""),
        auth_mode=os.getenv("AUTH_MODE", "supabase" if os.getenv("SUPABASE_URL") else "local").lower(),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET", ""),
        supabase_service_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        local_jwt_secret=os.getenv("LOCAL_JWT_SECRET", ""),
        storage_bucket=os.getenv("STORAGE_BUCKET", "submissions"),
        storage_dir=os.getenv("STORAGE_DIR", "./.storage"),
        max_upload_bytes=_int("MAX_UPLOAD_MB", 15) * 1024 * 1024,
        max_url_bytes=_int("MAX_URL_FETCH_MB", 2) * 1024 * 1024,
        url_timeout_s=float(os.getenv("URL_FETCH_TIMEOUT_S", "10")),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        review_rate_per_min=_int("REVIEW_RATE_PER_MIN", 20),
    )


settings = load_settings()
