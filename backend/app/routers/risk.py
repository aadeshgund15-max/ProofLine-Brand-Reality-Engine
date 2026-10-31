"""Unified, evidence-backed queue for unresolved review findings and web changes."""
from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.auth import Member, member_of
from app.db import get_conn, q

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


@router.get("/risk-queue")
def risk_queue(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    findings = q(conn, """select 'finding' item_type,f.id item_id,s.title source_label,s.id source_id,
                              f.title,f.explanation,f.severity,f.verification_status assessment,f.status,
                              f.created_at,coalesce(d.risk_score,0) risk_score,d.outcome automated_outcome,
                              (select count(*) from finding_evidence e where e.finding_id=f.id) evidence_count
                       from findings f join review_runs r on r.id=f.review_run_id
                       join submission_versions sv on sv.id=f.submission_version_id
                       join submissions s on s.id=sv.submission_id
                       left join automated_decisions d on d.review_run_id=r.id
                       where f.workspace_id=:w and f.status in ('open','needs_investigation')""", w=m.workspace_id)
    changes = q(conn, """select 'monitoring_change' item_type,c.id item_id,s.label source_label,s.id source_id,
                             c.change_summary title,c.change_excerpt explanation,'medium' severity,
                             coalesce(r.status,'needs_review') assessment,c.status,c.created_at,
                             coalesce(r.risk_score,100) risk_score,coalesce(r.outcome,'on_hold') automated_outcome,
                             0 evidence_count
                      from monitoring_changes c join monitored_sources s on s.id=c.monitored_source_id
                      left join monitoring_change_reviews r on r.change_id=c.id
                      where c.workspace_id=:w and c.status='open'""", w=m.workspace_id)
    items = findings + changes
    items.sort(key=lambda x: (x.get("risk_score", 0), x.get("created_at")), reverse=True)
    return items[:200]
