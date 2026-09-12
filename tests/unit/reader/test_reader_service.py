import asyncio
from collections.abc import Callable

import httpx
import pytest

from whsearch.exceptions import ReaderError
from whsearch.reader import ReaderService, RobotsPolicy

HTML = """<html><head><title>Example article</title></head>
<body><article><h1>Example article</h1>
<p>This is a sufficiently long paragraph used to exercise the offline reader path.</p>
<p>A second paragraph keeps the extracted document comfortably above the minimum.</p>
</article></body></html>"""


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def _allow_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML)


def test_reader_reads_page_offline() -> None:
    async def _main() -> None:
        async with _client(_allow_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "test-agent"))
            document = await service.read("https://example.com/article")
            assert document.url == "https://example.com/article"
            assert len(document.content) >= 20
            assert len(document.passages) >= 1

    asyncio.run(_main())


def test_reader_falls_back_without_trafilatura(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _main() -> None:
        async with _client(_allow_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "test-agent"))
            document = await service.read("https://example.com/article")
            assert len(document.passages) >= 1
            assert "sufficiently long paragraph" in document.content

    monkeypatch.setattr("whsearch.reader.service.trafilatura", None)
    asyncio.run(_main())


def test_reader_rejects_non_http_url() -> None:
    async def _main() -> None:
        async with _client(_allow_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "test-agent"))
            with pytest.raises(ReaderError, match="absolute HTTP"):
                await service.read("javascript:alert(1)")

    asyncio.run(_main())


def test_reader_rejects_unsupported_content_type() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"content-type": "application/pdf"}, text="%PDF")

    async def _main() -> None:
        async with _client(_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "test-agent"))
            with pytest.raises(ReaderError, match="unsupported content type"):
                await service.read("https://example.com/file.pdf")

    asyncio.run(_main())


def test_reader_rejects_empty_user_agent() -> None:
    async def _main() -> None:
        async with _client(_allow_handler) as client:
            with pytest.raises(ValueError, match="user_agent"):
                ReaderService(client, RobotsPolicy(client, "test-agent"), user_agent="  ")

    asyncio.run(_main())
