import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_protocol_schemas_and_private_url_rejection() -> None:
    async def run() -> None:
        root = Path(__file__).resolve().parents[3]
        env = {**os.environ, "PYTHONPATH": str(root / "src")}
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "whsearch.mcp.server"], env=env
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert set(tools) == {"search", "read_page", "search_and_read", "research"}
                assert "ctx" not in tools["search"].inputSchema["properties"]
                assert "domains" in tools["search_and_read"].inputSchema["properties"]
                response = await session.call_tool("read_page", {"url": "http://127.0.0.1/secret"})
                assert response.isError is True
                resources = await session.list_resources()
                assert {str(item.uri) for item in resources.resources} == {
                    "whsearch://health",
                    "whsearch://stats",
                }

    asyncio.run(run())


def test_server_lifespan_reuses_and_closes_application(monkeypatch: object) -> None:
    from types import SimpleNamespace

    import pytest

    from whsearch.domain import Document
    from whsearch.mcp import server

    assert isinstance(monkeypatch, pytest.MonkeyPatch)

    class Reader:
        async def read(self, url: str) -> Document:
            return Document(url, "title", "A page with a suitable amount of text.")

    class FakeApp:
        def __init__(self) -> None:
            self.reader = Reader()
            self.settings = SimpleNamespace(task_timeout_seconds=5)
            self.closed = 0

        async def aclose(self) -> None:
            self.closed += 1

    app = FakeApp()
    created = 0

    async def create() -> FakeApp:
        nonlocal created
        created += 1
        return app

    monkeypatch.setattr(server, "create_application", create)

    async def run() -> None:
        async with server._lifespan(server.mcp) as state:
            ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=state))
            await server.read_page("https://example.com/1", ctx)
            await server.read_page("https://example.com/2", ctx)
            assert created == 1 and app.closed == 0
        assert app.closed == 1

    asyncio.run(run())
