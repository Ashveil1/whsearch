import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from whsearch.agent import ResearchAgent
from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import (
    Claim,
    Document,
    Passage,
    ResearchBudget,
    ResearchReport,
    SearchQuery,
    SearchResult,
)
from whsearch.evidence import (
    SourcedPassage,
    build_answer,
    extract_claims,
    registrable_domain,
    verify_claims,
)
from whsearch.exceptions import ReaderError
from whsearch.index import SqliteDocumentStore
from whsearch.mcp.tools.research import research
from whsearch.mcp.tools.search_and_read import search_and_read
from whsearch.reader import ReaderService, RobotsPolicy
from whsearch.search import SearchService
from whsearch.search.providers.duckduckgo import _extract_target_url


def test_research_tool_calls_once_passes_recency_and_caps_pages() -> None:
    class Agent:
        def __init__(self) -> None:
            self.calls: list[tuple[ResearchBudget, int | None]] = []

        async def research(
            self, question: str, budget: ResearchBudget, *, recency_days: int | None = None
        ) -> ResearchReport:
            self.calls.append((budget, recency_days))
            return ResearchReport(question=question)

    agent = Agent()
    app = SimpleNamespace(settings=Settings(max_pages_per_task=2), research_agent=agent)
    asyncio.run(research(app, "question", max_pages=50, recency_days=7))  # type: ignore[arg-type]
    assert len(agent.calls) == 1
    assert agent.calls[0][0].max_pages == 2
    assert agent.calls[0][1] == 7


def test_sqlite_update_removes_old_terms_and_enforces_ttl_and_size() -> None:
    async def run() -> None:
        store = SqliteDocumentStore(max_bytes=1000)
        url = "https://example.com/a"

        def doc(text: str) -> Document:
            return Document(url=url, title="a", content=text, passages=(Passage(text, 0),))

        try:
            await store.put(doc("quokka zebra"))
            await store.put(doc("elephant tiger"))
            assert store.search_passages("quokka") == []
            assert store.search_passages("elephant")[0][2] == "elephant tiger"
            store._conn.execute("UPDATE documents SET fetched_at = 0")
            assert await store.get(url) is None
            assert store.search_passages("elephant") == []
            await store.put(doc("x" * 1001))
            assert await store.get(url) is None
        finally:
            store.close()

    asyncio.run(run())


def test_lexical_matches_never_claim_fact_checked() -> None:
    text = "The vaccine prevents the disease in adults and children"
    sources = [
        SourcedPassage("https://one.com", "one", 0, text),
        SourcedPassage("https://two.com", "two", 0, text + ": this claim is false"),
    ]
    claims, _ = verify_claims([Claim("a", text)], sources)
    assert claims[0].status.value != "supported"
    assert "not fact-checked" in build_answer(claims)[0]


def test_citation_markers_reference_urls_not_claim_positions() -> None:
    claims = [
        Claim("a", "First finding", sources=("https://one.com", "https://two.com")),
        Claim("b", "Second finding", sources=("https://three.com", "https://one.com")),
    ]
    answer, urls = build_answer(claims)
    assert urls == ("https://one.com", "https://two.com", "https://three.com")
    assert "First finding [1] [2]" in answer
    assert "Second finding [3] [1]" in answer


def test_public_suffix_and_thai_claims() -> None:
    assert registrable_domain("https://a.co.th") != registrable_domain("https://b.co.th")
    assert registrable_domain("https://one.github.io") != registrable_domain(
        "https://two.github.io"
    )
    assert extract_claims(["ประเทศไทยมีประชากรมากกว่าหกสิบล้านคนและมีกรุงเทพมหานครเป็นเมืองหลวง"])


def test_reader_checks_redirect_policy_and_never_fetches_private_url() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            reader = ReaderService(client, RobotsPolicy(client, "test"))
            with pytest.raises(ReaderError, match="non-public"):
                await reader.read("https://example.com/article")

    asyncio.run(run())
    assert not any("127.0.0.1" in url for url in requests)


