"""Ingestion (every format, through the real route + DB) and external verification persistence."""
import asyncio
import dataclasses
import os
import pathlib
import tempfile
import unittest
import uuid
from unittest import mock

from tests import pg_harness

if not pg_harness.enabled():
    raise unittest.SkipTest("PROOFLINE_TEST_PSQL not set")

os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="proofline-store-"))

from fastapi import HTTPException

from app.auth import Member, User
from app.config import settings
from app.core.ssrf import FetchResult
from app.providers.base import ProviderError, SearchHit
from app.routers import library, reviews, submissions, workspaces
from tests.pg_harness import PsqlConn

FX = pathlib.Path(__file__).parent / "fixtures"


class FakeUpload:
    def __init__(self, name, data, ctype="application/octet-stream"):
        self.filename, self.content_type, self._d = name, ctype, data
    async def read(self, n=-1):
        return self._d[:n] if n and n > 0 else self._d


def up(name):
    return FakeUpload(name, (FX / name).read_bytes())


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings_dir = os.environ["STORAGE_DIR"]
        object.__setattr__(settings, "storage_dir", settings_dir)
        cls.user = User(uuid.uuid4(), f"u-{uuid.uuid4().hex[:6]}@example.com")
        with PsqlConn() as c:
            c.execute("insert into app_users (id,email) values (:i,:e)", {"i": cls.user.id, "e": cls.user.email})
            cls.ws = workspaces.create_workspace(workspaces.WorkspaceIn(name="Ingest"), cls.user, c)["id"]
        cls.m = Member(cls.user, cls.ws, "owner")
        with PsqlConn() as c:
            cls.bp = workspaces.create_profile(workspaces.ProfileIn(name="B"), cls.m, c)["id"]
            library.create_fact(library.FactIn(brand_profile_id=cls.bp, key="price", name="Price", approved_value="$899",
                                               value_type="money", subject_terms=["Acme Pro Phone", "Acme Pro"]), cls.m, c)
            library.create_rule(library.RuleIn(brand_profile_id=cls.bp, key="sup", rule_type="claim_requires_evidence",
                                               description="Superlatives need evidence.", patterns=["best phone ever"]), cls.m, c)

    def sub(self, source_type, **kw):
        with PsqlConn() as c:
            return asyncio.run(submissions.create_submission(
                brand_profile_id=self.bp, title=kw.pop("title", "t"), source_type=source_type,
                text=kw.pop("text", None), url=kw.pop("url", None), file=kw.pop("file", None), m=self.m, conn=c))

    def review(self, vid):
        with PsqlConn() as c:
            return reviews.run_review(vid, self.m, c)


