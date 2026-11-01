import os
import unittest
from unittest.mock import patch

from tests import pg_harness


class DatabaseHarnessSafetyTests(unittest.TestCase):
    def test_database_tests_are_disabled_without_explicit_acknowledgement(self):
        with patch.dict(os.environ, {
            "PROOFLINE_TEST_PSQL": "host=localhost port=5432 user=proofline dbname=proofline_test",
        }, clear=False):
            os.environ.pop("PROOFLINE_ALLOW_DESTRUCTIVE_TESTS", None)
            self.assertFalse(pg_harness.enabled())

    def test_database_tests_reject_non_test_database_names(self):
        with patch.dict(os.environ, {
            "PROOFLINE_TEST_PSQL": "host=db.example port=5432 user=proofline dbname=postgres",
            "PROOFLINE_ALLOW_DESTRUCTIVE_TESTS": "YES_I_CREATED_A_DISPOSABLE_TEST_DATABASE",
        }, clear=False):
            self.assertFalse(pg_harness.enabled())

    def test_database_tests_require_complete_connection_fields(self):
        with patch.dict(os.environ, {
            "PROOFLINE_TEST_PSQL": "host=localhost dbname=proofline_test",
            "PROOFLINE_ALLOW_DESTRUCTIVE_TESTS": "YES_I_CREATED_A_DISPOSABLE_TEST_DATABASE",
        }, clear=False):
            self.assertFalse(pg_harness.enabled())

    def test_explicitly_confirmed_test_database_enables_harness(self):
        with patch.dict(os.environ, {
            "PROOFLINE_TEST_PSQL": "host=localhost port=5432 user=proofline dbname=proofline_test",
            "PROOFLINE_ALLOW_DESTRUCTIVE_TESTS": "YES_I_CREATED_A_DISPOSABLE_TEST_DATABASE",
        }, clear=False):
            self.assertTrue(pg_harness.enabled())


if __name__ == "__main__":
    unittest.main()
