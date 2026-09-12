from __future__ import annotations

from whsearch.application import Application
from whsearch.domain import SearchQuery
from whsearch.observability import get_logger

_logger = get_logger("mcp.search")


async def search(app: Application, query: str, limit: int = 10) -> list[dict[str, object]]:
    results = await app.search.search(SearchQuery(query, limit=limit))
    _logger.debug("search tool: query=%r returned=%d", query, len(results))
    return [
        {
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet,
            "source_type": result.source_type.value,
        }
        for result in results
    ]
