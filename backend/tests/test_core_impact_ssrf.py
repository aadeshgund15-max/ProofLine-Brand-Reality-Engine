import unittest

from app.core.impact import DepRow, resolve_impacted
from app.core.ssrf import (FetchError, UnsafeUrlError, ip_is_public, safe_fetch, validate_url)


def public_resolver(host, port):
    return ["93.184.216.34"]


class ImpactTests(unittest.TestCase):
    def rows(self):
        return [
            # S1 depends on fact F v1 (latest run)
            DepRow("S1", "S1v1", "run1", "2026-01-01", fact_id="F", fact_version_id="F1"),
            # S2 depends on a different fact
            DepRow("S2", "S2v1", "run2", "2026-01-02", fact_id="G", fact_version_id="G1"),
            # S3: old version v1 depended on F, but current version is v2 which does not
            DepRow("S3", "S3v1", "run3", "2026-01-03", fact_id="F", fact_version_id="F1"),
            DepRow("S3", "S3v2", "run4", "2026-01-04", fact_id="G", fact_version_id="G1"),
            # S4 already re-reviewed after a previous change: latest run used F2
            DepRow("S4", "S4v1", "run5", "2026-01-05", fact_id="F", fact_version_id="F1"),
            DepRow("S4", "S4v1", "run6", "2026-01-06", fact_id="F", fact_version_id="F2"),
            # S5 depends on a rule R v1
            DepRow("S5", "S5v1", "run7", "2026-01-07", rule_id="R", rule_version_id="R1"),
        ]

    CUR = {"S1": "S1v1", "S2": "S2v1", "S3": "S3v2", "S4": "S4v1", "S5": "S5v1"}

    def test_only_dependent_current_content_flagged(self):
        out = resolve_impacted(self.rows(), self.CUR, kind="fact", entity_id="F", old_version_id="F1")
        self.assertEqual(out, [("S1", "S1v1")])

    def test_after_second_change_only_rereviewed_flagged(self):
        out = resolve_impacted(self.rows(), self.CUR, kind="fact", entity_id="F", old_version_id="F2")
        self.assertEqual(out, [("S4", "S4v1")])

    def test_rule_change(self):
        out = resolve_impacted(self.rows(), self.CUR, kind="rule", entity_id="R", old_version_id="R1")
        self.assertEqual(out, [("S5", "S5v1")])

    def test_no_dependents(self):
        self.assertEqual(resolve_impacted(self.rows(), self.CUR, kind="fact", entity_id="Z", old_version_id="Z1"), [])


class SsrfTests(unittest.TestCase):
    def test_blocked_addresses(self):
        for ip in ["127.0.0.1", "10.0.0.5", "172.16.3.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                   "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
                   "224.0.0.1", "2002:7f00:0001::1"]:
            self.assertFalse(ip_is_public(ip), ip)
        self.assertTrue(ip_is_public("93.184.216.34"))
        self.assertTrue(ip_is_public("2606:2800:220:1:248:1893:25c8:1946"))

    def test_rejects_bad_urls(self):
        bad = ["file:///etc/passwd", "ftp://example.com/x", "gopher://x", "javascript:alert(1)",
               "http://user:pw@example.com/", "http://localhost/", "http://foo.localhost/",
               "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data",
               "http://example.com:22/", "http://printer.local/", "http:///nohost", "", "x" * 3000]
        for u in bad:
            with self.assertRaises((UnsafeUrlError, FetchError), msg=u):
                validate_url(u, public_resolver)

    def test_hostname_resolving_to_private_is_rejected(self):
        with self.assertRaises(UnsafeUrlError):
            validate_url("http://evil.example.com/", lambda h, p: ["10.1.2.3"])
        with self.assertRaises(UnsafeUrlError):  # mixed answers: one private address is enough
            validate_url("http://evil.example.com/", lambda h, p: ["93.184.216.34", "127.0.0.1"])

    def test_valid_url_pins_ip(self):
        t = validate_url("https://example.com/a?b=1", public_resolver)
        self.assertEqual((t.host, t.port, t.ip, t.path_qs), ("example.com", 443, "93.184.216.34", "/a?b=1"))

    def test_redirect_to_private_blocked(self):
        calls = []

        def resolver(host, port):
            return ["10.0.0.1"] if host == "internal.example.com" else ["93.184.216.34"]

        def transport(target, max_bytes, timeout):
            calls.append(target.host)
            return 302, {"location": "http://internal.example.com/secret"}, b"", False

        with self.assertRaises(UnsafeUrlError):
            safe_fetch("http://example.com/", resolver=resolver, transport=transport)
        self.assertEqual(calls, ["example.com"])  # never connected to the internal host

    def test_redirect_loop_and_limits(self):
        def transport(target, max_bytes, timeout):
            return 302, {"location": "/again"}, b"", False
        with self.assertRaises(FetchError):
            safe_fetch("http://example.com/", resolver=public_resolver, transport=transport, max_redirects=2)

    def test_http_error_and_success(self):
        res = safe_fetch("http://example.com/", resolver=public_resolver,
                         transport=lambda t, m, to: (200, {"content-type": "text/html"}, b"<p>hi</p>", False))
        self.assertEqual(res.status, 200)
        with self.assertRaises(FetchError):
            safe_fetch("http://example.com/", resolver=public_resolver,
                       transport=lambda t, m, to: (500, {}, b"", False))

    def test_relative_redirect_followed(self):
        seen = []

        def transport(target, max_bytes, timeout):
            seen.append(target.path_qs)
            if target.path_qs == "/a":
                return 301, {"location": "/b"}, b"", False
            return 200, {"content-type": "text/html"}, b"ok", False
        res = safe_fetch("http://example.com/a", resolver=public_resolver, transport=transport)
        self.assertEqual(seen, ["/a", "/b"])
        self.assertEqual(res.redirects, ["http://example.com/b"])


if __name__ == "__main__":
    unittest.main()
