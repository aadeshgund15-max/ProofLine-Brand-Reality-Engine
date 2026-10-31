"""Deterministic, explainable baseline governance for review runs.

This policy deliberately does not treat search snippets or lexical overlap as
enough to approve factual claims. A future source inspection and reliability
stage can satisfy that requirement without changing the decision record shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


POLICY_VERSION = "baseline-1"


@dataclass(frozen=True)
class AutomatedDecision:
    outcome: str
    risk_score: int
    rationale: str
    factors: list[dict[str, object]]
    policy_version: str = POLICY_VERSION


def assess_review(*, findings: Iterable[object], stages: dict[str, dict],
                  extraction_status: str, evidence_assessments: Iterable[str]) -> AutomatedDecision:
    """Calculate a bounded score and a fail-closed outcome from persisted review inputs."""
    factors: list[dict[str, object]] = []
    score = 0
    findings = list(findings)
    evidence_assessments = list(evidence_assessments)

    if extraction_status != "complete":
        score += 25
        factors.append({"code": "incomplete_extraction", "weight": 25,
                        "detail": f"Submission extraction is {extraction_status}."})

    required_stages = ("deterministic", "verification", "visual", "proof_provenance", "product_intelligence")
    failed_stages = [name for name in required_stages if stages.get(name, {}).get("status") != "completed"]
    if failed_stages:
        score += min(25, 10 + 5 * len(failed_stages))
        factors.append({"code": "incomplete_analysis", "weight": min(25, 10 + 5 * len(failed_stages)),
                        "detail": "Required analysis stages are incomplete: " + ", ".join(failed_stages) + "."})

    reject_reasons: list[str] = []
    hold_reasons: list[str] = []
    if failed_stages:
        hold_reasons.append("Mandatory analysis is incomplete: " + ", ".join(failed_stages) + ".")
    for finding in findings:
        origin = getattr(finding, "origin", "")
        category = getattr(finding, "category", "")
        severity = getattr(finding, "severity", "low")
        verification = getattr(finding, "verification_status", None)
        if origin == "verification":
            if verification == "contradicted":
                score += 45
                factors.append({"code": "contradictory_source_excerpt", "weight": 45,
                                "detail": "A retrieved excerpt was classified as contradicting a material claim; source quality still needs review."})
                hold_reasons.append("A retrieved source excerpt contradicts a material claim, and source quality has not yet been assessed.")
            elif verification == "conflicting":
                score += 35
                factors.append({"code": "conflicting_sources", "weight": 35,
                                "detail": "Retrieved source excerpts disagree about a material claim."})
                hold_reasons.append("Retrieved sources conflict about a material claim.")
            elif verification != "supported":
                score += 25
                factors.append({"code": "claim_not_verified", "weight": 25,
                                "detail": f"Material claim assessment is {verification or 'unknown'}."})
                hold_reasons.append("At least one material claim lacks a complete supporting assessment.")
            else:
                # Search APIs return excerpts/snippets. The current pipeline does not fetch and
                # inspect full source pages or evaluate source provenance/reliability.
                score += 15
                factors.append({"code": "source_quality_unassessed", "weight": 15,
                                "detail": "A claim has excerpt-level support, but full source content and reliability were not assessed."})
                hold_reasons.append("Search excerpts are not sufficient for automatic approval; full source content and reliability remain unchecked.")
        elif origin == "deterministic" and category == "rule_violation" and severity == "high":
            reject_reasons.append("A high severity approved brand rule was violated.")
            score += 55
            factors.append({"code": "high_severity_brand_rule_violation", "weight": 55,
                            "detail": "A configured high severity brand rule produced a deterministic violation."})
        elif origin == "extraction":
            hold_reasons.append("Content extraction is incomplete.")

        if severity == "high" and origin not in ("verification", "deterministic"):
            score += 15
            factors.append({"code": "high_severity_finding", "weight": 15,
                            "detail": "A high severity review finding needs policy evaluation."})
            hold_reasons.append("A high severity finding needs policy evaluation.")

    if not evidence_assessments:
        score += 30
        factors.append({"code": "missing_user_proof", "weight": 30,
                        "detail": "No processed user-provided proof was assessed for this review."})
        hold_reasons.append("Mandatory user-provided proof is missing.")
    else:
        unsupported = [status for status in evidence_assessments if status != "supported"]
        if unsupported:
            score += min(30, 15 + 5 * len(unsupported))
            factors.append({"code": "proof_not_established", "weight": min(30, 15 + 5 * len(unsupported)),
                            "detail": f"{len(unsupported)} of {len(evidence_assessments)} proof item(s) were not assessed as supported."})
            hold_reasons.append("Uploaded proof is incomplete, inconclusive, or does not support the submitted content.")

    if reject_reasons:
        outcome = "rejected"
        reasons = reject_reasons
    elif hold_reasons:
        outcome = "on_hold"
        reasons = hold_reasons
    else:
        outcome = "approved"
        reasons = ["All baseline mandatory checks passed under the recorded policy version."]

    score = min(100, score)
    return AutomatedDecision(outcome, score, " ".join(dict.fromkeys(reasons)), factors)
