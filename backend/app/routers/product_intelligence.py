"""Workspace-scoped Product Intelligence registry and research history."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Connection

from app import auth
from app.audit import audit
from app.auth import Member, member_of
from app.core.ssrf import FetchError, UnsafeUrlError, validate_url
from app.db import ex, get_conn, q, q1
from app.providers.base import get_search_provider

router = APIRouter(prefix="/api/workspaces/{workspace_id}/product-intelligence")
links_router = APIRouter(prefix="/api/workspaces/{workspace_id}")


class ProductIn(BaseModel):
    brand_profile_id: UUID
    product_name: str = Field(min_length=2, max_length=200)
    brand: Optional[str] = Field(default=None, max_length=120)
    manufacturer: Optional[str] = Field(default=None, max_length=200)
    model_number: Optional[str] = Field(default=None, max_length=120)
    product_category: Optional[str] = Field(default=None, max_length=120)
    market: Optional[str] = Field(default=None, max_length=120)
    official_website: Optional[str] = Field(default=None, max_length=2048)
    confirm_identity: bool = False

    @field_validator("product_name", "brand", "manufacturer", "model_number", "product_category", "market")
    @classmethod
    def normalize_identity(cls, value):
        return value.strip() if value else value


def _product(row: dict) -> dict:
    return {**row, "identity_confirmed": row["identity_status"] == "confirmed"}


@router.get("/status")
def integration_status(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    provider = get_search_provider()
    return {"search_provider": provider.name, "configured": provider.configured(),
            "message": "Configured search provider is available to the background research worker." if provider.configured()
            else "No product research search provider is configured. Set SEARCH_PROVIDER and TAVILY_API_KEY or BRAVE_API_KEY on the backend."}


@router.get("/products")
def list_products(m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    return [_product(row) for row in q(conn, """select p.*,r.id latest_run_id,r.status latest_research_status,
                     r.created_at latest_researched_at,r.coverage latest_coverage
                     from products p left join lateral (select id,status,created_at,coverage from product_research_runs
                     where product_id=p.id order by created_at desc limit 1) r on true
                     where p.workspace_id=:w order by p.updated_at desc""", w=m.workspace_id)]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    if not q1(conn, "select 1 from brand_profiles where id=:p and workspace_id=:w", p=body.brand_profile_id, w=m.workspace_id):
        raise HTTPException(404, "Brand profile not found")
    official = None
    if body.official_website:
        try:
            official = validate_url(body.official_website).url
        except (UnsafeUrlError, FetchError) as exc:
            raise HTTPException(422, f"Official website is not a safe public URL: {exc}") from exc
    identity_status = "confirmed" if body.confirm_identity else "ambiguous"
    row = q1(conn, """insert into products(workspace_id,brand_profile_id,product_name,brand,manufacturer,model_number,
                    product_category,market,official_website,identity_status,identity_confirmed_by,created_by)
                    values (:w,:b,:name,:brand,:manufacturer,:model,:category,:market,:official,:status,:confirmed_by,:user)
                    returning *""", w=m.workspace_id, b=body.brand_profile_id, name=body.product_name,
             brand=body.brand, manufacturer=body.manufacturer, model=body.model_number,
             category=body.product_category, market=body.market, official=official, status=identity_status,
             confirmed_by=m.user.id if body.confirm_identity else None, user=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "product.created", "product", row["id"],
          f"Product profile created: {body.product_name}", {"identity_status": identity_status})
    return _product(row)


@router.post("/products/{product_id}/research", status_code=202)
def start_research(product_id: UUID, m: Member = Depends(member_of(*auth.EDIT_ROLES)), conn: Connection = Depends(get_conn)):
    product = q1(conn, "select id,product_name,identity_status from products where id=:p and workspace_id=:w for update",
                 p=product_id, w=m.workspace_id)
    if not product:
        raise HTTPException(404, "Product profile not found")
    active = q1(conn, "select id from product_research_runs where product_id=:p and status in ('queued','running') limit 1",
                p=product_id)
    if active:
        raise HTTPException(409, "Research is already queued or running for this product.")
    workspace_active = q1(conn, "select count(*) n from product_research_runs where workspace_id=:w and status in ('queued','running')",
                          w=m.workspace_id)["n"]
    if workspace_active >= 5:
        raise HTTPException(429, "This workspace already has five queued or running product research jobs.")
    recent = q1(conn, "select count(*) n from product_research_runs where workspace_id=:w and created_at>now()-interval '1 day'",
                w=m.workspace_id)["n"]
    if recent >= 20:
        raise HTTPException(429, "The workspace product research limit of 20 runs per day has been reached.")
    run = q1(conn, """insert into product_research_runs(workspace_id,product_id,status,requested_by)
                      values (:w,:p,'queued',:u) returning id,status,created_at""",
             w=m.workspace_id, p=product_id, u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "product.research_queued", "product", product_id,
          f"Product research queued: {product['product_name']}", {"research_run_id": str(run["id"])})
    return {**run, "identity_status": product["identity_status"], "note": "A separate background worker must process this research job."}


@router.get("/products/{product_id}")
def get_product(product_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    product = q1(conn, "select * from products where id=:p and workspace_id=:w", p=product_id, w=m.workspace_id)
    if not product:
        raise HTTPException(404, "Product profile not found")
    runs = q(conn, """select id,status,query_count,result_count,unique_source_count,inspected_source_count,
                      inaccessible_source_count,coverage,error_summary,requested_by,started_at,completed_at,created_at
                      from product_research_runs where product_id=:p order by created_at desc limit 50""", p=product_id)
    latest = runs[0] if runs else None
    sources = q(conn, """select id,research_run_id,title,url,domain,source_category,publisher,published_at,retrieved_at,
                         access_status,extraction_status,left(extracted_text,2000) excerpt,content_hash,duplicate_of,
                         cached_from is not null cached,product_match_status,source_assessment,
                         (select array_agg(query_id) from product_research_query_sources x where x.source_id=product_research_sources.id) query_ids
                         from product_research_sources where product_id=:p and (:r is null or research_run_id=:r)
                         order by retrieved_at desc limit 300""", p=product_id, r=latest["id"] if latest else None)
    queries = q(conn, """select id,research_run_id,category,query_text,status,result_count,error_code,executed_at
                        from product_research_queries where research_run_id=:r order by executed_at""",
                r=latest["id"]) if latest else []
    profile = q1(conn, "select version_no,profile,coverage,created_at from product_profiles where product_id=:p order by version_no desc limit 1",
                 p=product_id)
    claim_evidence = q(conn, """with latest_reviews as (
                                select distinct on (submission_version_id) id,submission_version_id
                                from review_runs where workspace_id=:w
                                order by submission_version_id,started_at desc
                              )
                              select f.id finding_id,r.id review_run_id,s.title submission_title,
                                     f.excerpt claim_text,f.title finding_title,f.explanation,
                                     f.verification_status,sr.id source_id,sr.title source_title,sr.url source_url,
                                     sr.publisher,sr.published_at,sr.excerpt evidence_excerpt,sr.search_query,
                                     sr.product_research_source_id,prs.source_assessment,fe.stance
                              from submission_product_links l
                              join latest_reviews r on r.submission_version_id=l.submission_version_id
                              join findings f on f.review_run_id=r.id and f.origin='verification'
                              join submissions s on s.id=(select submission_id from submission_versions where id=l.submission_version_id)
                              left join finding_evidence fe on fe.finding_id=f.id and fe.kind='external_source'
                              left join source_records sr on sr.id=fe.source_record_id
                              left join product_research_sources prs on prs.id=sr.product_research_source_id
                                   and prs.workspace_id=l.workspace_id
                              where l.workspace_id=:w and l.product_id=:p
                              order by f.created_at desc,sr.created_at desc""", w=m.workspace_id, p=product_id)
    by_finding: dict[str, dict] = {}
    supporting_source_ids: set[str] = set()
    contradicting_source_ids: set[str] = set()
    for row in claim_evidence:
        finding_id = str(row["finding_id"])
        item = by_finding.setdefault(finding_id, {**{key: row[key] for key in (
            "finding_id", "review_run_id", "submission_title", "claim_text", "finding_title",
            "explanation", "verification_status")}, "evidence": []})
        if row.get("source_id"):
            item.setdefault("evidence", []).append({key: row[key] for key in (
                "source_id", "source_title", "source_url", "publisher", "published_at", "evidence_excerpt",
                "search_query", "product_research_source_id", "source_assessment", "stance")})
            if row["stance"] == "supports":
                supporting_source_ids.add(str(row["source_id"]))
            elif row["stance"] == "contradicts":
                contradicting_source_ids.add(str(row["source_id"]))
    claims = list(by_finding.values())
    inconclusive_statuses = {"insufficient_evidence", "needs_human_review", "unavailable", "outdated_evidence",
                             "partially_supported", "unable_to_determine", "conflicting"}
    claim_coverage = {"claims_evaluated": len(claims),
                      "supporting_sources": len(supporting_source_ids),
                      "contradicting_sources": len(contradicting_source_ids),
                      "claims_inconclusive": sum(c["verification_status"] in inconclusive_statuses for c in claims)}
    return {"product": _product(product), "runs": runs, "latest_run": latest, "queries": queries,
            "sources": sources, "profile": profile, "claims": claims, "claim_coverage": claim_coverage}


@router.get("/sources/{source_id}")
def get_source(source_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    source = q1(conn, """select id,title,url,domain,source_category,publisher,published_at,retrieved_at,access_status,
                         extraction_status,extracted_text,content_hash,duplicate_of,cached_from,product_match_status,
                         source_assessment,
                         (select array_agg(query_id) from product_research_query_sources x where x.source_id=product_research_sources.id) query_ids
                         from product_research_sources where id=:s and workspace_id=:w""", s=source_id, w=m.workspace_id)
    if not source:
        raise HTTPException(404, "Product source not found")
    return source


@links_router.post("/submission-versions/{version_id}/product", status_code=201)
def link_submission_product(version_id: UUID, product_id: UUID, m: Member = Depends(member_of(*auth.EDIT_ROLES)),
                            conn: Connection = Depends(get_conn)):
    version = q1(conn, """select sv.id,s.brand_profile_id from submission_versions sv join submissions s on s.id=sv.submission_id
                         where sv.id=:v and sv.workspace_id=:w""", v=version_id, w=m.workspace_id)
    product = q1(conn, "select id,brand_profile_id,product_name from products where id=:p and workspace_id=:w",
                 p=product_id, w=m.workspace_id)
    if not version or not product:
        raise HTTPException(404, "Submission version or product profile not found")
    if version["brand_profile_id"] != product["brand_profile_id"]:
        raise HTTPException(422, "The product and submission must use the same brand profile.")
    old = q1(conn, "select id from submission_product_links where submission_version_id=:v", v=version_id)
    if old:
        raise HTTPException(409, "A product is already linked to this submission version. Create a new version to change its product.")
    row = q1(conn, """insert into submission_product_links(workspace_id,submission_version_id,product_id,linked_by)
                      values (:w,:v,:p,:u) returning id,submission_version_id,product_id,created_at""",
             w=m.workspace_id, v=version_id, p=product_id, u=m.user.id)
    audit(conn, m.workspace_id, m.user.id, "submission.product_linked", "submission_version", version_id,
          f"Product linked to submission: {product['product_name']}", {"product_id": str(product_id)})
    return row


@links_router.get("/submission-versions/{version_id}/product")
def get_submission_product(version_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    row = q1(conn, """select l.id,l.product_id,p.product_name,p.brand,p.manufacturer,p.model_number,p.product_category,
                         p.market,p.identity_status,r.id latest_research_run_id,r.status research_status,r.coverage
                         from submission_product_links l join products p on p.id=l.product_id
                         left join lateral (select id,status,coverage from product_research_runs where product_id=p.id
                         order by created_at desc limit 1) r on true
                         where l.submission_version_id=:v and l.workspace_id=:w""", v=version_id, w=m.workspace_id)
    if not row:
        if not q1(conn, "select 1 from submission_versions where id=:v and workspace_id=:w", v=version_id, w=m.workspace_id):
            raise HTTPException(404, "Submission version not found")
        return None
    return row


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    run = q1(conn, "select * from product_research_runs where id=:r and workspace_id=:w", r=run_id, w=m.workspace_id)
    if not run:
        raise HTTPException(404, "Product research run not found")
    return run
