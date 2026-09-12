from __future__ import annotations

import httpx

DEFAULT_USER_AGENT = "WHSearch/0.1"


class HttpClientFactory:
    """Creates bounded HTTP clients with explicit timeouts and safe defaults."""

    def __init__(self, *, timeout: float = 15.0, max_connections: int = 10) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        self.timeout = httpx.Timeout(timeout)
        self.limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        )

    def create(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            limits=self.limits,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
