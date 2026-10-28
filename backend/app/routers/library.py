"""Brand library: facts, rules and source references with immutable versions."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Connection

from app import auth
from app.audit import audit
from app.auth import Member, member_of
from app.core.checks import find_dates, find_money
from app.db import get_conn, q, q1
from app.services.impact import flag_dependents

router = APIRouter(prefix="/api/workspaces/{workspace_id}")
Status = Literal["draft", "approved", "inactive"]


def _differs(a, b) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return list(a or []) != list(b or [])
    return a != b


def _terms(v: list[str]) -> list[str]:
    out = [t.strip() for t in v if t and t.strip()]
    if any(len(t) > 120 for t in out) or len(out) > 30:
        raise ValueError("Up to 30 terms of at most 120 characters")
    return out


# --------------------------------------------------------------------------- sources
class SourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: Optional[str] = Field(default=None, max_length=2048, pattern=r"^https?://")
    publisher: Optional[str] = Field(default=None, max_length=200)


@router.get("/sources")
def list_sources(kind: Optional[str] = None, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select id, kind, title, url, publisher, retrieved_at, published_at, access_status, created_at
                      from source_records where workspace_id = :w and (cast(:k as text) is null or kind = :k)
                      order by created_at desc limit 200""", w=m.workspace_id, k=kind)


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    row = q1(conn, """insert into source_records (workspace_id, kind, title, url, publisher, created_by)
                      values (:w, 'reference', :t, :u, :p, :c) returning id, kind, title, url, publisher, created_at""",
             w=m.workspace_id, t=body.title.strip(), u=body.url, p=body.publisher, c=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "source.created", "source_record", row["id"], f"Source “{row['title']}” added")
    return row


def _check_source(conn: Connection, ws: UUID, source_id: Optional[UUID]) -> None:
    if source_id and not q1(conn, "select 1 from source_records where id = :s and workspace_id = :w", s=source_id, w=ws):
        raise HTTPException(422, "source_record_id does not belong to this workspace")


# ---------------------------------------------------------------------------- facts
class FactIn(BaseModel):
    brand_profile_id: UUID
    key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    approved_value: str = Field(min_length=1, max_length=500)
    value_type: Literal["text", "number", "money", "date"]
    subject_terms: list[str] = []
    status: Status = "approved"
    source_record_id: Optional[UUID] = None
    effective_date: Optional[date] = None
    change_note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("subject_terms")
    @classmethod
    def _clean_terms(cls, v: list[str]) -> list[str]:
        return _terms(v)

    @model_validator(mode="after")
    def _semantic(self):
        if self.value_type == "money" and not find_money(self.approved_value):
            raise ValueError("approved_value is not a recognisable amount (e.g. ₹4,999 or $799)")
        if self.value_type == "date" and not find_dates(self.approved_value):
            raise ValueError("approved_value is not a recognisable date (e.g. 14 March 2026)")
        if self.value_type == "number" and not any(ch.isdigit() for ch in self.approved_value):
            raise ValueError("approved_value must contain a number (e.g. 5000 mAh)")
        if self.value_type != "text" and not self.subject_terms:
            raise ValueError("subject_terms are required so Proofline knows where this fact appears")
        return self


class FactUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    approved_value: Optional[str] = Field(default=None, min_length=1, max_length=500)
    value_type: Optional[Literal["text", "number", "money", "date"]] = None
    subject_terms: Optional[list[str]] = None
    status: Optional[Status] = None
    source_record_id: Optional[UUID] = None
    effective_date: Optional[date] = None
    change_note: Optional[str] = Field(default=None, max_length=500)


_FACT_SELECT = """select f.id, f.key, f.brand_profile_id, f.created_at, v.id version_id, v.version_no, v.name,
       v.approved_value, v.value_type, v.subject_terms, v.status, v.source_record_id, v.effective_date,
       v.change_note, v.created_at version_created_at
  from brand_facts f join brand_fact_versions v on v.id = f.current_version_id"""


