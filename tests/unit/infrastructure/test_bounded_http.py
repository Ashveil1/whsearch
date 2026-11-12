import asyncio
import gzip
import zlib
from collections.abc import AsyncIterator

import httpx
import pytest

from whsearch.infrastructure.http.bounded import BoundedTransport


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _client(stream: Chunks, encoding: str, max_bytes: int) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-encoding": encoding} if encoding else {}
        return httpx.Response(200, headers=headers, stream=stream)

    return httpx.AsyncClient(
        transport=BoundedTransport(httpx.MockTransport(handler), max_bytes=max_bytes)
    )


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
def test_normal_streams_decode_without_httpx_decoding_again(encoding: str) -> None:
    original = b"hello world" * 20
    encoded = (
        gzip.compress(original)
        if encoding == "gzip"
        else (zlib.compress(original) if encoding == "deflate" else original)
    )
    stream = Chunks([encoded[:5], encoded[5:]])

    async def run() -> None:
        async with _client(stream, encoding, 1024) as client:
            response = await client.get("https://example.com")
            assert response.content == original
        assert stream.closed

    asyncio.run(run())


def test_compressed_bomb_is_stopped_at_decoded_limit() -> None:
    stream = Chunks([gzip.compress(b"x" * 1_000_000)])

    async def run() -> None:
        async with _client(stream, "gzip", 2000) as client:
            with pytest.raises(httpx.ReadError, match="decoded size"):
                await client.get("https://example.com")
        assert stream.closed

    asyncio.run(run())


def test_raw_limit_and_unsupported_encoding() -> None:
    async def run() -> None:
        stream = Chunks([b"x" * 1025])
        async with _client(stream, "identity", 1024) as client:
            with pytest.raises(httpx.ReadError, match="raw size"):
                await client.get("https://example.com")
        assert stream.closed
        stream = Chunks([b"x"])
        async with _client(stream, "br", 1024) as client:
            with pytest.raises(httpx.DecodingError, match="unsupported"):
                await client.get("https://example.com")
        assert stream.closed

    asyncio.run(run())


def test_truncated_gzip_is_not_accepted() -> None:
    async def run() -> None:
        async with _client(Chunks([gzip.compress(b"hello")[:-5]]), "gzip", 1024) as client:
            with pytest.raises(httpx.DecodingError, match="incomplete"):
                await client.get("https://example.com")

    asyncio.run(run())


def test_application_http_client_does_not_persist_cookies() -> None:
    from whsearch.infrastructure.http.client import HttpClientFactory

    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "tracking=secret; Path=/"}, text="ok")

    async def run() -> None:
        client = HttpClientFactory().create()
        await client._transport.aclose()
        client._transport = BoundedTransport(httpx.MockTransport(handler), max_bytes=1024)
        try:
            await client.get("https://example.com/first")
            await client.get("https://example.com/second")
            assert seen == [None, None]
            assert len(client.cookies) == 0
        finally:
            await client.aclose()

    asyncio.run(run())
