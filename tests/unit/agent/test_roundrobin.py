import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx

from whsearch.agent import ResearchAgent
from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import Document, Passage, ResearchBudget, SearchQuery, SearchResult
from whsearch.mcp.tools.research import research as research_tool
from whsearch.mcp.tools.search_and_read import search_and_read
from whsearch.search import SearchService


class QuerySplitProvider:
    """Returns spam for the full question, gold for the keyword query."""

    vertical = "web"

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        if query.text == "zhypix ความสามารถ":
            return [
                SearchResult(title=f"G{i}", url=f"https://github.com/zhypix/{i}")
                for i in range(10)
            ]
        return [SearchResult(title=f"S{i}", url=f"https://spam.example/{i}") for i in range(10)]


class FixedReader:
    async def read(self, url: str) -> Document:
        text = "Zhypix is an Android AI assistant here." if "github" in url else (
            "Resume skills filler content here today."
        )
        passages = (Passage(text, 0),)
        return Document(url=url, title=url, content=text, passages=passages)


def test_round_robin_shares_budget_across_queries() -> None:
    async def _main() -> None:
        agent = ResearchAgent(SearchService(QuerySplitProvider()), FixedReader())
        report = await agent.research(
            "Zhypix คืออะไร มีความสามารถอะไรบ้าง?",
            ResearchBudget(max_queries=4, max_pages=5, max_rounds=1),
        )
        urls = list(report.sources)
        assert any("github.com" in url for url in urls)
        assert any("spam.example" in url for url in urls)

    asyncio.run(_main())


class DatedReader:
    async def read(self, url: str) -> Document:
        now = datetime.now(UTC)
        published: datetime | None = (
            now - timedelta(days=30) if "old" in url else now - timedelta(days=1)
        )
        if "undated" in url:
            published = None
        body = "This is a sufficiently long content body for recency testing purposes."
        return Document(
            url=url, title=url, content=body, passages=(Passage(body, 0),), published_at=published
        )


class ThreePageProvider:
    vertical = "web"

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return [
            SearchResult(title="Old", url="https://example.com/old"),
            SearchResult(title="New", url="https://example.com/new"),
            SearchResult(title="Undated", url="https://example.com/undated"),
        ]


def test_agent_recency_drops_old_dated_pages_but_keeps_undated() -> None:
    async def _main() -> None:
        agent = ResearchAgent(SearchService(ThreePageProvider()), DatedReader())
        report = await agent.research(
            "fresh news query",
            ResearchBudget(max_queries=1, max_pages=5, max_rounds=1),
            recency_days=7,
        )
        assert "https://example.com/old" not in report.sources
        assert "https://example.com/new" in report.sources
        assert "https://example.com/undated" in report.sources

    asyncio.run(_main())


def test_search_and_read_truncates_and_filters_recency() -> None:
    async def _main() -> None:
        client = httpx.AsyncClient()
        app = Application(
            client, settings=Settings(max_pages_per_task=5),
            provider=ThreePageProvider(), reader=DatedReader(),
        )
        try:
            output = await search_and_read(app, "q", limit=5, max_chars=10, recency_days=7)
        finally:
            await app.aclose()
        urls = [item["url"] for item in output]
        assert "https://example.com/old" not in urls
        assert output[0]["truncated"] is True
        content = output[0]["content"]
        assert isinstance(content, str) and len(content) == 10

    asyncio.run(_main())


def test_search_and_read_metadata_only() -> None:
    async def _main() -> None:
        client = httpx.AsyncClient()
        app = Application(
            client, settings=Settings(max_pages_per_task=5),
            provider=ThreePageProvider(), reader=DatedReader(),
        )
        try:
            output = await search_and_read(
                app, "q", limit=5, max_chars=0, include_passages=False
            )
        finally:
            await app.aclose()
        assert output[0]["content"] == ""
        assert "passages" not in output[0]

    asyncio.run(_main())


def test_research_tool_returns_answer() -> None:
    async def _main() -> None:
        client = httpx.AsyncClient()
        app = Application(
            client, settings=Settings(), provider=ThreePageProvider(), reader=DatedReader()
        )
        try:
            output = await research_tool(app, "fresh news query", max_pages=3, max_rounds=1)
        finally:
            await app.aclose()
        assert isinstance(output["answer"], str) and output["answer"] != ""
        assert isinstance(output["answer_citations"], list)

    asyncio.run(_main())
