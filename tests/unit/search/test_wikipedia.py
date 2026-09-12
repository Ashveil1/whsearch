import asyncio

import httpx
import pytest

from whsearch.domain import SearchQuery, SourceType
from whsearch.exceptions import ProviderError
from whsearch.search.providers.wikipedia import WikipediaProvider

PAYLOAD = {
    "query": {
        "search": [
            {
                "title": "Python (programming language)",
                "snippet": 'A <span class="x">high-level</span> language',
            },
            {"title": "Monty Python", "snippet": "Comedy group"},
        ]
    }
}


def _client(payload: object, status: int = 200) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert "wikipedia.org" in str(request.url)
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def test_wikipedia_parses_results() -> None:
    async def _main() -> None:
        async with _client(PAYLOAD) as client:
            results = await WikipediaProvider(client).search(SearchQuery("python", limit=5))
        assert len(results) == 2
        assert results[0].url == "https://en.wikipedia.org/wiki/Python_%28programming_language%29"
        assert results[0].snippet == "A high-level language"
        assert results[0].source_type == SourceType.DOCUMENTATION

    asyncio.run(_main())


def test_wikipedia_http_error_becomes_provider_error() -> None:
    async def _main() -> None:
        async with _client({}, status=500) as client:
            with pytest.raises(ProviderError, match="Wikipedia request failed"):
                await WikipediaProvider(client).search(SearchQuery("python"))

    asyncio.run(_main())


def test_wikipedia_bad_payload_becomes_provider_error() -> None:
    async def _main() -> None:
        async with _client({"unexpected": True}) as client:
            with pytest.raises(ProviderError, match="unexpected payload"):
                await WikipediaProvider(client).search(SearchQuery("python"))

    asyncio.run(_main())
