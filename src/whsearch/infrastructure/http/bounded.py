"""Bound raw and decompressed HTTP response bodies before httpx buffers them."""

from __future__ import annotations

import zlib
from collections.abc import AsyncIterator

import httpx


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(
        self, stream: httpx.AsyncByteStream, request: httpx.Request, max_bytes: int, encoding: str
    ) -> None:
        self._stream = stream
        self._request = request
        self._max_bytes = max_bytes
        self._encoding = encoding

    async def __aiter__(self) -> AsyncIterator[bytes]:
        decoder = (
            zlib.decompressobj(16 + zlib.MAX_WBITS if self._encoding == "gzip" else zlib.MAX_WBITS)
            if self._encoding in {"gzip", "deflate"}
            else None
        )
        raw_size = decoded_size = 0
        try:
            async for chunk in self._stream:
                raw_size += len(chunk)
                if raw_size > self._max_bytes:
                    raise httpx.ReadError("response exceeds raw size limit", request=self._request)
                if decoder is None:
                    decoded = chunk
                else:
                    decoded = decoder.decompress(chunk, self._max_bytes - decoded_size + 1)
                    if decoder.unused_data:
                        raise httpx.DecodingError(
                            "unexpected data after compressed response", request=self._request
                        )
                decoded_size += len(decoded)
                if decoded_size > self._max_bytes or (decoder and decoder.unconsumed_tail):
                    raise httpx.ReadError(
                        "response exceeds decoded size limit", request=self._request
                    )
                if decoded:
                    yield decoded
            if decoder and not decoder.eof:
                raise httpx.DecodingError("incomplete compressed response", request=self._request)
        except zlib.error as exc:
            raise httpx.DecodingError("invalid compressed response", request=self._request) from exc

    async def aclose(self) -> None:
        await self._stream.aclose()


class BoundedTransport(httpx.AsyncBaseTransport):
    """Enforce limits for every response, including provider and redirect bodies."""

    def __init__(self, inner: httpx.AsyncBaseTransport, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._inner = inner
        self._max_bytes = max_bytes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in {"", "identity", "gzip", "deflate"}:
            await response.aclose()
            raise httpx.DecodingError(f"unsupported content encoding: {encoding}", request=request)
        # Decode here, rather than letting httpx allocate unbounded decoded data.
        if encoding in {"gzip", "deflate"}:
            response.headers.pop("content-encoding", None)
            response.headers.pop("content-length", None)
        assert isinstance(response.stream, httpx.AsyncByteStream)
        response.stream = _BoundedStream(response.stream, request, self._max_bytes, encoding)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
