from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from whsearch.exceptions import ReaderError


def _origin_key(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{parsed.scheme}://[{host}]:{port}"
    except (ValueError, UnicodeError):
        return None


@dataclass
class _Origin:
    load_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    rate_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    parser: RobotFileParser | None = None
    expires: float = 0
    next_request: float = 0


class RobotsPolicy:
    """Bounded per-origin robots cache and pacing, shared by application calls."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        user_agent: str,
        *,
        delay_seconds: float = 0.0,
        max_origins: int = 1024,
    ) -> None:
        if delay_seconds < 0 or max_origins < 1:
            raise ValueError("delay_seconds must be non-negative and max_origins positive")
        self._client = client
        self._user_agent = user_agent
        self._delay = delay_seconds
        self._max_origins = max_origins
        self._origins: OrderedDict[str, _Origin] = OrderedDict()

    def _origin_state(self, url: str) -> _Origin | None:
        origin = _origin_key(url)
        if origin is None:
            return None
        state = self._origins.get(origin)
        if state is not None:
            self._origins.move_to_end(origin)
            return state
        if len(self._origins) >= self._max_origins:
            now = time.monotonic()
            for key, existing in self._origins.items():
                if (
                    not existing.load_lock.locked()
                    and not existing.rate_lock.locked()
                    and existing.next_request <= now
                ):
                    del self._origins[key]
                    break
            else:
                return None  # Fail closed while every slot is active or cooling down.
        state = _Origin()
        self._origins[origin] = state
        return state

    async def wait(self, url: str) -> None:
        state = self._origin_state(url)
        if state is None:
            raise ReaderError("robots origin capacity reached")
        async with state.rate_lock:
            await asyncio.sleep(max(0.0, state.next_request - time.monotonic()))
            state.next_request = time.monotonic() + self._delay

    async def allowed(self, url: str) -> bool:
        state = self._origin_state(url)
        if state is None:
            return False
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
        async with state.load_lock:
            if state.expires <= time.monotonic():
                state.parser = await self._load(origin)
                # Retry transient failures sooner than successful policies.
                ttl = 60 if state.parser is None else 3600
                state.expires = time.monotonic() + ttl
            return state.parser is not None and state.parser.can_fetch(self._user_agent, url)

    async def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        try:
            await self.wait(robots_url)
            async with self._client.stream(
                "GET",
                robots_url,
                follow_redirects=False,
                headers={"User-Agent": self._user_agent, "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code == 404:
                    parser = RobotFileParser()
                    parser.parse([])
                    return parser
                # Redirects and failures fail closed rather than bypassing policy.
                if response.status_code != 200:
                    return None
                if response.headers.get("content-encoding", "identity").lower() not in {
                    "",
                    "identity",
                }:
                    return None
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 512_000:
                        return None
        except (httpx.HTTPError, ReaderError):
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(bytes(data).decode("utf-8", errors="replace").splitlines())
        return parser
