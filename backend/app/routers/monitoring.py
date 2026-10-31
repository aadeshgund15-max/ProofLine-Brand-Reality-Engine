"""Register and inspect scheduled public-page monitoring sources."""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Connection

from app import auth
from app.audit import audit
from app.auth import Member, member_of
from app.core.ssrf import FetchError, UnsafeUrlError, validate_url
from app.db import ex, get_conn, q, q1

router = APIRouter(prefix="/api/workspaces/{workspace_id}/monitoring")


class SourceIn(BaseModel):
    brand_profile_id: UUID
    product_id: Optional[UUID] = None
    url: str = Field(min_length=8, max_length=2048)
    label: str = Field(min_length=1, max_length=120)
    interval_minutes: int = Field(default=60, ge=15, le=10080)

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value: str):
        if not value.strip():
            raise ValueError("A source label is required")
        return value.strip()


class SourcePatch(BaseModel):
    url: Optional[str] = Field(default=None, min_length=8, max_length=2048)
    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    interval_minutes: Optional[int] = Field(default=None, ge=15, le=10080)
    product_id: Optional[UUID] = None
    status: Optional[Literal["active", "paused", "removed"]] = None

    @model_validator(mode="after")
    def _has_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one source setting to update")
        return self

    @field_validator("label")
    @classmethod
    def nonblank_patch_label(cls, value: Optional[str]):
        if value is not None and not value.strip():
            raise ValueError("A source label cannot be blank")
        return value.strip() if value is not None else None


class ChangeStatus(BaseModel):
    status: Literal["reviewed", "dismissed"]
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str):
        if len(value.strip()) < 3:
            raise ValueError("A rationale of at least three characters is required")
        return value.strip()


def _safe_url(url: str) -> str:
    try:
        return validate_url(url).url
    except (UnsafeUrlError, FetchError) as exc:
        raise HTTPException(422, f"This monitoring URL is not allowed: {exc}") from exc