def test_redirect_destination_robots_are_checked() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            rules = "Disallow: /secret" if request.url.host == "other.example" else "Allow: /"
            return httpx.Response(200, text=f"User-agent: *\n{rules}")
        return httpx.Response(302, headers={"location": "https://other.example/secret"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ReaderError, match="robots"):
                await ReaderService(client, RobotsPolicy(client, "test")).read(
                    "https://example.com/x"
                )

    asyncio.run(run())
    assert "https://other.example/secret" not in requests
    assert "https://other.example/robots.txt" in requests


def test_absolute_ddg_redirect_is_unwrapped() -> None:
    assert (
        _extract_target_url("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa")
        == "https://example.com/a"
    )


def test_research_rounds_budget_and_followup_query() -> None:
    class Provider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            self.queries.append(query.text)
            return [SearchResult("title", f"https://example.com/{len(self.queries)}")]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "Python programming language offers many useful features for developers."
            return Document(url, "title", text, (Passage(text, 0),))

    async def run() -> None:
        provider = Provider()
        agent = ResearchAgent(SearchService(provider), Reader())
        report = await agent.research(
            "Python programming", ResearchBudget(max_queries=3, max_pages=3, max_rounds=3)
        )
        assert report.rounds > 1
        assert len(provider.queries) > 1
        assert any("offers many useful features" in q for q in provider.queries)
        assert len(report.sources) <= 3

    asyncio.run(run())


def test_metadata_only_really_omits_passages() -> None:
    class Provider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [SearchResult("title", "https://example.com")]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "This passage is long enough to be useful."
            return Document(
                url,
                "title",
                text,
                (Passage(text, 0),),
                published_at=datetime.now(UTC) - timedelta(days=1),
            )

    async def run() -> None:
        app = Application(
            httpx.AsyncClient(), settings=Settings(), provider=Provider(), reader=Reader()
        )
        try:
            result = await search_and_read(app, "query", max_chars=0)
            assert "passages" not in result[0]
        finally:
            await app.aclose()

    asyncio.run(run())


def test_robots_rate_limit_and_user_agent() -> None:
    import time

    timestamps: list[float] = []
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timestamps.append(time.monotonic())
        agents.append(request.headers.get("User-Agent", ""))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><body><p>A sufficiently long article body "
                "for a pacing test.</p></body></html>"
            ),
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            robots = RobotsPolicy(client, "TestAgent/1.0", delay_seconds=0.02)
            reader = ReaderService(client, robots, user_agent="TestAgent/1.0")
            await reader.read("https://example.com/article")
        assert len(timestamps) == 2
        assert timestamps[1] - timestamps[0] >= 0.015
        assert agents == ["TestAgent/1.0", "TestAgent/1.0"]

    asyncio.run(run())


def test_nonfinite_settings_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHSEARCH_DOMAIN_DELAY", "nan")
    with pytest.raises(ValueError):
        Settings.from_environment()


def test_legacy_cache_migrates_and_rebuilds_stale_fts(tmp_path: object) -> None:
    import sqlite3
    from pathlib import Path

    path = Path(str(tmp_path)) / "cache.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE documents (
            url TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
            author TEXT, published_at TEXT, language TEXT, canonical_url TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE passages (
            doc_url TEXT NOT NULL, idx INTEGER NOT NULL, section TEXT, text TEXT NOT NULL,
            PRIMARY KEY (doc_url, idx)
        );
        CREATE VIRTUAL TABLE passages_fts USING fts5(
            text, content='passages', content_rowid='rowid'
        );
        INSERT INTO documents (url,title,content) VALUES ('https://example.com','t','elephant');
        INSERT INTO passages VALUES ('https://example.com',0,NULL,'quokka');
        INSERT INTO passages_fts(rowid,text) VALUES (1,'quokka');
        DELETE FROM passages;
        INSERT INTO passages VALUES ('https://example.com',0,NULL,'elephant');
        INSERT INTO passages_fts(rowid,text) VALUES (1,'elephant');
    """)
    conn.commit()
    conn.close()
    store = SqliteDocumentStore(path)
    try:
        # Entries with unknown age are expired rather than served indefinitely.
        assert asyncio.run(store.get("https://example.com")) is None
        store._conn.execute("UPDATE documents SET fetched_at = ?", (datetime.now(UTC).timestamp(),))
        assert store.search_passages("quokka") == []
        assert store.search_passages("elephant")[0][2] == "elephant"
    finally:
        store.close()


def test_thai_ranking_matches_inside_unspaced_text() -> None:
    from whsearch.retrieval import rank_passages

    passages = [
        Passage("สภาพอากาศในยุโรปเปลี่ยนแปลงตลอดปี", 0),
        Passage("การเดินทางในประเทศไทยมีหลากหลายรูปแบบ", 1),
    ]
    assert rank_passages("ประเทศไทย", passages)[0].index == 1


def test_research_reports_failed_reads_as_attempts() -> None:
    class Provider:
        async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
            return [SearchResult("title", "https://example.com")]

    class Reader:
        async def read(self, url: str) -> Document:
            raise ReaderError("not readable")

    async def run() -> None:
        agent = ResearchAgent(SearchService(Provider()), Reader())
        report = await agent.research("query", ResearchBudget(max_queries=1, max_pages=1))
        assert report.pages_attempted == 1
        assert report.read_errors == 1
        assert report.queries_used == 1
        assert report.stopped_reason.value == "budget_exhausted"

    asyncio.run(run())