class IngestTests(Base):
    def test_every_format_end_to_end(self):
        expect = {"sample.docx": ("docx", "complete"), "sample.pdf": ("pdf", "complete"),
                  "sample.pptx": ("pptx", "complete"), "poster.png": ("image", None)}
        for name, (kind, status) in expect.items():
            with self.subTest(name):
                s = self.sub("file", file=up(name))
                v = s["version"]
                self.assertEqual(v["source_type"], kind)
                if status:
                    self.assertEqual(v["extraction_status"], status, v["warnings"])
                else:
                    self.assertIn(v["extraction_status"], ("complete", "partial"))
                run = self.review(v["id"])
                # sample content says $799 / $799; approved is $899 -> price finding with a real location
                price = [f for f in run["findings"] if "differs from approved value" in f["title"]]
                self.assertTrue(price, f"{name}: {[f['title'] for f in run['findings']]}")
                self.assertTrue(price[0]["location"], f"{name}: finding has no location")
                with PsqlConn() as c:
                    ver = submissions.get_version(v["id"], self.m, c)
                    self.assertTrue(ver["has_original"])
                    dl = submissions.download_original(v["id"], self.m, c)
                self.assertEqual(dl.body, (FX / name).read_bytes())

    def test_locations_are_slide_and_page_and_ocr(self):
        s = self.sub("file", file=up("sample.pptx"))
        run = self.review(s["version"]["id"])
        loc = [f["location"]["label"] for f in run["findings"] if f["location"]]
        self.assertIn("Slide 2", loc)
        s = self.sub("file", file=up("poster.png"))
        run = self.review(s["version"]["id"])
        self.assertTrue(any(f["location"]["kind"] == "ocr_line" for f in run["findings"] if f["location"]))

    def test_bad_files_are_stored_honestly_and_never_reviewed(self):
        with self.assertRaises(HTTPException) as cm:                  # corrupt Office archive: refused up front
            self.sub("file", file=up("corrupt.docx"))
        self.assertIn("corrupted", cm.exception.detail)
        s = self.sub("file", file=up("corrupt.pdf"))                  # passes header check, extraction fails
        self.assertEqual(s["version"]["extraction_status"], "failed")
        s2 = self.sub("file", file=up("scanned.pdf"))
        self.assertEqual(s2["version"]["extraction_status"], "empty")
        for sv in (s, s2):
            with self.assertRaises(HTTPException) as cm:
                self.review(sv["version"]["id"])
            self.assertEqual(cm.exception.status_code, 409)

    def test_partial_extraction_flagged_in_review(self):
        s = self.sub("file", file=up("with_picture.pptx"))
        self.assertEqual(s["version"]["extraction_status"], "partial")
        run = self.review(s["version"]["id"])
        self.assertEqual(run["status"], "completed_with_warnings")
        self.assertTrue(any(f["category"] == "extraction_limitation" for f in run["findings"]))

    def test_rejected_uploads(self):
        for f, frag in [(FakeUpload("x.docx", b""), "empty"),
                        (FakeUpload("evil.docx", (FX / "renamed.docx").read_bytes()), "Unsupported"),
                        (FakeUpload("a.docx", (FX / "sample.pdf").read_bytes()), "does not match"),
                        (FakeUpload("big.docx", (FX / "sample.docx").read_bytes()), "larger")]:
            with self.subTest(f.filename):
                limited = dataclasses.replace(settings, max_upload_bytes=10_000 if f.filename == "big.docx" else 15 * 1024 * 1024)
                with mock.patch.object(submissions, "settings", limited):
                    with self.assertRaises(HTTPException) as cm:
                        self.sub("file", file=f)
                self.assertEqual(cm.exception.status_code, 422)
                self.assertIn(frag, cm.exception.detail)

    def test_url_ingestion_and_ssrf(self):
        html = (FX / "sample.html").read_bytes()
        fake = FetchResult("https://example.com/p", 200, "text/html; charset=utf-8", html, [], False)
        with mock.patch.object(submissions, "safe_fetch", return_value=fake):
            s = self.sub("url", url="https://example.com/p")
        v = s["version"]
        self.assertEqual((v["source_type"], v["extraction_status"]), ("url", "complete"))
        with PsqlConn() as c:
            ver = submissions.get_version(v["id"], self.m, c)
        self.assertEqual(ver["original_url"], "https://example.com/p")
        self.assertIsNotNone(ver["retrieved_at"])
        self.assertNotIn("IGNORE ALL INSTRUCTIONS", ver["extracted_text"])
        run = self.review(v["id"])
        self.assertTrue(any("differs" in f["title"] for f in run["findings"]))
        # the real validator rejects internal targets before any connection is attempted
        for bad in ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
                    "http://[::1]:80/", "http://10.0.0.1/"]:
            with self.assertRaises(HTTPException, msg=bad) as cm:
                self.sub("url", url=bad)
            self.assertEqual(cm.exception.status_code, 422)
        # network failure is stored as failed extraction, never as success
        from app.core.ssrf import FetchError
        with mock.patch.object(submissions, "safe_fetch", side_effect=FetchError("HTTP 503")):
            s = self.sub("url", url="https://example.com/down")
        self.assertEqual(s["version"]["extraction_status"], "failed")

    def test_download_denied_to_other_workspace(self):
        s = self.sub("file", file=up("sample.docx"))
        other = User(uuid.uuid4(), f"o-{uuid.uuid4().hex[:6]}@example.com")
        with PsqlConn() as c:
            c.execute("insert into app_users (id,email) values (:i,:e)", {"i": other.id, "e": other.email})
            ws2 = workspaces.create_workspace(workspaces.WorkspaceIn(name="X"), other, c)["id"]
            with self.assertRaises(HTTPException) as cm:
                submissions.download_original(s["version"]["id"], Member(other, ws2, "owner"), c)
            self.assertEqual(cm.exception.status_code, 404)


class FakeSearch:
    name = "fake"
    def __init__(self, hits=None, error=None): self.hits, self.error = hits or [], error
    def configured(self): return True
    def search(self, q, limit=5):
        if self.error: raise ProviderError(self.error)
        return self.hits


