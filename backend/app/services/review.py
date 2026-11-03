"""Review pipeline orchestration.

Compute first (no DB writes, provider calls may be slow), then persist everything in ONE
transaction. If the essential deterministic stage raises, nothing partial is stored and a
'failed' run is recorded separately so the history stays honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Optional
from uuid import UUID

from sqlalchemy import Connection

from app.audit import audit
from app.core.checks import ENGINE_VERSION, FactV, RawFinding, RuleV, run_checks
from app.core.governance import AutomatedDecision
from app.core.visual import (analyze_document_typography_layout, analyze_logo_references,
                             analyze_palette)
from app.core.verification import SEMANTIC_ENGINE, fetch_claim_source, run_semantic_review, verify_claims
from app.db import ex, jb, q, q1, table_exists, transaction
from app.extract import locate
from app.providers.base import LlmProvider, ProviderError, SearchProvider

ENGINE = f"{ENGINE_VERSION}+{SEMANTIC_ENGINE}"


def load_reference_versions(conn: Connection, workspace_id: UUID, brand_profile_id: UUID):
    facts = q(conn, """select f.id fact_id, v.id version_id, f.key, v.name, v.approved_value, v.value_type,
                              v.subject_terms, v.status
                       from brand_facts f join brand_fact_versions v on v.id = f.current_version_id
                       where f.workspace_id = :ws and f.brand_profile_id = :bp""", ws=workspace_id, bp=brand_profile_id)
    rules = q(conn, """select r.id rule_id, v.id version_id, r.key, v.rule_type, v.description, v.patterns,
                              v.severity, v.applies_to, v.status
                       from brand_rules r join brand_rule_versions v on v.id = r.current_version_id
                       where r.workspace_id = :ws and r.brand_profile_id = :bp""", ws=workspace_id, bp=brand_profile_id)
    return (
        [FactV(str(f["fact_id"]), str(f["version_id"]), f["key"], f["name"], f["approved_value"], f["value_type"],
               tuple(f["subject_terms"] or ()), f["status"]) for f in facts],
        [RuleV(str(r["rule_id"]), str(r["version_id"]), r["key"], r["rule_type"], r["description"],
               tuple(r["patterns"] or ()), r["severity"], tuple(r["applies_to"] or ()), r["status"]) for r in rules],
    )


@dataclass
class Computed:
    findings: list[RawFinding] = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    fact_versions: list[str] = field(default_factory=list)
    rule_versions: list[str] = field(default_factory=list)
    stages: dict = field(default_factory=dict)
    evidence: list[tuple[int, dict]] = field(default_factory=list)  # (finding index, evidence dict)
    visual_details: dict = field(default_factory=dict)
    automated_decision: Optional[AutomatedDecision] = None
    status: str = "completed"


def compute_review(sv: dict, facts: list[FactV], rules: list[RuleV], search: SearchProvider,
                   llm: LlmProvider, brand_context: str = "", image_bytes: Optional[bytes] = None,
                   approved_colors: Optional[list[str]] = None,
                   product_sources: Optional[list[dict]] = None,
                   visual_pages: Optional[list[dict]] = None,
                   visual_page_count: Optional[int] = None,
                   visual_assets: Optional[list[dict]] = None,
                   approved_logos: Optional[list[dict]] = None,
                   document_bytes: Optional[bytes] = None) -> Computed:
    text = sv["extracted_text"]
    c = Computed()
    # Stage A: deterministic (essential: exceptions propagate)
    det = run_checks(text, facts, rules, sv["source_type"])
    c.findings.extend(det.findings)
    c.dependencies = det.dependencies
    c.fact_versions, c.rule_versions = det.evaluated_fact_versions, det.evaluated_rule_versions
    c.stages["deterministic"] = {"status": "completed", "message": f"{len(det.findings)} finding(s) from "
                                 f"{len(c.fact_versions)} fact(s) and {len(c.rule_versions)} rule(s)."}
    warn = False
    pages = visual_pages or ([{"page_number": 1, "image_bytes": image_bytes}] if image_bytes is not None else [])
    if pages and approved_colors:
        try:
            delta_threshold = float(os.getenv("PROOFLINE_VISUAL_DELTA_E_THRESHOLD", "18"))
            coverage_threshold = float(os.getenv("PROOFLINE_VISUAL_COVERAGE_THRESHOLD", "0.12"))
            page_results = []
            all_findings = []
            for page in pages:
                result = analyze_palette(page["image_bytes"], approved_colors,
                                         delta_threshold=delta_threshold,
                                         coverage_threshold=coverage_threshold)
                page_number = int(page.get("page_number", len(page_results) + 1))
                page_results.append({"page_number": page_number, **result})
                for vf in result["findings"]:
                    finding = {**vf, "page_number": page_number}
                    all_findings.append(finding)
                    c.findings.append(RawFinding(
                        origin="visual", category="unapproved_color", title="Possible unapproved dominant color",
                        explanation=(f"Page {page_number}: {vf['color']} covers {vf['coverage']:.0%} of the page and is ΔE {vf['delta_e']} "
                                     f"from nearest approved color {vf['nearest_approved']}. Photos and rendering effects can explain this difference."),
                        severity="medium", excerpt=f"Page {page_number}: {vf['color']}", verification_status="needs_human_review",
                        location={"label": f"Page {page_number}" if visual_page_count is not None else "Uploaded image",
                                  "kind": "page" if visual_page_count is not None else "image",
                                  **(vf.get("coordinates") or {})}))
            truncated = visual_page_count is not None and visual_page_count > len(pages)
            c.visual_details = {"status": "completed", "method": "CIE76 dominant-color distance",
                                "delta_threshold": delta_threshold, "coverage_threshold": coverage_threshold,
                                "page_count": visual_page_count or len(pages), "pages_analyzed": len(page_results),
                                "truncated": truncated, "pages": page_results, "findings": all_findings,
                                "limitations": ["Palette screening can flag colors in photographs, gradients, shadows, and antialiasing.",
                                                "Logo identity, typography, and layout are not analyzed."]}
            c.stages["visual"] = {"status": "partial", "message": (
                f"Color palette screened on {len(page_results)} page(s)" + (f" of {visual_page_count}; remaining pages were not analyzed." if truncated else ".") +
                " Logo, typography, and layout are not analyzed."),
                "findings": len(all_findings), "pages_analyzed": len(page_results),
                "page_count": visual_page_count or len(page_results), "truncated": truncated}
        except ValueError as e:
            c.visual_details = {"status": "failed", "message": str(e)}
            c.stages["visual"] = {"status": "failed", "message": "Image or PDF page palette analysis failed."}
    else:
        c.stages["visual"] = {"status": "unavailable", "message": "Palette screening needs an image or rendered PDF page and an approved palette. Typography and layout checks are not implemented."}
    logo_analysis = analyze_logo_references(visual_assets or [], approved_logos or [],
                                             max_hamming_distance=int(os.getenv("PROOFLINE_LOGO_MAX_HASH_DISTANCE", "7")))
    c.visual_details["logo_analysis"] = logo_analysis
    for item in logo_analysis.get("matches", []):
        page_label = f"Slide {item['page_number']}" if item.get("asset_kind") == "pptx_image" and item.get("page_number") else (
            f"Page {item['page_number']}" if item.get("page_number") else "Uploaded image")
        if item["status"] == "unrecognized_logo_candidate":
            title = "Logo candidate does not match an approved reference"
            explanation = item["message"]
            category = "unrecognized_logo_candidate"
        elif item.get("issues"):
            title = "Possible logo distortion or rotation"
            explanation = (f"{page_label}: the image resembles approved logo {item['reference_name']} "
                           f"(perceptual hash distance {item['perceptual_hash_distance']}/64) and has "
                           f"{', '.join(item['issues']).replace('_', ' ')}. Human review is required.")
            category = "possible_logo_misuse"
        else:
            title = "Image resembles an approved logo"
            explanation = (f"{page_label}: the image resembles approved logo {item['reference_name']} "
                           f"(perceptual hash distance {item['perceptual_hash_distance']}/64). This similarity "
                           "is a review lead, not identity proof.")
            category = "logo_reference_match"
        c.findings.append(RawFinding(origin="visual", category=category, title=title, explanation=explanation,
                                     severity="medium" if item.get("issues") or item["status"] == "unrecognized_logo_candidate" else "low",
                                     excerpt=page_label, verification_status="needs_human_review",
                                     location={"label": page_label,
                                               "kind": "slide" if item.get("asset_kind") == "pptx_image" else "page" if item.get("page_number") else "image",
                                               **(item.get("coordinates") or {})}))
    if approved_logos:
        previous_visual = c.stages.get("visual", {})
        previous_message = previous_visual.get("message", "Color palette comparison is unavailable.")
        c.stages["visual"] = {"status": "partial", "message": (
            f"{previous_message} Logo references compared against {logo_analysis['assets_examined']} extracted image asset(s). "
            "Similarity findings require human confirmation; typography and layout checks are unavailable."),
            "logo_candidates": len(logo_analysis.get("matches", []))}
    elif c.stages.get("visual", {}).get("status") == "unavailable":
        c.stages["visual"]["message"] += " No approved logo references are configured."
    if document_bytes is not None:
        try:
            approved_fonts = [font.strip() for font in os.getenv("PROOFLINE_APPROVED_FONT_FAMILIES", "").split(",") if font.strip()]
            min_font_size = os.getenv("PROOFLINE_FONT_MIN_SIZE_PT", "").strip()
            max_font_size = os.getenv("PROOFLINE_FONT_MAX_SIZE_PT", "").strip()
            min_margin = os.getenv("PROOFLINE_LAYOUT_MIN_MARGIN_INCHES", "").strip()
            style_results = analyze_document_typography_layout(
                document_bytes, sv["source_type"], approved_fonts=approved_fonts,
                min_font_size_pt=float(min_font_size) if min_font_size else None,
                max_font_size_pt=float(max_font_size) if max_font_size else None,
                min_margin_inches=float(min_margin) if min_margin else None)
            c.visual_details["typography_analysis"] = style_results["typography"]
            c.visual_details["layout_analysis"] = style_results["layout"]
            c.stages["typography"] = {"status": style_results["typography"]["status"],
                                       "message": style_results["typography"]["message"],
                                       "findings": len(style_results["typography"]["findings"])}
            c.stages["layout"] = {"status": style_results["layout"]["status"],
                                   "message": style_results["layout"]["message"],
                                   "findings": len(style_results["layout"]["findings"])}
            for category, section, title in (("typography", "typography", "Typography policy candidate"),
                                             ("layout", "layout", "Possible layout margin violation")):
                for item in style_results[section]["findings"]:
                    label = (f"Slide {item['page_number']}" if item.get("kind") == "slide" and item.get("page_number") else
                             f"Page {item['page_number']}" if item.get("page_number") else
                             f"Paragraph {item['coordinates'].get('paragraph')}" if item.get("coordinates", {}).get("paragraph") else "Document")
                    c.findings.append(RawFinding(origin="visual", category=f"visual_{category}", title=title,
                                                 explanation=f"{label}: {item['message']} Human review is required.",
                                                 severity="medium", excerpt=label,
                                                 verification_status="needs_human_review",
                                                 location={"label": label, "kind": item.get("kind", "document"),
                                                           **(item.get("coordinates") or {})}))
        except (ValueError, TypeError) as exc:
            c.visual_details["typography_layout_error"] = f"Configured typography/layout checks could not run ({type(exc).__name__})."
            c.stages["typography"] = {"status": "failed", "message": c.visual_details["typography_layout_error"]}
            c.stages["layout"] = {"status": "failed", "message": c.visual_details["typography_layout_error"]}
    c.stages["proof_provenance"] = {"status": "unavailable", "message": "Uploaded proof provenance and source reliability are not assessed yet."}
    warn = True
    # Extraction limitations are findings in their own right
    if sv["extraction_status"] != "complete":
        warn = True
        c.findings.append(RawFinding(
            origin="extraction", category="extraction_limitation",
            title=f"Extraction was {sv['extraction_status']}: review is incomplete",
            explanation=" ".join(sv["extraction_warnings"] or []) or "Content could not be fully extracted.",
            severity="medium", verification_status="needs_human_review"))
    # Stage B: semantic (optional)
    if llm.configured():
        try:
            sem, notes = run_semantic_review(text, facts, rules, llm)
            c.findings.extend(sem)
            c.stages["semantic"] = {"status": "completed", "message": " ".join(notes) or f"{len(sem)} suggestion(s)."}
        except ProviderError as e:
            warn = True
            c.stages["semantic"] = {"status": "failed", "message": str(e)}
    else:
        warn = True
        c.stages["semantic"] = {"status": "unavailable", "message": "Semantic review skipped: no LLM provider is configured."}
    # Stage C: external verification (optional)
    results, v_status, v_msg = verify_claims(text, search, llm if llm.configured() else None, brand_context,
                                              source_fetcher=fetch_claim_source, product_sources=product_sources)
    c.stages["verification"] = {"status": v_status, "message": v_msg}
    if v_status not in ("completed",):
        warn = True
    for r in results:
        sev = "high" if r.status in ("contradicted", "conflicting") else "medium"
        category = "verified_contradiction" if r.status == "contradicted" else "claim_verification"
        if r.status == "supported":
            title, expl = "Claim supported by retrieved evidence", "At least one retrieved source directly supports this claim."
            sev = "low"
        elif r.status == "contradicted":
            title, expl = "Claim contradicted by retrieved evidence", "A retrieved source directly contradicts this claim."
        elif r.status == "conflicting":
            title, expl = "Sources conflict on this claim", "Retrieved sources both support and contradict the claim."
        elif r.status == "insufficient_evidence":
            title, expl = "Insufficient evidence for claim", ("No retrieved source directly addressed this claim. "
                                                                "This is not evidence that the claim is false.")
        elif r.status == "unavailable":
            title, expl = "Claim could not be checked", r.note or "The verification service was unavailable."
        else:
            title, expl = "Claim needs human verification", r.note or "A human must assess the retrieved sources."
        if r.note and r.status not in ("unavailable", "needs_human_review"):
            expl += " " + r.note
        idx = len(c.findings)
        c.findings.append(RawFinding(
            origin="verification", category=category, title=title, explanation=expl, severity=sev,
            span_start=r.claim.start, span_end=r.claim.end, excerpt=r.claim.text, verification_status=r.status))
        for e in r.evidence:
            if e.access_status == "ok" and e.stance in ("irrelevant", "unclear"):
                continue
            c.evidence.append((idx, {"title": e.title, "url": e.url, "publisher": e.publisher,
                                     "published_at": e.published_at, "excerpt": e.quote or e.excerpt[:500],
                                     "stance": e.stance, "search_query": e.search_query,
                                     "access_status": e.access_status, "extraction_status": e.extraction_status,
                                     "product_research_source_id": e.product_research_source_id}))
    c.status = "completed_with_warnings" if warn else "completed"
    return c


def persist_review(conn: Connection, *, workspace_id: UUID, sv: dict, user_id: UUID, c: Computed) -> UUID:
    run = q1(conn, """insert into review_runs (workspace_id, submission_version_id, status, stages, engine_version,
                                              requested_by, completed_at)
                      values (:ws, :sv, :st, cast(:stages as jsonb), :eng, :u, now()) returning id""",
             ws=workspace_id, sv=sv["id"], st=c.status, stages=jb(c.stages), eng=ENGINE, u=user_id)
    run_id = run["id"]
    for fv in c.fact_versions:
        ex(conn, "insert into review_run_fact_versions values (:r, :v)", r=run_id, v=UUID(fv))
    for rv in c.rule_versions:
        ex(conn, "insert into review_run_rule_versions values (:r, :v)", r=run_id, v=UUID(rv))
    segs = sv["segments"] or []
    ids: list[UUID] = []
    for f in c.findings:
        loc = locate(segs, f.span_start)
        row = q1(conn, """insert into findings (workspace_id, review_run_id, submission_version_id, origin, category,
                            title, explanation, severity, excerpt, span_start, span_end, location, fact_version_id,
                            rule_version_id, verification_status)
                          values (:ws, :run, :sv, :o, :cat, :t, :e, :sev, :ex, :ss, :se, cast(:loc as jsonb), :fv, :rv, :vs)
                          returning id""",
                 ws=workspace_id, run=run_id, sv=sv["id"], o=f.origin, cat=f.category, t=f.title, e=f.explanation,
                 sev=f.severity, ex=f.excerpt, ss=f.span_start, se=f.span_end,
                 loc=jb(f.location or loc) if (f.location or loc) else None,
                 fv=UUID(f.fact_version_id) if f.fact_version_id else None,
                 rv=UUID(f.rule_version_id) if f.rule_version_id else None, vs=f.verification_status)
        ids.append(row["id"])
        # evidence links to the approved fact/rule that triggered the finding
        if f.fact_version_id:
            ex(conn, """insert into finding_evidence (workspace_id, finding_id, kind, fact_version_id, stance, excerpt)
                        values (:ws, :f, 'brand_fact', :v, 'reference', :ex)""",
               ws=workspace_id, f=row["id"], v=UUID(f.fact_version_id), ex=f.excerpt)
        if f.rule_version_id:
            ex(conn, """insert into finding_evidence (workspace_id, finding_id, kind, rule_version_id, stance, excerpt)
                        values (:ws, :f, 'brand_rule', :v, 'reference', :ex)""",
               ws=workspace_id, f=row["id"], v=UUID(f.rule_version_id), ex=f.excerpt)
    for idx, ev in c.evidence:
        src = q1(conn, """insert into source_records (workspace_id, kind, title, url, publisher, retrieved_at, published_at,
                            content_hash, access_status, excerpt, search_query, extraction_status, created_by,
                            product_research_source_id)
                          values (:ws, 'external_retrieval', :t, :u, :p, now(), cast(:pub as timestamptz),
                                  encode(digest(:ex, 'sha256'), 'hex'), :access, :ex, :query, :extract, :uid, :product_source) returning id""",
                 ws=workspace_id, t=ev["title"][:300], u=ev["url"], p=ev["publisher"], pub=_safe_ts(ev["published_at"]),
                 access=ev["access_status"], ex=ev["excerpt"], query=ev["search_query"], extract=ev["extraction_status"], uid=user_id,
                 product_source=UUID(ev["product_research_source_id"]) if ev.get("product_research_source_id") else None)
        ex(conn, """insert into finding_evidence (workspace_id, finding_id, kind, source_record_id, stance, excerpt)
                    values (:ws, :f, 'external_source', :s, :st, :ex)""",
           ws=workspace_id, f=ids[idx], s=src["id"], st=ev["stance"], ex=ev["excerpt"])
    # dependency links used by the Brand Time Machine
    first_for: dict[str, UUID] = {}
    for f, fid in zip(c.findings, ids):
        for v in (f.fact_version_id, f.rule_version_id):
            if v and v not in first_for:
                first_for[v] = fid
    for d in c.dependencies:
        ver = d.fact_version_id or d.rule_version_id
        ex(conn, """insert into finding_dependencies (workspace_id, review_run_id, submission_version_id, finding_id,
                      fact_id, fact_version_id, rule_id, rule_version_id, dependency_kind)
                    values (:ws, :run, :sv, :fid, :fi, :fv, :ri, :rv, :k)""",
           ws=workspace_id, run=run_id, sv=sv["id"], fid=first_for.get(ver) if d.kind == "violation" else None,
           fi=UUID(d.fact_id) if d.fact_id else None, fv=UUID(d.fact_version_id) if d.fact_version_id else None,
           ri=UUID(d.rule_id) if d.rule_id else None, rv=UUID(d.rule_version_id) if d.rule_version_id else None,
           k=d.kind)
    audit(conn, workspace_id, user_id, "review.completed", "review_run", run_id,
          f"Review run {c.status} with {len(c.findings)} finding(s)",
          {"submission_version_id": str(sv["id"]), "stages": {k: v["status"] for k, v in c.stages.items()},
           "fact_versions": c.fact_versions, "rule_versions": c.rule_versions,
           "automated_outcome": c.automated_decision.outcome if c.automated_decision else "unavailable",
           "risk_score": c.automated_decision.risk_score if c.automated_decision else None})
    if c.automated_decision is None:
        raise RuntimeError("Review has no automated governance assessment")
    ex(conn, """insert into automated_decisions
                (workspace_id, submission_version_id, review_run_id, outcome, risk_score, rationale, factors, policy_version)
                values (:ws, :sv, :run, :outcome, :score, :rationale, cast(:factors as jsonb), :policy)""",
       ws=workspace_id, sv=sv["id"], run=run_id, outcome=c.automated_decision.outcome,
       score=c.automated_decision.risk_score, rationale=c.automated_decision.rationale,
       factors=jb(c.automated_decision.factors), policy=c.automated_decision.policy_version)
    visual_status = c.stages.get("visual", {}).get("status", "unavailable")
    if table_exists(conn, "visual_analyses"):
        ex(conn, """insert into visual_analyses(workspace_id, submission_version_id, review_run_id, status, results)
                    values (:ws,:sv,:run,:st,cast(:results as jsonb))""",
           ws=workspace_id, sv=sv["id"], run=run_id, st=visual_status,
           results=jb(c.visual_details or c.stages.get("visual", {})))
    return run_id


def _safe_ts(s: Optional[str]) -> Optional[str]:
    """Only pass through values Postgres can parse; unknown formats become NULL rather than invented."""
    if not s:
        return None
    import re
    return s if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def record_failed_run(workspace_id: UUID, sv_id: UUID, user_id: UUID, error: str) -> UUID:
    with transaction() as conn:
        row = q1(conn, """insert into review_runs (workspace_id, submission_version_id, status, stages, engine_version,
                                                  requested_by, completed_at, error)
                          values (:ws, :sv, 'failed', '{}'::jsonb, :eng, :u, now(), :err) returning id""",
                 ws=workspace_id, sv=sv_id, eng=ENGINE, u=user_id, err=error[:500])
        audit(conn, workspace_id, user_id, "review.failed", "review_run", row["id"], "Review run failed",
              {"submission_version_id": str(sv_id)})
        return row["id"]
