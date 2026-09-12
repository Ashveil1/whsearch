import asyncio
from collections.abc import Sequence

import pytest

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.search.service import SearchService


class StubProvider:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return self._results


def test_search_service_deduplicates_results() -> None:
    provider = StubProvider(
        [
            SearchResult(title="A", url="https://example.com/page#one"),
            SearchResult(title="B", url="https://example.com/page#two"),
        ]
    )
    results = asyncio.run(SearchService(provider).search(SearchQuery("x", limit=10)))
    assert [r.title for r in results] == ["A"]


def test_search_service_caps_at_configured_max() -> None:
    provider = StubProvider(
        [SearchResult(title=f"N{i}", url=f"https://example.com/{i}") for i in range(5)]
    )
    results = asyncio.run(SearchService(provider, max_results=2).search(SearchQuery("x", limit=10)))
    assert len(results) == 2


def test_search_service_rejects_non_positive_max() -> None:
    with pytest.raises(ValueError, match="positive"):
        SearchService(StubProvider([]), max_results=0)


class FailingProvider:
    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        raise ProviderError("backend down")


def test_fan_out_merges_providers_primary_first() -> None:
    primary = StubProvider([SearchResult(title="A", url="https://example.com/a")])
    extra = StubProvider([SearchResult(title="B", url="https://example.org/b")])
    results = asyncio.run(
        SearchService(primary, extra_providers=[extra]).search(SearchQuery("x", limit=10))
    )
    assert [r.url for r in results] == ["https://example.com/a", "https://example.org/b"]


def test_fan_out_dedupes_across_providers() -> None:
    primary = StubProvider([SearchResult(title="A", url="https://example.com/a#1")])
    extra = StubProvider([SearchResult(title="A2", url="https://example.com/a#2")])
    results = asyncio.run(
        SearchService(primary, extra_providers=[extra]).search(SearchQuery("x", limit=10))
    )
    assert [r.title for r in results] == ["A"]


def test_fan_out_isolates_failing_provider() -> None:
    primary = StubProvider([SearchResult(title="A", url="https://example.com/a")])
    results = asyncio.run(
        SearchService(primary, extra_providers=[FailingProvider()]).search(
            SearchQuery("x", limit=10)
        )
    )
    assert [r.title for r in results] == ["A"]


def test_fan_out_all_failing_raises() -> None:
    service = SearchService(FailingProvider(), extra_providers=[FailingProvider()])
    with pytest.raises(ProviderError, match="all 2 search providers failed"):
        asyncio.run(service.search(SearchQuery("x")))


def test_single_provider_failure_propagates() -> None:
    with pytest.raises(ProviderError, match="backend down"):
        asyncio.run(SearchService(FailingProvider()).search(SearchQuery("x")))
