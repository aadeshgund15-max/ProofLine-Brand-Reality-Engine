"""Provider boundaries for the LLM and the source-search service.

Providers are only reported as *configured* when their credentials exist, and as *working*
only after a live probe (see /api/settings/providers). Nothing here fabricates a result: on
any failure a ProviderError is raised and the caller records an honest unavailable state.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol

try:
    import httpx
except ImportError:  # allows unit tests with fake providers where httpx is absent
    httpx = None  # type: ignore


class ProviderError(RuntimeError):
    pass


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    published_date: Optional[str] = None
    publisher: Optional[str] = None


class SearchProvider(Protocol):
    name: str
    def configured(self) -> bool: ...
    def search(self, query: str, limit: int = 5) -> list[SearchHit]: ...


class LlmProvider(Protocol):
    name: str
    def configured(self) -> bool: ...
    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> Any: ...


# ---------------------------------------------------------------- search
class TavilySearch:
    name = "tavily"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.Client] = None):
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")
        self._client = client


    @property
    def client(self):
        if self._client is None:
            self._client = httpx.Client(timeout=15)
        return self._client

    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if not self.configured():
            raise ProviderError("Tavily API key is not configured")
        try:
            r = self.client.post("https://api.tavily.com/search", json={
                "api_key": self.api_key, "query": query[:400], "max_results": limit,
                "search_depth": "basic", "include_answer": False})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"Search request failed ({type(e).__name__})") from e
        hits = []
        for it in data.get("results", []):
            if it.get("url") and it.get("content"):
                hits.append(SearchHit(it.get("title") or it["url"], it["url"], it["content"][:1200],
                                      it.get("published_date")))
        return hits[:limit]


class BraveSearch:
    name = "brave"

    def __init__(self, api_key: Optional[str] = None, client: Optional[httpx.Client] = None):
        self.api_key = api_key if api_key is not None else os.getenv("BRAVE_API_KEY", "")
        self._client = client


    @property
    def client(self):
        if self._client is None:
            self._client = httpx.Client(timeout=15)
        return self._client

    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if not self.configured():
            raise ProviderError("Brave API key is not configured")
        try:
            r = self.client.get("https://api.search.brave.com/res/v1/web/search",
                                params={"q": query[:400], "count": limit},
                                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"Search request failed ({type(e).__name__})") from e
        hits = []
        for it in data.get("web", {}).get("results", []):
            if it.get("url") and it.get("description"):
                hits.append(SearchHit(it.get("title") or it["url"], it["url"], it["description"][:1200],
                                      it.get("page_age"), (it.get("profile") or {}).get("name")))
        return hits[:limit]


class NoSearch:
    name = "none"
    def configured(self) -> bool: return False
    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        raise ProviderError("No search provider is configured")


def get_search_provider() -> SearchProvider:
    choice = os.getenv("SEARCH_PROVIDER", "").lower()
    if choice == "tavily" or (not choice and os.getenv("TAVILY_API_KEY")):
        return TavilySearch()
    if choice == "brave" or (not choice and os.getenv("BRAVE_API_KEY")):
        return BraveSearch()
    return NoSearch()


# ------------------------------------------------------------------- llm
class OpenAICompatibleLlm:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, Azure proxy, Ollama, vLLM, …)."""
    name = "openai-compatible"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, client: Optional[httpx.Client] = None):
        self.api_key = api_key if api_key is not None else os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", "")
        self._client = client


    @property
    def client(self):
        if self._client is None:
            self._client = httpx.Client(timeout=60)
        return self._client

    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> Any:
        if not self.configured():
            raise ProviderError("LLM provider is not configured")
        try:
            r = self.client.post(f"{self.base_url}/chat/completions",
                                 headers={"Authorization": f"Bearer {self.api_key}"},
                                 json={"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                                       "response_format": {"type": "json_object"},
                                       "messages": [{"role": "system", "content": system},
                                                    {"role": "user", "content": user}]})
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"LLM request failed or returned invalid JSON ({type(e).__name__})") from e


class NoLlm:
    name = "none"
    def configured(self) -> bool: return False
    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> Any:
        raise ProviderError("No LLM provider is configured")


def get_llm_provider() -> LlmProvider:
    p = OpenAICompatibleLlm()
    return p if p.configured() else NoLlm()
