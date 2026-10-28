from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Connection

from app.db import ex, jb


def audit(conn: Connection, workspace_id: UUID, actor_id: Optional[UUID], event_type: str,
          entity_type: str, entity_id: Optional[UUID], summary: str, payload: Optional[dict[str, Any]] = None) -> None:
    """Append-only audit record (a DB trigger blocks UPDATE/DELETE). Never put document text in payload."""
    ex(conn, """insert into audit_events (workspace_id, actor_id, event_type, entity_type, entity_id, summary, payload)
                values (:ws, :actor, :et, :ent, :eid, :sum, cast(:p as jsonb))""",
       ws=workspace_id, actor=actor_id, et=event_type, ent=entity_type, eid=entity_id, sum=summary,
       p=jb(payload or {}))