class FakeLlm:
    name = "fake"
    def configured(self): return True
    def complete_json(self, system, user, max_tokens=1500):
        if "judge whether retrieved web excerpts" in system:
            return {"items": [{"index": 0, "stance": "supports", "quote": "founded in 1999"},
                              {"index": 1, "stance": "irrelevant", "quote": ""}]}
        return {"issues": []}


class VerificationTests(Base):
    CLAIM = "Acme was founded in 1999 by two engineers."
    HITS = [SearchHit("Acme history", "https://example.org/history", "Acme was founded in 1999 in Pune.", "2021-05-01", "Example Org"),
            SearchHit("Cats", "https://example.org/cats", "Unrelated page about cats.")]

    def test_real_sources_persisted_and_classified(self):
        s = self.sub("text", text=self.CLAIM)
        with mock.patch.object(reviews, "get_search_provider", return_value=FakeSearch(self.HITS)), \
             mock.patch.object(reviews, "get_llm_provider", return_value=FakeLlm()):
            run = self.review(s["version"]["id"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["stages"]["verification"]["status"], "completed")
        f = next(x for x in run["findings"] if x["origin"] == "verification")
        self.assertEqual(f["verification_status"], "supported")
        with PsqlConn() as c:
            d = reviews.get_finding(f["id"], self.m, c)
        ext = [e for e in d["evidence"] if e["kind"] == "external_source"]
        self.assertEqual(len(ext), 1)                                # irrelevant source not attached as evidence
        self.assertEqual((ext[0]["source_url"], ext[0]["stance"]), ("https://example.org/history", "supports"))
        self.assertEqual(ext[0]["excerpt"], "founded in 1999")
        self.assertIsNotNone(ext[0]["retrieved_at"])
        self.assertIsNotNone(ext[0]["published_at"])

    def test_search_provider_failure_is_honest(self):
        s = self.sub("text", text=self.CLAIM)
        with mock.patch.object(reviews, "get_search_provider", return_value=FakeSearch(error="rate limited")):
            run = self.review(s["version"]["id"])
        self.assertEqual(run["status"], "completed_with_warnings")
        self.assertEqual(run["stages"]["verification"]["status"], "failed")
        f = next(x for x in run["findings"] if x["origin"] == "verification")
        self.assertEqual(f["verification_status"], "unavailable")
        self.assertEqual(f["evidence_count"], 0)

    def test_no_provider_configured_reports_unavailable_not_success(self):
        s = self.sub("text", text=self.CLAIM)
        run = self.review(s["version"]["id"])
        self.assertEqual(run["stages"]["verification"]["status"], "unavailable")
        self.assertEqual([f for f in run["findings"] if f["origin"] == "verification"], [])

    def test_search_without_llm_requires_human_review(self):
        s = self.sub("text", text=self.CLAIM)
        with mock.patch.object(reviews, "get_search_provider", return_value=FakeSearch(self.HITS)):
            run = self.review(s["version"]["id"])
        f = next(x for x in run["findings"] if x["origin"] == "verification")
        self.assertEqual(f["verification_status"], "needs_human_review")
        with PsqlConn() as c:
            d = reviews.get_finding(f["id"], self.m, c)
        self.assertTrue(all(e["stance"] == "unclassified" for e in d["evidence"]))

    def test_deterministic_stage_failure_records_failed_run_and_saves_no_findings(self):
        s = self.sub("text", text="Some content that will be reviewed.")
        vid = s["version"]["id"]
        from app.services import review as svc

        class Conn(PsqlConn):
            pass

        def boom(*a, **k):
            raise ValueError("engine crashed")
        import contextlib

        @contextlib.contextmanager
        def tx():
            with PsqlConn() as c:
                yield c
        with mock.patch.object(reviews, "compute_review", side_effect=boom), mock.patch.object(svc, "transaction", tx):
            with self.assertRaises(HTTPException) as cm:
                self.review(vid)
        self.assertEqual(cm.exception.status_code, 500)
        with PsqlConn() as c:
            runs = c.execute("select status, error from review_runs where submission_version_id = :v", {"v": vid}).mappings().all()
            n = c.execute("select count(*) n from findings where submission_version_id = :v", {"v": vid}).mappings().first()["n"]
        self.assertEqual([(r["status"], r["error"]) for r in runs], [("failed", "ValueError")])
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
