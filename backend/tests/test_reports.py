import unittest
from io import BytesIO

from pypdf import PdfReader
from app.routers.reports import _text, render_review_report


class ReportTests(unittest.TestCase):
    def test_report_text_escapes_markup_before_pdf_rendering(self):
        self.assertEqual(_text("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_report_is_generated_from_available_records_and_marks_missing_sections(self):
        pdf = render_review_report({
            "submission_id": "submission-test",
            "title": "Quarterly product claim review",
            "version_no": 2,
            "extraction_status": "complete",
            "review_id": None,
            "review_status": None,
            "findings": [],
            "assessments": [],
            "human_decisions": [],
        })

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)

    def test_report_preserves_research_coverage_source_limits_and_history(self):
        pdf = render_review_report({
            "submission_id": "submission-test",
            "title": "Pixel 9 Pro claim review",
            "version_no": 1,
            "extraction_status": "complete",
            "review_id": "review-test",
            "review_status": "completed_with_warnings",
            "stages": {},
            "findings": [],
            "assessments": [],
            "human_decisions": [{"decision": "changes_requested", "comment": "Add model-specific proof",
                                 "reviewer_email": "reviewer@example.test", "decided_at": "2026-11-01T10:00:00Z"}],
            "review_history": [{"id": "review-test", "version_no": 1, "status": "completed_with_warnings",
                                "started_at": "2026-11-01T09:59:00Z", "completed_at": "2026-11-01T10:00:00Z"}],
            "audit_history": [{"event_type": "review.completed", "summary": "Review finished",
                               "actor_email": "reviewer@example.test", "created_at": "2026-11-01T10:00:00Z"}],
            "product": {
                "brand": "Google", "product_name": "Pixel 9 Pro", "manufacturer": "Google",
                "model_number": "Pixel 9 Pro", "identity_status": "confirmed",
                "coverage": {"queries_executed": 12, "sources_inspected": 5, "sources_inaccessible": 2,
                             "profile_extraction_status": "completed"},
                "profile": {"facts": [], "sources": [{
                    "title": "Pixel updates", "url": "https://support.google.com/example",
                    "publisher": "Google", "published_at": None, "access_status": "ok",
                    "extraction_status": "complete", "product_match_status": "matched_by_identifier",
                    "source_assessment": {"signals": {
                        "authority": {"status": "manufacturer_claim_source"},
                        "relevance": {"status": "identifier_matched"},
                        "independence": {"status": "not_independent"},
                        "freshness": {"status": "unknown"},
                        "directness": {"status": "full_page_inspected"},
                    }},
                }]},
            },
        })

        extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("12 queries", extracted)
        self.assertIn("5 inspected sources", extracted)
        self.assertIn("not certification", extracted)
        self.assertIn("not_independent", extracted)
        self.assertIn("reviewer@example.test", extracted)
        self.assertIn("Review and audit history", extracted)

    def test_report_includes_logo_comparison_location_and_review_limit(self):
        pdf = render_review_report({
            "submission_id": "submission-test", "title": "Logo review", "version_no": 1,
            "extraction_status": "complete", "findings": [], "assessments": [],
            "visual_analysis": {"status": "partial", "results": {"logo_analysis": {
                "status": "partial", "assets_examined": 1, "matches": [{
                    "status": "similar_to_approved_logo", "review_status": "needs_human_review",
                    "reference_name": "Primary", "page_number": 2, "similarity": 0.953,
                    "issues": ["rotated_placement"], "coordinates": {"x_inches": 1.2},
                }], "limitations": ["Vector-only logos are not analyzed."],
            }, "typography_analysis": {"status": "partial", "message": "Font checks ran.", "findings": [{
                "page_number": 2, "message": "Font family Arial is not approved.",
                "coordinates": {"x_inches": 1.2},
            }]},
            }},
        })
        extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Approved logo comparison", extracted)
        self.assertIn("Primary", extracted)
        self.assertIn("slide/page 2", extracted)
        self.assertIn("needs_human_review", extracted)
        self.assertIn("Vector-only logos are not analyzed", extracted)
        self.assertIn("Font checks ran", extracted)
        self.assertIn("Font family Arial is not approved", extracted)


if __name__ == "__main__":
    unittest.main()
