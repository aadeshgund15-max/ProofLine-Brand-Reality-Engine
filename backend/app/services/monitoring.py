"""Durable public-page snapshot worker. It performs no script execution."""
from __future__ import annotations

import difflib
import hashlib
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone

from app.config import settings
from app.core.ssrf import FetchError, UnsafeUrlError, safe_fetch
from app.db import ex, jb, q, q1, transaction
from app.extract import extract_html, extract_text
from app.core.governance import assess_review
from app.services.product_intelligence import review_gate
from app.providers.base import get_llm_provider, get_search_provider
from app.services.review import compute_review, load_reference_versions
from app.core.verification import extract_claim_candidates

log = logging.getLogger("proofline.monitoring")


def _next_text(result) -> str:
    return " ".join((result.text or "").split())[:500_000]


def _meaningful_change(previous: str, current: str) -> bool:
    """Suppress small copy edits while always surfacing changed numerical/checkable claims."""
    old_claims = {" ".join(c.text.lower().split()) for c in extract_claim_candidates(previous)}
    new_claims = {" ".join(c.text.lower().split()) for c in extract_claim_candidates(current)}
    if old_claims != new_claims:
        return True
    number = re.compile(r"\b\d+(?:[.,]\d+)?\s*%?\b")
    if set(number.findall(previous)) != set(number.findall(current)):
        return True
    old_words, new_words = set(re.findall(r"[a-z0-9]+", previous.lower())), set(re.findall(r"[a-z0-9]+", current.lower()))
    changed = len(old_words ^ new_words)
    return changed >= 6 and changed / max(1, len(old_words | new_words)) >= 0.02


def _claim_due(limit: int) -> list[dict]:
    with transaction() as conn:
        return q(conn, """with chosen as (
                          select id from monitored_sources
                          where status='active' and next_check_at<=now()
                            and (lease_until is null or lease_until<now())
                          order by next_check_at limit :n for update skip locked
                        )
                          update monitored_sources s set lease_until=now()+interval '15 minutes'
                        from chosen where s.id=chosen.id
                        returning s.id,s.workspace_id,s.url,s.interval_minutes,s.failure_count""", n=limit)


def _record_failure(source: dict, started: datetime, code: str) -> dict:
    delay = min(1440, 15 * (2 ** min(int(source["failure_count"]), 6)))
    with transaction() as conn:
        ex(conn, """insert into monitoring_runs(workspace_id,monitored_source_id,status,error_code,started_at)
                    values (:w,:s,'failed',:e,:t)""", w=source["workspace_id"], s=source["id"], e=code[:80], t=started)
        ex(conn, """update monitored_sources set failure_count=failure_count+1,
                    next_check_at=now()+(:delay || ' minutes')::interval, lease_until=null,
                    status=case when :unsafe then 'error' else status end
                    where id=:s""", delay=delay, unsafe=code == "UnsafeUrlError", s=source["id"])
    return {"source_id": source["id"], "status": "failed", "error_code": code, "retry_in_minutes": delay}


def _check_one(source: dict) -> dict:
    started = datetime.now(timezone.utc)
    try:
        result = safe_fetch(source["url"], max_bytes=settings.max_url_bytes, timeout=settings.url_timeout_s)
        content_type = result.content_type.split(";", 1)[0].strip().lower()
        if content_type in ("text/html", "application/xhtml+xml"):
            extracted = extract_html(result.body, result.final_url, result.truncated)
        elif content_type == "text/plain":
            extracted = extract_text(result.body.decode("utf-8", "replace"))
        else:
            return _record_failure(source, started, "UnsupportedContentType")
        text = _next_text(extracted)
        if not text or extracted.status in ("failed", "empty", "unsupported"):
            return _record_failure(source, started, "NoReadablePageText")
    except (UnsafeUrlError, FetchError) as exc:
        return _record_failure(source, started, type(exc).__name__)
    except Exception as exc:
        return _record_failure(source, started, type(exc).__name__)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with transaction() as conn:
        previous = q1(conn, """select id,version_no,extracted_text,content_hash from monitoring_snapshots
                              where monitored_source_id=:s order by version_no desc limit 1 for update""", s=source["id"])
        if previous and previous["content_hash"] == digest:
            run = q1(conn, """insert into monitoring_runs(workspace_id,monitored_source_id,status,snapshot_id,started_at)
                              values (:w,:s,'unchanged',:snap,:t) returning id""",
                     w=source["workspace_id"], s=source["id"], snap=previous["id"], t=started)
            ex(conn, """update monitored_sources set last_checked_at=now(), next_check_at=now()+(:i || ' minutes')::interval,
                        failure_count=0,lease_until=null where id=:s""", i=source["interval_minutes"], s=source["id"])
            return {"source_id": source["id"], "run_id": run["id"], "status": "unchanged", "snapshot_id": previous["id"]}

        version = (previous["version_no"] if previous else 0) + 1
        meaningful = bool(previous and _meaningful_change(previous["extracted_text"], text))
        snap = q1(conn, """insert into monitoring_snapshots(workspace_id,monitored_source_id,version_no,final_url,
                         content_hash,extracted_text,metadata)
                         values (:w,:s,:v,:url,:hash,:text,cast(:meta as jsonb)) returning id""",
                  w=source["workspace_id"], s=source["id"], v=version, url=result.final_url, hash=digest, text=text,
                  meta=jb({"content_type": content_type, "truncated": result.truncated, "meaningful_change": meaningful,
                           "extraction_status": extracted.status, "extraction_warnings": extracted.warnings}))
        run_status = "completed" if not previous or meaningful else "unchanged"
        run = q1(conn, """insert into monitoring_runs(workspace_id,monitored_source_id,status,snapshot_id,started_at)
                          values (:w,:s,:status,:snap,:t) returning id""",
                 w=source["workspace_id"], s=source["id"], status=run_status, snap=snap["id"], t=started)
        change_id = None
        if previous and meaningful:
            diff = list(difflib.unified_diff(previous["extracted_text"].splitlines()[:500], text.splitlines()[:500],
                                             fromfile=f"snapshot-{previous['version_no']}", tofile=f"snapshot-{version}",
                                             lineterm=""))
            excerpt = "\n".join(diff[:30])[:2000]
            change = q1(conn, """insert into monitoring_changes(workspace_id,monitored_source_id,previous_snapshot_id,
                            current_snapshot_id,change_summary,change_excerpt)
                            values (:w,:s,:old,:new,:summary,:excerpt) returning id""",
                        w=source["workspace_id"], s=source["id"], old=previous["id"], new=snap["id"],
                        summary=f"Public page text changed between snapshots {previous['version_no']} and {version}.",
                        excerpt=excerpt)
            change_id = change["id"]
        ex(conn, """update monitored_sources set last_checked_at=now(),next_check_at=now()+(:i || ' minutes')::interval,
                    failure_count=0,lease_until=case when :changed then lease_until else null end where id=:s""",
           i=source["interval_minutes"], changed=bool(previous), s=source["id"])
        result_row = {"source_id": source["id"], "run_id": run["id"],
                      "status": "changed" if meaningful else "baseline" if not previous else "unchanged",
                      "snapshot_id": snap["id"], "change_id": change_id}
    if change_id:
        try:
            result_row["automatic_review"] = _review_change(source["id"], change_id, text, source["workspace_id"])
        finally:
            with transaction() as conn:
                ex(conn, "update monitored_sources set lease_until=null where id=:s", s=source["id"])
    return result_row