@router.get("/facts")
def list_facts(brand_profile_id: Optional[UUID] = None, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, _FACT_SELECT + """ where f.workspace_id = :w and (cast(:bp as uuid) is null or f.brand_profile_id = :bp)
                                    order by f.key""", w=m.workspace_id, bp=brand_profile_id)


@router.post("/facts", status_code=201)
def create_fact(body: FactIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id = :p and workspace_id = :w", p=body.brand_profile_id, w=m.workspace_id):
        raise HTTPException(422, "Unknown brand profile")
    _check_source(conn, m.workspace_id, body.source_record_id)
    if q1(conn, "select 1 from brand_facts where brand_profile_id = :p and key = :k", p=body.brand_profile_id, k=body.key.strip()):
        raise HTTPException(409, "A fact with this key already exists in the brand profile; edit it to create a new version")
    fact = q1(conn, "insert into brand_facts (workspace_id, brand_profile_id, key, created_by) values (:w,:p,:k,:u) returning id",
              w=m.workspace_id, p=body.brand_profile_id, k=body.key.strip(), u=m.user.id)
    ver = _insert_fact_version(conn, m, fact["id"], 1, body.model_dump(), body.change_note or "Initial version")
    audit(conn, m.workspace_id, m.user.id, "fact.created", "brand_fact", fact["id"], f"Fact “{body.key}” created (v1)",
          {"version_id": str(ver)})
    return get_fact(fact["id"], m, conn)


def _insert_fact_version(conn, m: Member, fact_id: UUID, no: int, d: dict, note: Optional[str]) -> UUID:
    row = q1(conn, """insert into brand_fact_versions (fact_id, workspace_id, version_no, name, approved_value, value_type,
                        subject_terms, status, source_record_id, effective_date, change_note, created_by)
                      values (:f,:w,:n,:name,:val,:vt,:terms,:st,:src,:eff,:note,:u) returning id""",
             f=fact_id, w=m.workspace_id, n=no, name=d["name"].strip(), val=d["approved_value"].strip(), vt=d["value_type"],
             terms=_terms(d["subject_terms"] or []), st=d["status"], src=d.get("source_record_id"),
             eff=d.get("effective_date"), note=note, u=m.user.id)
    from app.db import ex
    ex(conn, "update brand_facts set current_version_id = :v where id = :f", v=row["id"], f=fact_id)
    return row["id"]


@router.get("/facts/{fact_id}")
def get_fact(fact_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    cur = q1(conn, _FACT_SELECT + " where f.id = :f and f.workspace_id = :w", f=fact_id, w=m.workspace_id)
    if not cur:
        raise HTTPException(404, "Fact not found")
    versions = q(conn, """select v.id, v.version_no, v.name, v.approved_value, v.value_type, v.subject_terms, v.status,
                                 v.source_record_id, v.effective_date, v.change_note, v.created_at, u.email created_by,
                                 (v.id = f.current_version_id) is_current
                          from brand_fact_versions v join brand_facts f on f.id = v.fact_id
                          left join app_users u on u.id = v.created_by
                          where v.fact_id = :f order by v.version_no desc""", f=fact_id)
    return {**cur, "versions": versions}


@router.put("/facts/{fact_id}")
def update_fact(fact_id: UUID, body: FactUpdate, m: Member = Depends(member_of(*auth.EDIT_ROLES)),
                conn: Connection = Depends(get_conn)):
    """Never edits history: creates version n+1, then flags dependent content in the same transaction."""
    fact = q1(conn, "select id, key, current_version_id from brand_facts where id = :f and workspace_id = :w for update",
              f=fact_id, w=m.workspace_id)
    if not fact:
        raise HTTPException(404, "Fact not found")
    old = q1(conn, "select * from brand_fact_versions where id = :v", v=fact["current_version_id"])
    merged = {k: (getattr(body, k) if k in body.model_fields_set else old[k])
              for k in ("name", "approved_value", "value_type", "subject_terms", "status", "source_record_id", "effective_date")}
    FactIn(brand_profile_id=m.workspace_id, key=fact["key"], **{k: v for k, v in merged.items()})  # re-validate (raises 422)
    _check_source(conn, m.workspace_id, merged["source_record_id"])
    merged["approved_value"] = merged["approved_value"].strip()
    merged["subject_terms"] = _terms(merged["subject_terms"] or [])
    if not any(_differs(merged[k], old[k]) for k in merged):
        raise HTTPException(409, "No changes were made")
    material = any(_differs(merged[k], old[k]) for k in ("approved_value", "value_type", "subject_terms", "status"))
    new_id = _insert_fact_version(conn, m, fact_id, old["version_no"] + 1, merged, body.change_note)
    impacted = 0
    if old["status"] == "approved" and material:
        impacted = flag_dependents(conn, workspace_id=m.workspace_id, actor_id=m.user.id, kind="fact", entity_id=fact_id,
                                   entity_key=fact["key"], old_version_id=old["id"], new_version_id=new_id)
    audit(conn, m.workspace_id, m.user.id, "fact.updated", "brand_fact", fact_id,
          f"Fact “{fact['key']}” updated to v{old['version_no'] + 1}: “{old['approved_value']}” → “{merged['approved_value']}”",
          {"old_version_id": str(old["id"]), "new_version_id": str(new_id), "flagged_submissions": impacted})
    return {**get_fact(fact_id, m, conn), "flagged_submissions": impacted}


# ---------------------------------------------------------------------------- rules
RuleType = Literal["prohibited_phrase", "required_term", "approved_name", "claim_requires_evidence"]
ContentType = Literal["text", "docx", "pdf", "image", "pptx", "url"]


class RuleIn(BaseModel):
    brand_profile_id: UUID
    key: str = Field(min_length=1, max_length=120)
    rule_type: RuleType
    description: str = Field(min_length=1, max_length=1000)
    patterns: list[str] = Field(min_length=1)
    severity: Literal["low", "medium", "high"] = "medium"
    applies_to: list[ContentType] = []
    status: Status = "approved"
    source_record_id: Optional[UUID] = None
    change_note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("patterns")
    @classmethod
    def _clean_patterns(cls, v: list[str]) -> list[str]:
        cleaned = _terms(v)
        if not cleaned:
            raise ValueError("At least one non-empty pattern is required")
        return cleaned


class RuleUpdate(BaseModel):
    rule_type: Optional[RuleType] = None
    description: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    patterns: Optional[list[str]] = None
    severity: Optional[Literal["low", "medium", "high"]] = None
    applies_to: Optional[list[ContentType]] = None
    status: Optional[Status] = None
    source_record_id: Optional[UUID] = None
    change_note: Optional[str] = Field(default=None, max_length=500)


_RULE_SELECT = """select r.id, r.key, r.brand_profile_id, r.created_at, v.id version_id, v.version_no, v.rule_type,
       v.description, v.patterns, v.severity, v.applies_to, v.status, v.source_record_id, v.change_note
  from brand_rules r join brand_rule_versions v on v.id = r.current_version_id"""


@router.get("/rules")
def list_rules(brand_profile_id: Optional[UUID] = None, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, _RULE_SELECT + """ where r.workspace_id = :w and (cast(:bp as uuid) is null or r.brand_profile_id = :bp)
                                    order by r.key""", w=m.workspace_id, bp=brand_profile_id)


def _insert_rule_version(conn, m: Member, rule_id: UUID, no: int, d: dict, note: Optional[str]) -> UUID:
    from app.db import ex
    row = q1(conn, """insert into brand_rule_versions (rule_id, workspace_id, version_no, rule_type, description, patterns,
                        severity, applies_to, status, source_record_id, change_note, created_by)
                      values (:r,:w,:n,:t,:d,:p,:s,:a,:st,:src,:note,:u) returning id""",
             r=rule_id, w=m.workspace_id, n=no, t=d["rule_type"], d=d["description"].strip(), p=_terms(d["patterns"]),
             s=d["severity"], a=list(d["applies_to"] or []), st=d["status"], src=d.get("source_record_id"), note=note, u=m.user.id)
    ex(conn, "update brand_rules set current_version_id = :v where id = :r", v=row["id"], r=rule_id)
    return row["id"]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id = :p and workspace_id = :w", p=body.brand_profile_id, w=m.workspace_id):
        raise HTTPException(422, "Unknown brand profile")
    _check_source(conn, m.workspace_id, body.source_record_id)
    if q1(conn, "select 1 from brand_rules where brand_profile_id = :p and key = :k", p=body.brand_profile_id, k=body.key.strip()):
        raise HTTPException(409, "A rule with this key already exists; edit it to create a new version")
    rule = q1(conn, "insert into brand_rules (workspace_id, brand_profile_id, key, created_by) values (:w,:p,:k,:u) returning id",
              w=m.workspace_id, p=body.brand_profile_id, k=body.key.strip(), u=m.user.id)
    ver = _insert_rule_version(conn, m, rule["id"], 1, body.model_dump(), body.change_note or "Initial version")
    audit(conn, m.workspace_id, m.user.id, "rule.created", "brand_rule", rule["id"], f"Rule “{body.key}” created (v1)",
          {"version_id": str(ver)})
    return get_rule(rule["id"], m, conn)


@router.get("/rules/{rule_id}")
def get_rule(rule_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    cur = q1(conn, _RULE_SELECT + " where r.id = :r and r.workspace_id = :w", r=rule_id, w=m.workspace_id)
    if not cur:
        raise HTTPException(404, "Rule not found")
    versions = q(conn, """select v.id, v.version_no, v.rule_type, v.description, v.patterns, v.severity, v.applies_to, v.status,
                                 v.change_note, v.created_at, u.email created_by, (v.id = r.current_version_id) is_current
                          from brand_rule_versions v join brand_rules r on r.id = v.rule_id
                          left join app_users u on u.id = v.created_by where v.rule_id = :r order by v.version_no desc""", r=rule_id)
    return {**cur, "versions": versions}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: UUID, body: RuleUpdate, m: Member = Depends(member_of(*auth.EDIT_ROLES)),
                conn: Connection = Depends(get_conn)):
    rule = q1(conn, "select id, key, current_version_id from brand_rules where id = :r and workspace_id = :w for update",
              r=rule_id, w=m.workspace_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    old = q1(conn, "select * from brand_rule_versions where id = :v", v=rule["current_version_id"])
    merged = {k: (getattr(body, k) if k in body.model_fields_set else old[k])
              for k in ("rule_type", "description", "patterns", "severity", "applies_to", "status", "source_record_id")}
    RuleIn(brand_profile_id=m.workspace_id, key=rule["key"], **merged)  # re-validate
    _check_source(conn, m.workspace_id, merged["source_record_id"])
    merged["patterns"] = _terms(merged["patterns"])
    changed = {k: v for k, v in merged.items() if _differs(v, old[k])}
    if not changed:
        raise HTTPException(409, "No changes were made")
    material = any(k in changed for k in ("rule_type", "patterns", "severity", "applies_to", "status"))
    new_id = _insert_rule_version(conn, m, rule_id, old["version_no"] + 1, merged, body.change_note)
    impacted = 0
    if old["status"] == "approved" and material:
        impacted = flag_dependents(conn, workspace_id=m.workspace_id, actor_id=m.user.id, kind="rule", entity_id=rule_id,
                                   entity_key=rule["key"], old_version_id=old["id"], new_version_id=new_id)
    audit(conn, m.workspace_id, m.user.id, "rule.updated", "brand_rule", rule_id,
          f"Rule “{rule['key']}” updated to v{old['version_no'] + 1}",
          {"old_version_id": str(old["id"]), "new_version_id": str(new_id), "changed": sorted(changed),
           "flagged_submissions": impacted})
    return {**get_rule(rule_id, m, conn), "flagged_submissions": impacted}
