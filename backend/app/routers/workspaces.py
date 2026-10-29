from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Connection

from app import auth
from app.audit import audit
from app.auth import Member, User, current_user, member_of
from app.config import settings
from app.db import ex, get_conn, q, q1
from app.providers.base import ProviderError, get_llm_provider, get_search_provider

router = APIRouter(prefix="/api")


# ------------------------------------------------------------ local auth (AUTH_MODE=local only)
class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)


@router.post("/auth/signup")
def signup(body: Credentials, conn: Connection = Depends(get_conn)):
    if settings.auth_mode != "local":
        raise HTTPException(404, "Use Supabase Auth to sign up")
    email = body.email.lower()
    if q1(conn, "select 1 from app_users where email = :e", e=email):
        raise HTTPException(409, "An account with this email already exists")
    from uuid import uuid4
    uid = uuid4()
    ex(conn, "insert into app_users (id, email) values (:i, :e)", i=uid, e=email)
    ex(conn, "insert into local_credentials values (:i, :h)", i=uid, h=auth.hash_password(body.password))
    return {"access_token": auth.issue_local_token(uid, email), "user": {"id": uid, "email": email}}


@router.post("/auth/login")
def login(body: Credentials, conn: Connection = Depends(get_conn)):
    if settings.auth_mode != "local":
        raise HTTPException(404, "Use Supabase Auth to sign in")
    row = q1(conn, """select u.id, u.email, c.password_hash from app_users u
                      join local_credentials c on c.user_id = u.id where u.email = :e""", e=body.email.lower())
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": auth.issue_local_token(row["id"], row["email"]), "user": {"id": row["id"], "email": row["email"]}}


@router.get("/config")
def public_config():
    """Non-secret values the frontend needs. No keys beyond what is safe to expose."""
    return {"auth_mode": settings.auth_mode, "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
            "supported_types": ["text", "docx", "pdf", "image", "pptx", "url"]}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email}


# ---------------------------------------------------------------------------- workspaces
class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/workspaces")
def list_workspaces(user: User = Depends(current_user), conn: Connection = Depends(get_conn)):
    return q(conn, """select w.id, w.name, m.role, w.created_at from workspaces w
                      join workspace_members m on m.workspace_id = w.id where m.user_id = :u order by w.created_at""",
             u=user.id)


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), conn: Connection = Depends(get_conn)):
    ws = q1(conn, "insert into workspaces (name, created_by) values (:n, :u) returning id, name, created_at",
            n=body.name.strip(), u=user.id)
    ex(conn, "insert into workspace_members values (:w, :u, 'owner')", w=ws["id"], u=user.id)
    audit(conn, ws["id"], user.id, "workspace.created", "workspace", ws["id"], f"Workspace “{ws['name']}” created")
    return {**ws, "role": "owner"}


class MemberIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["owner", "editor", "reviewer"]


@router.get("/workspaces/{workspace_id}/members")
def list_members(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select u.id user_id, u.email, wm.role from workspace_members wm join app_users u on u.id = wm.user_id
                      where wm.workspace_id = :w order by u.email""", w=m.workspace_id)


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def add_member(body: MemberIn, m: Member = Depends(member_of("owner")), conn: Connection = Depends(get_conn)):
    target = q1(conn, "select id from app_users where email = :e", e=body.email.lower())
    if not target:
        raise HTTPException(404, "No Proofline user with that email. They must sign up first.")
    ex(conn, """insert into workspace_members values (:w, :u, :r)
                on conflict (workspace_id, user_id) do update set role = excluded.role""",
       w=m.workspace_id, u=target["id"], r=body.role)
    audit(conn, m.workspace_id, m.user.id, "member.set", "user", target["id"], f"{body.email} set to {body.role}")
    return {"user_id": target["id"], "role": body.role}


# --------------------------------------------------------------------- brand profiles
class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)


@router.get("/workspaces/{workspace_id}/profiles")
def list_profiles(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, "select id, name, description, created_at from brand_profiles where workspace_id = :w order by created_at",
             w=m.workspace_id)


@router.post("/workspaces/{workspace_id}/profiles", status_code=201)
def create_profile(body: ProfileIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    row = q1(conn, """insert into brand_profiles (workspace_id, name, description, created_by) values (:w,:n,:d,:u)
                      returning id, name, description, created_at""", w=m.workspace_id, n=body.name.strip(), d=body.description, u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "profile.created", "brand_profile", row["id"], f"Brand profile “{row['name']}” created")
    return row


# ------------------------------------------------------------------------- dashboard
@router.get("/workspaces/{workspace_id}/dashboard")
def dashboard(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    """Every number is an aggregate over persisted rows."""
    w = m.workspace_id
    one = lambda sql: q1(conn, sql, w=w)["n"]
    return {
        "facts": one("select count(*) n from brand_facts where workspace_id = :w"),
        "approved_facts": one("""select count(*) n from brand_fact_versions v
                                 join brand_facts f on f.current_version_id = v.id
                                 where f.workspace_id = :w and v.status = 'approved'"""),
        "rules": one("select count(*) n from brand_rules where workspace_id = :w"),
        "submissions": one("select count(*) n from submissions where workspace_id = :w"),
        "review_runs": one("select count(*) n from review_runs where workspace_id = :w"),
        "open_findings": one("select count(*) n from findings where workspace_id = :w and status = 'open'"),
        "open_findings_high": one("select count(*) n from findings where workspace_id = :w and status = 'open' and severity = 'high'"),
        "impact_review_required": one("select count(*) n from impact_records where workspace_id = :w and status = 'review_required'"),
        "recent_activity": q(conn, """select id, event_type, summary, created_at from audit_events
                                      where workspace_id = :w order by id desc limit 8""", w=w),
    }


# ----------------------------------------------------------------------------- settings
@router.get("/workspaces/{workspace_id}/settings/providers")
def provider_status(probe: bool = False, m: Member = Depends(member_of())):
    """Reports configuration. `configured` means credentials exist; `working` is only set after a
    live probe (probe=true), because configured != tested."""
    llm, search = get_llm_provider(), get_search_provider()
    out = {"llm": {"provider": llm.name, "configured": llm.configured(), "working": None, "message": None},
           "search": {"provider": search.name, "configured": search.configured(), "working": None, "message": None},
           "auth_mode": settings.auth_mode,
           "storage": "supabase" if settings.supabase_url and settings.supabase_service_key else "local-directory",
           "ocr": _ocr_status()}
    if probe:
        if llm.configured():
            try:
                r = llm.complete_json("Reply with JSON only.", 'Return {"ok": true}', 20)
                out["llm"]["working"] = bool(r.get("ok"))
            except ProviderError as e:
                out["llm"].update(working=False, message=str(e))
        if search.configured():
            try:
                out["search"]["working"] = len(search.search("Wikipedia", 1)) > 0
            except ProviderError as e:
                out["search"].update(working=False, message=str(e))
    for k in ("llm", "search"):
        if not out[k]["configured"]:
            out[k]["message"] = "Not configured. Features that depend on it report 'unavailable'."
    return out


def _ocr_status() -> dict:
    try:
        import pytesseract
        return {"available": True, "version": str(pytesseract.get_tesseract_version())}
    except Exception:
        return {"available": False, "version": None}