@router.get("/sources")
def list_sources(include_removed: bool = False, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select s.id,s.brand_profile_id,s.product_id,p.product_name,s.url,s.label,s.interval_minutes,s.status,s.last_checked_at,
                             s.next_check_at,s.failure_count,s.created_at,
                             (select count(*) from monitoring_snapshots p where p.monitored_source_id=s.id) snapshot_count,
                             (select count(*) from monitoring_changes c where c.monitored_source_id=s.id and c.status='open') open_changes
                      from monitored_sources s left join products p on p.id=s.product_id
                      where s.workspace_id=:w and (:all or s.status<>'removed')
                      order by s.created_at desc""", w=m.workspace_id, all=include_removed)


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id=:p and workspace_id=:w", p=body.brand_profile_id, w=m.workspace_id):
        raise HTTPException(404, "Brand profile not found")
    if body.product_id and not q1(conn, "select 1 from products where id=:p and workspace_id=:w and brand_profile_id=:b",
                                  p=body.product_id, w=m.workspace_id, b=body.brand_profile_id):
        raise HTTPException(422, "The linked product must belong to this workspace and brand profile.")
    url = _safe_url(body.url)
    existing = q1(conn, """select id from monitored_sources where workspace_id=:w and status<>'removed'
                          and lower(url)=lower(:url) limit 1""", w=m.workspace_id, url=url)
    if existing:
        raise HTTPException(409, "This URL is already monitored in the workspace. Edit the existing source instead.")
    active_count = q1(conn, "select count(*) n from monitored_sources where workspace_id=:w and status<>'removed'",
                      w=m.workspace_id)["n"]
    if active_count >= 100:
        raise HTTPException(409, "A workspace can monitor up to 100 public sources.")
    row = q1(conn, """insert into monitored_sources(workspace_id,brand_profile_id,product_id,url,label,interval_minutes,created_by)
                      values (:w,:p,:product,:url,:label,:i,:u)
                      returning id,brand_profile_id,product_id,url,label,interval_minutes,status,last_checked_at,next_check_at,created_at""",
             w=m.workspace_id, p=body.brand_profile_id, product=body.product_id, url=url,
             label=body.label.strip(), i=body.interval_minutes, u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "monitor.source_added", "monitored_source", row["id"],
          f"Public source registered: {body.label.strip()}", {"interval_minutes": body.interval_minutes})
    return row


@router.patch("/sources/{source_id}")
def update_source(source_id: UUID, body: SourcePatch, m: Member = Depends(member_of(*auth.EDIT_ROLES)),
                  conn: Connection = Depends(get_conn)):
    old = q1(conn, "select * from monitored_sources where id=:id and workspace_id=:w for update", id=source_id, w=m.workspace_id)
    if not old:
        raise HTTPException(404, "Monitored source not found")
    url = _safe_url(body.url) if body.url else old["url"]
    product_id = body.product_id if "product_id" in body.model_fields_set else old.get("product_id")
    if product_id and not q1(conn, "select 1 from products where id=:p and workspace_id=:w and brand_profile_id=:b",
                             p=product_id, w=m.workspace_id, b=old["brand_profile_id"]):
        raise HTTPException(422, "The linked product must belong to this workspace and source brand profile.")
    label = body.label.strip() if body.label else old["label"]
    interval = body.interval_minutes or old["interval_minutes"]
    status = body.status or old["status"]
    activate = status == "active" and old["status"] != "active"
    url_changed = url != old["url"]
    row = q1(conn, """update monitored_sources set url=:url,label=:label,interval_minutes=:i,status=:st,product_id=:p,
                      next_check_at=case when :activate or :url_changed then now() else next_check_at end,
                      lease_until=case when :activate then null else lease_until end
                      where id=:id returning id,url,label,interval_minutes,status,product_id,last_checked_at,next_check_at""",
             url=url, label=label, i=interval, st=status, p=product_id, activate=activate, url_changed=url_changed, id=source_id)
    audit(conn, m.workspace_id, m.user.id, "monitor.source_updated", "monitored_source", source_id,
          f"Monitoring source updated: {label}", {"status": status, "interval_minutes": interval})
    return row


@router.post("/sources/{source_id}/check", status_code=202)
def check_now(source_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    row = q1(conn, """update monitored_sources set next_check_at=now()
                      where id=:id and workspace_id=:w and status='active'
                      returning id""", id=source_id, w=m.workspace_id)
    if not row:
        if not q1(conn, "select 1 from monitored_sources where id=:id and workspace_id=:w", id=source_id, w=m.workspace_id):
            raise HTTPException(404, "Monitored source not found")
        raise HTTPException(409, "Resume this source before requesting a check")
    audit(conn, m.workspace_id, m.user.id, "monitor.check_requested", "monitored_source", source_id,
          "A one-time monitoring check was queued", {})
    return {"source_id": source_id, "status": "queued"}


@router.get("/changes")
def list_changes(status: str = Query("open", pattern="^(open|reviewed|dismissed|all)$"),
                 m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select c.id,c.monitored_source_id,s.label,s.url,c.previous_snapshot_id,c.current_snapshot_id,
                             p.version_no previous_version,n.version_no current_version,c.change_summary,c.change_excerpt,c.status,c.created_at,
                             r.status review_status,r.outcome,r.risk_score,r.report
                      from monitoring_changes c join monitored_sources s on s.id=c.monitored_source_id
                      join monitoring_snapshots p on p.id=c.previous_snapshot_id
                      join monitoring_snapshots n on n.id=c.current_snapshot_id
                      left join monitoring_change_reviews r on r.change_id=c.id
                      where c.workspace_id=:w and (:st='all' or c.status=:st)
                      order by c.created_at desc limit 200""", w=m.workspace_id, st=status)


@router.patch("/changes/{change_id}")
def update_change(change_id: UUID, body: ChangeStatus, m: Member = Depends(member_of(*auth.DECIDE_ROLES)),
                  conn: Connection = Depends(get_conn)):
    old = q1(conn, "select status from monitoring_changes where id=:id and workspace_id=:w for update", id=change_id, w=m.workspace_id)
    if not old:
        raise HTTPException(404, "Change alert not found")
    ex(conn, "update monitoring_changes set status=:st where id=:id and workspace_id=:w", st=body.status, id=change_id, w=m.workspace_id)
    audit(conn, m.workspace_id, m.user.id, "monitor.change_updated", "monitoring_change", change_id,
          f"Monitoring change marked {body.status}", {"from": old["status"], "to": body.status, "reason": body.reason})
    return {"id": change_id, "status": body.status}


@router.get("/sources/{source_id}/history")
def source_history(source_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from monitored_sources where id=:id and workspace_id=:w", id=source_id, w=m.workspace_id):
        raise HTTPException(404, "Monitored source not found")
    return {"snapshots": q(conn, "select id,version_no,final_url,fetched_at,content_hash,metadata from monitoring_snapshots where monitored_source_id=:s order by version_no desc limit 100", s=source_id),
            "runs": q(conn, "select id,status,snapshot_id,error_code,started_at,completed_at from monitoring_runs where monitored_source_id=:s order by completed_at desc limit 100", s=source_id)}
