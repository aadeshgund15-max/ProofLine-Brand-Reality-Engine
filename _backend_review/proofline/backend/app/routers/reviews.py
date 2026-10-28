"""Review runs, findings, human decisions."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection

from app import auth
from app.audit import audit
from app.auth import Member, member_of
from app.config import settings
from app.db import ex, get_conn, q, q1
from app.providers.base import get_llm_provider, get_search_provider
from app.services.review import compute_review, load_reference_versions, persist_review, record_failed_run

router = APIRouter(prefix="/api/workspaces/{workspace_id}")
_hits: dict[str, deque] = defaultdict(deque)


def _rate_limit(user_id: str) -> None:
    now, window = time.monotonic(), _hits[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.review_rate_per_min:
        raise HTTPException(429, "Too many review requests; try again in a minute")
    window.append(now)


@router.post("/submission-versions/{version_id}/review", status_code=201)
def run_review(version_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    _rate_limit(str(m.user.id))
    sv = q1(conn, """select sv.*, s.brand_profile_id, s.title from submission_versions sv
                     join submissions s on s.id = sv.submission_id where sv.id = :v and sv.workspace_id = :w""",
            v=version_id, w=m.workspace_id)
    if not sv:
        raise HTTPException(404, "Version not found")
    if sv["extraction_status"] in ("failed", "empty", "unsupported"):
        raise HTTPException(409, f"This version cannot be reviewed because extraction {sv['extraction_status']}. "
                                 "Fix the content and submit a new version.")
    facts, rules = load_reference_versions(conn, m.workspace_id, sv["brand_profile_id"])
    brand = q1(conn, "select name from brand_profiles where id = :b", b=sv["brand_profile_id"])
    try:
        computed = compute_review(sv, facts, rules, get_search_provider(), get_llm_provider(), brand["name"] if brand else "")
    except Exception as e:  # essential stage failed: nothing partial is persisted
        run_id = record_failed_run(m.workspace_id, version_id, m.user.id, f"{type(e).__name__}")
        raise HTTPException(500, f"The review failed and was recorded as failed (run {run_id}). No findings were saved.")
    run_id = persist_review(conn, workspace_id=m.workspace_id, sv=sv, user_id=m.user.id, c=computed)
    return get_run(run_id, m, conn)


@router.get("/review-runs/{run_id}")
def get_run(run_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    run = q1(conn, """select r.id, r.submission_version_id, sv.submission_id, s.title, sv.version_no, r.status, r.stages,
                             r.engine_version, r.started_at, r.completed_at, r.error, sv.extraction_status
                      from review_runs r join submission_versions sv on sv.id = r.submission_version_id
                      join submissions s on s.id = sv.submission_id where r.id = :r and r.workspace_id = :w""",
             r=run_id, w=m.workspace_id)
    if not run:
        raise HTTPException(404, "Review run not found")
    findings = q(conn, """select f.id, f.origin, f.category, f.title, f.explanation, f.severity, f.excerpt, f.span_start, f.span_end,
                                 f.location, f.verification_status, f.status, f.status_reason, f.created_at,
                                 (select count(*) from finding_evidence e where e.finding_id = f.id) evidence_count
                          from findings f where f.review_run_id = :r
                          order by case f.severity when 'high' then 0 when 'medium' then 1 else 2 end, f.span_start nulls last""",
                 r=run_id)
    facts = q(conn, """select v.id, f.key, v.name, v.version_no, v.approved_value from review_run_fact_versions x
                       join brand_fact_versions v on v.id = x.fact_version_id join brand_facts f on f.id = v.fact_id
                       where x.review_run_id = :r""", r=run_id)
    rules = q(conn, """select v.id, r.key, v.version_no, v.rule_type from review_run_rule_versions x
                       join brand_rule_versions v on v.id = x.rule_version_id join brand_rules r on r.id = v.rule_id
                       where x.review_run_id = :r""", r=run_id)
    return {**run, "findings": findings, "fact_versions_used": facts, "rule_versions_used": rules}


@router.get("/findings/{finding_id}")
def get_finding(finding_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    f = q1(conn, """select f.*, sv.version_no, sv.submission_id, s.title submission_title, sv.extracted_text
                    from findings f join submission_versions sv on sv.id = f.submission_version_id
                    join submissions s on s.id = sv.submission_id where f.id = :f and f.workspace_id = :w""",
           f=finding_id, w=m.workspace_id)
    if not f:
        raise HTTPException(404, "Finding not found")
    text = f.pop("extracted_text") or ""
    if f["span_start"] is not None:
        a, b = max(0, f["span_start"] - 150), min(len(text), (f["span_end"] or f["span_start"]) + 150)
        f["context"] = {"before": text[a:f["span_start"]], "match": text[f["span_start"]:f["span_end"]], "after": text[f["span_end"]:b]}
    evidence = q(conn, """select e.id, e.kind, e.stance, e.excerpt, e.created_at,
                                 fv.version_no fact_version_no, fv.name fact_name, fv.approved_value, fv.id fact_version_id,
                                 rv.version_no rule_version_no, rv.rule_type, rv.description rule_description, rv.id rule_version_id,
                                 sr.id source_id, sr.title source_title, sr.url source_url, sr.publisher, sr.retrieved_at,
                                 sr.published_at, sr.access_status
                          from finding_evidence e
                          left join brand_fact_versions fv on fv.id = e.fact_version_id
                          left join brand_rule_versions rv on rv.id = e.rule_version_id
                          left join source_records sr on sr.id = e.source_record_id
                          where e.finding_id = :f order by e.created_at""", f=finding_id)
    return {**f, "evidence": evidence}


class FindingStatusIn(BaseModel):
    status: Literal["open", "accepted", "resolved", "dismissed", "needs_investigation"]
    reason: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reason(self):
        if self.status == "dismissed" and not (self.reason or "").strip():
            raise ValueError("A reason is required to dismiss a finding")
        return self


@router.patch("/findings/{finding_id}/status")
def set_finding_status(finding_id: UUID, body: FindingStatusIn, m: Member = Depends(member_of(*auth.DECIDE_ROLES)),
                       conn: Connection = Depends(get_conn)):
    old = q1(conn, "select status, title from findings where id = :f and workspace_id = :w for update", f=finding_id, w=m.workspace_id)
    if not old:
        raise HTTPException(404, "Finding not found")
    ex(conn, "update findings set status = :s, status_reason = :r, updated_at = now() where id = :f",
       s=body.status, r=(body.reason or "").strip() or None, f=finding_id)
    audit(conn, m.workspace_id, m.user.id, "finding.status_changed", "finding", finding_id,
          f"Finding “{old['title']}”: {old['status']} → {body.status}", {"from": old["status"], "to": body.status, "reason": body.reason})
    return {"id": finding_id, "status": body.status}


class DecisionIn(BaseModel):
    decision: Literal["approved", "changes_requested", "rejected"]
    review_run_id: UUID
    comment: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _comment(self):
        if self.decision != "approved" and not (self.comment or "").strip():
            raise ValueError("A comment is required when requesting changes or rejecting")
        return self


@router.post("/submission-versions/{version_id}/decisions", status_code=201)
def record_decision(version_id: UUID, body: DecisionIn, m: Member = Depends(member_of(*auth.DECIDE_ROLES)),
                    conn: Connection = Depends(get_conn)):
    """Append-only. Resolves open Brand Time Machine impacts only if the run being decided on was started
    after the change, i.e. the content was really re-checked."""
    sv = q1(conn, """select sv.id, sv.submission_id, s.title, s.current_version_id from submission_versions sv
                     join submissions s on s.id = sv.submission_id where sv.id = :v and sv.workspace_id = :w""",
            v=version_id, w=m.workspace_id)
    if not sv:
        raise HTTPException(404, "Version not found")
    run = q1(conn, "select id, status, started_at from review_runs where id = :r and submission_version_id = :v",
             r=body.review_run_id, v=version_id)
    if not run or run["status"] == "failed":
        raise HTTPException(422, "review_run_id must be a completed review run of this exact version")
    dec = q1(conn, """insert into review_decisions (workspace_id, submission_version_id, review_run_id, decision, comment, decided_by)
                      values (:w,:v,:r,:d,:c,:u) returning id, decided_at""",
             w=m.workspace_id, v=version_id, r=run["id"], d=body.decision, c=body.comment, u=m.user.id)
    resolved = 0
    if sv["current_version_id"] == version_id:
        rows = q(conn, """update impact_records set status = 'resolved', resolved_at = now(), resolved_by = :u,
                              resolution_decision_id = :d, resolution_review_run_id = :r
                          where submission_id = :s and status = 'review_required' and created_at <= :started
                          returning id""", u=m.user.id, d=dec["id"], r=run["id"], s=sv["submission_id"], started=run["started_at"])
        resolved = len(rows)
    audit(conn, m.workspace_id, m.user.id, "decision.recorded", "submission_version", version_id,
          f"{body.decision.replace('_', ' ').capitalize()}: “{sv['title']}”",
          {"decision_id": str(dec["id"]), "review_run_id": str(run["id"]), "impacts_resolved": resolved})
    open_left = q1(conn, "select count(*) n from impact_records where submission_id = :s and status = 'review_required'",
                   s=sv["submission_id"])["n"]
    return {"id": dec["id"], "decided_at": dec["decided_at"], "impacts_resolved": resolved, "impacts_still_open": open_left,
            "note": None if not open_left else "Open impact flags remain: re-run the review on the current version, "
                                                 "then record a decision on that run."}