def _review_change(source_id, change_id, text: str, workspace_id) -> dict:
    """Recheck changed public text against current approved facts and rules."""
    try:
        with transaction() as conn:
            source = q1(conn, """select s.workspace_id,s.brand_profile_id,p.name brand_name,pr.id product_id,
                                 pr.product_name,pr.brand,pr.manufacturer,pr.model_number,pr.product_category,pr.market,
                                 pr.identity_status,r.id research_run_id,r.status research_status,r.coverage
                                 from monitored_sources s join brand_profiles p on p.id=s.brand_profile_id
                                 left join products pr on pr.id=s.product_id
                                 left join lateral (select id,status,coverage from product_research_runs where product_id=pr.id
                                 order by created_at desc limit 1) r on true
                                 where s.id=:s""", s=source_id)
            facts, rules = load_reference_versions(conn, source["workspace_id"], source["brand_profile_id"])
        product = {key: source.get(key) for key in ("id", "product_id", "product_name", "brand", "manufacturer",
                  "model_number", "product_category", "market", "identity_status", "research_status", "coverage")}
        product["id"] = product.get("product_id")
        context = " ".join(filter(None, [source["brand_name"], source.get("brand"), source.get("product_name"),
                          source.get("manufacturer"), source.get("model_number"), source.get("product_category"), source.get("market")]))
        computed = compute_review({"extracted_text": text, "source_type": "url", "extraction_status": "complete",
                                   "extraction_warnings": []}, facts, rules, get_search_provider(), get_llm_provider(),
                                  context)
        product_status, product_message = review_gate(product if product.get("product_id") else None)
        computed.stages["product_intelligence"] = {"status": product_status, "message": product_message,
            "product_id": str(product["product_id"]) if product.get("product_id") else None,
            "research_run_id": str(product["research_run_id"]) if product.get("research_run_id") else None,
            "coverage": product.get("coverage")}
        decision = assess_review(findings=computed.findings, stages=computed.stages, extraction_status="complete",
                                 evidence_assessments=[])
        report = {"stages": computed.stages, "findings": [asdict(f) for f in computed.findings],
                  "evidence": [{"finding_index": i, **item} for i, item in computed.evidence],
                  "fact_versions": computed.fact_versions, "rule_versions": computed.rule_versions,
                  "decision_rationale": decision.rationale, "factors": decision.factors}
        status = computed.status
    except Exception as exc:
        decision = assess_review(findings=[], stages={"review": {"status": "failed"}},
                                 extraction_status="failed", evidence_assessments=[])
        report = {"error_code": type(exc).__name__, "decision_rationale": "The automatic re-review failed; human review is required."}
        status = "failed"
    with transaction() as conn:
        row = q1(conn, """insert into monitoring_change_reviews(workspace_id,change_id,status,outcome,risk_score,
                           policy_version,report) values (:w,:c,:st,:o,:score,:policy,cast(:report as jsonb))
                           returning id,status,outcome,risk_score""",
                 w=workspace_id, c=change_id, st=status,
                 o=decision.outcome, score=decision.risk_score, policy=decision.policy_version, report=jb(report))
    return row


def run_due_checks(limit: int = 10) -> list[dict]:
    """Claim and check due sources; safe to run in multiple worker processes."""
    return [_check_one(source) for source in _claim_due(max(1, min(limit, 50)))]


def worker_loop(poll_seconds: int = 30) -> None:
    while True:
        try:
            run_due_checks()
        except Exception as exc:
            # Keep the worker alive through transient database and provider failures; never log page text.
            log.error("Monitoring poll failed (%s)", type(exc).__name__)
        time.sleep(max(5, poll_seconds))
