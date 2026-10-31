"""End-to-end scenario against a real PostgreSQL, calling the real route functions and SQL.

Skipped unless PROOFLINE_TEST_PSQL is set (see tests/pg_harness.py). Each `with PsqlConn()` block
is one request-scoped transaction, like the API's get_conn dependency.
"""
import asyncio
import hashlib
import unittest
import uuid

from tests import pg_harness

if not pg_harness.enabled():
    raise unittest.SkipTest("PROOFLINE_TEST_PSQL not set")

from fastapi import HTTPException
from pydantic import ValidationError

from app import auth
from app.auth import Member, User, member_of
from app.routers import impact_audit, library, reviews, submissions, workspaces
from tests.pg_harness import PsqlConn


def new_user(email):
    u = User(uuid.uuid4(), email)
    with PsqlConn() as c:
        c.execute("insert into app_users (id, email) values (:i, :e)", {"i": u.id, "e": email})
    return u


def member(user, ws, role="owner"):
    return Member(user, ws, role)


class Scenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with PsqlConn() as c:
            c.execute("truncate app_users cascade")
        cls.owner = new_user(f"owner-{uuid.uuid4().hex[:6]}@example.com")
        cls.other = new_user(f"other-{uuid.uuid4().hex[:6]}@example.com")
        with PsqlConn() as c:
            cls.ws = workspaces.create_workspace(workspaces.WorkspaceIn(name="Acme"), cls.owner, c)["id"]
            cls.ws2 = workspaces.create_workspace(workspaces.WorkspaceIn(name="Other Co"), cls.other, c)["id"]
        cls.m = member(cls.owner, cls.ws)
        with PsqlConn() as c:
            cls.bp = workspaces.create_profile(workspaces.ProfileIn(name="Acme brand"), cls.m, c)["id"]
            cls.price = library.create_fact(library.FactIn(
                brand_profile_id=cls.bp, key="pro_price", name="Pro price", approved_value="$799", value_type="money",
                subject_terms=["Acme Pro"]), cls.m, c)
            cls.launch = library.create_fact(library.FactIn(
                brand_profile_id=cls.bp, key="launch", name="Launch date", approved_value="14 March 2026",
                value_type="date", subject_terms=["launch"]), cls.m, c)
            cls.rule = library.create_rule(library.RuleIn(
                brand_profile_id=cls.bp, key="no_superlatives", rule_type="prohibited_phrase", severity="high",
                description="Do not claim to be the best phone ever.", patterns=["best phone ever"]), cls.m, c)

    def submit(self, title, text):
        with PsqlConn() as c:
            result = asyncio.run(submissions.create_submission(
                brand_profile_id=self.bp, title=title, source_type="text", text=text, url=None, file=None,
                m=self.m, conn=c))
            self.attach_test_proof(c, result["version"]["id"], text)
            return result

    def attach_test_proof(self, conn, version_id, text):
        data = text.encode("utf-8")
        conn.execute("""insert into submission_evidence
            (workspace_id,submission_version_id,original_filename,storage_path,mime_type,size_bytes,content_hash,
             extracted_text,extraction_status,extraction_warnings,segments,created_by)
            values (:w,:v,'test-proof.txt',:path,'text/plain',:size,:hash,:text,'complete','[]'::jsonb,'[]'::jsonb,:u)""",
                      {"w": self.ws, "v": version_id, "path": f"test/{version_id}.txt", "size": len(data),
                       "hash": hashlib.sha256(data).hexdigest(), "text": text, "u": self.owner.id})

    def review(self, version_id):
        with PsqlConn() as c:
            return reviews.run_review(version_id, self.m, c)

    def test_full_journey(self):
        # --- versions exist and library persisted
        self.assertEqual(self.price["version_no"], 1)
        self.assertEqual(self.price["versions"][0]["is_current"], True)

        # --- submissions: A conflicts with fact+rule, B unrelated, C only about launch date
        a = self.submit("Landing page", "The Acme Pro Phone costs $899. It is the best phone ever made.")
        b = self.submit("Cafe menu", "Our cafe sells coffee and tea.")
        c_ = self.submit("Press note", "The launch is on 14 March 2026.")
        va, vb, vc = (x["version"]["id"] for x in (a, b, c_))

        run_a = self.review(va)
        self.assertEqual(run_a["status"], "completed_with_warnings")  # no LLM / search configured: honest
        self.assertEqual(run_a["stages"]["verification"]["status"], "unavailable")
        self.assertEqual(run_a["stages"]["semantic"]["status"], "unavailable")
        titles = [f["title"] for f in run_a["findings"]]
        self.assertTrue(any("differs from approved value" in t for t in titles), titles)
        self.assertTrue(any("Prohibited wording" in t for t in titles), titles)
        self.assertEqual(len(run_a["fact_versions_used"]), 2)
        self.assertEqual(len(run_a["rule_versions_used"]), 1)

        # --- finding detail: evidence links to the exact approved fact version, with location
        price_f = next(f for f in run_a["findings"] if "differs" in f["title"])
        with PsqlConn() as c:
            detail = reviews.get_finding(price_f["id"], self.m, c)
        self.assertEqual(detail["context"]["match"], "$899")
        self.assertEqual(detail["location"]["label"], "Paragraph 1")
        ev = detail["evidence"][0]
        self.assertEqual((ev["kind"], ev["fact_version_no"], ev["approved_value"]), ("brand_fact", 1, "$799"))

        run_b, run_c = self.review(vb), self.review(vc)
        self.assertEqual([f for f in run_b["findings"] if f["category"] == "rule_violation"], [])

        # --- reviewer decision (append-only) on A v1
        with PsqlConn() as c:
            reviews.record_decision(va, reviews.DecisionIn(decision="changes_requested", review_run_id=run_a["id"],
                                                           comment="Fix price"), self.m, c)
            reviews.set_finding_status(price_f["id"], reviews.FindingStatusIn(status="accepted"), self.m, c)

        # --- revised submission = new version; old findings/decision preserved
        with PsqlConn() as c:
            rev = asyncio.run(submissions.create_version(
                a["id"], source_type="text", text="The Acme Pro Phone costs $799. It is a great phone.",
                url=None, file=None, m=self.m, conn=c))
            self.attach_test_proof(c, rev["version"]["id"], "The Acme Pro Phone costs $799. It is a great phone.")
        va2 = rev["version"]["id"]
        self.assertEqual(rev["version"]["version_no"], 2)
        run_a2 = self.review(va2)
        self.assertEqual([f for f in run_a2["findings"] if f["category"] == "rule_violation"], [])
        self.assertEqual(run_a2["automated_decision"]["outcome"], "on_hold")
        with PsqlConn() as c:
            with self.assertRaises(HTTPException) as blocked:
                reviews.record_decision(va2, reviews.DecisionIn(decision="approved", review_run_id=run_a2["id"]), self.m, c)
            self.assertEqual(blocked.exception.status_code, 409)
        with PsqlConn() as c:
            reviews.record_decision(va2, reviews.DecisionIn(decision="changes_requested", review_run_id=run_a2["id"],
                                                             comment="Address the automated hold before approval."), self.m, c)
            hist = submissions.get_submission(a["id"], self.m, c)
        self.assertEqual(len(hist["versions"]), 2)
        self.assertEqual(len(hist["decisions"]), 2)
        self.assertEqual(len(hist["review_runs"]), 2)

        # --- Brand Time Machine: change price fact -> only dependent CURRENT content flagged
        with PsqlConn() as c:
            upd = library.update_fact(self.price["id"], library.FactUpdate(approved_value="$849", change_note="Price rise"),
                                      self.m, c)
        self.assertEqual(upd["version_no"], 2)
        self.assertEqual(upd["flagged_submissions"], 1)
        self.assertEqual(len(upd["versions"]), 2)                      # v1 preserved
        self.assertEqual(upd["versions"][1]["approved_value"], "$799")
        with PsqlConn() as c:
            queue = impact_audit.list_impacts("review_required", self.m, c)
        self.assertEqual(len(queue), 1)
        q0 = queue[0]
        self.assertEqual((q0["submission_id"], q0["submission_version_id"]), (a["id"], va2))  # not v1, not B, not C
        self.assertEqual((q0["old_value"], q0["new_value"]), ("$799", "$849"))
        with PsqlConn() as c:  # unrelated content has no impact
            for sid in (b["id"], c_["id"]):
                self.assertEqual(submissions.get_submission(sid, self.m, c)["impacts"], [])

        # --- deciding on the stale (pre-change) run does NOT clear the flag
        with PsqlConn() as c:
            r = reviews.record_decision(va2, reviews.DecisionIn(decision="changes_requested", review_run_id=run_a2["id"],
                                                                comment="The reviewed version is stale."), self.m, c)
        self.assertEqual((r["impacts_resolved"], r["impacts_still_open"]), (0, 1))

        # --- re-review: new run uses fact v2 and now flags $799 as stale; decision then resolves the flag
        run_a3 = self.review(va2)
        self.assertTrue(any("differs from approved value" in f["title"] for f in run_a3["findings"]))
        self.assertEqual(run_a3["fact_versions_used"][0]["version_no"] if run_a3["fact_versions_used"][0]["key"] == "pro_price"
                         else run_a3["fact_versions_used"][1]["version_no"], 2)
        with PsqlConn() as c:
            r = reviews.record_decision(va2, reviews.DecisionIn(decision="changes_requested", review_run_id=run_a3["id"],
                                                                comment="Update price to $849"), self.m, c)
            self.assertEqual((r["impacts_resolved"], r["impacts_still_open"]), (1, 0))
            self.assertEqual(impact_audit.list_impacts("review_required", self.m, c), [])
            resolved = impact_audit.list_impacts("resolved", self.m, c)
            hist = submissions.get_submission(a["id"], self.m, c)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(len(hist["decisions"]), 4)                     # nothing overwritten
        self.assertEqual(len(hist["review_runs"]), 3)

        # --- rule change flags content that was reviewed against it (all current content), not the fact-only logic
        with PsqlConn() as c:
            ru = library.update_rule(self.rule["id"], library.RuleUpdate(patterns=["best phone ever", "world's best"]),
                                     self.m, c)
        self.assertEqual(ru["version_no"], 2)
        self.assertEqual(ru["flagged_submissions"], 3)  # A, B, C were all evaluated against this rule

        # --- audit trail
        with PsqlConn() as c:
            events = [e["event_type"] for e in impact_audit.list_audit(200, None, None, self.m, c)]
        for et in ("workspace.created", "fact.created", "fact.updated", "rule.updated", "submission.created",
                   "submission.version_created", "review.completed", "decision.recorded", "finding.status_changed",
                   "impact.flagged"):
            self.assertIn(et, events)

        # --- history is immutable at the database level
        for sql in ("update brand_fact_versions set approved_value = 'x'", "delete from audit_events",
                    "update review_decisions set decision = 'approved'", "update submission_versions set extracted_text = 'x'",
                    "delete from finding_evidence"):
            with self.assertRaises(RuntimeError, msg=sql):
                with PsqlConn() as c:
                    c.execute(sql)

    def test_isolation_between_workspaces(self):
        m2 = member(self.other, self.ws2)
        with PsqlConn() as c:
            with self.assertRaises(HTTPException) as cm:
                library.get_fact(self.price["id"], m2, c)             # workspace-2 member, workspace-1 id
            self.assertEqual(cm.exception.status_code, 404)
            self.assertEqual(library.list_facts(None, m2, c), [])
            with self.assertRaises(HTTPException):
                library.update_fact(self.price["id"], library.FactUpdate(approved_value="$1"), m2, c)
            with self.assertRaises(HTTPException):
                submissions.get_submission(uuid.uuid4(), m2, c)
            # membership dependency: outsider cannot enter workspace 1 at all
            with self.assertRaises(HTTPException) as cm:
                member_of()(workspace_id=self.ws, user=self.other, conn=c)
            self.assertEqual(cm.exception.status_code, 404)

    def test_roles(self):
        rev = new_user(f"rev-{uuid.uuid4().hex[:6]}@example.com")
        with PsqlConn() as c:
            workspaces.add_member(workspaces.MemberIn(email=rev.email, role="reviewer"), self.m, c)
            ok = member_of("owner", "reviewer")(workspace_id=self.ws, user=rev, conn=c)
            self.assertEqual(ok.role, "reviewer")
            with self.assertRaises(HTTPException) as cm:          # reviewers cannot edit the library
                member_of(*auth.EDIT_ROLES)(workspace_id=self.ws, user=rev, conn=c)
            self.assertEqual(cm.exception.status_code, 403)
            with self.assertRaises(HTTPException) as cm:          # non-owner cannot add members
                member_of("owner")(workspace_id=self.ws, user=rev, conn=c)
            self.assertEqual(cm.exception.status_code, 403)

    def test_failed_extraction_blocks_review(self):
        s = self.submit("Empty", "   ")
        self.assertEqual(s["version"]["extraction_status"], "empty")
        with self.assertRaises(HTTPException) as cm:
            self.review(s["version"]["id"])
        self.assertEqual(cm.exception.status_code, 409)

    def test_validation_and_db_constraints(self):
        with PsqlConn() as c:
            with self.assertRaises(HTTPException) as cm:           # duplicate key -> must edit instead
                library.create_fact(library.FactIn(brand_profile_id=self.bp, key="pro_price", name="x",
                                                   approved_value="$1", value_type="money", subject_terms=["x"]), self.m, c)
            self.assertEqual(cm.exception.status_code, 409)
        with self.assertRaises(ValidationError):
            reviews.FindingStatusIn(status="dismissed")
        with self.assertRaises(RuntimeError):                      # DB-level: dismissed needs a reason
            with PsqlConn() as c:
                fid = c.execute("select id from findings limit 1").mappings().first()["id"]
                c.execute("update findings set status='dismissed' where id=:f", {"f": fid})

    def test_dashboard_is_real_aggregates(self):
        with PsqlConn() as c:
            d = workspaces.dashboard(self.m, c)
            empty = workspaces.dashboard(member(self.other, self.ws2), c)
        self.assertGreaterEqual(d["facts"], 2)
        self.assertEqual((empty["facts"], empty["submissions"], empty["review_runs"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
