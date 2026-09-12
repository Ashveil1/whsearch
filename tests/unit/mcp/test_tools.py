import asyncio
from collections.abc import Sequence

import httpx

from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import Document, SearchQuery, SearchResult
from whsearch.exceptions import ReaderError
from whsearch.mcp.tools.search_and_read import search_and_read


class StubProvider:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return self._results


class StubReader:
    async def read(self, url: str) -> Document:
        if "bad" in url:
            raise ReaderError("unreadable in test")
        return Document(
            url=url,
            title=f"Title for {url}",
            content="This is a sufficiently long content body used by the MCP tool test.",
        )


def _make_app(urls: list[str], max_pages: int = 10) -> Application:
    settings = Settings(max_pages_per_task=max_pages)
    provider = StubProvider([SearchResult(title=f"T{i}", url=url) for i, url in enumerate(urls)])
    client = httpx.AsyncClient()
    return Application(client, settings=settings, provider=provider, reader=StubReader())


def test_search_and_read_preserves_order_and_isolates_failures() -> None:
    async def _main() -> None:
        app = _make_app(["https://example.com/good", "https://example.com/bad"])
        try:
            output = await search_and_read(app, "query", limit=2)
        finally:
            await app.aclose()
        assert [item["url"] for item in output] == [
            "https://example.com/good",
            "https://example.com/bad",
        ]
        assert output[0]["readable"] is True
        assert output[0]["content"] != ""
        assert output[1]["readable"] is False
        assert output[1]["error"] == "ReaderError"

    asyncio.run(_main())


def test_search_and_read_respects_max_pages_per_task() -> None:
    async def _main() -> None:
        app = _make_app([f"https://example.com/{i}" for i in range(5)], max_pages=2)
        try:
            output = await search_and_read(app, "query", limit=5)
        finally:
            await app.aclose()
        assert len(output) == 2

    asyncio.run(_main())
