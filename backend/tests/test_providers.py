import json
import unittest

import httpx

from app.providers.base import BraveSearch, OpenAICompatibleLlm, ProviderError, TavilySearch


class FakeHttpClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._result()

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._result()

    def _result(self):
        if self.error:
            raise self.error
        return self.response


def response(status=200, payload=None):
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "https://provider.example"))


class ProviderAdapterTests(unittest.TestCase):
    def test_tavily_parses_realistic_search_response_shape(self):
        client = FakeHttpClient(response=response(200, {"results": [
            {"title": "Manual", "url": "https://maker.example/manual", "content": "VH-2400 specifications", "published_date": "2026-01-02"},
            {"title": "Missing text", "url": "https://maker.example/empty"},
        ]}))
        provider = TavilySearch(api_key="test-key-not-real", client=client)

        hits = provider.search("VH-2400 manual", limit=1)

        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0].title, hits[0].url, hits[0].snippet),
                         ("Manual", "https://maker.example/manual", "VH-2400 specifications"))
        self.assertEqual(hits[0].published_date, "2026-01-02")
        self.assertEqual(client.calls[0][0], "POST")
        self.assertEqual(client.calls[0][2]["json"]["max_results"], 1)

    def test_brave_parses_publisher_and_page_age(self):
        client = FakeHttpClient(response=response(200, {"web": {"results": [
            {"title": "Independent test", "url": "https://lab.example/report", "description": "Tested VH-2400", "page_age": "2026-04-01", "profile": {"name": "Test Lab"}},
        ]}}))
        provider = BraveSearch(api_key="test-key-not-real", client=client)

        hits = provider.search("VH-2400 test")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].publisher, "Test Lab")
        self.assertEqual(hits[0].published_date, "2026-04-01")
        self.assertIn("X-Subscription-Token", client.calls[0][2]["headers"])

    def test_openai_compatible_llm_extracts_json_content(self):
        payload = {"choices": [{"message": {"content": json.dumps({"items": [{"quote": "Model VH-2400"}]})}}]}
        client = FakeHttpClient(response=response(200, payload))
        provider = OpenAICompatibleLlm(api_key="test-key-not-real", base_url="https://llm.example/v1",
                                       model="test-model", client=client)

        result = provider.complete_json("system", "user")

        self.assertEqual(result, {"items": [{"quote": "Model VH-2400"}]})
        self.assertTrue(client.calls[0][1].endswith("/chat/completions"))
        self.assertEqual(client.calls[0][2]["json"]["response_format"], {"type": "json_object"})

    def test_rate_limit_and_timeout_are_reported_without_credentials(self):
        for client in (
            FakeHttpClient(response=response(429, {"message": "rate limited"})),
            FakeHttpClient(error=httpx.TimeoutException("provider timeout")),
        ):
            with self.subTest(error=client.error or client.response.status_code):
                provider = TavilySearch(api_key="private-test-key", client=client)
                with self.assertRaises(ProviderError) as caught:
                    provider.search("test")
                self.assertNotIn("private-test-key", str(caught.exception))

    def test_invalid_llm_json_is_reported_without_credentials(self):
        payload = {"choices": [{"message": {"content": "not valid JSON"}}]}
        client = FakeHttpClient(response=response(200, payload))
        provider = OpenAICompatibleLlm(api_key="private-test-key", model="test", client=client)

        with self.assertRaises(ProviderError) as caught:
            provider.complete_json("system", "user")

        self.assertIn("invalid JSON", str(caught.exception))
        self.assertNotIn("private-test-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
