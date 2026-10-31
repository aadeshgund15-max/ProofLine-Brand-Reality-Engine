import unittest
from unittest.mock import patch

from app.main import health, readiness


class HealthTests(unittest.TestCase):
    def test_liveness_does_not_claim_database_readiness(self):
        self.assertEqual(health(), {"status": "alive"})

    def test_readiness_runs_a_read_only_database_probe(self):
        with patch("app.main.q1", return_value={"?column?": 1}) as query:
            self.assertEqual(readiness(object()), {"status": "ready", "database": "connected"})
        query.assert_called_once()
        self.assertEqual(str(query.call_args.args[1]).strip().lower(), "select 1")


if __name__ == "__main__":
    unittest.main()
