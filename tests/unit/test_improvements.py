import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from whsearch.agent import ResearchAgent
from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import Claim, Document, Passage, ResearchBudget, SearchQuery, SearchResult
from whsearch.evidence import SourcedPassage, verify_claims
from whsearch.exceptions import ProviderError, ReaderError
from whsearch.mcp.tools.search import search as search_tool
from whsearch.mcp.tools.search_and_read import search_and_read
from whsearch.reader import ReaderService, RobotsPolicy
from whsearch.search import SearchService
from whsearch.search.providers.duckduckgo import DuckDuckGoProvider, _extract_target_url
from whsearch.search.providers.duckduckgo_html import DuckDuckGoHtmlProvider
from whsearch.search.query import provider_query
from whsearch.search.service import _fuse_rrf


@pytest.mark.parametrize("provider_class", [DuckDuckGoProvider, DuckDuckGoHtmlProvider])
def test_site_domain_pushed_to_ddg_and_empty_snippet_is_not_fabricated(
    provider_class: type[DuckDuckGoProvider] | type[DuckDuckGoHtmlProvider],
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["q"])
        return httpx.Response(
            200,
            text='<a class="result-link" href="https://example.com/a">Result Title</a>',
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await provider_class(client).search(
                SearchQuery("example search", domains=("example.com",))
            )
            if provider_class is DuckDuckGoProvider:
                assert results[0].snippet == ""

    asyncio.run(run())
    assert seen == ["example search site:example.com"]
    assert provider_query("query", ("example.com OR site:evil.test",)) == "query"
    assert provider_query("site:example.com", ("example.com",)) == "site:example.com"


def test_ddg_url_unwrap_does_not_double_decode_target() -> None:
    url = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%252Fb"
    assert _extract_target_url(url) == "https://example.com/a%2Fb"


def test_repeated_entries_from_one_provider_do_not_add_rrf_votes() -> None:
    a = SearchResult("A", "https://example.com/a")
    b = SearchResult("B", "https://example.com/b")
    assert [item.url for item in _fuse_rrf([[a, a], [b]])] == [a.url, b.url]


def test_match_selection_includes_other_domains() -> None:
    claim = Claim("c", "Python is a popular programming language")
    sources = [
        *(SourcedPassage("https://one.com/" + str(i), "T", 0, claim.text) for i in range(7)),
        SourcedPassage("https://two.com/a", "T", 0, claim.text),
    ]
    matched, evidence = verify_claims([claim], sources)
    assert matched[0].status.value == "lexical_match"
    assert any(e.url == "https://two.com/a" for e in evidence)


def test_no_lexically_relevant_claim_does_not_become_an_answer() -> None:
    class Provider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [SearchResult("Weather", "https://example.com/weather")]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "The weather today is sunny in northern Norway."
            return Document(url, "Weather", text, (Passage(text, 0),))

    async def run() -> None:
        agent = ResearchAgent(SearchService(Provider()), Reader())
        report = await agent.research("Python", ResearchBudget(max_rounds=1))
        assert report.claims
        assert report.answer == ""
        assert not report.answer_citations

    asyncio.run(run())


def test_provider_deadline_cancels_slow_search() -> None:
    class SlowProvider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            await asyncio.sleep(10)
            return []

    async def run() -> None:
        service = SearchService(SlowProvider(), provider_timeout_seconds=0.01)
        with pytest.raises(ProviderError, match="timed out"):
            await service.search(SearchQuery("test"))

    asyncio.run(run())


def test_reader_deadline_cancels_slow_body() -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            await asyncio.sleep(10)
            yield b"unreachable"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=SlowStream())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = ReaderService(client, RobotsPolicy(client, "test"), timeout_seconds=0.01)
            with pytest.raises(ReaderError, match="deadline"):
                await service.read("https://example.com/article")

    asyncio.run(run())


def test_search_metadata_and_redirect_domain_filter() -> None:
    class Provider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [
                SearchResult("original", "https://example.com/article", metadata={"date": "2026"})
            ]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "A long article about the subject requested by the user."
            return Document("https://other.example/article", "new", text, (Passage(text, 0),))

    async def run() -> None:
        app = Application(
            httpx.AsyncClient(), settings=Settings(), provider=Provider(), reader=Reader()
        )
        try:
            items = await search_tool(app, "subject")
            metadata = items[0]["metadata"]
            assert isinstance(metadata, dict)
            assert metadata["date"] == "2026"
            assert metadata["whsearch"]["providers"] == ["Provider"]
            assert items[0]["snippet"] == ""
            result = await search_and_read(app, "subject", domains=["example.com"])
            assert result == []
            result = await search_and_read(app, "subject")
            assert result[0]["url"] == "https://other.example/article"
            assert result[0]["requested_url"] == "https://example.com/article"
            assert result[0]["metadata"] == metadata
        finally:
            await app.aclose()

    asyncio.run(run())


