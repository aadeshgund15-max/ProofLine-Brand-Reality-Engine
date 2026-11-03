import unittest

from app.routers.reviews import _assess_evidence
from app.extract import extract_file, validate_upload


class EvidenceAssessmentTests(unittest.TestCase):
    def test_keyword_overlap_is_only_partial_and_never_proof(self):
        result = _assess_evidence("Acme phone costs $799", "The Acme phone costs $799 in the current price list.")
        self.assertEqual(result[0], "partially_supported")
        self.assertIn("does not establish", result[1])
        self.assertIn("$799", result[2])

    def test_keyword_overlap_with_negation_still_requires_human_review(self):
        result = _assess_evidence("Acme phone costs $799", "The Acme phone does not cost $799.")
        self.assertEqual(result[0], "partially_supported")
        self.assertIn("human review is required", result[1])

    def test_misleading_keyword_overlap_never_marks_claim_supported(self):
        result = _assess_evidence("Acme phone is waterproof", "Acme phone is not waterproof and must stay dry.")
        self.assertEqual(result[0], "partially_supported")

    def test_missing_terms_is_insufficient(self):
        result = _assess_evidence("Acme phone costs $799", "The document describes the launch team.")
        self.assertEqual(result[0], "insufficient_evidence")

    def test_txt_evidence_is_validated_and_extracted(self):
        data = b"Acme phone costs $799."
        kind, error = validate_upload(data, "proof.txt", 1024)
        self.assertEqual((kind, error), ("text", None))
        self.assertEqual(extract_file(kind, data).status, "complete")


if __name__ == "__main__":
    unittest.main()
