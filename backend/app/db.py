"""Database access with SQLAlchemy Core. SQL lives next to the logic; the schema in
supabase/migrations is the source of truth."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        url = settings.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _engine


@contextmanager
def transaction() -> Iterator[Connection]:
    """One atomic unit of work: commits on success, rolls back on any exception."""
    with get_engine().begin() as conn:
        yield conn


def get_conn() -> Iterator[Connection]:
    """FastAPI dependency: a request-scoped transaction."""
    with transaction() as conn:
        yield conn


def q(conn: Connection, sql: str, **params: Any) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def q1(conn: Connection, sql: str, **params: Any) -> dict | None:
    r = conn.execute(text(sql), params).mappings().first()
    return dict(r) if r else None


def ex(conn: Connection, sql: str, **params: Any) -> None:
    conn.execute(text(sql), params)


def jb(value: Any) -> str:
    return json.dumps(value, default=str)
