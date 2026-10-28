"""Submissions: text / file / public-URL ingestion with immutable version snapshots."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import Connection

from app import auth, storage
from app.audit import audit
from app.auth import Member, member_of
from app.config import settings
from app.core.ssrf import FetchError, UnsafeUrlError, safe_fetch
from app.db import ex, get_conn, jb, q, q1
from app.extract import (ExtractionResult, extract_file, extract_html, extract_text, validate_upload)

router = APIRouter(prefix="/api/workspaces/{workspace_id}")
_pool = ThreadPoolExecutor(max_workers=4)
EXTRACT_TIMEOUT_S = 60
MAX_TEXT_CHARS = 500_000


class _Timeout(Exception):
    pass


def _with_timeout(fn, *args):
    """Run blocking work with a deadline. The worker thread cannot be killed, but the request is released."""
    fut = _pool.submit(fn, *args)
    try:
        return fut.result(timeout=EXTRACT_TIMEOUT_S)
    except FutureTimeout:
        raise _Timeout()


def _extract_with_timeout(kind: str, fn, *args) -> ExtractionResult:
    try:
        return _with_timeout(fn, *args)
    except _Timeout:
        return ExtractionResult(kind, "failed", "", [], [f"Processing timed out after {EXTRACT_TIMEOUT_S}s."], {})


async def _ingest(source_type: str, text: Optional[str], url: Optional[str], file: Optional[UploadFile]):
    """Returns (ExtractionResult, meta dict, original bytes or None). Raises 4xx for invalid input."""
    meta: dict = {"source_type": source_type, "original_filename": None, "original_url": None, "mime_type": None,
                  "size_bytes": None, "retrieved_at": None}
    if source_type == "text":
        if text is None or len(text) > MAX_TEXT_CHARS:
            raise HTTPException(422, f"Provide text of at most {MAX_TEXT_CHARS} characters")
        return extract_text(text), meta, None
    if source_type == "url":
        if not url:
            raise HTTPException(422, "Provide a URL")
        try:
            res = _with_timeout(lambda: safe_fetch(url, max_bytes=settings.max_url_bytes, timeout=settings.url_timeout_s))
        except UnsafeUrlError as e:
            raise HTTPException(422, f"This URL cannot be fetched: {e}")
        except (FetchError, _Timeout) as e:
            msg = str(e) or "timed out"
            ext = ExtractionResult("url", "failed", "", [], [f"The page could not be retrieved: {msg}"], {})
            meta.update(original_url=url, retrieved_at=datetime.now(timezone.utc))
            return ext, meta, None
        meta.update(original_url=res.final_url, retrieved_at=datetime.now(timezone.utc), size_bytes=len(res.body),
                    mime_type=res.content_type)
        ctype = res.content_type.split(";")[0].strip().lower()
        if ctype not in ("text/html", "application/xhtml+xml", "text/plain", ""):
            return ExtractionResult("url", "unsupported", "", [], [f"Content type {ctype} is not supported for URLs."], {}), meta, None
        if ctype == "text/plain":
            ext = extract_text(res.body.decode("utf-8", "replace"))
            ext.source_type = "url"
            return ext, meta, None
        return _extract_with_timeout("url", extract_html, res.body, res.final_url, res.truncated), meta, None
    if source_type == "file":
        if file is None:
            raise HTTPException(422, "Attach a file")
        data = await file.read(settings.max_upload_bytes + 1)
        kind, err = validate_upload(data, file.filename or "", settings.max_upload_bytes)
        if err:
            raise HTTPException(422, err)
        meta.update(source_type=kind, original_filename=file.filename, mime_type=file.content_type, size_bytes=len(data))
        return _extract_with_timeout(kind, extract_file, kind, data), meta, data
    raise HTTPException(422, "source_type must be text, file or url")


def _store_version(conn: Connection, m: Member, submission_id: UUID, version_no: int, ext: ExtractionResult,
                   meta: dict, original: Optional[bytes]) -> dict:
    vid = uuid4()
    key = None
    if original is not None:
        key = storage.put(f"{m.workspace_id}/{submission_id}/{vid}-{meta['original_filename'] or 'upload'}",
                          original, meta["mime_type"] or "application/octet-stream")
    src = meta["source_type"] if meta["source_type"] != "file" else ext.source_type
    row = q1(conn, """insert into submission_versions (id, submission_id, workspace_id, version_no, source_type,
                        original_filename, original_url, storage_path, mime_type, size_bytes, retrieved_at, extracted_text,
                        content_hash, extraction_status, extraction_warnings, extraction_quality, segments, created_by)
                      values (:id,:s,:w,:n,:st,:fn,:url,:sp,:mt,:sz,:ra,:txt,:h,:es,cast(:ew as jsonb),cast(:eq as jsonb),
                              cast(:seg as jsonb),:u)
                      returning id, version_no, source_type, extraction_status, extraction_warnings, content_hash, created_at""",
             id=vid, s=submission_id, w=m.workspace_id, n=version_no, st=src, fn=meta["original_filename"],
             url=meta["original_url"], sp=key, mt=meta["mime_type"], sz=meta["size_bytes"], ra=meta["retrieved_at"],
             txt=ext.text, h=hashlib.sha256(ext.text.encode()).hexdigest(), es=ext.status, ew=jb(ext.warnings),
             eq=jb(ext.quality), seg=jb([s.as_dict() for s in ext.segments]), u=m.user.id)
    ex(conn, "update submissions set current_version_id = :v where id = :s", v=vid, s=submission_id)
    return row


@router.post("/submissions", status_code=201)
async def create_submission(brand_profile_id: UUID = Form(...), title: str = Form(..., min_length=1, max_length=200),
                            source_type: str = Form(...), text: Optional[str] = Form(None), url: Optional[str] = Form(None),
                            file: Optional[UploadFile] = File(None),
                            m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id = :p and workspace_id = :w", p=brand_profile_id, w=m.workspace_id):
        raise HTTPException(422, "Unknown brand profile")
    ext, meta, original = await _ingest(source_type, text, url, file)
    sub = q1(conn, "insert into submissions (workspace_id, brand_profile_id, title, created_by) values (:w,:b,:t,:u) returning id",
             w=m.workspace_id, b=brand_profile_id, t=title.strip(), u=m.user.id)
    ver = _store_version(conn, m, sub["id"], 1, ext, meta, original)
    audit(conn, m.workspace_id, m.user.id, "submission.created", "submission", sub["id"],
          f"Submission “{title.strip()}” created (extraction {ext.status})",
          {"version_id": str(ver["id"]), "source_type": ver["source_type"], "content_hash": ver["content_hash"]})
    return {"id": sub["id"], "version": {**ver, "preview": ext.text[:600], "warnings": ext.warnings}}


@router.post("/submissions/{submission_id}/versions", status_code=201)
async def create_version(submission_id: UUID, source_type: str = Form(...), text: Optional[str] = Form(None),
                         url: Optional[str] = Form(None), file: Optional[UploadFile] = File(None),
                         m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    sub = q1(conn, "select id, title from submissions where id = :s and workspace_id = :w for update", s=submission_id, w=m.workspace_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    ext, meta, original = await _ingest(source_type, text, url, file)
    n = q1(conn, "select coalesce(max(version_no), 0) + 1 n from submission_versions where submission_id = :s", s=submission_id)["n"]
    ver = _store_version(conn, m, submission_id, n, ext, meta, original)
    audit(conn, m.workspace_id, m.user.id, "submission.version_created", "submission", submission_id,
          f"Version {n} of “{sub['title']}” created (extraction {ext.status})",
          {"version_id": str(ver["id"]), "content_hash": ver["content_hash"]})
    return {"id": submission_id, "version": {**ver, "preview": ext.text[:600], "warnings": ext.warnings}}


_LIST_SQL = """
select s.id, s.title, s.created_at, s.brand_profile_id, sv.id version_id, sv.version_no, sv.source_type,
       sv.extraction_status, sv.created_at version_created_at,
       (select r.status from review_runs r where r.submission_version_id = sv.id order by r.started_at desc limit 1) last_run_status,
       (select r.id from review_runs r where r.submission_version_id = sv.id order by r.started_at desc limit 1) last_run_id,
       (select d.decision from review_decisions d where d.submission_version_id = sv.id order by d.decided_at desc limit 1) last_decision,
       (select count(*) from impact_records i where i.submission_id = s.id and i.status = 'review_required') open_impacts,
       (select count(*) from findings f join review_runs r on r.id = f.review_run_id
          where f.submission_version_id = sv.id and f.status = 'open'
            and r.id = (select r2.id from review_runs r2 where r2.submission_version_id = sv.id order by r2.started_at desc limit 1)) open_findings
