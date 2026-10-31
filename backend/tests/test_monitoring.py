import unittest

from app.services.monitoring import _meaningful_change, _next_text


class MonitoringChangeTests(unittest.TestCase):
    def test_whitespace_only_change_is_not_material(self):
        self.assertFalse(_meaningful_change("Acme offers reliable home energy monitoring.",
                                            "Acme offers reliable\n home energy monitoring."))

    def test_numeric_claim_change_is_material(self):
        self.assertTrue(_meaningful_change("Our device reduces electricity use by 60% for every home.",
                                           "Our device reduces electricity use by 50% for every home."))

    def test_tiny_nonclaim_edit_is_suppressed(self):
        self.assertFalse(_meaningful_change("Explore our product and learn more today.",
                                            "Explore our product and learn more now."))

    def test_normalized_text_is_bounded_and_compacted(self):
        self.assertEqual(_next_text(type("Result", (), {"text": " one\n two ".strip()})()), "one two")


if __name__ == "__main__":
    unittest.main()
