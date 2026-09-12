import asyncio
from collections.abc import Sequence

import httpx

from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import Document, Passage, SearchQuery, SearchResult
from whsearch.mcp.tools.research import research


class StubProvider:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return self._results


class StubReader:
    async def read(self, url: str) -> Document:
        text = "Python is a popular programming language. It is widely used for automation."
        passages = tuple(
            Passage(text=part.strip(), index=index)
            for index, part in enumerate(text.split(". "))
            if part.strip()
        )
        return Document(
            url=url, title=f"Title {url}", content="\n\n".join(p.text for p in passages),
            passages=passages,
        )


def test_research_tool_returns_report_dict() -> None:
    async def _main() -> None:
        provider = StubProvider(
            [
                SearchResult(title="A", url="https://example.com/a"),
                SearchResult(title="B", url="https://example.org/b"),
            ]
        )
        client = httpx.AsyncClient()
        app = Application(client, settings=Settings(), provider=provider, reader=StubReader())
        try:
            output = await research(app, "What is Python?", max_pages=5, max_rounds=2)
        finally:
            await app.aclose()
        assert output["question"] == "What is Python?"
        assert output["stopped_reason"] in {
            "sufficient_evidence",
            "saturated",
            "budget_exhausted",
            "max_rounds",
        }
        claims = output["claims"]
        sources = output["sources"]
        assert isinstance(claims, list) and len(claims) > 0
        assert all({"id", "text", "status"} <= set(claim) for claim in claims)
        assert isinstance(sources, list) and len(sources) == 2

    asyncio.run(_main())
