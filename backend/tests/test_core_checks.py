import unittest

from app.core.checks import FactV, RuleV, run_checks, find_money, find_dates, sentences


def fact(**kw):
    base = dict(fact_id="f1", version_id="fv1", key="price", name="Pro price",
                approved_value="$799", value_type="money", subject_terms=("Acme Pro",))
    base.update(kw)
    return FactV(**base)


def rule(**kw):
    base = dict(rule_id="r1", version_id="rv1", key="r", rule_type="prohibited_phrase",
                description="Do not use superlatives.", patterns=("best ever",), severity="high")
    base.update(kw)
    return RuleV(**base)


class MoneyTests(unittest.TestCase):
    def test_mismatch_flagged_with_span(self):
        text = "The Acme Pro costs $899 today."
        res = run_checks(text, [fact()], [])
        self.assertEqual(len(res.findings), 1)
        f = res.findings[0]
        self.assertEqual(text[f.span_start:f.span_end], "$899")
        self.assertEqual(f.fact_version_id, "fv1")
        self.assertEqual(f.category, "rule_violation")
        self.assertEqual(res.dependencies[0].kind, "violation")

    def test_match_not_flagged_but_dependency_recorded(self):
        res = run_checks("The Acme Pro costs $799.", [fact()], [])
        self.assertEqual(res.findings, [])
        self.assertEqual([d.kind for d in res.dependencies], ["matched"])

    def test_unrelated_sentence_ignored_and_no_dependency(self):
        res = run_checks("Our cafe sells coffee for $5.", [fact()], [])
        self.assertEqual(res.findings, [])
        self.assertEqual(res.dependencies, [])

    def test_formats(self):
        self.assertEqual(find_money("Rs. 4,999")[0].value[1], 4999)
        self.assertEqual(find_money("₹4,999.50")[0].value[0], "INR")
        self.assertEqual(find_money("500 USD")[0].value, ("USD", 500))

    def test_currency_mismatch(self):
        res = run_checks("Acme Pro is €799.", [fact()], [])
        self.assertEqual(len(res.findings), 1)

    def test_draft_fact_ignored(self):
        res = run_checks("Acme Pro is $1.", [fact(status="draft")], [])
        self.assertEqual(res.findings, [])
        self.assertEqual(res.evaluated_fact_versions, [])


class DateAndNumberTests(unittest.TestCase):
    def test_date_mismatch(self):
        f = fact(key="launch", name="Launch date", approved_value="14 March 2026",
                 value_type="date", subject_terms=("launch",))
        res = run_checks("The launch is on 21 March 2026.", [f], [])
        self.assertEqual(len(res.findings), 1)
        res = run_checks("The launch is on March 14, 2026.", [f], [])
        self.assertEqual(res.findings, [])
        res = run_checks("Launch: 2026-03-14", [f], [])
        self.assertEqual(res.findings, [])

    def test_dates_parse(self):
        self.assertEqual(len(find_dates("on 1st Jan 2026 and 3/4/2025")), 2)

    def test_number_with_unit(self):
        f = fact(key="bat", name="Battery", approved_value="5000 mAh", value_type="number",
                 subject_terms=("battery",))
        res = run_checks("The battery is 4500 mAh and the phone weighs 200 g.", [f], [])
        self.assertEqual(len(res.findings), 1)
        self.assertIn("4500", res.findings[0].explanation)
        self.assertEqual(res.findings[0].severity, "high")

    def test_unitless_number_is_only_possible_inconsistency(self):
        f = fact(key="n", name="Stores", approved_value="42", value_type="number", subject_terms=("stores",))
        res = run_checks("We have 40 stores.", [f], [])
        self.assertEqual(res.findings[0].category, "possible_inconsistency")

    def test_money_and_dates_not_double_counted_as_numbers(self):
        f = fact(key="n", name="Stores", approved_value="42", value_type="number", subject_terms=("stores",))
        res = run_checks("Our stores opened on 14 March 2026 at $799.", [f], [])
        self.assertEqual(res.findings, [])


class TextFactAndRuleTests(unittest.TestCase):
    def test_name_variants(self):
        f = fact(key="n", name="Product name", approved_value="Acme Pro", value_type="text",
                 subject_terms=("AcmePro",))
        res = run_checks("Buy the acme-pro now. Also AcmePro rocks. And Acme Pro is correct.", [f], [])
        self.assertEqual(len(res.findings), 2)

    def test_prohibited_phrase_with_spans(self):
        text = "This is the Best Ever phone."
        res = run_checks(text, [], [rule()])
        self.assertEqual(len(res.findings), 1)
        f = res.findings[0]
        self.assertEqual(text[f.span_start:f.span_end], "Best Ever")
        self.assertEqual(f.rule_version_id, "rv1")
        self.assertEqual(res.dependencies[0].kind, "violation")

    def test_prohibited_not_substring(self):
        res = run_checks("worst everything", [], [rule(patterns=("best ever",))])
        self.assertEqual(res.findings, [])
        res = run_checks("a bestseller", [], [rule(patterns=("best",))])
        self.assertEqual(res.findings, [])

    def test_required_term(self):
        r = rule(rule_type="required_term", patterns=("Acme Inc.",), description="Include legal name.")
        self.assertEqual(len(run_checks("Hello", [], [r]).findings), 1)
        self.assertEqual(run_checks("From Acme Inc. with love", [], [r]).findings, [])
        self.assertEqual(run_checks("   ", [], [r]).findings, [])

    def test_claim_requires_evidence_is_not_verified(self):
        r = rule(rule_type="claim_requires_evidence", patterns=("fastest",))
        res = run_checks("The fastest phone.", [], [r])
        self.assertEqual(res.findings[0].verification_status, "needs_human_review")
        self.assertEqual(res.findings[0].category, "claim_verification")

    def test_approved_name_rule(self):
        r = rule(rule_type="approved_name", patterns=("Acme Pro",), description="Use approved name.")
        res = run_checks("The ACME PRO and Acme Pro and AcmePro.", [], [r])
        self.assertEqual(len(res.findings), 2)

    def test_applies_to_filter(self):
        r = rule(applies_to=("pptx",))
        self.assertEqual(run_checks("best ever", [], [r], content_type="text").findings, [])
        self.assertEqual(len(run_checks("best ever", [], [r], content_type="pptx").findings), 1)

    def test_inactive_rule_ignored(self):
        self.assertEqual(run_checks("best ever", [], [rule(status="inactive")]).findings, [])

    def test_sentence_offsets(self):
        text = "One two. Three four!\nFive 4.5 six."
        for s, e, seg in sentences(text):
            self.assertEqual(text[s:e], seg)


if __name__ == "__main__":
    unittest.main()
