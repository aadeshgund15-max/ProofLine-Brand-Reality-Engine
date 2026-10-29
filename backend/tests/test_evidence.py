import unittest

from app.routers.reviews import _assess_evidence
from app.extract import extract_file, validate_upload


class EvidenceAssessmentTests(unittest.TestCase):
    def test_supported_evidence_includes_claim_terms(self):
        result = _assess_evidence("Acme phone costs $799", "The Acme phone costs $799 in the current price list.")
        self.assertEqual(result[0], "supported")
        self.assertIn("$799", result[2])

    def test_contradicted_evidence_is_explicit(self):
        result = _assess_evidence("Acme phone costs $799", "The Acme phone does not cost $799.")
        self.assertEqual(result[0], "contradicted")

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
