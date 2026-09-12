from __future__ import annotations

from whsearch.application import Application
from whsearch.domain import SearchQuery
from whsearch.observability import get_logger

_logger = get_logger("mcp.search")


async def search(
    app: Application,
    query: str,
    limit: int = 10,
    *,
    recency_days: int | None = None,
    domains: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, object]]:
    """Search with optional domain allowlist and recency hint.

    `recency_days` is best-effort: current keyless providers (DuckDuckGo,
    Wikipedia) do not expose publish dates at search time, so it is kept on
    the query for future providers and documented in output. `domains`
    filters results to the given registrable domains.
    """
    cleaned_domains = tuple(d.strip() for d in (domains or []) if d and d.strip())
    results = await app.search.search(
        SearchQuery(query, limit=limit, recency_days=recency_days, domains=cleaned_domains)
    )
    _logger.debug("search tool: query=%r returned=%d", query, len(results))
    return [
        {
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet
            or f"{result.title} — result for '{query.strip()}'",
            "source_type": result.source_type.value,
            "score": result.score,
        }
        for result in results
    ]
