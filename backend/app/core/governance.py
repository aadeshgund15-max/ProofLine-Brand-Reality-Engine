"""Deterministic, explainable baseline governance for review runs.

This policy deliberately does not treat search snippets or lexical overlap as
enough to approve factual claims. A future source inspection and reliability
stage can satisfy that requirement without changing the decision record shape.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable


POLICY_VERSION = "baseline-1"
DEFAULT_WEIGHTS = {
    "incomplete_extraction": 25,
    "incomplete_analysis_base": 10,
    "incomplete_analysis_per_stage": 5,
    "incomplete_analysis_max": 25,
    "contradicted_claim": 45,
    "conflicting_claim": 35,
    "unverified_claim": 25,
    "supported_excerpt": 15,
    "missing_user_proof": 30,
    "unsupported_proof_base": 15,
    "unsupported_proof_each": 5,
    "unsupported_proof_max": 30,
    "high_severity_rule_violation": 55,
    "high_severity_other_finding": 15,
}


@dataclass(frozen=True)
class GovernancePolicy:
    version: str
    weights: dict[str, int]


def load_governance_policy() -> GovernancePolicy:
    """Load validated risk weights from a server-only JSON environment setting."""
    raw = os.getenv("PROOFLINE_GOVERNANCE_POLICY_JSON", "").strip()
    version = os.getenv("PROOFLINE_GOVERNANCE_POLICY_VERSION", POLICY_VERSION).strip() or POLICY_VERSION
    weights = dict(DEFAULT_WEIGHTS)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("PROOFLINE_GOVERNANCE_POLICY_JSON must be valid JSON") from exc
        if not isinstance(parsed, dict) or set(parsed) - {"version", "weights"}:
            raise ValueError("Governance policy JSON may contain only 'version' and 'weights'")
        if parsed.get("version") is not None:
            version = parsed["version"]
        overrides = parsed.get("weights", {})
        if not isinstance(overrides, dict) or set(overrides) - set(DEFAULT_WEIGHTS):
            raise ValueError("Governance policy contains unknown or invalid weight keys")
        for key, value in overrides.items():
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"Governance weight '{key}' must be an integer from 0 to 100")
            weights[key] = value
    if not isinstance(version, str) or not version.strip() or len(version) > 80:
        raise ValueError("Governance policy version must be a non-empty string of at most 80 characters")
    return GovernancePolicy(version.strip(), weights)


@dataclass(frozen=True)
class AutomatedDecision:
    outcome: str
    risk_score: int
    rationale: str
    factors: list[dict[str, object]]
    policy_version: str = POLICY_VERSION


def assess_review(*, findings: Iterable[object], stages: dict[str, dict],
                  extraction_status: str, evidence_assessments: Iterable[str],
                  policy: GovernancePolicy | None = None) -> AutomatedDecision:
    """Calculate a bounded score and a fail-closed outcome from persisted review inputs."""
    policy = policy or load_governance_policy()
    weights = policy.weights
    factors: list[dict[str, object]] = []
    score = 0
    findings = list(findings)
    evidence_assessments = list(evidence_assessments)

    if extraction_status != "complete":
        score += weights["incomplete_extraction"]
        factors.append({"code": "incomplete_extraction", "weight": weights["incomplete_extraction"],
                        "detail": f"Submission extraction is {extraction_status}."})

    required_stages = ("deterministic", "verification", "visual", "proof_provenance", "product_intelligence")
    failed_stages = [name for name in required_stages if stages.get(name, {}).get("status") != "completed"]
    if failed_stages:
        incomplete_weight = min(weights["incomplete_analysis_max"],
                                weights["incomplete_analysis_base"] + weights["incomplete_analysis_per_stage"] * len(failed_stages))
        score += incomplete_weight
        factors.append({"code": "incomplete_analysis", "weight": incomplete_weight,
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
                score += weights["contradicted_claim"]
                factors.append({"code": "contradictory_source_excerpt", "weight": weights["contradicted_claim"],
                                "detail": "A retrieved excerpt was classified as contradicting a material claim; source quality still needs review."})
                hold_reasons.append("A retrieved source excerpt contradicts a material claim, and source quality has not yet been assessed.")
            elif verification == "conflicting":
                score += weights["conflicting_claim"]
                factors.append({"code": "conflicting_sources", "weight": weights["conflicting_claim"],
                                "detail": "Retrieved source excerpts disagree about a material claim."})
                hold_reasons.append("Retrieved sources conflict about a material claim.")
            elif verification != "supported":
                score += weights["unverified_claim"]
                factors.append({"code": "claim_not_verified", "weight": weights["unverified_claim"],
                                "detail": f"Material claim assessment is {verification or 'unknown'}."})
                hold_reasons.append("At least one material claim lacks a complete supporting assessment.")
            else:
                # Search APIs return excerpts/snippets. The current pipeline does not fetch and
                # inspect full source pages or evaluate source provenance/reliability.
                score += weights["supported_excerpt"]
                factors.append({"code": "source_quality_unassessed", "weight": weights["supported_excerpt"],
                                "detail": "A claim has excerpt-level support, but full source content and reliability were not assessed."})
                hold_reasons.append("Search excerpts are not sufficient for automatic approval; full source content and reliability remain unchecked.")
        elif origin == "deterministic" and category == "rule_violation" and severity == "high":
            reject_reasons.append("A high severity approved brand rule was violated.")
            score += weights["high_severity_rule_violation"]
            factors.append({"code": "high_severity_brand_rule_violation", "weight": weights["high_severity_rule_violation"],
                            "detail": "A configured high severity brand rule produced a deterministic violation."})
        elif origin == "extraction":
            hold_reasons.append("Content extraction is incomplete.")

        if severity == "high" and origin not in ("verification", "deterministic"):
            score += weights["high_severity_other_finding"]
            factors.append({"code": "high_severity_finding", "weight": weights["high_severity_other_finding"],
                            "detail": "A high severity review finding needs policy evaluation."})
            hold_reasons.append("A high severity finding needs policy evaluation.")

    if not evidence_assessments:
        score += weights["missing_user_proof"]
        factors.append({"code": "missing_user_proof", "weight": weights["missing_user_proof"],
                        "detail": "No processed user-provided proof was assessed for this review."})
        hold_reasons.append("Mandatory user-provided proof is missing.")
    else:
        unsupported = [status for status in evidence_assessments if status != "supported"]
        if unsupported:
            proof_weight = min(weights["unsupported_proof_max"],
                               weights["unsupported_proof_base"] + weights["unsupported_proof_each"] * len(unsupported))
            score += proof_weight
            factors.append({"code": "proof_not_established", "weight": proof_weight,
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
    return AutomatedDecision(outcome, score, " ".join(dict.fromkeys(reasons)), factors, policy.version)
