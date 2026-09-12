import asyncio
from collections.abc import Sequence

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.search.service import SearchService


class StubProvider:
    vertical = "web"

    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return self._results


class NewsStub:
    vertical = "news"

    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        self.calls += 1
        return self._results


class AcademicStub:
    vertical = "academic"

    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        self.calls += 1
        return self._results


class FailingProvider:
    vertical = "web"

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        raise ProviderError("backend down")


def test_rrf_prefers_best_snippet_for_same_url() -> None:
    echo = SearchResult(title="T", url="https://example.com/a", snippet="1. T")
    real = SearchResult(
        title="T", url="https://example.com/a", snippet="T is a great tool for testing things."
    )
    service = SearchService(StubProvider([echo]), extra_providers=[StubProvider([real])])
    results = asyncio.run(service.search(SearchQuery("T", limit=5)))
    assert len(results) == 1
    assert results[0].snippet == "T is a great tool for testing things."


def test_numbering_prefix_stripped_from_snippets() -> None:
    provider = StubProvider([SearchResult(title="T", url="https://e.com/1", snippet="2. T")])
    results = asyncio.run(SearchService(provider).search(SearchQuery("T", limit=5)))
    assert results[0].snippet == "T"


def test_site_operator_becomes_domain_allowlist() -> None:
    provider = StubProvider(
        [
            SearchResult(title="A", url="https://github.com/a"),
            SearchResult(title="B", url="https://example.com/b"),
        ]
    )
    results = service_search(provider, "tool site:github.com")
    assert [r.url for r in results] == ["https://github.com/a"]


def service_search(provider: StubProvider, text: str) -> Sequence[SearchResult]:
    return asyncio.run(SearchService(provider).search(SearchQuery(text, limit=5)))


def test_excluded_terms_filtered() -> None:
    provider = StubProvider(
        [
            SearchResult(title="Python tutorial", url="https://e.com/1", snippet="learn here"),
            SearchResult(title="Python reference", url="https://e.com/2", snippet="docs here"),
        ]
    )
    results = asyncio.run(SearchService(provider).search(SearchQuery("python -tutorial", limit=5)))
    assert [r.url for r in results] == ["https://e.com/2"]


def test_news_provider_only_used_for_news_intent() -> None:
    news = NewsStub([SearchResult(title="N", url="https://news.example.com/n")])
    service = SearchService(
        StubProvider([SearchResult(title="A", url="https://example.com/a")]),
        extra_providers=[news],
    )
    asyncio.run(service.search(SearchQuery("plain tech query", limit=5)))
    assert news.calls == 0
    asyncio.run(service.search(SearchQuery("ข่าวล่าสุด", limit=5)))
    assert news.calls == 1


def test_academic_provider_only_used_for_academic_intent() -> None:
    academic = AcademicStub([SearchResult(title="P", url="https://doi.org/10.1/x")])
    service = SearchService(
        StubProvider([SearchResult(title="A", url="https://example.com/a")]),
        extra_providers=[academic],
    )
    asyncio.run(service.search(SearchQuery("plain tech query", limit=5)))
    assert academic.calls == 0
    asyncio.run(service.search(SearchQuery("arxiv paper on testing", limit=5)))
    assert academic.calls == 1


def test_cache_serves_stale_on_total_failure() -> None:
    good = StubProvider([SearchResult(title="A", url="https://example.com/a")])
    service = SearchService(good)
    first = asyncio.run(service.search(SearchQuery("cached query", limit=5)))
    assert len(first) == 1
    # Swap in a failing backend; cached query must still resolve.
    service._providers = [FailingProvider()]
    second = asyncio.run(service.search(SearchQuery("cached query", limit=5)))
    assert [r.url for r in second] == ["https://example.com/a"]


def test_empty_results_retry_with_simplified_query() -> None:
    seen: list[str] = []

    class RecordingProvider:
        vertical = "web"

        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            seen.append(query.text)
            if '"' in query.text:
                return []
            return [SearchResult(title="A", url="https://example.com/a")]

    results = asyncio.run(
        SearchService(RecordingProvider()).search(SearchQuery('"quoted" python', limit=5))
    )
    assert [r.url for r in results] == ["https://example.com/a"]
    assert seen == ['"quoted" python', "quoted python"]
