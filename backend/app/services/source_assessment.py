"""Conservative, explainable source signals for product research records.

These rules describe observable signals. They do not verify a source, certify a
product, or decide whether a claim is true.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit


POLICY_VERSION = "source-signals-1"
_METHODOLOGY_TERMS = re.compile(
    r"\b(methodology|methods|sample size|participants|protocol|randomi[sz]ed|"
    r"independent laboratory|test procedure|tested against|control group|n\s*=\s*\d+)\b",
    re.I,
)
_DISCLOSURE_TERMS = re.compile(
    r"\b(sponsored by|paid partnership|affiliate link|commission may|funded by|"
    r"conflict of interest|financial relationship|provided by the manufacturer)\b",
    re.I,
)


def _positive_days(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return max(1, min(value, 3650))
    except (TypeError, ValueError):
        return default


def _published_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def assess_source(source: dict, *, now: datetime | None = None) -> dict:
    """Return a versioned assessment with explicit unknown states and reasons."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    text = source.get("text") or source.get("extracted_text") or ""
    category = str(source.get("category") or source.get("source_category") or "")
    match = source.get("product_match_status") or "unassessed"
    access = source.get("access_status") or "unknown"
    extraction = source.get("extraction_status") or "unknown"
    duplicate = bool(source.get("duplicate") or source.get("duplicate_of"))
    host = (urlsplit(str(source.get("url") or "")).hostname or "").lower().removeprefix("www.")

    if category == "official_candidate":
        authority = {"status": "manufacturer_claim_source", "verified": False,
                     "reason": "Domain matches the user-provided official website; statements remain manufacturer claims."}
    elif category == "government_or_regulator_candidate":
        authority = {"status": "registry_candidate_unverified", "verified": False,
                     "reason": "Domain/category is a government or regulator candidate; no registry record was checked."}
    elif category == "research_or_publication_candidate":
        authority = {"status": "publication_candidate_unverified", "verified": False,
                     "reason": "Domain/category suggests a publication; publication quality and peer review were not verified."}
    elif host:
        authority = {"status": "unassessed", "verified": False,
                     "reason": "No configured authority rule established this source's authority."}
    else:
        authority = {"status": "unassessed", "verified": False,
                     "reason": "A usable source hostname is unavailable."}

    if category == "official_candidate":
        independence = {"status": "not_independent", "reason": "Official manufacturer content is not independent verification."}
    else:
        independence = {"status": "unassessed", "reason": "Organizational independence was not verified."}

    if match == "matched_by_identifier":
        relevance = {"status": "identifier_matched", "reason": "Inspected page contained the supplied product identifier or exact product name."}
    elif match == "ambiguous":
        relevance = {"status": "ambiguous_product_match", "reason": "The source was not matched confidently to the supplied product identity."}
    else:
        relevance = {"status": "unassessed", "reason": "Product identity match was not assessed."}

    published = _published_datetime(source.get("published_at"))
    if published is None:
        freshness = {"status": "unknown", "age_days": None,
                     "reason": "No parseable publication date is available; retrieval date is not a publication date."}
    else:
        age_days = max(0, (now - published).days)
        fresh_days = _positive_days("PROOFLINE_SOURCE_FRESH_DAYS", 365)
        outdated_days = _positive_days("PROOFLINE_SOURCE_OUTDATED_DAYS", 1095)
        if age_days <= fresh_days:
            status = "recent_under_configured_threshold"
        elif age_days >= max(fresh_days + 1, outdated_days):
            status = "potentially_outdated"
        else:
            status = "aging"
        freshness = {"status": status, "age_days": age_days,
                     "threshold_days": {"recent": fresh_days, "potentially_outdated": outdated_days},
                     "reason": "Age is compared with configurable calendar thresholds; suitability depends on the product and claim."}

    readable = access == "ok" and extraction not in {"empty", "failed", "unsupported"} and bool(text.strip())
    directness = {"status": "full_page_inspected" if readable else "not_fully_inspected",
                  "reason": "Assessment uses retrieved page text." if readable else
                  "Search snippets or inaccessible/empty page text are not inspected source evidence."}
    methodology = {"status": "indicators_found" if _METHODOLOGY_TERMS.search(text) else "not_assessed",
                   "reason": "Method-related terms were found; study design was not validated." if _METHODOLOGY_TERMS.search(text)
                   else "No methodology indicator was found by the configured text scan; methodology quality is unknown."}
    disclosure = {"status": "disclosure_text_found" if _DISCLOSURE_TERMS.search(text) else "not_assessed",
                  "reason": "A possible sponsorship or relationship disclosure phrase was found." if _DISCLOSURE_TERMS.search(text)
                  else "No configured disclosure phrase was found; absence of detected text does not establish absence of a conflict."}
    duplication = {"status": "duplicate_content" if duplicate else "not_marked_duplicate",
                   "reason": "A matching content hash was linked to an earlier source record." if duplicate
                   else "No matching content hash was recorded for this source."}

    insufficient = not readable or match != "matched_by_identifier"
    return {
        "policy_version": POLICY_VERSION,
        "assessed_at": now.isoformat(),
        "overall_status": "insufficient_evidence" if insufficient else "human_review_required",
        "signals": {
            "authority": authority,
            "relevance": relevance,
            "independence": independence,
            "freshness": freshness,
            "directness": directness,
            "methodology": methodology,
            "conflicts_of_interest": disclosure,
            "corroboration": {"status": "not_assessed", "reason": "Corroboration requires matching source passages to a specific fact or claim."},
            "duplication": duplication,
        },
        "limitations": [
            "Signals are rule-based triage and are not a source-quality certification.",
            "Official manufacturer statements are claims, not independent verification.",
            "No certification registry or issuing authority was queried by this assessment.",
        ],
    }
