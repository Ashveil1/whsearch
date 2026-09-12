from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from whsearch.application import create_application
from whsearch.mcp.tools.read_page import read_page as read_page_impl
from whsearch.mcp.tools.research import research as research_impl
from whsearch.mcp.tools.search import search as search_impl
from whsearch.mcp.tools.search_and_read import search_and_read as search_and_read_impl
from whsearch.observability import configure_logging

mcp = FastMCP(
    "WHSearch",
    instructions="AI-native search and web reading. Respects robots.txt and resource limits.",
)


@mcp.tool()
async def search(
    query: str,
    limit: int = 10,
    recency_days: int | None = None,
    domains: list[str] | None = None,
) -> list[dict[str, object]]:
    """Search the web through the configured discovery provider.

    Args:
        query: Search keywords.
        limit: Max results (1-100).
        recency_days: Best-effort freshness hint kept for future providers.
        domains: Optional allowlist, e.g. ["github.com", "wikipedia.org"].
    """
    # One application per call keeps connection pools isolated between
    # tool invocations; parallelism happens inside search_and_read instead.
    app = await create_application()
    try:
        return await search_impl(
            app, query, limit, recency_days=recency_days, domains=domains
        )
    finally:
        await app.aclose()


@mcp.tool()
async def read_page(url: str) -> dict[str, object]:
    """Fetch and extract a readable web page, subject to robots.txt."""
    app = await create_application()
    try:
        return await read_page_impl(app, url)
    finally:
        await app.aclose()


@mcp.tool()
async def search_and_read(
    query: str,
    limit: int = 5,
    max_chars: int = 8000,
    include_passages: bool = True,
    max_passages: int = 5,
    recency_days: int | None = None,
) -> list[dict[str, object]]:
    """Search the web and read the returned pages.

    Args:
        query: Search keywords.
        limit: Max pages to read.
        max_chars: Truncate each page content to this many chars (0 = metadata only).
        include_passages: Include top passages plus metadata.
        max_passages: Max passages per page when include_passages is true.
        recency_days: Drop dated pages older than this (undated pages kept).
    """
    app = await create_application()
    try:
        return await search_and_read_impl(
            app,
            query,
            limit,
            max_chars=max_chars,
            include_passages=include_passages,
            max_passages=max_passages,
            recency_days=recency_days,
        )
    finally:
        await app.aclose()


@mcp.tool()
async def research(
    question: str,
    max_queries: int = 8,
    max_pages: int = 20,
    max_rounds: int = 3,
    recency_days: int | None = None,
) -> dict[str, object]:
    """Run budgeted multi-round research with claim-level evidence.

    Args:
        question: Research question.
        max_queries: Max sub-queries to plan.
        max_pages: Max pages to read.
        max_rounds: Max research rounds.
        recency_days: Prefer/filter pages newer than this (undated kept).
    """
    app = await create_application()
    try:
        return await research_impl(
            app, question, max_queries, max_pages, max_rounds, recency_days=recency_days
        )
    finally:
        await app.aclose()


def main() -> None:
    configure_logging()
    mcp.run()


@mcp.resource(
    "whsearch://stats",
    name="whsearch-stats",
    description="Engine stats: providers, budgets, and local index usage.",
)
async def whsearch_stats() -> dict[str, object]:
    """Bounded engine stats for MCP clients (no secrets)."""
    from whsearch.config import Settings
    from whsearch.reader.browser import is_browser_available

    settings = Settings.from_environment()
    index_info: dict[str, object] = {
        "enabled": settings.index_path is not None,
        "path": settings.index_path,
        "max_entries": settings.index_max_entries,
    }
    if settings.index_path:
        try:
            from pathlib import Path

            size = Path(settings.index_path).stat().st_size
            index_info["size_bytes"] = size
        except OSError:
            index_info["size_bytes"] = None
    return {
        "name": "WHSearch",
        "providers": [
            "duckduckgo-lite",
            "duckduckgo-html",
            "wikipedia-en",
            "wikipedia-th",
            "googlenews",
            "openalex-academic",
            "youtube-video",
        ],
        "limits": {
            "max_search_results": settings.max_search_results,
            "max_pages_per_task": settings.max_pages_per_task,
            "max_response_bytes": settings.max_response_bytes,
            "request_timeout_seconds": settings.request_timeout_seconds,
        },
        "reader": {
            "browser_installed": is_browser_available(),
            "browser_enabled": settings.browser_enabled,
            "browser_timeout_seconds": settings.browser_timeout_seconds,
        },
        "index": index_info,
    }


@mcp.resource(
    "whsearch://health",
    name="whsearch-health",
    description="Liveness check with version and provider list.",
)
async def whsearch_health() -> dict[str, object]:
    return {"status": "ok", "service": "WHSearch", "version": "0.2.0"}


if __name__ == "__main__":
    main()
