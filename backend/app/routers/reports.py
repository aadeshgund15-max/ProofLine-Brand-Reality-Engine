"""Read-only, workspace-scoped PDF exports for persisted submission reviews."""
from __future__ import annotations

import html
import io
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import Connection

from app.auth import Member, member_of
from app.db import get_conn, q, q1

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


def _text(value: Any, fallback: str = "Not recorded") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return html.escape(str(value)).replace("\n", "<br/>")


def render_review_report(data: dict[str, Any]) -> bytes:
    """Render persisted report fields without inventing absent evidence or conclusions."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.65 * inch, title="Proofline Review Report")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], alignment=TA_CENTER,
                              textColor=colors.HexColor("#17324D"), spaceAfter=14))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#17324D"),
                              spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10,
                              textColor=colors.HexColor("#536273")))
    story = [Paragraph("Proofline · Review report", styles["ReportTitle"]),
             Paragraph(_text(data.get("title")), styles["Heading1"]),
             Paragraph(f"Generated {datetime.now(timezone.utc).isoformat()} · Submission { _text(data.get('submission_id')) }",
                       styles["Small"]), Spacer(1, 10)]

    metadata = [
        ["Submission", _text(data.get("title")), "Revision", _text(data.get("version_no"))],
        ["Created", _text(data.get("created_at")), "Extraction", _text(data.get("extraction_status"))],
        ["Review run", _text(data.get("review_id")), "Review status", _text(data.get("review_status"))],
    ]
    table = Table(metadata, colWidths=[0.9 * inch, 2.55 * inch, 0.9 * inch, 2.25 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F7")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EEF3F7")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D6DEE6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([table, Paragraph("Scope and limitations", styles["Section"]),
                  Paragraph("This report contains records stored by Proofline for this submission and review. "
                            "A missing section means no corresponding record was available; it does not establish "
                            "that a claim is true or false.", styles["BodyText"])])

    stages = data.get("stages") or {}
    story.append(Paragraph("Review stages", styles["Section"]))
    if stages:
        for name, stage in stages.items():
            stage = stage if isinstance(stage, dict) else {"status": str(stage)}
            story.append(Paragraph(f"<b>{_text(name.replace('_', ' ').title())}</b> · "
                                   f"{_text(stage.get('status'))} · {_text(stage.get('message'))}", styles["BodyText"]))
    else:
        story.append(Paragraph("No review stage records are available.", styles["BodyText"]))

    story.append(Paragraph("Product identity and research", styles["Section"]))
    product = data.get("product")
    if product:
        story.append(Paragraph(f"{_text(product.get('brand'))} {_text(product.get('product_name'))} · "
                                f"manufacturer {_text(product.get('manufacturer'))} · model {_text(product.get('model_number'))} · "
                                f"identity {_text(product.get('identity_status'))}", styles["BodyText"]))
        profile = product.get("profile") or {}
        coverage = product.get("coverage") or {}
        story.append(Paragraph(f"Research coverage: {_text(coverage.get('queries_executed', 0))} queries · "
                               f"{_text(coverage.get('sources_inspected', 0))} inspected sources · "
                               f"{_text(coverage.get('sources_inaccessible', 0))} inaccessible · "
                               f"profile extraction {_text(coverage.get('profile_extraction_status', 'not recorded'))}.",
                               styles["BodyText"]))
        for source in profile.get("sources") or []:
            story.append(Paragraph(f"Source: {_text(source.get('title'))} · {_text(source.get('url'))} · "
                                   f"{_text(source.get('access_status'))} / {_text(source.get('extraction_status'))} · "
                                   f"product match {_text(source.get('product_match_status'))}", styles["Small"]))
        facts = profile.get("facts") or []
        for fact in facts:
            story.append(Paragraph(f"<b>{_text(fact.get('category'))}</b>: {_text(fact.get('quote'))}<br/>"
                                   f"Source: {_text(fact.get('source_title'))} · {_text(fact.get('source_url'))} · "
                                   f"evidence status {_text(fact.get('evidence_status'))}", styles["BodyText"]))
        story.append(Paragraph("These are source-bound observations; independent verification and source-quality "
                               "assessment are not implied.", styles["Small"]))
    else:
        story.append(Paragraph("No product was linked to this submission revision.", styles["BodyText"]))

    story.append(Paragraph("Findings and evidence", styles["Section"]))
    findings = data.get("findings") or []
    if findings:
        evidence_by_finding: dict[str, list[dict]] = {}
        for evidence in data.get("finding_evidence") or []:
            evidence_by_finding.setdefault(str(evidence.get("finding_id")), []).append(evidence)
        for finding in findings:
            story.append(Paragraph(f"<b>{_text(finding.get('title'))}</b> · "
                                   f"{_text(finding.get('severity'))} · {_text(finding.get('verification_status'))}",
                                   styles["BodyText"]))
            story.append(Paragraph(_text(finding.get("excerpt")), styles["Small"]))
            story.append(Paragraph(_text(finding.get("explanation")), styles["BodyText"]))
            for evidence in evidence_by_finding.get(str(finding.get("id")), []):
                story.append(Paragraph(f"Evidence · {_text(evidence.get('stance'))}: {_text(evidence.get('excerpt'))}<br/>"
                                       f"{_text(evidence.get('source_title'))} · {_text(evidence.get('source_url'))}",
                                       styles["Small"]))
            story.append(Spacer(1, 6))
    else:
        story.append(Paragraph("No findings are recorded for the latest review run.", styles["BodyText"]))

    story.append(Paragraph("Uploaded proof assessments", styles["Section"]))
    assessments = data.get("assessments") or []
    if assessments:
        for item in assessments:
            story.append(Paragraph(f"<b>{_text(item.get('original_filename'))}</b> · {_text(item.get('assessment'))}: "
                                   f"{_text(item.get('explanation'))}<br/>{_text(item.get('excerpt'))}", styles["BodyText"]))
    else:
        story.append(Paragraph("No uploaded-proof assessments are recorded for this review.", styles["BodyText"]))

    visual = data.get("visual_analysis")
    story.append(Paragraph("Visual analysis", styles["Section"]))
    if visual:
        results = visual.get("results") or {}
        story.append(Paragraph(f"Status: {_text(visual.get('status'))}. {_text(results.get('message'))}", styles["BodyText"]))
        for finding in results.get("findings") or []:
            story.append(Paragraph(_text(finding), styles["Small"]))
        for limitation in results.get("limitations") or []:
            story.append(Paragraph(_text(limitation), styles["Small"]))
    else:
        story.append(Paragraph("No visual-analysis record is available for the latest review.", styles["BodyText"]))

    decision = data.get("automated_decision")
    story.append(Paragraph("Governance decision and history", styles["Section"]))
    if decision:
        story.append(Paragraph(f"Automated outcome: <b>{_text(decision.get('outcome'))}</b> · risk score "
                               f"{_text(decision.get('risk_score'))}/100 · policy {_text(decision.get('policy_version'))}",
                               styles["BodyText"]))
        story.append(Paragraph(_text(decision.get("rationale")), styles["BodyText"]))
        for factor in decision.get("factors") or []:
            story.append(Paragraph(f"{_text(factor.get('detail'))} · weight {_text(factor.get('weight'))}", styles["Small"]))
    else:
        story.append(Paragraph("No automated decision is recorded for the latest review.", styles["BodyText"]))
    for item in data.get("human_decisions") or []:
        story.append(Paragraph(f"Human decision: {_text(item.get('decision'))} · {_text(item.get('decided_at'))} · "
                               f"{_text(item.get('comment'))}", styles["BodyText"]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#536273"))
        canvas.drawString(0.65 * inch, 0.35 * inch, "Proofline · Evidence report")
        canvas.drawRightString(7.85 * inch, 0.35 * inch, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


@router.get("/submissions/{submission_id}/report.pdf")
def download_report(submission_id: UUID, m: Member = Depends(member_of()), conn: Connection = Depends(get_conn)):
    submission = q1(conn, """select s.id submission_id,s.title,s.created_at,sv.id version_id,sv.version_no,
                            sv.extraction_status,sv.extraction_warnings,sv.extracted_text,sv.created_at version_created_at
                            from submissions s join submission_versions sv on sv.id=s.current_version_id
                            where s.id=:s and s.workspace_id=:w""", s=submission_id, w=m.workspace_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    run = q1(conn, """select id,status,stages,engine_version,started_at,completed_at
                     from review_runs where submission_version_id=:v and workspace_id=:w
                     order by started_at desc limit 1""", v=submission["version_id"], w=m.workspace_id)
    findings = q(conn, """select id,title,category,severity,verification_status,excerpt,explanation,created_at
                         from findings where review_run_id=:r and workspace_id=:w order by created_at""",
                 r=run["id"] if run else None, w=m.workspace_id) if run else []
    finding_evidence = q(conn, """select fe.finding_id,fe.stance,fe.excerpt,sr.title source_title,sr.url source_url
                                  from finding_evidence fe left join source_records sr on sr.id=fe.source_record_id
                                  where fe.workspace_id=:w and fe.finding_id in
                                  (select id from findings where review_run_id=:r and workspace_id=:w)
                                  order by fe.created_at""", w=m.workspace_id, r=run["id"]) if run else []
    assessments = q(conn, """select e.original_filename,a.assessment,a.explanation,a.excerpt
                            from evidence_assessments a join submission_evidence e on e.id=a.evidence_id
                            where a.review_run_id=:r and a.workspace_id=:w order by a.created_at""",
                    r=run["id"] if run else None, w=m.workspace_id) if run else []
    visual = q1(conn, """select status,results from visual_analyses where review_run_id=:r and workspace_id=:w""",
                r=run["id"], w=m.workspace_id) if run else None
    decision = q1(conn, """select outcome,risk_score,rationale,factors,policy_version
                           from automated_decisions where review_run_id=:r and workspace_id=:w""",
                  r=run["id"], w=m.workspace_id) if run else None
    human = q(conn, """select decision,comment,decided_at from review_decisions
                       where submission_version_id=:v and workspace_id=:w order by decided_at""",
              v=submission["version_id"], w=m.workspace_id)
    product = q1(conn, """select p.product_name,p.brand,p.manufacturer,p.model_number,p.identity_status,
                          pp.profile
                   from submission_product_links l join products p on p.id=l.product_id
                   left join lateral (select profile,coverage from product_profiles where product_id=p.id
                                      order by version_no desc limit 1) pp on true
                   where l.submission_version_id=:v and l.workspace_id=:w""",
                 v=submission["version_id"], w=m.workspace_id)
    payload = {**submission, "review_id": run.get("id") if run else None,
               "review_status": run.get("status") if run else None,
               "stages": run.get("stages") if run else {}, "findings": findings,
               "finding_evidence": finding_evidence, "assessments": assessments,
               "visual_analysis": visual, "automated_decision": decision,
               "human_decisions": human, "product": product}
    pdf = render_review_report(payload)
    safe_title = "".join(c for c in (submission["title"] or "submission")
                         if c.isascii() and (c.isalnum() or c in "-_ ")).strip()
    filename = (safe_title or "submission")[:80].replace(" ", "-") + "-proofline-report.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
