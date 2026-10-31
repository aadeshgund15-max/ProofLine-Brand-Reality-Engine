import unittest
from datetime import datetime, timezone

from app.services.source_assessment import assess_source


class SourceAssessmentTests(unittest.TestCase):
    def test_manufacturer_claim_is_not_independent_verification(self):
        assessment = assess_source({
            "category": "official_candidate", "url": "https://maker.example/product",
            "product_match_status": "matched_by_identifier", "access_status": "ok",
            "extraction_status": "complete", "text": "Model QX-4 specifications",
        }, now=datetime(2026, 10, 31, tzinfo=timezone.utc))
        self.assertEqual(assessment["overall_status"], "human_review_required")
        self.assertEqual(assessment["signals"]["independence"]["status"], "not_independent")
        self.assertFalse(assessment["signals"]["authority"]["verified"])

    def test_unmatched_or_uninspected_source_is_insufficient(self):
        assessment = assess_source({
            "category": "general_public_source", "url": "https://news.example/item",
            "published_at": "2023-01-01", "product_match_status": "ambiguous",
            "access_status": "blocked", "extraction_status": "unsupported", "text": "snippet only",
        }, now=datetime(2026, 10, 31, tzinfo=timezone.utc))
        self.assertEqual(assessment["overall_status"], "insufficient_evidence")
        self.assertEqual(assessment["signals"]["directness"]["status"], "not_fully_inspected")
        self.assertEqual(assessment["signals"]["freshness"]["status"], "potentially_outdated")

    def test_unknown_signals_remain_unknown_and_disclosures_are_reported(self):
        assessment = assess_source({
            "category": "general_public_source", "url": "https://reviews.example/item",
            "product_match_status": "matched_by_identifier", "access_status": "ok",
            "extraction_status": "complete", "text": "Test procedure and sponsored by Example",
        }, now=datetime(2026, 10, 31, tzinfo=timezone.utc))
        signals = assessment["signals"]
        self.assertEqual(signals["independence"]["status"], "unassessed")
        self.assertEqual(signals["freshness"]["status"], "unknown")
        self.assertEqual(signals["methodology"]["status"], "indicators_found")
        self.assertEqual(signals["conflicts_of_interest"]["status"], "disclosure_text_found")
        self.assertEqual(signals["corroboration"]["status"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
