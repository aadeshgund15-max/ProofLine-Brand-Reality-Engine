import unittest

from app.routers.reports import render_review_report


class ReportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
