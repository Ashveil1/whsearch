from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

try:
    import trafilatura
except ImportError:  # pragma: no cover - degraded mode without optional extraction
    trafilatura = None  # type: ignore[assignment]

from whsearch.domain import Document, Passage
from whsearch.exceptions import ReaderError
from whsearch.infrastructure.http import DEFAULT_USER_AGENT
from whsearch.observability import get_logger

from .extractors.html import HtmlExtractor
from .robots import RobotsPolicy

_logger = get_logger("reader")


class ReaderService:
    """Fetches and extracts web documents while enforcing access/resource limits."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        robots: RobotsPolicy,
        *,
        max_bytes: int = 2_000_000,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        if not user_agent.strip():
            raise ValueError("user_agent must not be empty")
        self._client = client
        self._robots = robots
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._fallback = HtmlExtractor()

    async def read(self, url: str) -> Document:
        _validate_url(url)
        if not await self._robots.allowed(url):
            raise ReaderError("robots.txt disallows this URL or robots policy is unavailable")
        try:
            async with self._client.stream(
                "GET", url, headers={"User-Agent": self._user_agent}
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    raise ReaderError(f"unsupported content type: {content_type or 'unknown'}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self._max_bytes:
                        raise ReaderError("document exceeds configured size limit")
        except ReaderError:
            raise
        except httpx.HTTPError as exc:
            raise ReaderError(f"HTTP fetch failed: {exc}") from exc

        html = bytes(data).decode(response.encoding or "utf-8", errors="replace")
        document = _extract(url, html)
        if len(document.content) < 20:
            raise ReaderError("extracted document is too short")
        _logger.debug(
            "read completed: url=%r bytes=%d passages=%d", url, len(data), len(document.passages)
        )
        return document


def _extract(url: str, html: str) -> Document:
    if trafilatura is not None:
        extracted: Any = trafilatura.bare_extraction(html, url=url, output_format="python")
        if extracted is not None:
            text = (
                getattr(extracted, "text", None) or getattr(extracted, "raw_text", None) or ""
            ).strip()
            title = (getattr(extracted, "title", None) or "").strip()
            if not title:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "html.parser")
                title_node = soup.title
                title = title_node.get_text(" ", strip=True) if title_node is not None else ""
            author = getattr(extracted, "author", None)
            language = getattr(extracted, "language", None)
            date_value = getattr(extracted, "date", None)
            published_at = _parse_date(date_value)
            if text:
                passages = tuple(
                    Passage(text=part.strip(), index=index)
                    for index, part in enumerate(text.split("\n"))
                    if part.strip()
                )
                return Document(
                    url=url,
                    title=title or url,
                    content="\n\n".join(p.text for p in passages),
                    passages=passages,
                    author=author,
                    language=language,
                    published_at=published_at,
                )
            _logger.debug("trafilatura returned no text for url=%r; using HTML fallback", url)
    else:
        _logger.debug("trafilatura unavailable; using HTML fallback for url=%r", url)
    return HtmlExtractor().extract(url, html)


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReaderError("URL must be an absolute HTTP(S) URL")
