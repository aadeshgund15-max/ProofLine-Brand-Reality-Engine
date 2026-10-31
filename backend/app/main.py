from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Connection
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import get_conn, q1
from app.routers import impact_audit, library, monitoring, product_intelligence, reports, reviews, risk, submissions, visual, workspaces

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proofline")  # never log document text

app = FastAPI(title="Proofline API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type"])

for r in (workspaces.router, library.router, submissions.router, reviews.router, impact_audit.router, visual.router,
          monitoring.router, risk.router, product_intelligence.router, product_intelligence.links_router, reports.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError):
    # Never include the DB URL or driver exception text in a client response or logs.
    log.error("Database connection failed (%s) on %s %s", type(exc.orig).__name__, request.method, request.url.path)
    return JSONResponse(
        {"detail": "The Proofline database is unavailable. Check DATABASE_URL and network access. Supabase direct database hosts are IPv6-only by default; use the Session pooler connection string for IPv4-only networks."},
        status_code=503,
    )


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/api/health")
def health():
    return {"status": "alive"}


@app.get("/api/health/ready")
def readiness(conn: Connection = Depends(get_conn)):
    """Read-only readiness probe; never exposes the configured database identity."""
    q1(conn, "select 1")
    return {"status": "ready", "database": "connected"}
