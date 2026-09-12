import asyncio
from collections.abc import Sequence

import httpx
import pytest

from whsearch.agent import ResearchAgent
from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import Document, Passage, ResearchBudget, SearchQuery, SearchResult
from whsearch.index import SqliteDocumentStore
from whsearch.search import SearchService

DOCS = {
    "https://example.com/python": (
        "Python is a popular programming language. It is widely used for web development.",
    ),
    "https://example.org/python": (
        "Python is a popular programming language. Many developers enjoy its clear syntax.",
    ),
}


class StubProvider:
    def __init__(self, urls: Sequence[str]) -> None:
        self._urls = list(urls)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return [SearchResult(title=f"T{i}", url=url) for i, url in enumerate(self._urls)]


class StubReader:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self, url: str) -> Document:
        self.calls += 1
        (text,) = DOCS[url]
        passages = tuple(
            Passage(text=part.strip(), index=index)
            for index, part in enumerate(text.split(". "))
            if part.strip()
        )
        return Document(
            url=url, title=f"Title {url}", content="\n\n".join(p.text for p in passages),
            passages=passages,
        )


def _make_agent(
    urls: list[str], store: SqliteDocumentStore | None = None
) -> tuple[ResearchAgent, StubReader]:
    provider = StubProvider(urls)
    search = SearchService(provider)
    reader = StubReader()
    return ResearchAgent(search, reader, store=store), reader


def test_agent_reports_supported_claims() -> None:
    async def _main() -> None:
        agent, _ = _make_agent(list(DOCS))
        report = await agent.research(
            "What is Python programming?", ResearchBudget(max_rounds=3, max_pages=10)
        )
        assert report.question == "What is Python programming?"
        assert report.rounds >= 1
        assert set(report.sources) == set(DOCS)
        supported = [c for c in report.claims if c.status.value == "supported"]
        assert any("popular programming language" in c.text for c in supported)
        assert len(report.evidence) > 0

    asyncio.run(_main())


def test_agent_respects_page_budget() -> None:
    async def _main() -> None:
        agent, _ = _make_agent(list(DOCS))
        report = await agent.research("Python", ResearchBudget(max_pages=1, max_rounds=2))
        assert len(report.sources) <= 1

    asyncio.run(_main())


def test_agent_reuses_index_cache() -> None:
    async def _main() -> None:
        store = SqliteDocumentStore()
        try:
            agent, reader = _make_agent(list(DOCS), store=store)
            await agent.research("Python programming", ResearchBudget(max_rounds=1))
            first_calls = reader.calls
            assert first_calls == 2
            await agent.research("Python programming", ResearchBudget(max_rounds=1))
            assert reader.calls == first_calls
        finally:
            store.close()

    asyncio.run(_main())


def test_agent_rejects_empty_question() -> None:
    async def _main() -> None:
        agent, _ = _make_agent([])
        with pytest.raises(ValueError, match="must not be empty"):
            await agent.research("   ")

    asyncio.run(_main())


def test_application_exposes_research_agent() -> None:
    async def _main() -> None:
        client = httpx.AsyncClient()
        settings = Settings(max_pages_per_task=4)
        async with Application(client, settings=settings, provider=StubProvider([])) as app:
            assert app.research_agent is not None
            assert app.store is None

    asyncio.run(_main())
