"""Workspace-scoped approved visual references and palette versions."""
from __future__ import annotations

import hashlib
import re
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection

from app import storage
from app.audit import audit
from app.auth import Member, member_of
from app.config import settings
from app.db import ex, get_conn, jb, q, q1
from app.extract import validate_upload

router = APIRouter(prefix="/api/workspaces/{workspace_id}/visual")


@router.get("/assets")
def list_assets(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, """select id, brand_profile_id, family_id, version_no, name, asset_type, category,
                             original_filename, mime_type, size_bytes, content_hash, approved, approved_by, created_at
                      from brand_assets where workspace_id=:w order by created_at desc""", w=m.workspace_id)


@router.get("/assets/{asset_id}/content")
def asset_content(asset_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    asset = q1(conn, "select storage_path,mime_type,original_filename from brand_assets where id=:id and workspace_id=:w and approved=true",
               id=asset_id, w=m.workspace_id)
    if not asset:
        raise HTTPException(404, "Approved visual asset not found")
    data = storage.get(asset["storage_path"])
    if data is None:
        raise HTTPException(404, "Stored visual asset is unavailable")
    return Response(data, media_type=asset["mime_type"], headers={"Cache-Control": "private, no-store",
                                                                   "X-Content-Type-Options": "nosniff"})


@router.post("/assets", status_code=201)
async def upload_asset(brand_profile_id: UUID = Form(...), name: str = Form(..., min_length=1, max_length=120),
                       asset_type: str = Form(...), category: str = Form("general", max_length=80),
                       family_id: Optional[UUID] = Form(None), file: UploadFile = File(...),
                       m: Member = Depends(member_of("owner")), conn: Connection = Depends(get_conn)):
    if asset_type not in ("logo", "reference_image"):
        raise HTTPException(422, "asset_type must be logo or reference_image")
    profile = q1(conn, "select id from brand_profiles where id=:p and workspace_id=:w", p=brand_profile_id, w=m.workspace_id)
    if not profile:
        raise HTTPException(404, "Brand profile not found")
    data = await file.read(settings.max_upload_bytes + 1)
    kind, err = validate_upload(data, file.filename or "", settings.max_upload_bytes)
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    if err or kind != "image" or not (is_png or is_jpeg):
        raise HTTPException(422, err or "Approved visual references must be PNG or JPG images")
    mime = "image/png" if is_png else "image/jpeg"
    family = family_id or uuid4()
    latest = q1(conn, "select coalesce(max(version_no),0) n from brand_assets where family_id=:f and workspace_id=:w",
                f=family, w=m.workspace_id)
    version = latest["n"] + 1
    asset_id = uuid4()
    key = f"{m.workspace_id}/brand-assets/{asset_id}-{file.filename or 'reference'}"
    try:
        storage.put(key, data, mime)
    except storage.StorageError as exc:
        raise HTTPException(503, str(exc)) from exc
    approved = True
    row = q1(conn, """insert into brand_assets
                      (id,workspace_id,brand_profile_id,family_id,version_no,name,asset_type,category,original_filename,
                       storage_path,mime_type,size_bytes,content_hash,approved,approved_by,created_by)
                      values (:id,:w,:p,:f,:v,:n,:t,:c,:fn,:sp,:mt,:sz,:h,:a,:by,:u)
                      returning id,brand_profile_id,family_id,version_no,name,asset_type,category,original_filename,
                                mime_type,size_bytes,content_hash,approved,approved_by,created_at""",
                id=asset_id, w=m.workspace_id, p=brand_profile_id, f=family, v=version, n=name.strip(),
                t=asset_type, c=category.strip() or "general", fn=file.filename or "reference", sp=key, mt=mime,
                sz=len(data), h=hashlib.sha256(data).hexdigest(), a=approved,
                by=m.user.id if approved else None, u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "visual.asset_added", "brand_asset", asset_id,
          f"Visual reference added: {name.strip()}", {"version": version, "approved": approved, "type": asset_type})
    return row


class PaletteIn(BaseModel):
    brand_profile_id: UUID
    colors: list[str] = Field(min_length=1, max_length=20)

    @field_validator("colors")
    @classmethod
    def valid_colors(cls, values):
        for value in values:
            if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value.strip()):
                raise ValueError("Palette colors must be six digit hex values")
        return ["#" + value.strip().lstrip("#").upper() for value in values]


@router.get("/palette")
def get_palette(brand_profile_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id=:p and workspace_id=:w", p=brand_profile_id, w=m.workspace_id):
        raise HTTPException(404, "Brand profile not found")
    return q(conn, """select id, brand_profile_id, version_no, colors, approved_by, created_at
                      from brand_palette_versions where workspace_id=:w and brand_profile_id=:p
                      order by version_no desc""", w=m.workspace_id, p=brand_profile_id)


@router.post("/palette", status_code=201)
def save_palette(body: PaletteIn, m: Member = Depends(member_of("owner")), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id=:p and workspace_id=:w", p=body.brand_profile_id, w=m.workspace_id):
        raise HTTPException(404, "Brand profile not found")
    version = q1(conn, "select coalesce(max(version_no),0)+1 n from brand_palette_versions where brand_profile_id=:p",
                 p=body.brand_profile_id)["n"]
    row = q1(conn, """insert into brand_palette_versions(workspace_id,brand_profile_id,version_no,colors,approved_by)
                      values (:w,:p,:v,cast(:c as jsonb),:u)
                      returning id,brand_profile_id,version_no,colors,approved_by,created_at""",
             w=m.workspace_id, p=body.brand_profile_id, v=version, c=jb(body.colors), u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "visual.palette_added", "brand_profile", body.brand_profile_id,
          f"Approved brand palette v{version} created", {"version": version, "colors": body.colors})
    return row
