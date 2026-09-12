from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger

_logger = get_logger("search.duckduckgo")


class DuckDuckGoProvider:
    """Small HTML search provider; no API key and no anti-bot bypassing."""

    endpoint = "https://lite.duckduckgo.com/lite/"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params = {"q": query.text, "kl": "wt-wt"}
        try:
            response = await self._client.get(self.endpoint, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning("DuckDuckGo request failed: %s", exc)
            raise ProviderError(f"DuckDuckGo request failed: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for anchor in soup.select("a.result-link"):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            url = _extract_target_url(href)
            if url is None:
                continue
            container = anchor.find_parent("tr") or anchor.parent
            snippet_node = container.select_one(".result-snippet") if container else None
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append(
                SearchResult(
                    title=anchor.get_text(" ", strip=True),
                    url=url,
                    snippet=snippet,
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("DuckDuckGo search: query=%r returned=%d", query.text, len(results))
        return results


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
