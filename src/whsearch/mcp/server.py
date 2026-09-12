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
async def search(query: str, limit: int = 10) -> list[dict[str, object]]:
    """Search the web through the configured discovery provider."""
    # One application per call keeps connection pools isolated between
    # tool invocations; parallelism happens inside search_and_read instead.
    app = await create_application()
    try:
        return await search_impl(app, query, limit)
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
async def search_and_read(query: str, limit: int = 5) -> list[dict[str, object]]:
    """Search the web and read the returned pages."""
    app = await create_application()
    try:
        return await search_and_read_impl(app, query, limit)
    finally:
        await app.aclose()


@mcp.tool()
async def research(
    question: str, max_queries: int = 8, max_pages: int = 20, max_rounds: int = 3
) -> dict[str, object]:
    """Run budgeted multi-round research with claim-level evidence."""
    app = await create_application()
    try:
        return await research_impl(app, question, max_queries, max_pages, max_rounds)
    finally:
        await app.aclose()


def main() -> None:
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
