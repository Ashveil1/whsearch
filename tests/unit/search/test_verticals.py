import asyncio

import httpx
import pytest

from whsearch.domain import SearchQuery
from whsearch.exceptions import ProviderError
from whsearch.search.providers.googlenews import GoogleNewsProvider
from whsearch.search.providers.openalex import OpenAlexProvider, _reconstruct_abstract

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Spain wins World Cup - ESPN</title>
<link>https://news.google.com/articles/abc123</link>
<pubDate>Sat, 12 Sep 2026 10:00:00 GMT</pubDate>
<source url="https://www.espn.com">ESPN</source></item>
<item><title>Bad item without link</title><link></link></item>
</channel></rss>"""

OPENALEX = {
    "results": [
        {
            "title": "Retrieval-Augmented Generation: A Survey",
            "doi": "https://doi.org/10.1/survey",
            "id": "https://openalex.org/W1",
            "publication_date": "2024-01-15",
            "cited_by_count": 120,
            "primary_location": {"source": {"display_name": "Nature"}},
            "abstract_inverted_index": {"Retrieval": [0], "models": [1], "survey": [2]},
        },
        {"title": "", "doi": "", "id": "not-a-url"},
    ]
}


def _client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _rss_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/rss/search"
    return httpx.Response(200, text=RSS)


def _openalex_handler(request: httpx.Request) -> httpx.Response:
    assert "openalex.org" in request.url.host
    import json

    return httpx.Response(200, text=json.dumps(OPENALEX))


def test_googlenews_parses_items_and_skips_bad_ones() -> None:
    async def _main() -> None:
        async with _client(_rss_handler) as client:
            results = await GoogleNewsProvider(client).search(SearchQuery("World Cup", limit=5))
        assert len(results) == 1
        item = results[0]
        assert item.title == "Spain wins World Cup - ESPN"
        assert item.source_type.value == "news"
        assert item.metadata.get("published") == "2026-09-12"
        assert item.metadata.get("source") == "ESPN"

    asyncio.run(_main())


def test_googlenews_uses_thai_params_for_thai_query() -> None:
    seen: dict[str, str] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, text=RSS)

    async def _main() -> None:
        async with _client(_handler) as client:
            await GoogleNewsProvider(client).search(SearchQuery("ผลบอลโลก", limit=2))

    asyncio.run(_main())
    assert seen.get("gl") == "TH"


def test_googlenews_http_error_becomes_provider_error() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def _main() -> None:
        async with _client(_handler) as client:
            with pytest.raises(ProviderError):
                await GoogleNewsProvider(client).search(SearchQuery("x", limit=2))

    asyncio.run(_main())


def test_openalex_parses_works_and_skips_invalid() -> None:
    async def _main() -> None:
        async with _client(_openalex_handler) as client:
            results = await OpenAlexProvider(client).search(SearchQuery("retrieval", limit=5))
        assert len(results) == 1
        item = results[0]
        assert item.url == "https://doi.org/10.1/survey"
        assert item.source_type.value == "academic"
        assert "Nature" in item.snippet and "2024-01-15" in item.snippet

    asyncio.run(_main())


def test_reconstruct_abstract_orders_positions() -> None:
    assert _reconstruct_abstract({"world": [1], "hello": [0]}) == "hello world"
    assert _reconstruct_abstract({}) == ""
    assert _reconstruct_abstract(None) == ""
