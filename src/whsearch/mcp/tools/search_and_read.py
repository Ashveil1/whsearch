from __future__ import annotations

import asyncio

from whsearch.application import Application
from whsearch.domain import SearchQuery
from whsearch.exceptions import AISearchError
from whsearch.observability import get_logger

_logger = get_logger("mcp.search_and_read")


async def search_and_read(app: Application, query: str, limit: int = 5) -> list[dict[str, object]]:
    results = await app.search.search(SearchQuery(query, limit=limit))
    bounded = list(results)[: app.settings.max_pages_per_task]
    semaphore = asyncio.Semaphore(max(1, min(len(bounded) or 1, app.settings.max_pages_per_task)))

    async def _read_one(url: str, title: str, snippet: str) -> dict[str, object]:
        item: dict[str, object] = {"title": title, "url": url, "snippet": snippet}
        async with semaphore:
            try:
                document = await app.reader.read(url)
            except AISearchError as exc:
                item["readable"] = False
                item["error"] = type(exc).__name__
                _logger.debug("page unreadable: url=%r error=%s", url, exc)
            except Exception as exc:  # pragma: no cover - defensive: one page never fails the batch
                item["readable"] = False
                item["error"] = type(exc).__name__
                _logger.exception("unexpected read failure: url=%r", url)
            else:
                item["content"] = document.content
                item["readable"] = True
        return item

    # gather preserves input order, so output matches search ranking.
    pages = await asyncio.gather(
        *(_read_one(result.url, result.title, result.snippet) for result in bounded)
    )
    output = list(pages)
    _logger.debug(
        "search_and_read completed: query=%r pages=%d readable=%d",
        query,
        len(output),
        sum(1 for item in output if item.get("readable") is True),
    )
    return output
