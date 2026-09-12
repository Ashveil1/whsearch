from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.search.providers.duckduckgo import _extract_target_url
from whsearch.search.query import df_for_recency, kl_for_query

_logger = get_logger("search.duckduckgo_html")


class DuckDuckGoHtmlProvider:
    """Fallback HTML provider (html.duckduckgo.com) with richer snippets.

    Uses the classic HTML endpoint which exposes `.result__snippet`
    blocks. Kept separate from the lite provider so fan-out still works
    when one layout/endpoint is blocked or changes.
    """

    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params: dict[str, str] = {"q": query.text, "kl": kl_for_query(query.text)}
        date_filter = df_for_recency(query.recency_days)
        if date_filter:
            params["df"] = date_filter
        try:
            response = await self._client.get(
                self.endpoint,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning("DuckDuckGo HTML request failed: %s", exc)
            raise ProviderError(f"DuckDuckGo HTML request failed: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for block in soup.select(".result"):
            link = block.select_one("a.result__a")
            if link is None:
                continue
            href = link.get("href")
            if not isinstance(href, str):
                continue
            url = _extract_target_url(href)
            if url is None or "duckduckgo.com" in url:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            snippet_node = block.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            if not snippet:
                body = block.get_text(" ", strip=True)
                if body and body != title:
                    snippet = body[:500]
                else:
                    snippet = f"{title} — result for '{query.text}'"
            results.append(
                SearchResult(title=title, url=url, snippet=snippet[:500])
            )
            if len(results) >= query.limit:
                break
        _logger.debug(
            "DuckDuckGo HTML search: query=%r returned=%d", query.text, len(results)
        )
        return results
