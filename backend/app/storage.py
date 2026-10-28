"""Private storage for original uploads. Supabase Storage (private bucket, service key) when
configured; otherwise a local directory that is never served statically. Downloads always go
through an authenticated API route that checks workspace membership."""
from __future__ import annotations

import pathlib
import re
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

from app.config import settings


class StorageError(RuntimeError):
    """A safe, actionable error returned by the configured object store."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Supabase Storage rejected the upload ({status_code}): {detail}")
        self.status_code = status_code


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "file"


def _use_supabase() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def put(key: str, data: bytes, content_type: str) -> str:
    key = "/".join(_safe(p) for p in key.split("/"))
    if _use_supabase():
        headers = {
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "apikey": settings.supabase_service_key,
            "Content-Type": content_type or "application/octet-stream",
            "x-upsert": "false",
        }
        r = httpx.post(f"{settings.supabase_url}/storage/v1/object/{settings.storage_bucket}/{key}", content=data,
                       headers=headers,
                       timeout=30)
        if r.is_error:
            try:
                detail = r.json().get("message") or r.json().get("error") or "unknown storage error"
            except ValueError:
                detail = "unknown storage error"
            raise StorageError(r.status_code, str(detail)[:240])
        return key
    base = pathlib.Path(settings.storage_dir).resolve()
    path = (base / key).resolve()
    if base not in path.parents:
        raise ValueError("invalid storage key")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def get(key: str) -> Optional[bytes]:
    if _use_supabase():
        r = httpx.get(f"{settings.supabase_url}/storage/v1/object/{settings.storage_bucket}/{key}",
                      headers={"Authorization": f"Bearer {settings.supabase_service_key}"}, timeout=30)
        return r.content if r.status_code == 200 else None
    base = pathlib.Path(settings.storage_dir).resolve()
    path = (base / key).resolve()
    if base not in path.parents or not path.is_file():
        return None
    return path.read_bytes()
