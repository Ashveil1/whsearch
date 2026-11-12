import asyncio
import socket
from typing import Any

import httpcore
import pytest

from whsearch.infrastructure.http.client import HttpClientFactory
from whsearch.infrastructure.http.safe_network import PublicNetworkBackend, is_public_address


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
def test_non_public_addresses_are_blocked(address: str) -> None:
    assert not is_public_address(address)


def test_connection_uses_checked_address_not_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = PublicNetworkBackend()
    connected: list[str] = []

    async def resolve(*args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    class FakeBackend:
        async def connect_tcp(self, host: str, port: int, **kwargs: Any) -> Any:
            connected.append(host)
            return object()

    monkeypatch.setattr("whsearch.infrastructure.http.safe_network.anyio.getaddrinfo", resolve)
    backend._backend = FakeBackend()  # type: ignore[assignment]
    asyncio.run(backend.connect_tcp("example.com", 443))
    assert connected == ["93.184.216.34"]


def test_mixed_public_and_private_dns_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(*args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr("whsearch.infrastructure.http.safe_network.anyio.getaddrinfo", resolve)
    with pytest.raises(httpcore.ConnectError, match="not a public"):
        asyncio.run(PublicNetworkBackend().connect_tcp("example.com", 443))


def test_factory_uses_guarded_backend_and_no_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:1234")
    client = HttpClientFactory().create()
    try:
        assert client.trust_env is False
        assert isinstance(client._transport._inner._pool._network_backend, PublicNetworkBackend)  # type: ignore[attr-defined]
    finally:
        asyncio.run(client.aclose())


def test_real_http_client_refuses_loopback_connection() -> None:
    async def run() -> None:
        accepted = False

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal accepted
            accepted = True
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        assert server.sockets
        port = server.sockets[0].getsockname()[1]
        client = HttpClientFactory().create()
        try:
            import httpx

            with pytest.raises(httpx.ConnectError):
                await client.get(f"http://127.0.0.1:{port}/")
            assert not accepted
        finally:
            await client.aclose()
            server.close()
            await server.wait_closed()

    asyncio.run(run())
