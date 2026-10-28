"""Brand Time Machine queue and audit history."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from app.auth import Member, member_of
from app.db import get_conn, q, q1

router = APIRouter(prefix="/api/workspaces/{workspace_id}")

_IMPACT_SQL = """
select i.id, i.status, i.change_kind, i.created_at, i.resolved_at, i.submission_id, i.submission_version_id,
       s.title, sv.version_no flagged_version_no, cur.version_no current_version_no, cur.id current_version_id,
       coalesce(fk.key, rk.key) entity_key,
       fo.approved_value old_value, fo.version_no old_version_no, fn.approved_value new_value, fn.version_no new_version_no,
       fo.name fact_name,
       ro.description old_rule, ro.patterns old_patterns, ro.version_no old_rule_version_no,
       rn.description new_rule, rn.patterns new_patterns, rn.version_no new_rule_version_no,
       u.email resolved_by
from impact_records i
join submissions s on s.id = i.submission_id
join submission_versions sv on sv.id = i.submission_version_id
join submission_versions cur on cur.id = s.current_version_id
left join brand_facts fk on fk.id = i.fact_id
left join brand_rules rk on rk.id = i.rule_id
left join brand_fact_versions fo on i.change_kind = 'fact' and fo.id = i.old_version_id
left join brand_fact_versions fn on i.change_kind = 'fact' and fn.id = i.new_version_id
left join brand_rule_versions ro on i.change_kind = 'rule' and ro.id = i.old_version_id
left join brand_rule_versions rn on i.change_kind = 'rule' and rn.id = i.new_version_id
left join app_users u on u.id = i.resolved_by
where i.workspace_id = :w and (cast(:st as text) is null or i.status = :st)"""


@router.get("/impacts")
def list_impacts(status: Optional[str] = Query(None, pattern="^(review_required|resolved)$"),
                 m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, _IMPACT_SQL + " order by i.created_at desc limit 300", w=m.workspace_id, st=status)


@router.get("/impacts/{impact_id}")
def get_impact(impact_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    row = q1(conn, _IMPACT_SQL + " and i.id = :i", w=m.workspace_id, st=None, i=impact_id)
    if not row:
        raise HTTPException(404, "Impact record not found")
    return row


@router.get("/audit")
def list_audit(limit: int = Query(50, ge=1, le=200), before_id: Optional[int] = None, event_type: Optional[str] = None,
               m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select a.id, a.event_type, a.entity_type, a.entity_id, a.summary, a.payload, a.created_at, u.email actor
                      from audit_events a left join app_users u on u.id = a.actor_id
                      where a.workspace_id = :w and (cast(:b as bigint) is null or a.id < :b)
                        and (cast(:t as text) is null or a.event_type like :t || '%')
                      order by a.id desc limit :n""", w=m.workspace_id, b=before_id, t=event_type, n=limit)
