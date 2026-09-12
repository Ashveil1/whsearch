from __future__ import annotations

import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
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

from .browser import BrowserRenderer
from .extractors.html import HtmlExtractor
from .robots import RobotsPolicy

_logger = get_logger("reader")

#: Rendered output below this length is not worth keeping over static text.
_BROWSER_MIN_CHARS = 200


def _needs_browser(content: str) -> bool:
    """True for JS-shell pages: almost nothing, or the same line repeated.

    Length alone misses pages like `bankhunprathed.vercel.app` whose static
    HTML is just one meta description stamped 3 times (310 chars of noise).
    """
    if len(content) < _BROWSER_MIN_CHARS:
        return True
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    return len(lines) >= 3 and len(set(lines)) * 3 <= len(lines)


class ReaderService:
    """Fetches and extracts web documents while enforcing access/resource limits."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        robots: RobotsPolicy,
        *,
        max_bytes: int = 2_000_000,
        user_agent: str = DEFAULT_USER_AGENT,
        browser: BrowserRenderer | None = None,
    ) -> None:
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        if not user_agent.strip():
            raise ValueError("user_agent must not be empty")
        self._client = client
        self._robots = robots
        self._max_bytes = max_bytes
        self._user_agent = user_agent
        self._browser = browser
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
        try:
            document = _extract(url, html)
        except ValueError:
            document = None
        if document is not None and not _needs_browser(document.content):
            pass
        elif self._browser is not None:
            rendered = await self._browser.render_text(url, user_agent=self._user_agent)
            rebuilt = _from_rendered(url, html, document, rendered)
            if rebuilt is not None:
                document = rebuilt
        if document is None or len(document.content) < 20:
            raise ReaderError("extracted document is too short")
        _logger.debug(
            "read completed: url=%r bytes=%d passages=%d", url, len(data), len(document.passages)
        )
        return document

    async def aclose(self) -> None:
        """Release the optional headless browser; safe to call without one."""
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None


def _from_rendered(
    url: str, html: str, document: Document | None, rendered: str | None
) -> Document | None:
    """Rebuild a document from browser-rendered text when static text is thin."""
    if not rendered or len(rendered) < _BROWSER_MIN_CHARS:
        return None
    if document is not None and len(rendered) <= len(document.content):
        return None
    passages = tuple(
        Passage(text=part.strip(), index=index)
        for index, part in enumerate(rendered.split("\n"))
        if part.strip()
    )
    if not passages:
        return None
    if document is not None:
        return Document(
            url=document.url,
            title=document.title,
            content="\n\n".join(p.text for p in passages),
            passages=passages,
            author=document.author,
            language=document.language,
            published_at=document.published_at,
            canonical_url=document.canonical_url,
        )
    return Document(
        url=url,
        title=url,
        content="\n\n".join(p.text for p in passages),
        passages=passages,
        published_at=_extract_published_at(html, url),
    )


def _extract(url: str, html: str) -> Document:
    from bs4 import BeautifulSoup

    soup_title = ""
    try:
        quick = BeautifulSoup(html, "html.parser")
        title_node = quick.title
        soup_title = title_node.get_text(" ", strip=True) if title_node is not None else ""
    except Exception:  # pragma: no cover - title is best-effort
        soup_title = ""
    published_fallback = _extract_published_at(html, url)
    if trafilatura is not None:
        extracted: Any = trafilatura.bare_extraction(html, url=url, output_format="python")
        if extracted is not None:
            text = (
                getattr(extracted, "text", None) or getattr(extracted, "raw_text", None) or ""
            ).strip()
            # L2: JS-heavy pages often leave trafilatura with nothing but keep
            # the article inside embedded JSON (Next/Nuxt/LD+JSON).
            if len(text) < 200:
                embedded = _embedded_text(html)
                if len(embedded) > len(text):
                    text = embedded
            title = (getattr(extracted, "title", None) or "").strip() or soup_title
            author = getattr(extracted, "author", None)
            language = getattr(extracted, "language", None)
            date_value = getattr(extracted, "date", None)
            published_at = _parse_date(date_value) or published_fallback
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
    return HtmlExtractor().extract(url, html, published_at=published_fallback)


def _extract_published_at(html: str, url: str) -> datetime | None:
    """Keyless date enrichment: meta tags, <time>, JSON-LD, then URL pattern."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # pragma: no cover - malformed HTML is best-effort
        soup = None
    if soup is not None:
        for attr, value in (
            ("property", "article:published_time"),
            ("property", "article:published"),
            ("name", "publish-date"),
            ("name", "publish_date"),
            ("name", "date"),
            ("name", "DC.date.issued"),
            ("itemprop", "datePublished"),
            ("property", "og:published_time"),
        ):
            node = soup.find("meta", attrs={attr: value})
            content = node.get("content", "") if node else ""
            parsed = _parse_date(content) if isinstance(content, str) else None
            if parsed is not None:
                return parsed
        time_node = soup.find("time", attrs={"datetime": True})
        if time_node is not None:
            parsed = _parse_date(str(time_node.get("datetime", "")))
            if parsed is not None:
                return parsed
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text()
            if not raw or not isinstance(raw, str):
                continue
            for candidate in _json_ld_dates(raw):
                parsed = _parse_date(candidate)
                if parsed is not None:
                    return parsed
    match = re.search(
        r"/(19\d{2}|20\d{2})[/-](0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])(?=[/?#\"'_-]|$)",
        url,
    )
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _json_ld_dates(raw: str) -> list[str]:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    nodes = payload if isinstance(payload, list) else [payload]
    dates: list[str] = []
    stack: list[object] = list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("datePublished", "dateCreated", "uploadDate"):
                value = node.get(key)
                if isinstance(value, str) and value:
                    dates.append(value)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return dates


def _embedded_text(html: str, *, limit: int = 20000) -> str:
    """L2 fallback for JS-heavy pages: text hidden in embedded JSON/meta."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # pragma: no cover - malformed HTML is best-effort
        return ""
    chunks: list[str] = []
    for script_id in ("__NEXT_DATA__", "__NUXT_DATA__", "__NUXT__"):
        node = soup.find("script", id=script_id)
        raw = (node.string or node.get_text()) if node else ""
        if raw and isinstance(raw, str):
            chunks.extend(_json_strings(raw, cap=8000))
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if raw and isinstance(raw, str):
            chunks.extend(_json_strings(raw, cap=8000))
    for attr, value in (
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
    ):
        node = soup.find("meta", attrs={attr: value})
        content = node.get("content", "") if node else ""
        if isinstance(content, str) and content.strip():
            chunks.append(content.strip())
    text = "\n".join(c for c in chunks if c.strip())
    return text[:limit]


def _json_strings(raw: str, *, cap: int) -> list[str]:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    stack: list[object] = [payload]
    while stack and sum(len(s) for s in out) < cap:
        node = stack.pop()
        if isinstance(node, str):
            cleaned = re.sub(r"\s+", " ", node).strip()
            if len(cleaned) >= 40:
                out.append(cleaned)
        elif isinstance(node, dict):
            for key in ("articleBody", "description", "text", "content", "title"):
                value = node.get(key)
                if isinstance(value, str) and len(value.strip()) >= 40:
                    out.append(re.sub(r"\s+", " ", value).strip())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(pattern) + 4], pattern)
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(text)
    except (ValueError, TypeError):
        return None


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReaderError("URL must be an absolute HTTP(S) URL")