from submissions s join submission_versions sv on sv.id = s.current_version_id
where s.workspace_id = :w order by s.created_at desc limit 200"""


@router.get("/submissions")
def list_submissions(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return q(conn, _LIST_SQL, w=m.workspace_id)


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    sub = q1(conn, "select id, title, brand_profile_id, current_version_id, created_at from submissions where id = :s and workspace_id = :w",
             s=submission_id, w=m.workspace_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    versions = q(conn, """select sv.id, sv.version_no, sv.source_type, sv.original_filename, sv.original_url, sv.extraction_status,
                                 sv.extraction_warnings, sv.content_hash, sv.created_at, u.email created_by
                          from submission_versions sv left join app_users u on u.id = sv.created_by
                          where sv.submission_id = :s order by sv.version_no desc""", s=submission_id)
    runs = q(conn, """select r.id, r.submission_version_id, r.status, r.stages, r.started_at, r.completed_at, r.engine_version,
                             (select count(*) from findings f where f.review_run_id = r.id) finding_count
                      from review_runs r join submission_versions sv on sv.id = r.submission_version_id
                      where sv.submission_id = :s order by r.started_at desc""", s=submission_id)
    decisions = q(conn, """select d.id, d.submission_version_id, d.review_run_id, d.decision, d.comment, d.decided_at, u.email decided_by
                           from review_decisions d join submission_versions sv on sv.id = d.submission_version_id
                           left join app_users u on u.id = d.decided_by
                           where sv.submission_id = :s order by d.decided_at desc""", s=submission_id)
    impacts = q(conn, """select id, submission_version_id, change_kind, status, created_at, resolved_at
                         from impact_records where submission_id = :s order by created_at desc""", s=submission_id)
    return {**sub, "versions": versions, "review_runs": runs, "decisions": decisions, "impacts": impacts}


@router.get("/submission-versions/{version_id}")
def get_version(version_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    row = q1(conn, """select sv.id, sv.submission_id, s.title, sv.version_no, sv.source_type, sv.original_filename, sv.original_url,
                             sv.mime_type, sv.size_bytes, sv.retrieved_at, sv.extracted_text, sv.content_hash, sv.extraction_status,
                             sv.extraction_warnings, sv.extraction_quality, sv.segments, sv.created_at,
                             (sv.storage_path is not null) has_original
                      from submission_versions sv join submissions s on s.id = sv.submission_id
                      where sv.id = :v and sv.workspace_id = :w""", v=version_id, w=m.workspace_id)
    if not row:
        raise HTTPException(404, "Version not found")
    return row


@router.get("/submission-versions/{version_id}/original")
def download_original(version_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    row = q1(conn, "select storage_path, original_filename, mime_type from submission_versions where id = :v and workspace_id = :w",
             v=version_id, w=m.workspace_id)
    if not row or not row["storage_path"]:
        raise HTTPException(404, "No stored original for this version")
    data = storage.get(row["storage_path"])
    if data is None:
        raise HTTPException(404, "Stored file is missing")
    safe = "".join(c for c in (row["original_filename"] or "download") if c.isalnum() or c in "._-") or "download"
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})
