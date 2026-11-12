from __future__ import annotations

import ssl
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from .bounded import BoundedTransport
from .safe_network import PublicNetworkBackend

DEFAULT_USER_AGENT = "WHSearch/0.1"


class _RejectCookies(DefaultCookiePolicy):
    """Never persist upstream tracking or session cookies across tool calls."""

    def set_ok(self, cookie: Cookie, request: Any) -> bool:
        return False


class HttpClientFactory:
    """Creates bounded HTTP clients with explicit timeouts and safe defaults."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_connections: int = 10,
        max_response_bytes: int = 5_000_000,
        ca_file: str | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.max_response_bytes = max_response_bytes
        self.ca_file = ca_file
        self.timeout = httpx.Timeout(timeout)
        self.limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        )

    def create(self) -> httpx.AsyncClient:
        # httpx has no public network-backend hook. Keep this isolated and
        # covered by tests; the bounded dependency versions are intentional.
        verify = ssl.create_default_context(cafile=self.ca_file) if self.ca_file else True
        transport = httpx.AsyncHTTPTransport(limits=self.limits, trust_env=False, verify=verify)
        transport._pool._network_backend = PublicNetworkBackend()
        return httpx.AsyncClient(
            transport=BoundedTransport(transport, max_bytes=self.max_response_bytes),
            trust_env=False,
            cookies=CookieJar(policy=_RejectCookies()),
            timeout=self.timeout,
            limits=self.limits,
            follow_redirects=True,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json,application/rss+xml",
                "Accept-Encoding": "gzip, deflate",
            },
        )
