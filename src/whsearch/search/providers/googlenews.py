from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from whsearch.domain import SearchQuery, SearchResult, SourceType
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.search.query import is_thai_query

_logger = get_logger("search.googlenews")

_ENDPOINT = "https://news.google.com/rss/search"


class GoogleNewsProvider:
    """Keyless news search via Google News RSS (no key, stable XML feed).

    Returns headline title/snippet/date even when the article page itself
    is JS-heavy; the reader treats unreadable pages as best-effort skips.
    """

    vertical = "news"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        thai = is_thai_query(query.text)
        params = {
            "q": query.text,
            "hl": "th" if thai else "en-US",
            "gl": "TH" if thai else "US",
            "ceid": "TH:th" if thai else "US:en",
        }
        try:
            response = await self._client.get(
                _ENDPOINT,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            )
            response.raise_for_status()
            items = _parse_rss(response.text)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            _logger.warning("Google News request failed: %s", exc)
            raise ProviderError(f"Google News request failed: {exc}") from exc

        results: list[SearchResult] = []
        for title, link, pub_date, source in items:
            if not link.startswith(("http://", "https://")) or not title:
                continue
            snippet = title
            meta: dict[str, object] = {}
            details = [p for p in [source, pub_date] if p]
            if details:
                snippet = f"{title} ({', '.join(details)})"
                meta = {"source": source, "published": pub_date}
            results.append(
                SearchResult(
                    title=title,
                    url=link,
                    snippet=re.sub(r"\s+", " ", snippet).strip()[:500],
                    source_type=SourceType.NEWS,
                    metadata=meta,
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("Google News search: query=%r returned=%d", query.text, len(results))
        return results


def _parse_rss(xml_text: str) -> list[tuple[str, str, str, str]]:
    root = ET.fromstring(xml_text)
    items: list[tuple[str, str, str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        source_node = item.find("source")
        source = (source_node.text or "").strip() if source_node is not None else ""
        pub_date = ""
        if pub_raw:
            try:
                pub_date = parsedate_to_datetime(pub_raw).date().isoformat()
            except (ValueError, TypeError):
                pub_date = ""
        items.append((title, link, pub_date, source))
    return items
