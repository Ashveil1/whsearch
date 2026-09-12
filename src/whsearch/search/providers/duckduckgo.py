from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.search.query import df_for_recency, kl_for_query

_logger = get_logger("search.duckduckgo")


class DuckDuckGoProvider:
    """Small HTML search provider; no API key and no anti-bot bypassing."""

    endpoint = "https://lite.duckduckgo.com/lite/"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params: dict[str, str] = {"q": query.text, "kl": kl_for_query(query.text)}
        date_filter = df_for_recency(query.recency_days)
        if date_filter:
            params["df"] = date_filter
        try:
            response = await self._client.get(self.endpoint, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning("DuckDuckGo request failed: %s", exc)
            raise ProviderError(f"DuckDuckGo request failed: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        anchors = soup.select("a.result-link")
        if not anchors:
            # Fallback selectors: DDG lite layout changes frequently.
            anchors = soup.select("a[href]")
        for anchor in anchors:
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            url = _extract_target_url(href)
            if url is None:
                continue
            # Skip DDG internal links (e.g. /lite/, /html/, ads).
            if "duckduckgo.com" in url:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title or len(title) < 2:
                continue
            snippet = _extract_snippet(anchor, title, query.text)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("DuckDuckGo search: query=%r returned=%d", query.text, len(results))
        return results


def _extract_snippet(anchor: object, title: str, query_text: str) -> str:
    """Best-effort snippet extraction with multiple fallback strategies."""
    from bs4 import Tag

    assert isinstance(anchor, Tag)
    # Strategy 1: classic lite layout — snippet cell in the same <tr>.
    container = anchor.find_parent("tr")
    if container is not None and isinstance(container, Tag):
        snippet_node = container.select_one(".result-snippet")
        if snippet_node is not None:
            text = snippet_node.get_text(" ", strip=True)
            if text:
                return text[:500]
        # Strategy 2: last <td> in the row often holds the description.
        cells = container.find_all("td")
        if len(cells) >= 2:
            fallback = cells[-1].get_text(" ", strip=True)
            # Avoid echoing the title back as the snippet.
            if fallback and fallback != title and len(fallback) > len(title):
                # Strip a leading title repeat ("TitleDescription...").
                if fallback.startswith(title):
                    fallback = fallback[len(title) :].strip(" -–—:|")
                if fallback:
                    return fallback[:500]
        row_text = container.get_text(" ", strip=True)
        if row_text and row_text != title:
            cleaned = row_text
            if cleaned.startswith(title):
                cleaned = cleaned[len(title) :].strip(" -–—:|")
            if len(cleaned) >= 20:
                return cleaned[:500]
    # Strategy 3: sibling / parent text around the link.
    parent = anchor.parent
    if parent is not None and isinstance(parent, Tag):
        sibling = parent.find_next_sibling()
        if sibling is not None and isinstance(sibling, Tag):
            text = sibling.get_text(" ", strip=True)
            if text and text != title and len(text) >= 20:
                return text[:500]
        parent_text = parent.get_text(" ", strip=True)
        if parent_text and parent_text != title and len(parent_text) >= 20:
            if parent_text.startswith(title):
                parent_text = parent_text[len(title) :].strip(" -–—:|")
            if parent_text:
                return parent_text[:500]
    # Strategy 4: never return empty — fall back to a query-context snippet
    # so callers (and MCP clients) always have something to display.
    return f"{title} — result for '{query_text}'"


def _extract_target_url(href: str) -> str | None:
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return href
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            decoded = unquote(target)
            target_parsed = urlparse(decoded)
            if target_parsed.scheme in {"http", "https"} and target_parsed.netloc:
                return decoded
    return None
