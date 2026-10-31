import unittest

from app.services.product_intelligence import (
    QUERY_CATEGORIES, _coverage, _extract_profile_facts, _product_match_status, _query_text,
    _source_category, _url_key, review_gate,
)


PRODUCT = {
    "product_name": "Volt Home Battery", "brand": "Volt", "manufacturer": "Volt Energy",
    "model_number": "VH-2400", "market": "India", "official_website": "https://volt.example/products",
}


class FakeLlm:
    name = "fake"

    def __init__(self, response, configured=True):
        self.response = response
        self._configured = configured

    def configured(self):
        return self._configured

    def complete_json(self, system, user, max_tokens=1500):
        return self.response


class ProductResearchUnitTests(unittest.TestCase):
    def test_product_research_generates_multiple_distinct_categories(self):
        queries = [_query_text(category, template, PRODUCT) for category, template in QUERY_CATEGORIES]
        self.assertGreaterEqual(len(queries), 15)
        self.assertEqual(len(set(queries)), len(queries))
        self.assertTrue(all("VH-2400" in query and "India" in query for query in queries))

    def test_similar_product_name_without_exact_identifier_stays_ambiguous(self):
        self.assertEqual(_product_match_status(PRODUCT, "Volt Home Battery reviewed by customers", "https://reviews.example/item"), "ambiguous")
        self.assertEqual(_product_match_status(PRODUCT, "Datasheet for model VH-2400", "https://docs.example/vh"), "matched_by_identifier")
        self.assertEqual(_product_match_status(PRODUCT, "Model VH-24000 has a different battery", "https://docs.example/vh"), "ambiguous")
        self.assertEqual(_product_match_status(PRODUCT, "Another Volt battery manual", "https://volt.example/manual"), "ambiguous")

    def test_official_domain_is_only_a_candidate_classification(self):
        self.assertEqual(_source_category("https://volt.example/specs", "official_specs", PRODUCT["official_website"]), "official_candidate")
        self.assertEqual(_source_category("https://fda.gov/device", "certifications_safety", None), "government_or_regulator_candidate")
        self.assertEqual(_source_category("https://example.com", "official_specs", PRODUCT["official_website"]), "general_public_source")

    def test_tracking_variants_deduplicate(self):
        self.assertEqual(_url_key("https://news.example/article?utm_source=mail&id=2#top"),
                         _url_key("https://news.example/article?id=2"))

    def test_coverage_is_only_derived_from_recorded_queries_and_sources(self):
        rows = [("official_specs", "completed", 2), ("manuals", "failed", 0)]
        sources = [{"access_status": "ok", "extraction_status": "complete"},
                   {"access_status": "unreachable", "extraction_status": "fetch_failed"}]
        coverage = _coverage(rows, sources, ["official_specs", "manuals"], "2026-10-31T00:00:00+00:00")
        self.assertEqual(coverage["queries_executed"], 2)
        self.assertEqual(coverage["queries_failed"], 1)
        self.assertEqual(coverage["search_results_discovered"], 2)
        self.assertEqual(coverage["sources_inspected"], 1)
        self.assertEqual(coverage["sources_inaccessible"], 1)
        self.assertEqual(coverage["independent_sources_assessed"], 0)
        self.assertEqual(coverage["categories_with_insufficient_information"], ["manuals"])

    def test_submission_gate_holds_unconfirmed_or_unresearched_products(self):
        self.assertEqual(review_gate(None)[0], "unavailable")
        unconfirmed = {"identity_status": "ambiguous", "research_status": "completed", "coverage": {"sources_inspected": 4}}
        self.assertEqual(review_gate(unconfirmed)[0], "partial")
        stale = {"identity_status": "confirmed", "research_status": "partial", "coverage": {"sources_inspected": 4}}
        self.assertEqual(review_gate(stale)[0], "partial")
        ready = {"identity_status": "confirmed", "research_status": "completed", "coverage": {
            "sources_inspected": 2, "profile_extraction_status": "completed", "product_facts_supported": 1}}
        self.assertEqual(review_gate(ready)[0], "completed")

    def test_profile_facts_require_an_exact_quote_from_a_matched_inspected_source(self):
        source_id = "source-1"
        source = {"id": source_id, "title": "Manual", "url": "https://docs.example/vh",
                  "product_match_status": "matched_by_identifier", "access_status": "ok",
                  "text": "Model VH-2400 has a 2.4 kWh capacity."}
        llm = FakeLlm({"facts": [
            {"category": "specifications", "source_id": source_id,
             "quote": "Model VH-2400 has a 2.4 kWh capacity."},
            {"category": "specifications", "source_id": source_id,
             "quote": "The battery lasts 20 hours."},
        ]})

        facts, status, _ = _extract_profile_facts(PRODUCT, [source], llm)

        self.assertEqual(status, "completed")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["statement"], "Model VH-2400 has a 2.4 kWh capacity.")
        self.assertEqual(facts[0]["evidence_status"], "supported_by_source")

    def test_profile_facts_are_unavailable_without_an_llm_or_matching_source(self):
        source = {"id": "source-1", "product_match_status": "ambiguous", "access_status": "ok",
                  "text": "A page about a similar battery."}
        facts, status, _ = _extract_profile_facts(PRODUCT, [source], FakeLlm({}, configured=False))
        self.assertEqual(facts, [])
        self.assertEqual(status, "unavailable")


if __name__ == "__main__":
    unittest.main()