def test_partial_provider_failure_and_cache_are_visible() -> None:
    class FailingProvider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            raise ProviderError("upstream unavailable")

    class WorkingProvider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [SearchResult("A", "https://example.com/a")]

    async def run() -> None:
        service = SearchService(WorkingProvider(), extra_providers=[FailingProvider()])
        results = await service.search(SearchQuery("test"))
        info = results[0].metadata["whsearch"]
        assert info["providers"] == ["WorkingProvider"]
        assert info["failed_providers"] == ["FailingProvider"]
        assert info["stale_cache"] is False
        service._providers = [FailingProvider()]
        cached = await service.search(SearchQuery("test"))
        assert cached[0].metadata["whsearch"]["stale_cache"] is True
        key = service._cache_key(SearchQuery("test"))
        _, old_results = service._cache[key]
        service._cache[key] = (0, old_results)
        with pytest.raises(ProviderError):
            await service.search(SearchQuery("test"))

    asyncio.run(run())


def test_partial_failure_without_results_is_not_silent() -> None:
    class Empty:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return []

    class Failure:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            raise ProviderError("offline")

    service = SearchService(Empty(), extra_providers=[Failure()])
    with pytest.raises(ProviderError, match="no results"):
        asyncio.run(service.search(SearchQuery("test")))


def test_robots_cache_is_bounded_and_active_origins_are_not_evicted() -> None:
    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            started.set()
            await release.wait()
            return httpx.Response(200, text="User-agent: *\nAllow: /")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            policy = RobotsPolicy(client, "test", max_origins=1)
            first = asyncio.create_task(policy.allowed("https://one.example/page"))
            await started.wait()
            assert not await policy.allowed("https://two.example/page")
            assert len(policy._origins) == 1
            release.set()
            assert await first
            assert await policy.allowed("https://two.example/page")
            assert len(policy._origins) == 1

    asyncio.run(run())


def test_research_preserves_site_constraint_for_followups() -> None:
    class Provider:
        def __init__(self) -> None:
            self.seen: list[SearchQuery] = []

        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            self.seen.append(query)
            return [SearchResult("Python", f"https://example.com/{len(self.seen)}")]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "Python programming is a widely used language for many tasks."
            return Document(url, "Python", text, (Passage(text, 0),))

    async def run() -> None:
        provider = Provider()
        agent = ResearchAgent(SearchService(provider), Reader())
        await agent.research(
            "Python site:example.com", ResearchBudget(max_queries=4, max_pages=4, max_rounds=3)
        )
        assert len(provider.seen) > 1
        assert all(q.domains == ("example.com",) for q in provider.seen)

    asyncio.run(run())


def test_html_fallback_preserves_each_passage_section() -> None:
    from whsearch.reader.extractors.html import HtmlExtractor

    html = """<html><body><article>
        <h2>First</h2><p>This is the first paragraph with enough content.</p>
        <h2>Second</h2><p>This is the second paragraph with enough content.</p>
    </article></body></html>"""
    doc = HtmlExtractor().extract("https://example.com", html)
    assert [p.section for p in doc.passages] == ["First", "Second"]


def test_evidence_contains_section_publication_and_truncation() -> None:
    from datetime import UTC, datetime

    date = datetime(2025, 1, 2, tzinfo=UTC)
    text = "This example sentence contains enough words to test the metadata."
    sources = [SourcedPassage("https://example.com", "T", 0, text, "00:10 Intro", date, True)]
    _, evidence = verify_claims([Claim("c", text)], sources)
    assert evidence[0].section == "00:10 Intro"
    assert evidence[0].published_at == date
    assert evidence[0].truncated is True


def test_domain_filter_handles_international_hostnames_and_partial_failure() -> None:
    from whsearch.search.service import _result_allowed

    assert _result_allowed("https://xn--mgbh0fb.xn--kgbechtv/page", ("مثال.إختبار",))
    assert not _result_allowed("https://notexample.com", ("example.com",))

    class OtherDomain:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [SearchResult("Other", "https://other.com/")]

    class Failure:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            raise ProviderError("offline")

    service = SearchService(OtherDomain(), extra_providers=[Failure()])
    with pytest.raises(ProviderError, match="no matching results"):
        asyncio.run(service.search(SearchQuery("topic", domains=("example.com",))))


def test_robots_origin_keys_normalize_default_port_and_host() -> None:
    from whsearch.reader.robots import _origin_key

    assert _origin_key("https://EXAMPLE.com./one") == _origin_key("https://example.com:443/two")
    assert _origin_key("https://example.com:444/two") != _origin_key("https://example.com/one")


def test_provider_failures_do_not_leak_queries_in_warning_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client:
            provider = DuckDuckGoProvider(client)
            with pytest.raises(ProviderError) as error:
                await provider.search(SearchQuery("private patient query"))
            assert "private patient query" not in str(error.value)

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert "private patient query" not in caplog.text
