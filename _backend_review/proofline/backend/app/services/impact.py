"""Brand Time Machine: create impact records inside the same transaction as the new version.

Uses recorded finding_dependencies rows only (no text search). Equivalent to
app.core.impact.resolve_impacted, which is unit-tested; this is the SQL form of it.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection

from app.audit import audit
from app.db import ex, q

_IMPACTED_SQL = """
with latest_runs as (
  select distinct on (r.submission_version_id) r.id
  from review_runs r
  join submission_versions sv on sv.id = r.submission_version_id
  join submissions s on s.id = sv.submission_id and s.current_version_id = sv.id
  where r.workspace_id = :ws and r.status in ('completed','completed_with_warnings')
  order by r.submission_version_id, r.started_at desc, r.id
)
select distinct sv.submission_id, d.submission_version_id
from finding_dependencies d
join latest_runs lr on lr.id = d.review_run_id
join submission_versions sv on sv.id = d.submission_version_id
where d.{col_id} = :eid and d.{col_ver} = :old
"""


def flag_dependents(conn: Connection, *, workspace_id: UUID, actor_id: UUID, kind: str, entity_id: UUID,
                    entity_key: str, old_version_id: UUID, new_version_id: UUID) -> int:
    col_id, col_ver = ("fact_id", "fact_version_id") if kind == "fact" else ("rule_id", "rule_version_id")
    rows = q(conn, _IMPACTED_SQL.format(col_id=col_id, col_ver=col_ver),
             ws=workspace_id, eid=entity_id, old=old_version_id)
    for r in rows:
        ex(conn, f"""insert into impact_records
              (workspace_id, submission_id, submission_version_id, change_kind, {col_id}, old_version_id,
               new_version_id, created_by)
              values (:ws, :sub, :sv, :kind, :eid, :old, :new, :actor)
              on conflict do nothing""",
           ws=workspace_id, sub=r["submission_id"], sv=r["submission_version_id"], kind=kind, eid=entity_id,
           old=old_version_id, new=new_version_id, actor=actor_id)
        audit(conn, workspace_id, actor_id, "impact.flagged", "submission", r["submission_id"],
              f"Flagged for review: {kind} “{entity_key}” changed", {
                  "change_kind": kind, "entity_id": str(entity_id), "old_version_id": str(old_version_id),
                  "new_version_id": str(new_version_id), "submission_version_id": str(r["submission_version_id"])})
    return len(rows)
