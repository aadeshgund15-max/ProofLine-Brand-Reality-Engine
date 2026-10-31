import unittest
from types import SimpleNamespace

from app.core.governance import assess_review


class GovernanceTests(unittest.TestCase):
    def test_missing_visual_stage_blocks_approval_and_names_reason(self):
        result = assess_review(
            findings=[],
            stages={"deterministic": {"status": "completed"}, "verification": {"status": "completed"}},
            extraction_status="complete",
            evidence_assessments=["supported"],
        )
        self.assertEqual(result.outcome, "on_hold")
        self.assertIn("visual", result.rationale)

    def test_high_severity_approved_rule_violation_is_rejected(self):
        finding = SimpleNamespace(origin="deterministic", category="rule_violation", severity="high",
                                  verification_status="not_applicable")
        result = assess_review(
            findings=[finding],
            stages={"deterministic": {"status": "completed"}, "verification": {"status": "completed"},
                    "visual": {"status": "completed"}, "proof_provenance": {"status": "completed"},
                    "product_intelligence": {"status": "completed"}},
            extraction_status="complete",
            evidence_assessments=["supported"],
        )
        self.assertEqual(result.outcome, "rejected")
        self.assertEqual(result.risk_score, 55)

    def test_conflicting_claim_sources_hold_even_when_other_checks_pass(self):
        finding = SimpleNamespace(origin="verification", category="claim_verification", severity="high",
                                  verification_status="conflicting")
        result = assess_review(
            findings=[finding],
            stages={"deterministic": {"status": "completed"}, "verification": {"status": "completed"},
                    "visual": {"status": "completed"}, "proof_provenance": {"status": "completed"},
                    "product_intelligence": {"status": "completed"}},
            extraction_status="complete",
            evidence_assessments=["supported"],
        )
        self.assertEqual(result.outcome, "on_hold")
        self.assertIn("conflict", result.rationale)

    def test_complete_no_claim_review_can_be_approved(self):
        result = assess_review(
            findings=[],
            stages={"deterministic": {"status": "completed"}, "verification": {"status": "completed"},
                    "visual": {"status": "completed"}, "proof_provenance": {"status": "completed"},
                    "product_intelligence": {"status": "completed"}},
            extraction_status="complete",
            evidence_assessments=["supported"],
        )
        self.assertEqual((result.outcome, result.risk_score), ("approved", 0))

    def test_missing_product_research_blocks_approval(self):
        result = assess_review(
            findings=[],
            stages={"deterministic": {"status": "completed"}, "verification": {"status": "completed"},
                    "visual": {"status": "completed"}, "proof_provenance": {"status": "completed"}},
            extraction_status="complete",
            evidence_assessments=["supported"],
        )
        self.assertEqual(result.outcome, "on_hold")
        self.assertIn("product_intelligence", result.rationale)


if __name__ == "__main__":
    unittest.main()
