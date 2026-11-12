"""MCP protocol and real application against deterministic HTTP fixtures (no network)."""

import asyncio

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from whsearch.application import Application
from whsearch.config import Settings
from whsearch.mcp import server
from whsearch.search.providers.duckduckgo import DuckDuckGoProvider


def test_all_mcp_tools_through_real_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, str]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.host, request.url.path))
        if request.url.host == "lite.duckduckgo.com":
            return httpx.Response(
                200,
                text='<table><tr><td><a class="result-link" href="https://example.com/fresh">'
                'Fresh Python</a></td></tr><tr><td class="result-snippet">Fresh article</td>'
                '</tr><tr><td><a class="result-link" href="https://example.org/old">'
                'Old Python</a></td></tr><tr><td class="result-snippet">Old article</td>'
                "</tr></table>",
            )
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        date = "2099-01-01" if request.url.path == "/fresh" else "2001-01-01"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>Python article</title>"
            f'<meta property="article:published_time" content="{date}">'
            "</head><body><article><p>Python is a programming language "
            "used widely for automation and research.</p><p>Python is useful for programming "
            "applications and software development.</p></article></body></html>",
        )

    async def create() -> Application:
        # MockTransport is test-only; production must use the guarded HTTP transport.
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        return Application(
            client,
            settings=Settings(per_domain_delay_seconds=0),
            provider=DuckDuckGoProvider(client),
        )

    monkeypatch.setattr(server, "create_application", create)

    async def run() -> None:
        async with create_connected_server_and_client_session(server.mcp) as session:
            result = await session.call_tool("search", {"query": "Python programming", "limit": 2})
            assert not result.isError and result.structuredContent is not None
            results = result.structuredContent["result"]
            assert [item["snippet"] for item in results] == ["Fresh article", "Old article"]

            result = await session.call_tool("read_page", {"url": "https://example.com/fresh"})
            assert not result.isError and result.structuredContent is not None
            assert "Python is a programming language" in result.structuredContent["content"]

            result = await session.call_tool(
                "search_and_read", {"query": "Python programming", "limit": 2, "recency_days": 30}
            )
            assert not result.isError and result.structuredContent is not None
            assert [item["url"] for item in result.structuredContent["result"]] == [
                "https://example.com/fresh"
            ]

            result = await session.call_tool(
                "research",
                {
                    "question": "Python programming",
                    "max_queries": 1,
                    "max_pages": 2,
                    "max_rounds": 1,
                    "recency_days": 30,
                },
            )
            assert not result.isError and result.structuredContent is not None
            report = result.structuredContent
            assert report["answer"] and report["answer_citations"] == ["https://example.com/fresh"]
            assert report["pages_attempted"] == 2
            assert all(item["url"] == "https://example.com/fresh" for item in report["evidence"])
        assert ("example.com", "/robots.txt") in requests
        assert ("example.org", "/robots.txt") in requests

    asyncio.run(run())
